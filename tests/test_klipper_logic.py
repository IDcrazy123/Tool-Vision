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


if __name__ == "__main__":
    unittest.main()
