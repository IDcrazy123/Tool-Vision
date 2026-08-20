import math
import unittest

import numpy as np

from server.transform import TransformError, TransformModel


class TransformModelTests(unittest.TestCase):
    def _payload(self):
        pixel_to_machine = np.array([[0.010, 0.002], [-0.001, 0.008]])
        samples = []
        for index in range(10):
            angle = 2.0 * math.pi * index / 10.0
            pixel_delta = np.array([40.0 * math.cos(angle), 30.0 * math.sin(angle)])
            machine_delta = pixel_to_machine @ pixel_delta
            samples.append(
                {
                    "pixel_delta": pixel_delta.tolist(),
                    "machine_delta": machine_delta.tolist(),
                }
            )
        return {
            "model": "affine",
            "samples": samples,
            "target": [640.0, 360.0],
            "frame_width": 1280,
            "frame_height": 720,
            "max_rms_error": 0.001,
        }, pixel_to_machine

    def test_affine_fit_and_correction(self):
        payload, expected_matrix = self._payload()
        model = TransformModel()
        status = model.fit(payload)
        self.assertTrue(status["calibrated"])
        self.assertLess(status["rms_error"], 1e-10)

        point = np.array([620.0, 370.0])
        expected = expected_matrix @ (np.array(payload["target"]) - point)
        result = model.correction(
            {"point": point.tolist(), "frame_width": 1280, "frame_height": 720}
        )
        self.assertAlmostEqual(result["move_x"], expected[0], places=8)
        self.assertAlmostEqual(result["move_y"], expected[1], places=8)

    def test_resolution_change_requires_recalibration(self):
        payload, _ = self._payload()
        model = TransformModel()
        model.fit(payload)
        with self.assertRaises(TransformError):
            model.correction(
                {"point": [320, 240], "frame_width": 640, "frame_height": 480}
            )

    def test_rank_deficient_moves_are_rejected(self):
        model = TransformModel()
        samples = [
            {"pixel_delta": [value, 0], "machine_delta": [value * 0.01, 0]}
            for value in (10, 20, 30, 40)
        ]
        with self.assertRaises(TransformError):
            model.fit(
                {
                    "model": "affine",
                    "samples": samples,
                    "target": [100, 100],
                    "frame_width": 200,
                    "frame_height": 200,
                }
            )


if __name__ == "__main__":
    unittest.main()
