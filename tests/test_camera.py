import unittest
from unittest import mock

import cv2
import numpy as np

from server.camera import (
    CameraError,
    CameraSource,
    _camera_url,
    choose_camera,
    resolve_camera,
)


class CameraDiscoveryTests(unittest.TestCase):
    def test_only_enabled_camera_is_selected(self):
        cameras = [
            {"name": "bed", "enabled": False},
            {"name": "nozzle", "enabled": True},
        ]
        self.assertEqual(choose_camera(cameras)["name"], "nozzle")

    def test_unique_alignment_name_wins_without_list_order_guess(self):
        cameras = [
            {"name": "chamber", "location": "printer"},
            {"name": "alignment", "location": "tool"},
        ]
        self.assertEqual(choose_camera(cameras)["name"], "alignment")

    def test_ambiguous_cameras_are_rejected_and_listed(self):
        cameras = [{"name": "left"}, {"name": "right"}]
        with self.assertRaisesRegex(CameraError, "left.*right"):
            choose_camera(cameras)

    def test_exact_requested_name_is_case_insensitive(self):
        cameras = [{"name": "Nozzle Cam"}, {"name": "bed"}]
        self.assertEqual(
            choose_camera(cameras, "nozzle cam")["name"], "Nozzle Cam"
        )

    def test_relative_moonraker_camera_uses_same_host_port_80(self):
        self.assertEqual(
            _camera_url("/webcam/?action=snapshot", "http://printer.local:7125"),
            "http://printer.local/webcam/?action=snapshot",
        )

    @mock.patch("server.camera._http_json")
    def test_resolver_prefers_snapshot_and_preserves_metadata(self, fetch):
        fetch.return_value = {
            "result": {
                "webcams": [
                    {
                        "name": "nozzle",
                        "location": "tool",
                        "snapshot_url": "/webcam/snapshot",
                        "stream_url": "/webcam/stream",
                        "flip_horizontal": True,
                        "rotation": 90,
                    }
                ]
            }
        }
        result = resolve_camera({"moonraker_url": "http://printer:7125"})
        self.assertEqual(result["source"], "http://printer/webcam/snapshot")
        self.assertTrue(result["flip_horizontal"])
        self.assertEqual(result["rotation"], 90)


class NativeFrameTests(unittest.TestCase):
    def test_rotation_changes_dimensions_without_resizing(self):
        source = CameraSource({"source": "unused", "rotation": 90})
        frame = np.zeros((600, 800, 3), dtype=np.uint8)
        transformed = source._apply_metadata(frame)
        self.assertEqual(transformed.shape[:2], (800, 600))

    def test_http_mjpeg_decodes_first_native_frame(self):
        frame = np.full((333, 777, 3), 180, dtype=np.uint8)
        ok, encoded = cv2.imencode(".jpg", frame)
        self.assertTrue(ok)
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = (
            b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
            + encoded.tobytes()
            + b"\r\n--frame"
        )
        with mock.patch("urllib.request.urlopen", return_value=response):
            captured = CameraSource({"source": "http://camera/stream"}).capture()
        self.assertEqual(captured.shape[:2], (333, 777))


if __name__ == "__main__":
    unittest.main()
