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

    @mock.patch("server.camera._http_json")
    def test_invalid_moonraker_rotation_is_a_camera_domain_error(self, fetch):
        fetch.return_value = {
            "result": {
                "webcams": [
                    {
                        "name": "nozzle",
                        "snapshot_url": "/webcam/snapshot",
                        "rotation": "sideways",
                    }
                ]
            }
        }
        with self.assertRaisesRegex(CameraError, "rotation"):
            resolve_camera({"moonraker_url": "http://printer:7125"})


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

    def test_http_frame_over_configured_pixel_limit_is_rejected(self):
        frame = np.full((30, 40, 3), 180, dtype=np.uint8)
        ok, encoded = cv2.imencode(".jpg", frame)
        self.assertTrue(ok)
        response = mock.MagicMock()
        response.__enter__.return_value.read.side_effect = [encoded.tobytes(), b""]
        source = CameraSource(
            {"source": "http://camera/snapshot"}, max_pixels=1000
        )
        with mock.patch("urllib.request.urlopen", return_value=response):
            with self.assertRaisesRegex(CameraError, "pixel limit"):
                source.capture()

    def test_opencv_decode_limit_error_is_a_camera_domain_error(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.side_effect = [b"not-an-image", b""]
        source = CameraSource({"source": "http://camera/snapshot"})
        with mock.patch("urllib.request.urlopen", return_value=response), mock.patch(
            "server.camera.cv2.imdecode", side_effect=cv2.error("decode limit")
        ):
            with self.assertRaisesRegex(CameraError, "decoder|pixel limit"):
                source.capture()

    def test_network_capture_opens_with_backend_deadlines(self):
        device = mock.MagicMock()
        device.open.return_value = True
        device.isOpened.return_value = True
        device.read.return_value = (True, np.zeros((100, 100, 3), dtype=np.uint8))
        with mock.patch("server.camera.cv2.VideoCapture", return_value=device) as ctor:
            CameraSource({"source": "rtsp://camera/stream"}, timeout=1.25).capture()
        ctor.assert_called_once_with()
        device.open.assert_called_once_with(
            "rtsp://camera/stream",
            cv2.CAP_ANY,
            [
                cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
                1250,
                cv2.CAP_PROP_READ_TIMEOUT_MSEC,
                1250,
            ],
        )


if __name__ == "__main__":
    unittest.main()
