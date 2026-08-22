from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from klippy.extras.tool_vision import ToolVision, ToolVisionError


class OffsetSignTests(unittest.TestCase):
    def test_camera_points_match_ktamv_ten_point_half_mm_pattern(self):
        self.assertEqual(len(ToolVision.CAMERA_POINTS), 10)
        self.assertEqual(ToolVision.CAMERA_POINTS[0], (0.0, -0.5))
        self.assertEqual(ToolVision.CAMERA_POINTS[5], (0.0, 0.5))

    def test_xy_offset_is_centered_raw_position_minus_reference(self):
        vision = object.__new__(ToolVision)
        vision.results = {}
        vision._move_to_station = lambda *args: None
        vision._center_nozzle = lambda: (
            [100.2, 199.7, 8.0],
            {"confidence": 0.9, "stability_px": 0.4},
        )
        vision._measure_xy(1, [100.0, 200.0, 8.0])
        self.assertAlmostEqual(vision.results["1"]["x"], 0.2)
        self.assertAlmostEqual(vision.results["1"]["y"], -0.3)

    def test_z_offset_is_trigger_minus_reference(self):
        vision = object.__new__(ToolVision)
        vision.results = {}
        vision._move_to_station = lambda *args: None
        vision._run_z_probe = lambda gcmd: 7.2
        vision._measure_z(object(), 1, 7.0)
        self.assertAlmostEqual(vision.results["1"]["z"], 0.2)


class SafeTravelTests(unittest.TestCase):
    def test_station_travel_lifts_then_moves_xy_then_descends(self):
        vision = object.__new__(ToolVision)
        vision.state = {
            "stations": {
                "camera": {"position": [120.0, 80.0, 6.0], "safe_z": 15.0},
                "switch": {"position": [60.0, 10.0, 8.0], "safe_z": 18.0},
            }
        }
        vision.results = {}
        vision.adapter = type(
            "Adapter", (), {"configured_offset": lambda self, tool: [0.2, -0.1, 0.05]}
        )()
        positions = [[10.0, 20.0, 4.0]]
        moves = []
        vision._raw_position = lambda: list(positions[-1])
        vision._axis_limits = lambda: ([0, 0, 0], [300, 300, 250])
        vision._validate_position = lambda position: None

        def move(position, speed):
            positions.append(list(position))
            moves.append((list(position), speed))

        vision._move_raw = move
        target = vision._move_to_station("camera", 1)
        self.assertEqual(target, [120.2, 79.9, 6.05])
        self.assertEqual(
            [item[0] for item in moves],
            [
                [10.0, 20.0, 18.0],
                [120.2, 79.9, 18.0],
                [120.2, 79.9, 6.05],
            ],
        )

    def test_missing_station_fails_before_motion(self):
        vision = object.__new__(ToolVision)
        vision.state = {"stations": {}}
        with self.assertRaises(ToolVisionError):
            vision._move_to_station("camera", 0)


class CameraCenteringTests(unittest.TestCase):
    @staticmethod
    def make_centering_vision(observations, corrections):
        vision = object.__new__(ToolVision)
        position = [100.0, 100.0, 5.0]
        observation_iterator = iter(observations)
        correction_iterator = iter(corrections)
        vision._raw_position = lambda: list(position)
        vision._settle = lambda: None
        vision._detect = lambda: next(observation_iterator)

        class Client:
            @staticmethod
            def request(*args, **kwargs):
                return {"correction": next(correction_iterator)}

        vision.client = Client()

        def move(target, speed):
            position[:] = target

        vision._move_raw = move
        return vision

    def test_centering_rejects_frame_that_does_not_reflect_commanded_move(self):
        vision = self.make_centering_vision(
            [
                {
                    "x": 600.0,
                    "y": 360.0,
                    "frame_width": 1280,
                    "frame_height": 720,
                    "stability_px": 0.1,
                },
                {
                    "x": 600.0,
                    "y": 360.0,
                    "frame_width": 1280,
                    "frame_height": 720,
                    "stability_px": 0.1,
                },
            ],
            [
                {
                    "move_x": 0.1,
                    "move_y": 0.0,
                    "distance_mm": 0.1,
                    "estimated_uncertainty_mm": 0.005,
                },
                {
                    "move_x": 0.1,
                    "move_y": 0.0,
                    "distance_mm": 0.1,
                    "estimated_uncertainty_mm": 0.005,
                },
            ],
        )
        with self.assertRaisesRegex(ToolVisionError, "fresh|commanded move"):
            vision._center_nozzle()

    def test_centering_accepts_a_fresh_frame_that_reaches_target(self):
        vision = self.make_centering_vision(
            [
                {
                    "x": 600.0,
                    "y": 360.0,
                    "frame_width": 1280,
                    "frame_height": 720,
                    "stability_px": 0.1,
                },
                {
                    "x": 639.5,
                    "y": 360.0,
                    "frame_width": 1280,
                    "frame_height": 720,
                    "stability_px": 0.1,
                },
            ],
            [
                {
                    "move_x": 0.1,
                    "move_y": 0.0,
                    "distance_mm": 0.1,
                    "estimated_uncertainty_mm": 0.005,
                },
                {
                    "move_x": 0.001,
                    "move_y": 0.0,
                    "distance_mm": 0.001,
                    "estimated_uncertainty_mm": 0.005,
                },
            ],
        )
        centered, observation = vision._center_nozzle()
        self.assertGreater(centered[0], 100.0)
        self.assertEqual(observation["x"], 639.5)

    def test_centering_rejects_incomplete_host_correction(self):
        vision = self.make_centering_vision(
            [
                {
                    "x": 640.0,
                    "y": 360.0,
                    "frame_width": 1280,
                    "frame_height": 720,
                    "stability_px": 0.1,
                }
            ],
            [{"move_x": 0.0, "move_y": 0.0}],
        )
        with self.assertRaisesRegex(ToolVisionError, "incomplete"):
            vision._center_nozzle()

    def test_centering_includes_uncertainty_in_acceptance_gate(self):
        vision = self.make_centering_vision(
            [
                {
                    "x": 630.0,
                    "y": 360.0,
                    "frame_width": 1280,
                    "frame_height": 720,
                    "stability_px": 0.1,
                },
                {
                    "x": 639.8,
                    "y": 360.0,
                    "frame_width": 1280,
                    "frame_height": 720,
                    "stability_px": 0.1,
                },
            ],
            [
                {
                    "move_x": 0.010,
                    "move_y": 0.0,
                    "estimated_uncertainty_mm": 0.010,
                },
                {
                    "move_x": 0.001,
                    "move_y": 0.0,
                    "estimated_uncertainty_mm": 0.005,
                },
            ],
        )
        centered, _ = vision._center_nozzle()
        self.assertGreater(centered[0], 100.0)


class ThermalCalibrationTests(unittest.TestCase):
    class FakeGcode:
        def __init__(self, events):
            self.events = events

        def run_script_from_command(self, command):
            self.events.append(("gcode", command))

    class FakeCommand:
        def __init__(self, events):
            self.events = events

        def respond_info(self, message):
            self.events.append(("info", message))

    class FakeAdapter:
        def __init__(self, events):
            self.events = events
            self.active = 0

        def tool_numbers(self):
            return [0, 1]

        def active_tool_number(self):
            return self.active

        def select(self, number):
            self.active = number
            self.events.append(("select", number))

    def make_vision(self, result_file):
        events = []
        vision = object.__new__(ToolVision)
        vision.reference_tool = 0
        vision.state = {"stations": {"switch": {}}}
        vision.probe_multi_axis = object()
        vision.adapter = self.FakeAdapter(events)
        vision.gcode = self.FakeGcode(events)
        vision.start_gcode = "start"
        vision.before_tool_gcode = "before"
        vision.after_select_gcode = "after_select"
        vision.after_tool_gcode = "after"
        vision.finish_gcode = "finish"
        vision.abort_gcode = "abort"
        vision.result_file = str(result_file)
        vision.last_run = None
        vision.results = {}
        vision._run_template = lambda template, tool: events.append(
            ("template", template, tool)
        )
        vision._report = lambda gcmd: events.append(("report",))
        return vision, events

    def test_heated_calibration_preheats_waits_after_pickup_and_cools(self):
        with TemporaryDirectory() as directory:
            vision, events = self.make_vision(Path(directory) / "results.json")

            def measure(gcmd, number, reference):
                events.append(("measure", number))
                vision.results[str(number)] = {"z": 0.0}
                return 1.0 if reference is None else reference

            vision._measure_z = measure
            vision._calibrate_all(self.FakeCommand(events), "Z", 150.0)

        self.assertEqual(
            [event for event in events if event[0] == "gcode"],
            [
                ("gcode", "M104 T0 S150.0"),
                ("gcode", "M104 T1 S150.0"),
                ("gcode", "M109 S150.0"),
                ("gcode", "M109 S150.0"),
                ("gcode", "M104 T0 S0"),
                ("gcode", "M104 T1 S0"),
            ],
        )
        for number in (0, 1):
            self.assertLess(
                events.index(("select", number)),
                events.index(("template", "after_select", number)),
            )
            self.assertLess(
                events.index(("template", "after_select", number)),
                events.index(("measure", number)),
            )
        self.assertLess(
            events.index(("template", "finish", 0)),
            events.index(("gcode", "M104 T0 S0")),
        )

    def test_heaters_are_turned_off_when_measurement_fails(self):
        with TemporaryDirectory() as directory:
            vision, events = self.make_vision(Path(directory) / "results.json")

            def fail_measure(gcmd, number, reference):
                vision.results[str(number)] = {"z": 0.0}
                if number == 1:
                    raise RuntimeError("probe failure")
                return 1.0

            vision._measure_z = fail_measure
            with self.assertRaisesRegex(RuntimeError, "probe failure"):
                vision._calibrate_all(self.FakeCommand(events), "Z", 150.0)

        self.assertIn(("template", "abort", 1), events)
        self.assertIn(("gcode", "M104 T0 S0"), events)
        self.assertIn(("gcode", "M104 T1 S0"), events)

    def test_xy_rehydrates_host_before_any_heating_or_toolchange(self):
        with TemporaryDirectory() as directory:
            vision, events = self.make_vision(Path(directory) / "results.json")
            vision.state["stations"]["camera"] = {}
            vision.state["vision"] = {
                "profile": {"schema_version": 1},
                "transform": {"schema_version": 2},
            }
            vision._configure_server = lambda include_learned=True: events.append(
                ("configure", include_learned)
            )

            def measure(number, reference):
                events.append(("measure_xy", number))
                vision.results[str(number)] = {"x": 0.0, "y": 0.0}
                return [100.0, 100.0, 5.0]

            vision._measure_xy = measure
            vision._calibrate_all(self.FakeCommand(events), "XY", 150.0)

        self.assertEqual(events[0], ("configure", True))
        self.assertLess(
            events.index(("configure", True)),
            events.index(("gcode", "M104 T0 S150.0")),
        )
        self.assertLess(
            events.index(("configure", True)), events.index(("select", 0))
        )

    def test_old_transform_schema_fails_before_heating(self):
        with TemporaryDirectory() as directory:
            vision, events = self.make_vision(Path(directory) / "results.json")
            vision.state["stations"]["camera"] = {}
            vision.state["vision"] = {
                "profile": {"schema_version": 1},
                "transform": {"schema_version": 1},
            }
            with self.assertRaisesRegex(ToolVisionError, "older safety schema"):
                vision._calibrate_all(self.FakeCommand(events), "XY", 150.0)

        self.assertFalse(any(event[0] == "gcode" for event in events))
        self.assertFalse(any(event[0] == "select" for event in events))

    def test_console_command_defaults_to_axiscope_temperature(self):
        captured = []
        vision = object.__new__(ToolVision)
        vision._guard = lambda gcmd, callback: callback()
        vision._calibrate_all = lambda gcmd, mode, temperature: captured.append(
            (mode, temperature)
        )

        class Command:
            def get(self, name, default):
                return default

            def get_float(self, name, default, minval=None):
                return default

        vision.cmd_CALIBRATE(Command())
        self.assertEqual(
            captured, [("XYZ", ToolVision.DEFAULT_CALIBRATION_TEMPERATURE)]
        )


if __name__ == "__main__":
    unittest.main()
