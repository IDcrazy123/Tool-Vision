"""Portable XYZ tool-offset measurement for Klipper toolchangers.

The host service owns camera I/O, OpenCV detection, and NumPy fitting. This
Klipper extension owns motion, switch probing, tool selection, and reporting.
No production tool offset is modified automatically.
"""

import json
import math
import os
import time
import urllib.error
import urllib.request


class ToolVisionError(RuntimeError):
    """User-facing Tool Vision failure."""


class ToolVision:
    VERSION = "2.0.0"
    STATE_NAME = "TOOL_VISION_STATE"

    def __init__(self, config):
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object("gcode")
        self.gcode_move = self.printer.load_object(config, "gcode_move")
        self.config = config

        if config.has_section("axiscope"):
            raise config.error(
                "[tool_vision] conflicts with [axiscope]; both allocate "
                "probe_multi_axis"
            )
        if config.has_section("tools_calibrate"):
            raise config.error(
                "[tool_vision] conflicts with [tools_calibrate]; both allocate "
                "probe_multi_axis"
            )

        self.server_url = config.get("server_url", "http://127.0.0.1:8085").rstrip("/")
        self.camera_source = config.get("camera_source")
        self.camera_mode = config.get("camera_mode", "auto").lower()
        self.camera_rotation = config.getint("camera_rotation", 0)
        self.camera_flip_x = config.getboolean("camera_flip_x", False)
        self.camera_flip_y = config.getboolean("camera_flip_y", False)
        self.camera_width = config.getint("camera_width", 0, minval=0)
        self.camera_height = config.getint("camera_height", 0, minval=0)
        self.camera_fps = config.getfloat("camera_fps", 0.0, minval=0.0)
        self.camera_connect_timeout = config.getfloat(
            "camera_connect_timeout", 2.0, above=0.0
        )
        self.camera_read_timeout = config.getfloat(
            "camera_read_timeout", 5.0, above=0.0
        )
        self.camera_max_frame_bytes = config.getint(
            "camera_max_frame_bytes", 8388608, minval=65536
        )
        self.camera_warmup_frames = config.getint(
            "camera_warmup_frames", 0, minval=0
        )

        self.camera_x = config.getfloat("camera_x_pos", None)
        self.camera_y = config.getfloat("camera_y_pos", None)
        self.camera_z = config.getfloat("camera_z_pos", None)
        self.camera_safe_z = config.getfloat("camera_safe_z", None)
        self.camera_target_x_ratio = config.getfloat(
            "camera_target_x_ratio", 0.5, minval=0.0, maxval=1.0
        )
        self.camera_target_y_ratio = config.getfloat(
            "camera_target_y_ratio", 0.5, minval=0.0, maxval=1.0
        )
        self.camera_roi_x_min = config.getfloat(
            "camera_roi_x_min", 0.0, minval=0.0, maxval=1.0
        )
        self.camera_roi_y_min = config.getfloat(
            "camera_roi_y_min", 0.0, minval=0.0, maxval=1.0
        )
        self.camera_roi_x_max = config.getfloat(
            "camera_roi_x_max", 1.0, minval=0.0, maxval=1.0
        )
        self.camera_roi_y_max = config.getfloat(
            "camera_roi_y_max", 1.0, minval=0.0, maxval=1.0
        )

        self.detector_gamma = config.getfloat(
            "detector_gamma", 1.0, above=0.0
        )
        self.detector_sensitivity = config.getfloat(
            "detector_sensitivity", 1.0, minval=0.25, maxval=4.0
        )
        self.detector_min_area_ratio = config.getfloat(
            "detector_min_area_ratio", 0.0002, above=0.0, below=1.0
        )
        self.detector_max_area_ratio = config.getfloat(
            "detector_max_area_ratio", 0.08, above=0.0, below=1.0
        )
        self.detector_min_circularity = config.getfloat(
            "detector_min_circularity", 0.55, minval=0.0, maxval=1.0
        )
        self.detector_min_convexity = config.getfloat(
            "detector_min_convexity", 0.45, minval=0.0, maxval=1.0
        )
        self.detector_min_inertia = config.getfloat(
            "detector_min_inertia", 0.35, minval=0.0, maxval=1.0
        )
        self.detector_min_confidence = config.getfloat(
            "detector_min_confidence", 0.35, minval=0.0, maxval=1.0
        )
        self.detector_adaptive_block_size = config.getint(
            "detector_adaptive_block_size", 35, minval=3
        )
        self.detector_adaptive_c = config.getfloat("detector_adaptive_c", 3.0)
        self.detector_blur_size = config.getint(
            "detector_blur_size", 5, minval=3
        )
        self.detector_polarity = config.get("detector_polarity", "auto").lower()
        self.detection_stable_frames = config.getint(
            "detection_stable_frames", 3, minval=1
        )
        self.detection_stability_px = config.getfloat(
            "detection_stability_px", 2.0, minval=0.0
        )
        self.detection_stability_ratio = config.getfloat(
            "detection_stability_ratio", 0.0, minval=0.0, maxval=1.0
        )
        self.detection_timeout = config.getfloat(
            "detection_timeout", 12.0, above=0.0
        )
        self.detection_frame_interval_ms = config.getint(
            "detection_frame_interval_ms", 120, minval=0
        )

        self.reference_tool = config.getint("reference_tool", 0, minval=0)
        self.tool_select_command = config.get("tool_select_command", "T{tool}")
        configured_tools = config.get("tool_numbers", "").strip()
        self.configured_tool_numbers = None
        if configured_tools:
            try:
                self.configured_tool_numbers = [
                    int(value.strip()) for value in configured_tools.split(",")
                    if value.strip()
                ]
            except ValueError:
                raise config.error("tool_numbers must be comma-separated integers")

        self.xy_travel_speed = config.getfloat(
            "xy_travel_speed", 100.0, above=0.0
        )
        self.z_travel_speed = config.getfloat(
            "z_travel_speed", 10.0, above=0.0
        )
        self.camera_move_speed = config.getfloat(
            "camera_move_speed", 20.0, above=0.0
        )
        self.camera_fine_speed = config.getfloat(
            "camera_fine_speed", 5.0, above=0.0
        )
        self.camera_settle_ms = config.getint("camera_settle_ms", 350, minval=0)
        self.camera_calibration_radius = config.getfloat(
            "camera_calibration_radius", 0.6, above=0.0
        )
        self.camera_calibration_points = config.getint(
            "camera_calibration_points", 10, minval=4, maxval=32
        )
        self.camera_model = config.get("camera_model", "affine").lower()
        self.camera_max_rms_error = config.getfloat(
            "camera_max_rms_error", 0.08, above=0.0
        )
        self.camera_center_tolerance = config.getfloat(
            "camera_center_tolerance", 0.01, above=0.0
        )
        self.camera_center_max_iterations = config.getint(
            "camera_center_max_iterations", 12, minval=1, maxval=50
        )
        self.camera_center_max_correction = config.getfloat(
            "camera_center_max_correction", 2.0, above=0.0
        )
        self.camera_center_max_step = config.getfloat(
            "camera_center_max_step", 0.6, above=0.0
        )
        self.camera_center_damping = config.getfloat(
            "camera_center_damping", 0.8, above=0.0, maxval=1.0
        )

        self.pin = config.get("pin", None)
        self.zswitch_x = config.getfloat("zswitch_x_pos", None)
        self.zswitch_y = config.getfloat("zswitch_y_pos", None)
        self.zswitch_z = config.getfloat("zswitch_z_pos", None)
        self.zswitch_safe_z = config.getfloat("zswitch_safe_z", None)
        self.zswitch_lift_z = config.getfloat(
            "zswitch_lift_z", 2.0, minval=0.0
        )
        self.probe_speed_ratio = config.getfloat(
            "probe_speed_ratio", 0.5, above=0.0, maxval=1.0
        )
        self.probe_max_distance = config.getfloat(
            "probe_max_distance", 10.0, above=0.0
        )
        self.probe_samples = config.getint("probe_samples", 10, minval=1)

        self.allow_during_print = config.getboolean("allow_during_print", False)
        self.result_file = os.path.expanduser(
            config.get(
                "result_file",
                "~/printer_data/config/tool_vision_results.json",
            )
        )

        self.gcode_macro = self.printer.load_object(config, "gcode_macro")
        self.start_gcode = self.gcode_macro.load_template(
            config, "start_gcode", ""
        )
        self.before_tool_gcode = self.gcode_macro.load_template(
            config, "before_tool_gcode", ""
        )
        self.after_tool_gcode = self.gcode_macro.load_template(
            config, "after_tool_gcode", ""
        )
        self.finish_gcode = self.gcode_macro.load_template(
            config, "finish_gcode", ""
        )
        self.abort_gcode = self.gcode_macro.load_template(
            config, "abort_gcode", ""
        )

        self.probe_multi_axis = None
        if self.pin is not None:
            from . import tools_calibrate
            self.probe_multi_axis = tools_calibrate.PrinterProbeMultiAxis(
                config,
                tools_calibrate.ProbeEndstopWrapper(config, "x"),
                tools_calibrate.ProbeEndstopWrapper(config, "y"),
                tools_calibrate.ProbeEndstopWrapper(config, "z"),
            )
            query_endstops = self.printer.load_object(config, "query_endstops")
            query_endstops.register_endstop(
                self.probe_multi_axis.mcu_probe[-1].mcu_endstop,
                "ToolVision",
            )

        toolchanger_name = config.get("toolchanger_object", "toolchanger")
        self.toolchanger = self.printer.load_object(config, toolchanger_name)
        self.reactor = self.printer.get_reactor()
        self.toolhead = None
        self.busy = False
        self.server_configured = False
        self.camera_calibrated = False
        self.camera_transform = {}
        self.xy_reference = None
        self.z_reference = None
        self.results = {}
        self.last_observation = None
        self.last_error = None
        self.last_run = None

        self._validate_config(config)
        self._register_commands()
        self.printer.register_event_handler("klippy:connect", self._handle_connect)

    def _validate_config(self, config):
        if self.camera_rotation not in (0, 90, 180, 270):
            raise config.error("camera_rotation must be 0, 90, 180, or 270")
        if self.camera_mode not in ("auto", "http", "opencv"):
            raise config.error("camera_mode must be auto, http, or opencv")
        if self.detector_polarity not in ("auto", "dark", "light"):
            raise config.error("detector_polarity must be auto, dark, or light")
        if self.camera_model not in ("affine", "quadratic"):
            raise config.error("camera_model must be affine or quadratic")
        if self.detector_min_area_ratio >= self.detector_max_area_ratio:
            raise config.error("detector_min_area_ratio must be below max")
        if not (
            self.camera_roi_x_min < self.camera_roi_x_max
            and self.camera_roi_y_min < self.camera_roi_y_max
        ):
            raise config.error("camera ROI minimums must be below maximums")
        tool_numbers = self._tool_numbers()
        if not tool_numbers:
            raise config.error("tool_numbers cannot be empty")
        if any(tool < 0 for tool in tool_numbers):
            raise config.error("tool_numbers cannot contain negative values")
        if len(tool_numbers) != len(set(tool_numbers)):
            raise config.error("tool_numbers cannot contain duplicates")
        if self.reference_tool not in tool_numbers:
            raise config.error("reference_tool is not present in tool_numbers")
        if (
            self.camera_z is not None
            and self.camera_safe_z is not None
            and self.camera_safe_z < self.camera_z
        ):
            raise config.error("camera_safe_z must be at or above camera_z_pos")
        if (
            self.zswitch_z is not None
            and self.zswitch_safe_z is not None
            and self.zswitch_safe_z < self.zswitch_z + self.zswitch_lift_z
        ):
            raise config.error(
                "zswitch_safe_z must be at or above the switch approach Z"
            )
        if self.camera_center_tolerance > self.camera_center_max_correction:
            raise config.error(
                "camera_center_tolerance cannot exceed max correction"
            )

    def _handle_connect(self):
        self.toolhead = self.printer.lookup_object("toolhead")
        self.gcode.respond_info(
            "Tool Vision %s loaded in report-only mode" % self.VERSION
        )

    def _register_commands(self):
        commands = {
            "TV_STATUS": (self.cmd_STATUS, "Show Tool Vision status"),
            "TV_SERVER_CONFIGURE": (
                self.cmd_SERVER_CONFIGURE,
                "Send camera and detector configuration to the host service",
            ),
            "TV_CAMERA_CHECK": (
                self.cmd_CAMERA_CHECK,
                "Detect the nozzle at the current position",
            ),
            "TV_MOVE_TO_CAMERA": (
                self.cmd_MOVE_TO_CAMERA,
                "Move safely to the configured camera station",
            ),
            "TV_MOVE_TO_ZSWITCH": (
                self.cmd_MOVE_TO_ZSWITCH,
                "Move safely to the configured Z switch",
            ),
            "TV_CALIBRATE_CAMERA": (
                self.cmd_CALIBRATE_CAMERA,
                "Calibrate native camera pixels to machine XY movement",
            ),
            "TV_MEASURE_XY": (
                self.cmd_MEASURE_XY,
                "Measure one tool XY offset relative to the reference",
            ),
            "TV_MEASURE_Z": (
                self.cmd_MEASURE_Z,
                "Measure one tool Z offset relative to the reference",
            ),
            "TV_CALIBRATE_ALL": (
                self.cmd_CALIBRATE_ALL,
                "Measure all tool offsets; MODE=XYZ, XY, or Z",
            ),
            "TV_REPORT": (self.cmd_REPORT, "Report measured offsets"),
        }
        for name, item in commands.items():
            self.gcode.register_command(name, item[0], desc=item[1])

    # HTTP API

    def _api(self, method, path, payload=None, timeout=3.0):
        url = self.server_url + path
        data = None
        headers = {"Accept": "application/json"}
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            url, data=data, headers=headers, method=method
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            try:
                message = json.loads(body).get("error", body)
            except ValueError:
                message = body
            raise ToolVisionError("vision server HTTP %d: %s" % (exc.code, message))
        except (urllib.error.URLError, OSError) as exc:
            raise ToolVisionError("vision server unavailable: %s" % exc)
        try:
            result = json.loads(body)
        except ValueError:
            raise ToolVisionError("vision server returned invalid JSON")
        if not result.get("ok", False):
            raise ToolVisionError(result.get("error", "vision server request failed"))
        return result

    def _server_payload(self):
        return {
            "camera_source": self.camera_source,
            "camera_mode": self.camera_mode,
            "camera_rotation": self.camera_rotation,
            "camera_flip_x": self.camera_flip_x,
            "camera_flip_y": self.camera_flip_y,
            "camera_width": self.camera_width,
            "camera_height": self.camera_height,
            "camera_fps": self.camera_fps,
            "camera_connect_timeout": self.camera_connect_timeout,
            "camera_read_timeout": self.camera_read_timeout,
            "camera_max_frame_bytes": self.camera_max_frame_bytes,
            "camera_warmup_frames": self.camera_warmup_frames,
            "camera_target_x_ratio": self.camera_target_x_ratio,
            "camera_target_y_ratio": self.camera_target_y_ratio,
            "camera_roi_x_min": self.camera_roi_x_min,
            "camera_roi_y_min": self.camera_roi_y_min,
            "camera_roi_x_max": self.camera_roi_x_max,
            "camera_roi_y_max": self.camera_roi_y_max,
            "detector_gamma": self.detector_gamma,
            "detector_sensitivity": self.detector_sensitivity,
            "detector_min_area_ratio": self.detector_min_area_ratio,
            "detector_max_area_ratio": self.detector_max_area_ratio,
            "detector_min_circularity": self.detector_min_circularity,
            "detector_min_convexity": self.detector_min_convexity,
            "detector_min_inertia": self.detector_min_inertia,
            "detector_min_confidence": self.detector_min_confidence,
            "detector_adaptive_block_size": self.detector_adaptive_block_size,
            "detector_adaptive_c": self.detector_adaptive_c,
            "detector_blur_size": self.detector_blur_size,
            "detector_polarity": self.detector_polarity,
            "detection_stable_frames": self.detection_stable_frames,
            "detection_stability_px": self.detection_stability_px,
            "detection_stability_ratio": self.detection_stability_ratio,
            "detection_timeout": self.detection_timeout,
            "detection_frame_interval_ms": self.detection_frame_interval_ms,
        }

    def _configure_server(self):
        result = self._api("POST", "/api/v1/config", self._server_payload())
        self.server_configured = True
        self.camera_calibrated = False
        self.camera_transform = result.get("transform", {})
        return result

    def _detect(self):
        if not self.server_configured:
            self._configure_server()
        response = self._api("POST", "/api/v1/jobs/detect", {})
        job_id = response["job"]["job_id"]
        deadline = time.monotonic() + self.detection_timeout + 10.0
        while time.monotonic() < deadline:
            job = self._api(
                "GET", "/api/v1/jobs/%s" % job_id, timeout=2.0
            )["job"]
            if job["state"] == "complete":
                self.last_observation = job["result"]
                return job["result"]
            if job["state"] == "error":
                raise ToolVisionError(job.get("error") or "nozzle detection failed")
            self.reactor.pause(self.reactor.monotonic() + 0.15)
        raise ToolVisionError("nozzle detection job timed out")

    # Motion and safety

    def _tool_numbers(self):
        if self.configured_tool_numbers is not None:
            return list(self.configured_tool_numbers)
        return [int(value) for value in self.toolchanger.tool_numbers]

    def _active_tool_number(self):
        active = getattr(self.toolchanger, "active_tool", None)
        if active is None:
            raise ToolVisionError("toolchanger has no active tool")
        return int(active.tool_number)

    def _assert_homed(self):
        eventtime = self.reactor.monotonic()
        homed = self.toolhead.get_kinematics().get_status(eventtime)["homed_axes"]
        if not all(axis in homed for axis in "xyz"):
            raise ToolVisionError("home X, Y, and Z before running Tool Vision")

    def _assert_idle(self):
        if self.allow_during_print:
            return
        print_stats = self.printer.lookup_object("print_stats", None)
        if print_stats is not None:
            status = print_stats.get_status(self.reactor.monotonic())
            state = str(status.get("state", ""))
            if state.lower() in ("printing", "paused"):
                raise ToolVisionError("Tool Vision is disabled during a print")

    def _station_ready(self, station):
        if station == "camera":
            values = (self.camera_x, self.camera_y, self.camera_z, self.camera_safe_z)
        else:
            values = (
                self.zswitch_x,
                self.zswitch_y,
                self.zswitch_z,
                self.zswitch_safe_z,
            )
        return all(value is not None for value in values)

    def _axis_limits(self):
        status = self.toolhead.get_status(self.reactor.monotonic())
        minimum = status.get("axis_minimum")
        maximum = status.get("axis_maximum")
        if minimum is None or maximum is None:
            return None
        return (
            (float(minimum.x), float(maximum.x)),
            (float(minimum.y), float(maximum.y)),
            (float(minimum.z), float(maximum.z)),
        )

    def _validate_target(self, x=None, y=None, z=None):
        limits = self._axis_limits()
        if limits is None:
            return
        for index, item in enumerate((x, y, z)):
            if item is None:
                continue
            if item < limits[index][0] or item > limits[index][1]:
                raise ToolVisionError(
                    "%s target %.3f is outside %.3f..%.3f"
                    % ("XYZ"[index], item, limits[index][0], limits[index][1])
                )

    def _gcode_position(self):
        pos = self.gcode_move.get_status()["gcode_position"]
        return [float(pos.x), float(pos.y), float(pos.z)]

    def _raw_position(self):
        pos = self.gcode_move.get_status()["position"]
        return [float(pos.x), float(pos.y), float(pos.z)]

    def _move(self, x=None, y=None, z=None, speed=None):
        self._validate_target(x, y, z)
        fields = []
        for axis, value in (("X", x), ("Y", y), ("Z", z)):
            if value is not None:
                fields.append("%s%.5f" % (axis, value))
        if not fields:
            return
        fields.append("F%.1f" % ((speed or self.xy_travel_speed) * 60.0))
        self.gcode.run_script_from_command("G1 " + " ".join(fields))
        self.toolhead.wait_moves()

    def _move_to_station(self, station):
        if not self._station_ready(station):
            raise ToolVisionError("%s station coordinates are incomplete" % station)
        current = self._gcode_position()
        if station == "camera":
            x, y, z, safe_z = (
                self.camera_x,
                self.camera_y,
                self.camera_z,
                self.camera_safe_z,
            )
        else:
            x, y, z, safe_z = (
                self.zswitch_x,
                self.zswitch_y,
                self.zswitch_z + self.zswitch_lift_z,
                self.zswitch_safe_z,
            )
        travel_z = max(current[2], safe_z)
        self._validate_target(x, y, z)
        self._validate_target(z=travel_z)
        if current[2] < travel_z:
            self._move(z=travel_z, speed=self.z_travel_speed)
        self._move(x=x, y=y, speed=self.xy_travel_speed)
        self._move(z=z, speed=self.z_travel_speed)
        self._settle()

    def _settle(self):
        if self.camera_settle_ms > 0:
            self.reactor.pause(
                self.reactor.monotonic() + self.camera_settle_ms / 1000.0
            )

    def _select_tool(self, tool_number):
        tool_number = int(tool_number)
        if tool_number not in self._tool_numbers():
            raise ToolVisionError("tool T%d is not configured" % tool_number)
        if getattr(self.toolchanger, "active_tool", None) is not None:
            if self._active_tool_number() == tool_number:
                return
        self._run_template(self.before_tool_gcode, tool_number)
        try:
            command = self.tool_select_command.format(
                tool=tool_number, reference_tool=self.reference_tool
            )
        except (KeyError, ValueError) as exc:
            raise ToolVisionError("invalid tool_select_command: %s" % exc)
        self.gcode.run_script_from_command(command)
        self.toolhead.wait_moves()
        if self._active_tool_number() != tool_number:
            raise ToolVisionError("toolchanger did not activate T%d" % tool_number)
        self._run_template(self.after_tool_gcode, tool_number)

    # Measurement primitives

    def _calibrate_camera(self, gcmd):
        self._move_to_station("camera")
        baseline = self._detect()
        base_gcode = self._gcode_position()
        base_raw = self._raw_position()
        frame_width = int(baseline["frame_width"])
        frame_height = int(baseline["frame_height"])
        samples = []

        point_count = self.camera_calibration_points
        if self.camera_model == "quadratic" and point_count < 8:
            raise ToolVisionError("quadratic camera_model requires at least 8 points")
        for index in range(point_count):
            angle = (2.0 * math.pi * index) / point_count
            dx = self.camera_calibration_radius * math.cos(angle)
            dy = self.camera_calibration_radius * math.sin(angle)
            self._move(
                x=base_gcode[0] + dx,
                y=base_gcode[1] + dy,
                speed=self.camera_move_speed,
            )
            self._settle()
            observation = self._detect()
            if (
                int(observation["frame_width"]) != frame_width
                or int(observation["frame_height"]) != frame_height
            ):
                raise ToolVisionError("camera resolution changed during calibration")
            raw = self._raw_position()
            pixel_delta = [
                float(observation["x"]) - float(baseline["x"]),
                float(observation["y"]) - float(baseline["y"]),
            ]
            if math.hypot(pixel_delta[0], pixel_delta[1]) < 0.5:
                raise ToolVisionError(
                    "camera did not observe calibration move %d" % (index + 1)
                )
            samples.append(
                {
                    "pixel_delta": pixel_delta,
                    "machine_delta": [raw[0] - base_raw[0], raw[1] - base_raw[1]],
                }
            )
            gcmd.respond_info(
                "Camera point %d/%d: dpx=(%.2f, %.2f)"
                % (index + 1, point_count, pixel_delta[0], pixel_delta[1])
            )
            self._move(
                x=base_gcode[0],
                y=base_gcode[1],
                speed=self.camera_move_speed,
            )

        target = [float(baseline["target_x"]), float(baseline["target_y"])]
        response = self._api(
            "POST",
            "/api/v1/model",
            {
                "model": self.camera_model,
                "samples": samples,
                "target": target,
                "frame_width": frame_width,
                "frame_height": frame_height,
                "max_rms_error": self.camera_max_rms_error,
            },
        )
        self.camera_transform = response["transform"]
        self.camera_calibrated = True
        gcmd.respond_info(
            "Camera calibrated at %dx%d: RMS %.4fmm, condition %.1f"
            % (
                frame_width,
                frame_height,
                self.camera_transform["rms_error"],
                self.camera_transform["condition"],
            )
        )
        return self.camera_transform

    def _center_nozzle(self, gcmd):
        if not self.camera_calibrated:
            raise ToolVisionError("run TV_CALIBRATE_CAMERA first")
        self._move_to_station("camera")
        for iteration in range(1, self.camera_center_max_iterations + 1):
            observation = self._detect()
            correction = self._api(
                "POST",
                "/api/v1/offset",
                {
                    "point": [observation["x"], observation["y"]],
                    "frame_width": observation["frame_width"],
                    "frame_height": observation["frame_height"],
                },
            )["correction"]
            distance = float(correction["distance_mm"])
            gcmd.respond_info(
                "Center %d/%d: move=(%.4f, %.4f) distance=%.4fmm"
                % (
                    iteration,
                    self.camera_center_max_iterations,
                    correction["move_x"],
                    correction["move_y"],
                    distance,
                )
            )
            if distance <= self.camera_center_tolerance:
                return self._raw_position(), observation
            if distance > self.camera_center_max_correction:
                raise ToolVisionError(
                    "camera correction %.3fmm exceeds safety limit %.3fmm"
                    % (distance, self.camera_center_max_correction)
                )
            scale = self.camera_center_damping
            if distance * scale > self.camera_center_max_step:
                scale = self.camera_center_max_step / distance
            current = self._gcode_position()
            self._move(
                x=current[0] + correction["move_x"] * scale,
                y=current[1] + correction["move_y"] * scale,
                speed=self.camera_fine_speed,
            )
            self._settle()
        raise ToolVisionError("nozzle did not converge to the camera target")

    def _measure_xy(self, gcmd, tool_number, set_reference=False):
        self._select_tool(tool_number)
        raw, observation = self._center_nozzle(gcmd)
        if set_reference:
            self.xy_reference = [raw[0], raw[1]]
            offset = [0.0, 0.0]
        else:
            if self.xy_reference is None:
                raise ToolVisionError("measure the XY reference tool first")
            offset = [
                raw[0] - self.xy_reference[0],
                raw[1] - self.xy_reference[1],
            ]
        result = self.results.setdefault(str(tool_number), {})
        result.update(
            {
                "x": round(offset[0], 5),
                "y": round(offset[1], 5),
                "xy_raw": [round(raw[0], 5), round(raw[1], 5)],
                "xy_confidence": round(float(observation["confidence"]), 4),
                "xy_stdev": [
                    round(float(observation["stdev_x"]), 4),
                    round(float(observation["stdev_y"]), 4),
                ],
            }
        )
        return result

    def _measure_z(self, tool_number, set_reference=False):
        if self.probe_multi_axis is None:
            raise ToolVisionError("Z switch pin is not configured")
        self._select_tool(tool_number)
        self._move_to_station("zswitch")
        start_pos = self.toolhead.get_position()
        try:
            measured = self.probe_multi_axis.run_probe(
                "z-",
                self._active_gcmd,
                speed_ratio=self.probe_speed_ratio,
                max_distance=self.probe_max_distance,
                samples=self.probe_samples,
            )[2]
        finally:
            self.toolhead.move(start_pos, self.z_travel_speed)
            self.toolhead.set_position(start_pos)
            self.toolhead.wait_moves()
        if set_reference:
            self.z_reference = float(measured)
            offset = 0.0
        else:
            if self.z_reference is None:
                raise ToolVisionError("measure the Z reference tool first")
            offset = float(measured) - self.z_reference
        result = self.results.setdefault(str(tool_number), {})
        result.update(
            {
                "z": round(offset, 5),
                "z_trigger": round(float(measured), 5),
            }
        )
        return result

    # Command orchestration

    def _run_guarded(self, gcmd, callback):
        if self.busy:
            raise gcmd.error("Tool Vision is already running")
        self.busy = True
        self._active_gcmd = gcmd
        state_saved = False
        self.last_error = None
        try:
            self._assert_idle()
            self._assert_homed()
            self.gcode.run_script_from_command(
                "SAVE_GCODE_STATE NAME=%s" % self.STATE_NAME
            )
            state_saved = True
            self.gcode.run_script_from_command("G90")
            return callback()
        except Exception as exc:
            self.last_error = str(exc)
            try:
                self._run_template(self.abort_gcode, self._safe_active_tool())
            except Exception:
                pass
            if isinstance(exc, self.printer.command_error):
                raise
            raise gcmd.error("Tool Vision: %s" % exc)
        finally:
            if state_saved:
                try:
                    self.gcode.run_script_from_command(
                        "RESTORE_GCODE_STATE NAME=%s MOVE=0" % self.STATE_NAME
                    )
                except Exception:
                    pass
            self._active_gcmd = None
            self.busy = False

    def _safe_active_tool(self):
        try:
            return self._active_tool_number()
        except Exception:
            return self.reference_tool

    def _run_template(self, template, tool_number):
        if not template:
            return
        eventtime = self.reactor.monotonic()
        context = template.create_template_context()
        context.update(
            {
                "tool_number": tool_number,
                "reference_tool": self.reference_tool,
                "toolchanger": self.toolchanger.get_status(eventtime),
                "tool_vision": self.get_status(eventtime),
            }
        )
        template.run_gcode_from_command(context)

    def _run_all(self, gcmd, mode):
        mode = mode.upper()
        if mode not in ("XYZ", "XY", "Z"):
            raise ToolVisionError("MODE must be XYZ, XY, or Z")
        if mode in ("XYZ", "XY") and not self._station_ready("camera"):
            raise ToolVisionError("camera station coordinates are incomplete")
        if mode in ("XYZ", "Z"):
            if self.probe_multi_axis is None or not self._station_ready("zswitch"):
                raise ToolVisionError("Z switch configuration is incomplete")

        self.results = {}
        self.xy_reference = None
        self.z_reference = None
        self.last_run = time.time()
        self._run_template(self.start_gcode, self.reference_tool)
        self._select_tool(self.reference_tool)
        if mode in ("XYZ", "XY"):
            self._configure_server()
            self._calibrate_camera(gcmd)
            self._measure_xy(gcmd, self.reference_tool, set_reference=True)
        if mode in ("XYZ", "Z"):
            self._measure_z(self.reference_tool, set_reference=True)

        for tool_number in self._tool_numbers():
            if tool_number == self.reference_tool:
                continue
            gcmd.respond_info("Measuring T%d (%s)..." % (tool_number, mode))
            if mode in ("XYZ", "XY"):
                self._measure_xy(gcmd, tool_number, set_reference=False)
            if mode in ("XYZ", "Z"):
                self._measure_z(tool_number, set_reference=False)

        self._select_tool(self.reference_tool)
        self._run_template(self.finish_gcode, self.reference_tool)
        self._save_results(mode)
        self._report(gcmd)

    def _save_results(self, mode):
        if not self.result_file:
            return
        parent = os.path.dirname(self.result_file)
        if parent and not os.path.isdir(parent):
            os.makedirs(parent)
        payload = {
            "schema_version": 1,
            "tool_vision_version": self.VERSION,
            "timestamp": self.last_run,
            "mode": mode,
            "reference_tool": self.reference_tool,
            "camera_transform": self.camera_transform,
            "results": self.results,
        }
        temporary = self.result_file + ".tmp"
        with open(temporary, "w") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temporary, self.result_file)

    def _report(self, gcmd):
        gcmd.respond_info("=== Tool Vision measured offsets (report only) ===")
        for tool_number in self._tool_numbers():
            result = self.results.get(str(tool_number), {})
            values = []
            for axis in "xyz":
                if axis in result:
                    values.append("%s=%+.5f" % (axis.upper(), result[axis]))
            if values:
                gcmd.respond_info("T%d %s" % (tool_number, " ".join(values)))
            if tool_number != self.reference_tool and all(
                axis in result for axis in "xyz"
            ):
                gcmd.respond_info(
                    "Suggested: SET_TOOL_PARAMETER T=%d "
                    "PARAMETER=gcode_x_offset VALUE=%.5f"
                    % (tool_number, result["x"])
                )
                gcmd.respond_info(
                    "Suggested: SET_TOOL_PARAMETER T=%d "
                    "PARAMETER=gcode_y_offset VALUE=%.5f"
                    % (tool_number, result["y"])
                )
                gcmd.respond_info(
                    "Suggested: SET_TOOL_PARAMETER T=%d "
                    "PARAMETER=gcode_z_offset VALUE=%.5f"
                    % (tool_number, result["z"])
                )
        if self.result_file:
            gcmd.respond_info("Results file: %s" % self.result_file)

    # GCode handlers

    def cmd_STATUS(self, gcmd):
        try:
            health = self._api("GET", "/api/v1/health", timeout=2.0)
            server = "configured=%s busy=%s" % (
                health["configured"], health["busy"]
            )
        except Exception as exc:
            server = "unavailable (%s)" % exc
        gcmd.respond_info(
            "Tool Vision %s: busy=%s server=%s results=%d last_error=%s"
            % (
                self.VERSION,
                self.busy,
                server,
                len(self.results),
                self.last_error or "none",
            )
        )

    def cmd_SERVER_CONFIGURE(self, gcmd):
        result = self._configure_server()
        gcmd.respond_info(
            "Vision server configured; native frame size will be detected on capture"
        )
        return result

    def cmd_CAMERA_CHECK(self, gcmd):
        observation = self._detect()
        gcmd.respond_info(
            "Nozzle: X%.2f Y%.2f frame=%dx%d confidence=%.3f stdev=(%.2f, %.2f)"
            % (
                observation["x"],
                observation["y"],
                observation["frame_width"],
                observation["frame_height"],
                observation["confidence"],
                observation["stdev_x"],
                observation["stdev_y"],
            )
        )

    def cmd_MOVE_TO_CAMERA(self, gcmd):
        return self._run_guarded(gcmd, lambda: self._move_to_station("camera"))

    def cmd_MOVE_TO_ZSWITCH(self, gcmd):
        return self._run_guarded(gcmd, lambda: self._move_to_station("zswitch"))

    def cmd_CALIBRATE_CAMERA(self, gcmd):
        def work():
            self._select_tool(gcmd.get_int("TOOL", self.reference_tool))
            self._configure_server()
            return self._calibrate_camera(gcmd)
        return self._run_guarded(gcmd, work)

    def cmd_MEASURE_XY(self, gcmd):
        tool_number = gcmd.get_int("TOOL", self._safe_active_tool())
        set_reference = bool(gcmd.get_int("REFERENCE", 0, minval=0, maxval=1))
        return self._run_guarded(
            gcmd,
            lambda: self._measure_xy(gcmd, tool_number, set_reference),
        )

    def cmd_MEASURE_Z(self, gcmd):
        tool_number = gcmd.get_int("TOOL", self._safe_active_tool())
        set_reference = bool(gcmd.get_int("REFERENCE", 0, minval=0, maxval=1))
        return self._run_guarded(
            gcmd,
            lambda: self._measure_z(tool_number, set_reference),
        )

    def cmd_CALIBRATE_ALL(self, gcmd):
        mode = gcmd.get("MODE", "XYZ")
        return self._run_guarded(gcmd, lambda: self._run_all(gcmd, mode))

    def cmd_REPORT(self, gcmd):
        self._report(gcmd)

    def get_status(self, eventtime=None):
        return {
            "version": self.VERSION,
            "busy": self.busy,
            "server_configured": self.server_configured,
            "camera_calibrated": self.camera_calibrated,
            "camera_transform": self.camera_transform,
            "last_observation": self.last_observation,
            "results": self.results,
            "reference_tool": self.reference_tool,
            "tool_numbers": self._tool_numbers(),
            "last_error": self.last_error,
            "last_run": self.last_run,
            "result_file": self.result_file,
        }


def load_config(config):
    return ToolVision(config)
