import unittest

import cv2
import numpy as np

from server.detection import DetectionError, NozzleDetector


class StaticCamera:
    def __init__(self, frame):
        self.frame = frame

    def capture(self):
        return self.frame.copy()


def nozzle_frame(width=1280, height=720, center=None, radius=26, blur=0):
    center = center or (width // 2, height // 2)
    frame = np.full((height, width, 3), 220, dtype=np.uint8)
    cv2.circle(frame, center, radius, (25, 25, 25), -1)
    if blur:
        frame = cv2.GaussianBlur(frame, (blur, blur), 0)
    return frame


class LearnedDetectionTests(unittest.TestCase):
    def setUp(self):
        self.detector = NozzleDetector()
        self.detector.FRAME_INTERVAL = 0

    def test_setup_learns_native_resolution_and_stable_nozzle(self):
        result = self.detector.learn(StaticCamera(nozzle_frame()))
        self.assertEqual(result["profile"]["frame_width"], 1280)
        self.assertEqual(result["profile"]["frame_height"], 720)
        self.assertAlmostEqual(result["observation"]["x"], 640, delta=1)
        self.assertAlmostEqual(result["observation"]["y"], 360, delta=1)
        self.assertLessEqual(result["observation"]["stability_px"], 1.5)
        self.assertIn("sharpness", result["observation"])
        self.assertNotIn("focus_ok", result["observation"])

    def test_profile_tracks_shifted_nozzle_during_calibration(self):
        self.detector.learn(StaticCamera(nozzle_frame()))
        observation = self.detector.detect_stable(
            StaticCamera(nozzle_frame(center=(670, 340))), timeout=1
        )
        self.assertAlmostEqual(observation["x"], 670, delta=1)
        self.assertAlmostEqual(observation["y"], 340, delta=1)

    def test_resolution_change_requires_setup_again(self):
        self.detector.learn(StaticCamera(nozzle_frame()))
        with self.assertRaisesRegex(DetectionError, "resolution changed"):
            self.detector.detect_stable(
                StaticCamera(nozzle_frame(800, 600)), timeout=0.1
            )

    def test_sharpness_is_relative_not_a_hardware_rejection_threshold(self):
        self.detector.learn(StaticCamera(nozzle_frame()))
        sharp = self.detector.detect_stable(StaticCamera(nozzle_frame()), timeout=1)
        blurred = self.detector.detect_stable(
            StaticCamera(nozzle_frame(blur=15)), timeout=1
        )
        self.assertGreater(sharp["sharpness"], blurred["sharpness"])
        self.assertEqual(
            blurred["sharpness_note"],
            "relative metric; stable detection is the acceptance gate",
        )

    def test_blank_frame_does_not_teach_a_profile(self):
        blank = np.full((480, 640, 3), 127, dtype=np.uint8)
        with self.assertRaises(DetectionError):
            self.detector.learn(StaticCamera(blank))


if __name__ == "__main__":
    unittest.main()
