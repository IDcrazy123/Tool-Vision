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

    def test_adaptive_threshold_scales_down_for_a_small_roi(self):
        settings = self._settings()
        settings.update(
            {
                "camera_roi_x_min": 0.40,
                "camera_roi_y_min": 0.35,
                "camera_roi_x_max": 0.60,
                "camera_roi_y_max": 0.65,
                "detector_adaptive_block_size": 35,
            }
        )
        frame = np.full((80, 120, 3), 255, dtype=np.uint8)
        cv2.circle(frame, (60, 40), 4, (0, 0, 0), -1)
        detector = NozzleDetector(settings, lambda *args: None)
        result, annotated = detector.detect_frame(frame)
        self.assertIsNotNone(result)
        self.assertEqual(annotated.shape, frame.shape)


if __name__ == "__main__":
    unittest.main()
