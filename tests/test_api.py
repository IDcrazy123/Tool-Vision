import threading
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
        self.assertEqual(payload["version"], "3.3.0-rc1")
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
            {
                "pixel_delta": [x * 100, y * 100],
                "machine_delta": [x, y],
                "stability_px": 0.2,
            }
            for x, y in moves
        ]
        fitted = self.client.post(
            "/api/v2/transform/fit",
            json={
                "samples": samples,
                "frame_width": 640,
                "frame_height": 480,
                "base_stability_px": 0.2,
                "max_uncertainty_mm": 0.015,
            },
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

    @mock.patch("server.app.resolve_camera")
    @mock.patch("server.app.CameraSource")
    def test_failed_reconfigure_keeps_previous_runtime_and_clears_gate(
        self, source, resolver
    ):
        previous = FakeCamera()
        candidate = FakeCamera()
        candidate.capture = mock.MagicMock(side_effect=RuntimeError("capture failed"))
        source.return_value = candidate
        resolver.return_value = {
            "name": "replacement",
            "location": "tool",
            "source": "unused",
            "rotation": 0,
            "discovered": True,
        }
        state = ServiceState()
        state.camera = previous
        try:
            with self.assertRaisesRegex(RuntimeError, "capture failed"):
                state.configure({"camera_source": "unused"})
            self.assertIs(state.camera, previous)
            self.assertFalse(previous.closed)
            self.assertTrue(candidate.closed)
            self.assertFalse(state.configuring)
        finally:
            state.close()

    @mock.patch("server.app.resolve_camera")
    @mock.patch("server.app.CameraSource")
    def test_preview_encode_failure_cannot_partially_swap_camera(
        self, source, resolver
    ):
        previous = FakeCamera()
        candidate = FakeCamera()
        source.return_value = candidate
        resolver.return_value = {
            "name": "replacement",
            "location": "tool",
            "source": "unused",
            "rotation": 0,
            "discovered": True,
        }
        state = ServiceState()
        state.camera = previous
        try:
            with mock.patch(
                "server.app.cv2.imencode", side_effect=RuntimeError("encode failed")
            ):
                with self.assertRaisesRegex(RuntimeError, "encode failed"):
                    state.configure({"camera_source": "unused"})
            self.assertIs(state.camera, previous)
            self.assertFalse(previous.closed)
            self.assertTrue(candidate.closed)
            self.assertFalse(state.configuring)
        finally:
            state.close()

    @mock.patch("server.app.resolve_camera")
    @mock.patch("server.app.CameraSource")
    def test_job_cannot_start_while_reconfigure_is_capturing(
        self, source, resolver
    ):
        entered = threading.Event()
        release = threading.Event()
        candidate = FakeCamera()

        def blocked_capture():
            entered.set()
            release.wait(2)
            return frame()

        candidate.capture = blocked_capture
        source.return_value = candidate
        resolver.return_value = {
            "name": "replacement",
            "location": "tool",
            "source": "unused",
            "rotation": 0,
            "discovered": True,
        }

        state = ServiceState()
        state.camera = FakeCamera()
        state.detector = mock.MagicMock()
        state.detector.profile = {"schema_version": 1}
        errors = []
        worker = threading.Thread(
            target=lambda: self._configure_in_thread(state, errors)
        )
        worker.start()
        self.assertTrue(entered.wait(1), "configure did not reach camera capture")
        try:
            with self.assertRaisesRegex(DetectionError, "configur"):
                state.start_job("detect")
        finally:
            release.set()
            worker.join(2)
            state.close()
        self.assertFalse(worker.is_alive())
        self.assertEqual(errors, [])

    @staticmethod
    def _configure_in_thread(state, errors):
        try:
            state.configure({"camera_source": "unused"})
        except Exception as exc:  # captured for assertion in the test thread
            errors.append(exc)


if __name__ == "__main__":
    unittest.main()
