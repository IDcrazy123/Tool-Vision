import unittest

import cv2
import numpy as np

from server.camera import CameraSource
from server.detection import NozzleDetector


class NativeResolutionDetectionTests(unittest.TestCase):
    @staticmethod
    def _settings():
        return {
            "camera_target_x_ratio": 0.5,
            "camera_target_y_ratio": 0.5,
            "camera_roi_x_min": 0.1,
            "camera_roi_y_min": 0.1,
            "camera_roi_x_max": 0.9,
            "camera_roi_y_max": 0.9,
            "detector_polarity": "dark",
            "detector_min_area_ratio": 0.0001,
            "detector_max_area_ratio": 0.02,
            "detector_min_circularity": 0.6,
            "detector_min_convexity": 0.6,
            "detector_min_inertia": 0.6,
            "detector_min_confidence": 0.2,
            "detector_sensitivity": 1.0,
            "detection_stable_frames": 1,
        }

    def test_detector_uses_actual_1280x720_frame(self):
        frame = np.full((720, 1280, 3), 255, dtype=np.uint8)
        cv2.circle(frame, (640, 360), 20, (0, 0, 0), -1)
        detector = NozzleDetector(self._settings(), lambda *args: None)
        result, annotated = detector.detect_frame(frame)
        self.assertIsNotNone(result)
        self.assertEqual(result["frame_width"], 1280)
        self.assertEqual(result["frame_height"], 720)
        self.assertAlmostEqual(result["x"], 640, delta=2)
        self.assertAlmostEqual(result["y"], 360, delta=2)
        self.assertEqual(annotated.shape, frame.shape)

    def test_detector_uses_actual_800x600_frame(self):
        frame = np.full((600, 800, 3), 255, dtype=np.uint8)
        cv2.circle(frame, (400, 300), 16, (0, 0, 0), -1)
        detector = NozzleDetector(self._settings(), lambda *args: None)
        result, annotated = detector.detect_frame(frame)
        self.assertIsNotNone(result)
        self.assertEqual((result["frame_width"], result["frame_height"]), (800, 600))
        self.assertEqual(annotated.shape, frame.shape)

    def test_rotation_swaps_native_dimensions_without_resize(self):
        source = CameraSource(
            {"camera_source": "0", "camera_mode": "opencv", "camera_rotation": 90},
            lambda *args: None,
        )
        frame = np.zeros((600, 800, 3), dtype=np.uint8)
        transformed = source._transform(frame)
        self.assertEqual(transformed.shape, (800, 600, 3))
        source.close()

    def test_focus_score_rejects_a_blurred_reference_nozzle(self):
        sharp = np.full((600, 800, 3), 255, dtype=np.uint8)
        cv2.circle(sharp, (400, 300), 28, (0, 0, 0), -1)
        blurry = cv2.GaussianBlur(sharp, (0, 0), 4.0)
        detector = NozzleDetector(self._settings(), lambda *args: None)

        sharp_result, _ = detector.detect_frame(sharp)
        blurry_result, _ = detector.detect_frame(blurry)

        self.assertIsNotNone(sharp_result)
        self.assertIsNotNone(blurry_result)
        self.assertTrue(sharp_result["focus_ok"])
        self.assertGreater(
            sharp_result["focus_score"], blurry_result["focus_score"] * 5
        )
        self.assertFalse(blurry_result["focus_ok"])

    def test_learned_profile_brackets_the_taught_nozzle_area(self):
        frame = np.full((720, 1280, 3), 255, dtype=np.uint8)
        cv2.circle(frame, (640, 360), 24, (0, 0, 0), -1)
        detector = NozzleDetector(self._settings(), lambda *args: None)
        observation, _ = detector.detect_frame(frame)

        learned = detector.recommended_settings(observation)
        area_ratio = observation["area_px"] / (1280.0 * 720.0)
        self.assertLess(learned["detector_min_area_ratio"], area_ratio)
        self.assertGreater(learned["detector_max_area_ratio"], area_ratio)
        self.assertEqual(learned["detector_polarity"], "dark")


if __name__ == "__main__":
    unittest.main()
