import json
import tempfile
import unittest
from pathlib import Path

from klippy.extras.tool_vision import ToolVision, ToolVisionError


class FakeConfig:
    @staticmethod
    def error(message):
        return ValueError(message)


class ConfigurationSafetyTests(unittest.TestCase):
    @staticmethod
    def _instance(tool_numbers=None):
        numbers = [0, 1] if tool_numbers is None else list(tool_numbers)
        vision = object.__new__(ToolVision)
        vision.camera_rotation = 0
        vision.camera_mode = "auto"
        vision.detector_mode = "auto"
        vision.station_mode = "auto"
        vision.detector_polarity = "auto"
        vision.camera_model = "affine"
        vision.detector_min_area_ratio = 0.001
        vision.detector_max_area_ratio = 0.1
        vision.camera_roi_x_min = 0.1
        vision.camera_roi_y_min = 0.1
        vision.camera_roi_x_max = 0.9
        vision.camera_roi_y_max = 0.9
        vision.reference_tool = 0
        vision.camera_z = 6.0
        vision.camera_safe_z = 15.0
        vision.zswitch_z = 7.0
        vision.zswitch_lift_z = 2.0
        vision.zswitch_approach_z = 9.0
        vision.zswitch_safe_z = 15.0
        vision.camera_center_tolerance = 0.01
        vision.camera_center_max_correction = 2.0
        vision.configured_tool_numbers = numbers
        vision._tool_numbers = lambda: list(numbers)
        return vision

    def test_valid_portable_configuration_passes_safety_validation(self):
        self._instance()._validate_config(FakeConfig())

    def test_station_safe_z_cannot_be_below_measurement_z(self):
        vision = self._instance()
        vision.camera_safe_z = 5.0
        with self.assertRaises(ValueError):
            vision._validate_config(FakeConfig())

    def test_duplicate_tool_numbers_are_rejected(self):
        vision = self._instance([0, 1, 1])
        with self.assertRaises(ValueError):
            vision._validate_config(FakeConfig())

    def test_dynamic_tool_discovery_is_deferred_until_connect(self):
        vision = self._instance()
        vision.configured_tool_numbers = None
        vision._tool_numbers = lambda: []
        vision._validate_config(FakeConfig())

    def test_empty_discovered_tool_list_is_rejected_after_connect(self):
        vision = self._instance()
        with self.assertRaises(ValueError):
            vision._validate_tool_numbers(FakeConfig.error, [])


class SafeStationMotionTests(unittest.TestCase):
    @staticmethod
    def _instance(current_z):
        vision = object.__new__(ToolVision)
        vision.camera_x = 120.0
        vision.camera_y = 80.0
        vision.camera_z = 6.0
        vision.camera_safe_z = 15.0
        vision.zswitch_x = 68.0
        vision.zswitch_y = -10.0
        vision.zswitch_z = 7.0
        vision.zswitch_approach_z = 9.0
        vision.zswitch_safe_z = 15.0
        vision.zswitch_lift_z = 2.0
        vision.xy_travel_speed = 100.0
        vision.z_travel_speed = 10.0
        vision._gcode_position = lambda: [10.0, 20.0, current_z]
        vision._validate_target = lambda *args, **kwargs: None
        vision._settle = lambda: None
        moves = []
        vision._move = lambda **kwargs: moves.append(kwargs)
        return vision, moves

    def test_low_z_is_lifted_before_xy_travel(self):
        vision, moves = self._instance(current_z=4.0)
        vision._move_to_station("camera")
        self.assertEqual(
            moves,
            [
                {"z": 15.0, "speed": 10.0},
                {"x": 120.0, "y": 80.0, "speed": 100.0},
                {"z": 6.0, "speed": 10.0},
            ],
        )

    def test_existing_higher_z_is_preserved_until_after_xy_travel(self):
        vision, moves = self._instance(current_z=22.0)
        vision._move_to_station("camera")
        self.assertEqual(
            moves,
            [
                {"x": 120.0, "y": 80.0, "speed": 100.0},
                {"z": 6.0, "speed": 10.0},
            ],
        )

    def test_incomplete_camera_station_fails_before_motion(self):
        vision, moves = self._instance(current_z=10.0)
        vision.camera_x = None
        with self.assertRaises(ToolVisionError):
            vision._move_to_station("camera")
        self.assertEqual(moves, [])

    def test_automatic_safe_z_uses_clearance_and_clamps_to_machine_limit(self):
        vision = object.__new__(ToolVision)
        vision.setup_clearance = 5.0
        vision._axis_limits = lambda: ((0.0, 300.0), (0.0, 300.0), (0.0, 20.0))
        vision._validate_target = lambda **kwargs: None
        self.assertEqual(vision._automatic_safe_z(8.0), 13.0)
        self.assertEqual(vision._automatic_safe_z(18.0), 20.0)


class LearnedSetupTests(unittest.TestCase):
    @staticmethod
    def _state_instance(path):
        vision = object.__new__(ToolVision)
        vision.state_file = str(path)
        vision.detector_mode = "auto"
        vision.station_mode = "auto"
        vision.last_error = None
        vision.learned_state = {}
        vision.camera_x = None
        vision.camera_y = None
        vision.camera_z = None
        vision.camera_safe_z = None
        vision.zswitch_x = None
        vision.zswitch_y = None
        vision.zswitch_z = None
        vision.zswitch_approach_z = None
        vision.zswitch_safe_z = None
        for key, attribute in ToolVision.DETECTOR_ATTRIBUTES.items():
            if key == "detector_polarity":
                value = "auto"
            elif key in (
                "detector_adaptive_block_size",
                "detector_blur_size",
                "detection_stable_frames",
                "detection_frame_interval_ms",
            ):
                value = 3
            else:
                value = 1.0
            setattr(vision, attribute, value)
        return vision

    def test_taught_stations_and_detector_survive_restart(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            payload = {
                "schema_version": 1,
                "stations": {
                    "camera": {"x": 120, "y": 80, "z": 6, "safe_z": 11},
                    "zswitch": {
                        "x": 68,
                        "y": -10,
                        "trigger_z": 7.2,
                        "approach_z": 9,
                        "safe_z": 14,
                    },
                },
                "detector_settings": {"detector_sensitivity": 1.4},
            }
            path.write_text(json.dumps(payload), encoding="utf-8")
            vision = self._state_instance(path)
            vision.camera_x = 999.0

            vision._load_learned_state()

            self.assertEqual(
                (vision.camera_x, vision.camera_y, vision.camera_z),
                (120.0, 80.0, 6.0),
            )
            self.assertEqual(vision.zswitch_approach_z, 9.0)
            self.assertEqual(vision.detector_sensitivity, 1.4)

    def test_switch_setup_uses_current_position_and_verified_trigger(self):
        class Gcmd:
            @staticmethod
            def get_int(name, default, **kwargs):
                return default

            @staticmethod
            def get_float(name, default):
                return default

            @staticmethod
            def respond_info(message):
                return None

        vision = object.__new__(ToolVision)
        vision.probe_multi_axis = object()
        vision.toolhead = type(
            "Toolhead", (), {"get_position": staticmethod(lambda: [68.0, -10.0, 9.0])}
        )()
        vision.reference_tool = 0
        vision.probe_samples = 10
        vision.probe_max_distance = 10.0
        vision.learned_state = {}
        vision.last_setup = None
        vision._require_setup_tool = lambda gcmd: 0
        vision._gcode_position = lambda: [68.0, -10.0, 9.0]
        vision._automatic_safe_z = lambda z, requested: 14.0
        vision._run_z_probe = lambda samples: 7.25
        vision._save_learned_state = lambda: None

        station = vision._setup_zswitch(Gcmd())

        self.assertEqual(station["approach_z"], 9.0)
        self.assertEqual(station["trigger_z"], 7.25)
        self.assertEqual(vision.zswitch_lift_z, 1.75)
        self.assertEqual(vision.last_setup, "zswitch")

    def test_camera_setup_persists_centered_station_and_learned_detector(self):
        class Gcmd:
            @staticmethod
            def get_int(name, default, **kwargs):
                return default

            @staticmethod
            def get_float(name, default):
                return default

            @staticmethod
            def respond_info(message):
                return None

        vision = self._state_instance(Path("unused.json"))
        vision.reference_tool = 0
        vision.detection_timeout = 1.0
        vision.camera_x = None
        vision.camera_y = None
        vision.camera_z = None
        vision.camera_safe_z = None
        vision.camera_transform = {}
        vision.last_setup = None
        vision._require_setup_tool = lambda gcmd: 0
        configured = []
        vision._configure_server = lambda: configured.append(True)
        observation = {
            "focus_ok": True,
            "focus_grade": "clear",
            "focus_score": 0.04,
            "confidence": 0.9,
            "diameter_px": 30.0,
            "frame_width": 1280,
            "frame_height": 720,
        }
        learned = {"detector_sensitivity": 1.25}
        vision._api = lambda *args, **kwargs: {
            "observation": observation,
            "learned_settings": learned,
        }
        positions = iter(([120.0, 80.0, 6.0], [120.2, 79.9, 6.0]))
        vision._gcode_position = lambda: list(next(positions))
        vision._automatic_safe_z = lambda z, requested: 11.0
        vision._calibrate_camera = lambda gcmd: setattr(
            vision, "camera_transform", {"calibrated": True}
        )
        vision._center_nozzle = lambda gcmd: (
            [120.2, 79.9, 6.0],
            {"confidence": 0.95},
        )
        vision._save_learned_state = lambda: None

        result = vision._setup_camera(Gcmd())

        self.assertEqual(len(configured), 2)
        self.assertEqual((vision.camera_x, vision.camera_y), (120.2, 79.9))
        self.assertEqual(vision.camera_safe_z, 11.0)
        self.assertEqual(vision.detector_sensitivity, 1.25)
        self.assertTrue(result["transform"]["calibrated"])
        self.assertEqual(vision.last_setup, "camera")


class OffsetSignTests(unittest.TestCase):
    def test_xy_delta_matches_ktamv_raw_position_direction(self):
        vision = object.__new__(ToolVision)
        vision.results = {}
        vision.xy_reference = [100.0, 200.0]
        vision._select_tool = lambda tool_number: None
        vision._center_nozzle = lambda gcmd: (
            [100.2, 199.7, 6.0],
            {"confidence": 0.9, "stdev_x": 0.2, "stdev_y": 0.3},
        )

        result = vision._measure_xy(object(), 1, set_reference=False)
        self.assertEqual(result["x"], 0.2)
        self.assertEqual(result["y"], -0.3)

    def test_z_delta_matches_axiscope_trigger_direction(self):
        class Probe:
            @staticmethod
            def run_probe(*args, **kwargs):
                return [0.0, 0.0, 7.2]

        class Toolhead:
            def __init__(self):
                self.returned = False

            @staticmethod
            def get_position():
                return [68.0, -10.0, 9.0]

            def move(self, position, speed):
                self.returned = (position, speed)

            @staticmethod
            def set_position(position):
                return None

            @staticmethod
            def wait_moves():
                return None

        vision = object.__new__(ToolVision)
        vision.probe_multi_axis = Probe()
        vision.toolhead = Toolhead()
        vision.results = {}
        vision.z_reference = 7.0
        vision.z_travel_speed = 5.0
        vision.probe_speed_ratio = 0.5
        vision.probe_max_distance = 10.0
        vision.probe_samples = 5
        vision._active_gcmd = object()
        vision._select_tool = lambda tool_number: None
        vision._move_to_station = lambda station: None

        result = vision._measure_z(1, set_reference=False)
        self.assertEqual(result["z"], 0.2)
        self.assertEqual(vision.toolhead.returned, ([68.0, -10.0, 9.0], 5.0))


if __name__ == "__main__":
    unittest.main()
