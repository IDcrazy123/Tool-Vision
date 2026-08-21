import time
import unittest
from unittest import mock

import cv2
import numpy as np

from server.app import ServiceState, create_app
from server.detection import DetectionError, NozzleDetector


def frame():
    image = np.full((480, 640, 3), 220, dtype=np.uint8)
    cv2.circle(image, (320, 240), 22, (20, 20, 20), -1)
    return image


class FakeCamera:
    def __init__(self):
        self.closed = False

    def capture(self):
        return frame()

    def close(self):
        self.closed = True


class ApiTests(unittest.TestCase):
    def setUp(self):
        self.app = create_app()
        self.app.testing = True
        self.client = self.app.test_client()
        self.old_interval = NozzleDetector.FRAME_INTERVAL
        NozzleDetector.FRAME_INTERVAL = 0

    def tearDown(self):
        NozzleDetector.FRAME_INTERVAL = self.old_interval
        self.app.config["TOOL_VISION_STATE"].close()

    def test_health_is_versioned_and_unconfigured(self):
        response = self.client.get("/api/v2/health")
        self.assertEqual(response.status_code, 200)
        payload = response.get_json()
        self.assertEqual(payload["version"], "3.2.1")
        self.assertFalse(payload["configured"])
        self.assertFalse(payload["transform"]["calibrated"])

    @mock.patch("server.app.resolve_camera")
    @mock.patch("server.app.CameraSource")
    def test_configure_learn_and_preview_work_as_one_serial_job(self, source, resolver):
        resolver.return_value = {
            "name": "nozzle",
            "location": "tool",
            "source": "unused",
            "rotation": 0,
            "discovered": True,
        }
        source.return_value = FakeCamera()
        configured = self.client.post("/api/v2/config", json={})
        self.assertEqual(configured.status_code, 200)
        started = self.client.post("/api/v2/jobs/learn", json={})
        self.assertEqual(started.status_code, 202)
        job_id = started.get_json()["id"]
        deadline = time.monotonic() + 2
        job = None
        while time.monotonic() < deadline:
            job = self.client.get("/api/v2/jobs/%s" % job_id).get_json()
            if job["status"] in ("complete", "error"):
                break
            time.sleep(0.01)
        self.assertEqual(job["status"], "complete", job)
        self.assertEqual(job["result"]["profile"]["frame_width"], 640)
        self.assertEqual(self.client.get("/api/v2/frame").status_code, 200)

    def test_transform_round_trip(self):
        moves = [
            [0, -0.5], [0.294, -0.405], [0.476, -0.155], [0.476, 0.155],
            [0.294, 0.405], [0, 0.5], [-0.294, 0.405], [-0.476, 0.155],
            [-0.476, -0.155], [-0.294, -0.405],
        ]
        samples = [
            {"pixel_delta": [x * 100, y * 100], "machine_delta": [x, y]}
            for x, y in moves
        ]
        fitted = self.client.post(
            "/api/v2/transform/fit",
            json={"samples": samples, "frame_width": 640, "frame_height": 480},
        )
        self.assertEqual(fitted.status_code, 200, fitted.get_json())
        correction = self.client.post(
            "/api/v2/transform/correction",
            json={"point": [310, 235], "frame_width": 640, "frame_height": 480},
        ).get_json()["correction"]
        self.assertAlmostEqual(correction["move_x"], 0.1)
        self.assertAlmostEqual(correction["move_y"], 0.05)

    def test_missing_job_and_route_remain_404(self):
        self.assertEqual(self.client.get("/api/v2/jobs/missing").status_code, 404)
        self.assertEqual(self.client.get("/missing").status_code, 404)


class ServiceConcurrencyTests(unittest.TestCase):
    def test_reconfigure_is_rejected_while_job_is_active(self):
        state = ServiceState()
        state.active_job = "running"
        try:
            with self.assertRaises(DetectionError):
                state.configure({"camera_source": "unused"})
        finally:
            state.close()


if __name__ == "__main__":
    unittest.main()
