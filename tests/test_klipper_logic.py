import unittest

from klippy.extras.tool_vision import ToolVision, ToolVisionError


class FakeConfig:
    @staticmethod
    def error(message):
        return ValueError(message)


class ConfigurationSafetyTests(unittest.TestCase):
    @staticmethod
    def _instance(tool_numbers=None):
        vision = object.__new__(ToolVision)
        vision.camera_rotation = 0
        vision.camera_mode = "auto"
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
        vision.zswitch_safe_z = 15.0
        vision.camera_center_tolerance = 0.01
        vision.camera_center_max_correction = 2.0
        vision._tool_numbers = lambda: list(tool_numbers or [0, 1])
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
