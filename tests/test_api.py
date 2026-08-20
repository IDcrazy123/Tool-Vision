import logging
import tempfile
import unittest
from unittest import mock

from server.app import ServiceState, create_app
from server.detection import DetectionError


class ApiContractTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.app = create_app(self.temp_directory.name)
        self.app.testing = True
        self.client = self.app.test_client()

    def tearDown(self):
        state = self.app.config["TOOL_VISION_STATE"]
        state.executor.shutdown(wait=False, cancel_futures=True)
        for handler in list(state.log.handlers):
            handler.close()
            state.log.removeHandler(handler)
        self.temp_directory.cleanup()

    def test_health_reports_unconfigured_native_camera_state(self):
        response = self.client.get("/api/v1/health")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertTrue(payload["ok"])
        self.assertFalse(payload["configured"])
        self.assertIsNone(payload["camera_frame"])

    def test_model_fit_and_offset_round_trip(self):
        samples = [
            {"pixel_delta": [20, 0], "machine_delta": [0.2, 0]},
            {"pixel_delta": [-20, 0], "machine_delta": [-0.2, 0]},
            {"pixel_delta": [0, 20], "machine_delta": [0, 0.2]},
            {"pixel_delta": [0, -20], "machine_delta": [0, -0.2]},
        ]
        fit = self.client.post(
            "/api/v1/model",
            json={
                "model": "affine",
                "samples": samples,
                "target": [512, 384],
                "frame_width": 1024,
                "frame_height": 768,
                "max_rms_error": 0.001,
            },
        )
        self.assertEqual(fit.status_code, 200)
        self.assertTrue(fit.get_json()["transform"]["calibrated"])

        offset = self.client.post(
            "/api/v1/offset",
            json={"point": [502, 379], "frame_width": 1024, "frame_height": 768},
        )
        self.assertEqual(offset.status_code, 200)
        correction = offset.get_json()["correction"]
        self.assertAlmostEqual(correction["move_x"], 0.1)
        self.assertAlmostEqual(correction["move_y"], 0.05)

    def test_missing_job_and_frame_return_not_found(self):
        self.assertEqual(self.client.get("/api/v1/jobs/missing").status_code, 404)
        self.assertEqual(self.client.get("/api/v1/frame").status_code, 404)


class ServiceConcurrencyTests(unittest.TestCase):
    def test_reconfigure_is_rejected_while_detection_is_active(self):
        state = ServiceState(logging.getLogger("tool_vision_test"))
        state.active_job = "running-job"
        try:
            with mock.patch("server.app.CameraSource") as camera_class:
                with self.assertRaises(DetectionError):
                    state.configure({"camera_source": "unused"})
                camera_class.assert_not_called()
        finally:
            state.executor.shutdown(wait=False, cancel_futures=True)


if __name__ == "__main__":
    unittest.main()
