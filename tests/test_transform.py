import unittest

from server.transform import TransformError, TransformModel


MOVES = [
    [0.000, -0.500],
    [0.294, -0.405],
    [0.476, -0.155],
    [0.476, 0.155],
    [0.294, 0.405],
    [0.000, 0.500],
    [-0.294, 0.405],
    [-0.476, 0.155],
    [-0.476, -0.155],
    [-0.294, -0.405],
]


def sample_payload(bad=()):
    samples = []
    for index, move in enumerate(MOVES):
        pixel = [move[0] * 100.0, move[1] * 80.0]
        if index in bad:
            pixel = [pixel[0] + 90, pixel[1] - 70]
        samples.append({"pixel_delta": pixel, "machine_delta": move})
    return {
        "samples": samples,
        "frame_width": 1280,
        "frame_height": 720,
        "target_ratio": [0.5, 0.5],
    }


class TransformTests(unittest.TestCase):
    def test_ten_point_fit_and_correction_have_ktamv_sign(self):
        model = TransformModel()
        transform = model.fit(sample_payload())
        self.assertTrue(model.status()["calibrated"])
        self.assertEqual(transform["used_samples"], 10)
        correction = model.correction(
            {"point": [630, 356], "frame_width": 1280, "frame_height": 720}
        )
        self.assertAlmostEqual(correction["move_x"], 0.1, places=6)
        self.assertAlmostEqual(correction["move_y"], 0.05, places=6)

    def test_two_inconsistent_points_are_rejected(self):
        transform = TransformModel().fit(sample_payload(bad=(1, 6)))
        self.assertGreaterEqual(transform["used_samples"], 8)
        self.assertLessEqual(transform["rejected_samples"], 2)

    def test_more_than_25_percent_bad_points_are_rejected(self):
        with self.assertRaises(TransformError):
            TransformModel().fit(sample_payload(bad=(0, 1, 2)))

    def test_rank_deficient_samples_are_rejected(self):
        payload = sample_payload()
        for sample in payload["samples"]:
            sample["pixel_delta"][1] = 0
        with self.assertRaisesRegex(TransformError, "span both"):
            TransformModel().fit(payload)

    def test_resolution_change_requires_recalibration(self):
        model = TransformModel()
        model.fit(sample_payload())
        with self.assertRaisesRegex(TransformError, "resolution changed"):
            model.correction(
                {"point": [320, 240], "frame_width": 640, "frame_height": 480}
            )


if __name__ == "__main__":
    unittest.main()
