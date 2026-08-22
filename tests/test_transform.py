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


def sample_payload(bad=(), pixel_scale=(100.0, 80.0)):
    samples = []
    for index, move in enumerate(MOVES):
        pixel = [move[0] * pixel_scale[0], move[1] * pixel_scale[1]]
        if index in bad:
            pixel = [pixel[0] + 90, pixel[1] - 70]
        samples.append(
            {
                "pixel_delta": pixel,
                "machine_delta": move,
                "stability_px": 0.2,
            }
        )
    return {
        "samples": samples,
        "frame_width": 1280,
        "frame_height": 720,
        "target_ratio": [0.5, 0.5],
        "base_stability_px": 0.2,
        "max_uncertainty_mm": 0.015,
    }


class TransformTests(unittest.TestCase):
    def test_ten_point_fit_and_correction_have_ktamv_sign(self):
        model = TransformModel()
        transform = model.fit(sample_payload())
        self.assertTrue(model.status()["calibrated"])
        self.assertEqual(transform["schema_version"], 2)
        self.assertEqual(transform["used_samples"], 10)
        correction = model.correction(
            {"point": [630, 356], "frame_width": 1280, "frame_height": 720}
        )
        self.assertAlmostEqual(correction["move_x"], 0.1, places=6)
        self.assertAlmostEqual(correction["move_y"], 0.05, places=6)
        self.assertLessEqual(correction["estimated_uncertainty_mm"], 0.015)

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

    def test_tiny_pixel_motion_is_rejected_as_unresolvable(self):
        with self.assertRaisesRegex(TransformError, "uncertainty|sensitivity"):
            TransformModel().fit(sample_payload(pixel_scale=(0.001, 0.001)))

    def test_excessive_sample_count_is_rejected(self):
        payload = sample_payload()
        payload["samples"] = payload["samples"] * 7
        with self.assertRaisesRegex(TransformError, "too many"):
            TransformModel().fit(payload)

    def test_saved_transform_rejects_forged_uncertainty_evidence(self):
        transform = TransformModel().fit(sample_payload())
        transform["estimated_uncertainty_mm"] = 0.0
        with self.assertRaisesRegex(TransformError, "uncertainty evidence"):
            TransformModel(transform)

    def test_saved_transform_rejects_non_numeric_schema_as_domain_error(self):
        transform = TransformModel().fit(sample_payload())
        transform["schema_version"] = "invalid"
        with self.assertRaisesRegex(TransformError, "schema"):
            TransformModel(transform)


if __name__ == "__main__":
    unittest.main()
