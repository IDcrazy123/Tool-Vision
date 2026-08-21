"""Automatic relative XYZ tool-offset measurement for Klipper.

The operator teaches each physical station once. Camera processing lives in a
separate host service; this extension alone owns motion, probing and tool
selection. Measured production offsets are reported, never silently applied.
"""

import math
import os
import time

from .tool_vision_client import ClientError, VisionClient
from .tool_vision_state import StateError, StateStore, atomic_write_json
from .tool_vision_toolchanger import ToolchangerAdapter, ToolchangerError


class ToolVisionError(RuntimeError):
    """A safe, user-facing ToolVision failure."""


class ToolVision:
    VERSION = "3.2.1"
    # Axiscope's official configuration and the legacy toolchanger calibration
    # both use 150 C. Keep it in code so normal users do not need another cfg
    # value or console parameter merely to get repeatable heated Z results.
    DEFAULT_CALIBRATION_TEMPERATURE = 150.0
    CAMERA_POINTS = (
        (0.000, -0.500),
        (0.294, -0.405),
        (0.476, -0.155),
        (0.476, 0.155),
        (0.294, 0.405),
        (0.000, 0.500),
        (-0.294, 0.405),
        (-0.476, 0.155),
        (-0.476, -0.155),
        (-0.294, -0.405),
    )
    XY_SPEED = 80.0
    Z_SPEED = 10.0
    FINE_SPEED = 5.0
    CLEARANCE = 5.0
    CENTER_TOLERANCE = 0.015
    CENTER_MAX_DISTANCE = 2.0
    CENTER_MAX_STEP = 0.60
    CENTER_ITERATIONS = 12

    def __init__(self, config):
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object("gcode")
        self.reactor = self.printer.get_reactor()
        self.config = config

        if config.has_section("axiscope"):
            raise config.error(
                "[tool_vision] cannot share probe_multi_axis with [axiscope]"
            )
        if config.has_section("tools_calibrate"):
            raise config.error(
                "[tool_vision] cannot share probe_multi_axis with [tools_calibrate]"
            )

        self.server_url = config.get("server_url", "http://127.0.0.1:8085")
        self.moonraker_url = config.get(
            "moonraker_url", "http://127.0.0.1:7125"
        )
        self.camera_source = config.get("camera_source", None)
        self.camera_name = config.get("camera_name", None)
        self.reference_tool = config.getint("reference_tool", 0, minval=0)
        self.tool_select_command = config.get("tool_select_command", "T{tool}")
        self.pin = config.get("pin", None)

        self.state_file = os.path.expanduser(
            config.get(
                "state_file", "~/printer_data/config/tool_vision_state.json"
            )
        )
        self.result_file = os.path.expanduser(
            config.get(
                "result_file", "~/printer_data/config/tool_vision_results.json"
            )
        )
        self.state_store = StateStore(self.state_file, self.VERSION)
        self.last_error = None
        try:
            self.state = self.state_store.load(self.reference_tool)
            if self.state["reference_tool"] != self.reference_tool:
                raise StateError(
                    "saved reference tool is T%d, config requests T%d"
                    % (self.state["reference_tool"], self.reference_tool)
                )
        except StateError as exc:
            # A corrupt optional learned file must not prevent Klipper startup.
            self.state = self.state_store.empty(self.reference_tool)
            self.last_error = "ignored learned state: %s" % exc

        self.gcode_macro = self.printer.load_object(config, "gcode_macro")
        self.start_gcode = self.gcode_macro.load_template(config, "start_gcode", "")
        self.before_tool_gcode = self.gcode_macro.load_template(
            config, "before_tool_gcode", ""
        )
        # Runs after the requested tool is active and (when TEMP is used) has
        # reached temperature. This is the safe place for a machine-specific
        # nozzle scrubber; its coordinates cannot be inferred by ToolVision.
        self.after_select_gcode = self.gcode_macro.load_template(
            config, "after_select_gcode", ""
        )
        self.after_tool_gcode = self.gcode_macro.load_template(
            config, "after_tool_gcode", ""
        )
        self.finish_gcode = self.gcode_macro.load_template(config, "finish_gcode", "")
        self.abort_gcode = self.gcode_macro.load_template(config, "abort_gcode", "")

        toolchanger_name = config.get("toolchanger_object", "toolchanger")
        self.toolchanger = self.printer.load_object(config, toolchanger_name)
        self.adapter = ToolchangerAdapter(
            self.toolchanger, self.gcode, self.reactor, self.tool_select_command
        )
        self.client = VisionClient(self.server_url, self.reactor)
        self.probe_multi_axis = self._create_probe(config) if self.pin else None
        self.toolhead = None
        self.busy = False
        self.results = {}
        self.last_run = None
        self.last_setup = None
        self.last_observation = None

        self._register_commands()
        self.printer.register_event_handler("klippy:connect", self._handle_connect)

    def _create_probe(self, config):
        """Use the same multi-axis probe primitive as Axiscope/toolchanger."""
        from . import tools_calibrate

        probe = tools_calibrate.PrinterProbeMultiAxis(
            config,
            tools_calibrate.ProbeEndstopWrapper(config, "x"),
            tools_calibrate.ProbeEndstopWrapper(config, "y"),
            tools_calibrate.ProbeEndstopWrapper(config, "z"),
        )
        # Current klipper-toolchanger guidance: 3-5 samples, 0.05 mm for a good
        # contact probe, median/average. Median is more resistant to one bad hit.
        probe.sample_count = 5
        probe.samples_result = "median"
        probe.samples_tolerance = 0.05
        probe.samples_retries = 2
        query_endstops = self.printer.load_object(config, "query_endstops")
        query_endstops.register_endstop(
            probe.mcu_probe[2].mcu_endstop, "ToolVision switch"
        )
        return probe

    def _handle_connect(self):
        self.toolhead = self.printer.lookup_object("toolhead")
        try:
            numbers = self.adapter.tool_numbers()
            if self.reference_tool not in numbers:
                raise ToolVisionError(
                    "reference tool T%d is not assigned" % self.reference_tool
                )
        except (ToolchangerError, ToolVisionError) as exc:
            self.last_error = str(exc)

    def _register_commands(self):
        commands = {
            "TOOL_VISION_STATUS": (
                self.cmd_STATUS,
                "Show learned stations, camera and latest measurements",
            ),
            "TOOL_VISION_SETUP_CAMERA": (
                self.cmd_SETUP_CAMERA,
                "Teach camera position, detector and pixel scale from current T0",
            ),
            "TOOL_VISION_SETUP_SWITCH": (
                self.cmd_SETUP_SWITCH,
                "Teach switch position and reference trigger from current T0",
            ),
            "TOOL_VISION_CALIBRATE": (
                self.cmd_CALIBRATE,
                "Auto-heat, measure relative offsets, then cool every tool",
            ),
            "TOOL_VISION_REPORT": (
                self.cmd_REPORT,
                "Report the latest measured offsets",
            ),
        }
        for name, (handler, description) in commands.items():
            self.gcode.register_command(name, handler, desc=description)

    # ------------------------------------------------------------------
    # Safety and coordinate helpers

    def _assert_ready(self):
        if self.toolhead is None:
            raise ToolVisionError("Klipper is not connected")
        now = self.reactor.monotonic()
        homed = str(self.toolhead.get_status(now).get("homed_axes", ""))
        if not all(axis in homed for axis in "xyz"):
            raise ToolVisionError("home XYZ before using ToolVision")
        print_stats = self.printer.lookup_object("print_stats", None)
        if print_stats is not None:
            state = str(print_stats.get_status(now).get("state", "")).lower()
            if state in ("printing", "paused"):
                raise ToolVisionError("ToolVision is disabled while a print is active")

    def _require_reference_tool(self):
        active = self.adapter.active_tool_number()
        if active != self.reference_tool:
            shown = "none" if active is None else "T%d" % active
            raise ToolVisionError(
                "setup requires T%d already mounted (active: %s)"
                % (self.reference_tool, shown)
            )

    def _axis_limits(self):
        status = self.toolhead.get_kinematics().get_status(self.reactor.monotonic())
        minimum = status.get("axis_minimum")
        maximum = status.get("axis_maximum")
        if minimum is None or maximum is None:
            raise ToolVisionError("kinematics does not expose XYZ limits")

        def values(item):
            if hasattr(item, "x"):
                return [float(item.x), float(item.y), float(item.z)]
            return [float(item[index]) for index in range(3)]

        return values(minimum), values(maximum)

    def _validate_position(self, position):
        minimum, maximum = self._axis_limits()
        for index, axis in enumerate("XYZ"):
            value = float(position[index])
            if not math.isfinite(value) or not minimum[index] <= value <= maximum[index]:
                raise ToolVisionError(
                    "%s target %.3f is outside [%.3f, %.3f]"
                    % (axis, value, minimum[index], maximum[index])
                )

    def _raw_position(self):
        return [float(value) for value in self.toolhead.get_position()[:3]]

    def _move_raw(self, position, speed):
        self._validate_position(position)
        self.toolhead.manual_move(list(position[:3]), float(speed))
        self.toolhead.wait_moves()

    def _safe_z(self, station_z, requested=None):
        _, maximum = self._axis_limits()
        safe_z = min(maximum[2], station_z + self.CLEARANCE)
        if requested is not None:
            safe_z = float(requested)
        if safe_z < station_z + 0.5:
            raise ToolVisionError("SAFE_Z must be at least 0.5 mm above setup Z")
        self._validate_position([self._raw_position()[0], self._raw_position()[1], safe_z])
        return safe_z

    def _approach_offset(self, tool_number):
        result = self.results.get(str(tool_number), {})
        configured = self.adapter.configured_offset(tool_number)
        return [
            float(result.get("x", configured[0]) or 0.0),
            float(result.get("y", configured[1]) or 0.0),
            float(result.get("z", configured[2]) or 0.0),
        ]

    def _move_to_station(self, name, tool_number):
        station = self.state["stations"].get(name)
        if station is None:
            raise ToolVisionError("%s station has not been taught" % name)
        base = list(station["position"])
        offset = self._approach_offset(tool_number)
        target = [base[index] + offset[index] for index in range(3)]
        self._validate_position(target)

        safe_candidates = [float(station["safe_z"])]
        for learned in self.state["stations"].values():
            if isinstance(learned, dict) and "safe_z" in learned:
                safe_candidates.append(float(learned["safe_z"]))
        current = self._raw_position()
        travel_z = max([current[2]] + safe_candidates)
        _, maximum = self._axis_limits()
        travel_z = min(travel_z, maximum[2])
        if current[2] < travel_z - 1e-6:
            self._move_raw([current[0], current[1], travel_z], self.Z_SPEED)
        current = self._raw_position()
        self._move_raw([target[0], target[1], current[2]], self.XY_SPEED)
        self._move_raw(target, self.Z_SPEED)
        return target

    def _settle(self, milliseconds=300):
        self.toolhead.wait_moves()
        self.reactor.pause(
            self.reactor.monotonic() + max(0.0, float(milliseconds) / 1000.0)
        )

    def _switch_triggered(self):
        if self.probe_multi_axis is None:
            raise ToolVisionError("switch support requires pin in [tool_vision]")
        print_time = self.toolhead.get_last_move_time()
        return bool(self.probe_multi_axis.mcu_probe[2].query_endstop(print_time))

    def _run_z_probe(self, gcmd):
        if self._switch_triggered():
            raise ToolVisionError(
                "switch is already triggered; raise the nozzle and check pin polarity"
            )
        start = self._raw_position()
        result = self.probe_multi_axis.run_probe(
            "z-", gcmd, speed_ratio=0.5, max_distance=10.0, samples=5
        )
        trigger_z = float(result[2])
        self._move_raw(start, self.Z_SPEED)
        return trigger_z

    # ------------------------------------------------------------------
    # Host service and camera workflow

    def _server_payload(self, include_learned=True):
        payload = {"moonraker_url": self.moonraker_url}
        if self.camera_source:
            payload["camera_source"] = self.camera_source
        if self.camera_name:
            payload["camera_name"] = self.camera_name
        if include_learned:
            vision = self.state.get("vision", {})
            if vision.get("profile"):
                payload["profile"] = vision["profile"]
            if vision.get("transform"):
                payload["transform"] = vision["transform"]
        return payload

    def _configure_server(self, include_learned=True):
        return self.client.configure(self._server_payload(include_learned))

    def _configure_server_with(self, profile=None, transform=None):
        payload = self._server_payload(include_learned=False)
        if profile is not None:
            payload["profile"] = profile
        if transform is not None:
            payload["transform"] = transform
        return self.client.configure(payload)

    def _detect(self):
        result = self.client.run_job("detect", timeout=18.0)
        observation = result.get("observation")
        if not isinstance(observation, dict):
            raise ToolVisionError("host service returned no nozzle observation")
        self.last_observation = observation
        return observation

    def _calibrate_camera_transform(self, gcmd, initial_observation):
        base = self._raw_position()
        base_pixel = [
            float(initial_observation["x"]),
            float(initial_observation["y"]),
        ]
        samples = []
        try:
            for index, move in enumerate(self.CAMERA_POINTS):
                target = [base[0] + move[0], base[1] + move[1], base[2]]
                self._move_raw(target, self.FINE_SPEED)
                self._settle()
                try:
                    observation = self._detect()
                    samples.append(
                        {
                            "pixel_delta": [
                                float(observation["x"]) - base_pixel[0],
                                float(observation["y"]) - base_pixel[1],
                            ],
                            "machine_delta": list(move),
                        }
                    )
                    gcmd.respond_info(
                        "Camera calibration point %d/10 accepted" % (index + 1)
                    )
                except (ClientError, ToolVisionError) as exc:
                    gcmd.respond_info(
                        "Camera calibration point %d/10 skipped: %s"
                        % (index + 1, exc)
                    )
                self._move_raw(base, self.FINE_SPEED)
        finally:
            if self._within_limits(base):
                self._move_raw(base, self.FINE_SPEED)

        if len(samples) < 8:
            raise ToolVisionError(
                "camera setup needs at least 8/10 stable calibration points; got %d"
                % len(samples)
            )
        payload = {
            "samples": samples,
            "frame_width": int(initial_observation["frame_width"]),
            "frame_height": int(initial_observation["frame_height"]),
            "target_ratio": [0.5, 0.5],
        }
        result = self.client.request(
            "POST", "/api/v2/transform/fit", payload, timeout=8.0
        )
        transform = result.get("transform")
        if not isinstance(transform, dict):
            raise ToolVisionError("host service returned no camera transform")
        return transform

    def _within_limits(self, position):
        try:
            self._validate_position(position)
            return True
        except ToolVisionError:
            return False

    def _center_nozzle(self):
        start = self._raw_position()
        latest = None
        for _ in range(self.CENTER_ITERATIONS):
            self._settle()
            latest = self._detect()
            result = self.client.request(
                "POST",
                "/api/v2/transform/correction",
                {
                    "point": [latest["x"], latest["y"]],
                    "frame_width": latest["frame_width"],
                    "frame_height": latest["frame_height"],
                },
            )
            correction = result.get("correction", {})
            move_x = float(correction.get("move_x", 0.0))
            move_y = float(correction.get("move_y", 0.0))
            distance = math.hypot(move_x, move_y)
            if distance <= self.CENTER_TOLERANCE:
                return self._raw_position(), latest
            scale = min(0.85, self.CENTER_MAX_STEP / max(distance, 1e-12))
            current = self._raw_position()
            target = [
                current[0] + move_x * scale,
                current[1] + move_y * scale,
                current[2],
            ]
            if math.hypot(target[0] - start[0], target[1] - start[1]) > self.CENTER_MAX_DISTANCE:
                raise ToolVisionError(
                    "camera correction exceeded 2 mm; move nozzle nearer center and retry"
                )
            self._move_raw(target, self.FINE_SPEED)
        raise ToolVisionError(
            "nozzle did not converge to camera center within %d iterations"
            % self.CENTER_ITERATIONS
        )

    # ------------------------------------------------------------------
    # Setup and measurement

    def _setup_camera(self, gcmd):
        self._require_reference_tool()
        initial = self._raw_position()
        safe_z = self._safe_z(initial[2], gcmd.get_float("SAFE_Z", None))

        # Do not feed an old profile into learning. The service evaluates all
        # strategies afresh for the camera/nozzle currently in view.
        self._configure_server(include_learned=False)
        learned = self.client.run_job("learn", timeout=25.0)
        profile = learned.get("profile")
        observation = learned.get("observation")
        if not isinstance(profile, dict) or not isinstance(observation, dict):
            raise ToolVisionError("camera learning returned incomplete data")

        self._configure_server_with(profile=profile)
        # Capture a fresh base point after reconfiguration, then preserve the
        # exact ten-position kTAMV motion pattern around it.
        base_observation = self._detect()
        transform = self._calibrate_camera_transform(gcmd, base_observation)
        self._configure_server_with(profile=profile, transform=transform)
        centered, final_observation = self._center_nozzle()
        # Learned state is updated only after every detection, fit and centering
        # check succeeds, so a failed setup cannot mix new and old calibration.
        self.state["vision"] = {"profile": profile, "transform": transform}
        self.state["stations"]["camera"] = {
            "position": centered,
            "safe_z": safe_z,
            "frame_width": int(final_observation["frame_width"]),
            "frame_height": int(final_observation["frame_height"]),
        }
        self.state = self.state_store.save(self.state)
        self.last_setup = "camera"
        self.last_observation = final_observation
        gcmd.respond_info(
            "Camera taught at X%.3f Y%.3f Z%.3f; sharpness %.4f; "
            "transform RMS %.4f mm (%d samples)"
            % (
                centered[0],
                centered[1],
                centered[2],
                float(final_observation.get("sharpness", 0.0)),
                float(transform.get("rms_error_mm", 0.0)),
                int(transform.get("used_samples", 0)),
            )
        )

    def _setup_switch(self, gcmd):
        if self.probe_multi_axis is None:
            raise ToolVisionError("add pin to [tool_vision] before switch setup")
        self._require_reference_tool()
        position = self._raw_position()
        safe_z = self._safe_z(position[2], gcmd.get_float("SAFE_Z", None))
        trigger_z = self._run_z_probe(gcmd)
        self.state["stations"]["switch"] = {
            "position": position,
            "safe_z": safe_z,
            "trigger_z": trigger_z,
        }
        self.state = self.state_store.save(self.state)
        self.last_setup = "switch"
        gcmd.respond_info(
            "Switch taught at X%.3f Y%.3f, approach Z%.3f, trigger Z%.5f"
            % (position[0], position[1], position[2], trigger_z)
        )

    def _measure_xy(self, tool_number, reference_position=None):
        self._move_to_station("camera", tool_number)
        centered, observation = self._center_nozzle()
        result = self.results.setdefault(str(tool_number), {})
        result.update(
            {
                "center_position": centered,
                "xy_confidence": float(observation.get("confidence", 0.0)),
                "xy_stability_px": float(observation.get("stability_px", 0.0)),
            }
        )
        if reference_position is None:
            result.update({"x": 0.0, "y": 0.0})
            return centered
        result.update(
            {
                "x": centered[0] - reference_position[0],
                "y": centered[1] - reference_position[1],
            }
        )
        return reference_position

    def _measure_z(self, gcmd, tool_number, reference_trigger=None):
        self._move_to_station("switch", tool_number)
        trigger = self._run_z_probe(gcmd)
        result = self.results.setdefault(str(tool_number), {})
        result["trigger_z"] = trigger
        if reference_trigger is None:
            result["z"] = 0.0
            return trigger
        result["z"] = trigger - reference_trigger
        return reference_trigger

    def _set_all_tool_temperatures(self, tools, temperature):
        """Set every tool without waiting, following Axiscope's M104 pattern."""
        for number in tools:
            self.gcode.run_script_from_command(
                "M104 T%d S%.1f" % (int(number), float(temperature))
            )

    def _wait_for_active_tool_temperature(self, temperature):
        """Wait only after pickup, when Klipper knows the active extruder."""
        self.gcode.run_script_from_command("M109 S%.1f" % float(temperature))

    def _cool_all_tools(self, gcmd, tools):
        """Best-effort cleanup which must not hide an earlier calibration error."""
        for number in tools:
            try:
                self.gcode.run_script_from_command("M104 T%d S0" % int(number))
            except Exception as exc:
                gcmd.respond_info(
                    "Warning: could not turn off T%d heater: %s" % (number, exc)
                )

    def _calibrate_all(
        self, gcmd, mode, temperature=DEFAULT_CALIBRATION_TEMPERATURE
    ):
        mode = mode.upper()
        if mode not in ("XY", "Z", "XYZ"):
            raise ToolVisionError("MODE must be XY, Z, or XYZ")
        temperature = float(temperature)
        if not math.isfinite(temperature) or temperature < 0.0:
            raise ToolVisionError("TEMP must be a finite value of 0 or higher")
        if "X" in mode and "camera" not in self.state["stations"]:
            raise ToolVisionError("run TOOL_VISION_SETUP_CAMERA first")
        if "Z" in mode:
            if self.probe_multi_axis is None:
                raise ToolVisionError("Z calibration requires pin in [tool_vision]")
            if "switch" not in self.state["stations"]:
                raise ToolVisionError("run TOOL_VISION_SETUP_SWITCH first")

        tools = self.adapter.tool_numbers()
        tools = [self.reference_tool] + [
            number for number in tools if number != self.reference_tool
        ]
        original_tool = self.adapter.active_tool_number()
        self.results = {}
        reference_xy = None
        reference_z = None
        try:
            self._run_template(self.start_gcode, self.reference_tool)
            try:
                if temperature > 0.0:
                    # Axiscope's documented workflow preheats every tool to
                    # 150 C. Setting all targets first lets parked tools warm
                    # in parallel; M109 still verifies each mounted tool.
                    self._set_all_tool_temperatures(tools, temperature)
                    gcmd.respond_info(
                        "Preheating %d tools to %.1f C"
                        % (len(tools), temperature)
                    )
                for number in tools:
                    self._run_template(self.before_tool_gcode, number)
                    self.adapter.select(number)
                    if temperature > 0.0:
                        self._wait_for_active_tool_temperature(temperature)
                    self._run_template(self.after_select_gcode, number)
                    if "X" in mode:
                        reference_xy = self._measure_xy(number, reference_xy)
                    if "Z" in mode:
                        reference_z = self._measure_z(gcmd, number, reference_z)
                    self._run_template(self.after_tool_gcode, number)
                    result = self.results[str(number)]
                    gcmd.respond_info(
                        "T%d measured: X%s Y%s Z%s"
                        % (
                            number,
                            self._format_value(result.get("x")),
                            self._format_value(result.get("y")),
                            self._format_value(result.get("z")),
                        )
                    )
            except Exception:
                self._run_template(
                    self.abort_gcode, self.adapter.active_tool_number()
                )
                raise
            finally:
                if original_tool is not None:
                    try:
                        self.adapter.select(original_tool)
                    except Exception:
                        pass
            self._run_template(self.finish_gcode, original_tool)
        finally:
            if temperature > 0.0:
                # This is deliberately outside the finish hook: cleanup runs
                # after it and also covers start/measure/finish exceptions.
                self._cool_all_tools(gcmd, tools)
        self.last_run = time.time()
        payload = {
            "schema_version": 1,
            "tool_vision_version": self.VERSION,
            "measured": self.last_run,
            "mode": mode,
            "temperature": temperature,
            "reference_tool": self.reference_tool,
            "offsets": self.results,
            "note": "report only; offsets were not applied automatically",
        }
        atomic_write_json(self.result_file, payload)
        self._report(gcmd)

    @staticmethod
    def _format_value(value):
        return "--" if value is None else "%+.5f" % float(value)

    def _report(self, gcmd):
        if not self.results:
            gcmd.respond_info("No measurements in this Klipper session")
            return
        lines = [
            "ToolVision relative offsets (reference T%d, report only):"
            % self.reference_tool
        ]
        for number in sorted(int(value) for value in self.results):
            result = self.results[str(number)]
            lines.append(
                "T%d  X=%s  Y=%s  Z=%s"
                % (
                    number,
                    self._format_value(result.get("x")),
                    self._format_value(result.get("y")),
                    self._format_value(result.get("z")),
                )
            )
        lines.append("Saved: %s" % self.result_file)
        gcmd.respond_info("\n".join(lines))

    def _run_template(self, template, tool_number):
        if template is None:
            return
        template.run_gcode_from_command(
            {"tool": -1 if tool_number is None else int(tool_number)}
        )

    def _guard(self, gcmd, callback):
        if self.busy:
            raise gcmd.error("ToolVision is already running")
        self.busy = True
        self.last_error = None
        try:
            self._assert_ready()
            self.gcode.run_script_from_command(
                "SAVE_GCODE_STATE NAME=tool_vision_runtime"
            )
            callback()
        except (ToolVisionError, ToolchangerError, ClientError, StateError) as exc:
            self.last_error = str(exc)
            raise gcmd.error(str(exc))
        except Exception as exc:
            self.last_error = str(exc)
            raise
        finally:
            try:
                self.gcode.run_script_from_command(
                    "RESTORE_GCODE_STATE NAME=tool_vision_runtime MOVE=0"
                )
            except Exception:
                pass
            self.busy = False

    # ------------------------------------------------------------------
    # G-code commands and status

    def cmd_SETUP_CAMERA(self, gcmd):
        self._guard(gcmd, lambda: self._setup_camera(gcmd))

    def cmd_SETUP_SWITCH(self, gcmd):
        self._guard(gcmd, lambda: self._setup_switch(gcmd))

    def cmd_CALIBRATE(self, gcmd):
        mode = gcmd.get("MODE", "XYZ")
        temperature = gcmd.get_float(
            "TEMP", self.DEFAULT_CALIBRATION_TEMPERATURE, minval=0.0
        )
        self._guard(
            gcmd, lambda: self._calibrate_all(gcmd, mode, temperature)
        )

    def cmd_REPORT(self, gcmd):
        self._report(gcmd)

    def cmd_STATUS(self, gcmd):
        stations = self.state.get("stations", {})
        vision = self.state.get("vision", {})
        try:
            server = self.client.request("GET", "/api/v2/health", timeout=2.0)
            service_text = "online %s" % server.get("version", "")
            camera = server.get("camera") or {}
            if camera.get("name"):
                service_text += ", camera %s" % camera["name"]
        except ClientError as exc:
            service_text = "offline (%s)" % exc
        gcmd.respond_info(
            "ToolVision %s\nService: %s\nCamera setup: %s\nSwitch setup: %s\n"
            "Detector learned: %s\nTransform calibrated: %s\nLast error: %s"
            % (
                self.VERSION,
                service_text,
                "yes" if "camera" in stations else "no",
                "yes" if "switch" in stations else "no",
                "yes" if vision.get("profile") else "no",
                "yes" if vision.get("transform") else "no",
                self.last_error or "none",
            )
        )

    def get_status(self, eventtime=None):
        vision = self.state.get("vision", {})
        return {
            "version": self.VERSION,
            "busy": self.busy,
            "reference_tool": self.reference_tool,
            "camera_ready": "camera" in self.state.get("stations", {}),
            "switch_ready": "switch" in self.state.get("stations", {}),
            "detector_learned": bool(vision.get("profile")),
            "transform_calibrated": bool(vision.get("transform")),
            "last_setup": self.last_setup,
            "last_run": self.last_run,
            "last_error": self.last_error,
            "results": self.results,
        }


def load_config(config):
    return ToolVision(config)
