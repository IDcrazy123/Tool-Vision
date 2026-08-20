"""Camera acquisition without assuming a fixed frame size."""

import threading
import time

import cv2
import numpy as np
import requests


class CameraError(RuntimeError):
    """Raised when a camera frame cannot be acquired."""


class CameraSource:
    """Read frames from HTTP MJPEG/snapshot, RTSP, or a V4L2 device."""

    def __init__(self, settings, logger):
        self.log = logger
        self.settings = dict(settings)
        self.source = str(self.settings.get("camera_source", "")).strip()
        if not self.source:
            raise CameraError("camera_source is required")

        self.mode = str(self.settings.get("camera_mode", "auto")).lower()
        if self.mode not in ("auto", "http", "opencv"):
            raise CameraError("camera_mode must be auto, http, or opencv")

        self.rotation = int(self.settings.get("camera_rotation", 0))
        if self.rotation not in (0, 90, 180, 270):
            raise CameraError("camera_rotation must be 0, 90, 180, or 270")

        self.flip_x = bool(self.settings.get("camera_flip_x", False))
        self.flip_y = bool(self.settings.get("camera_flip_y", False))
        self.connect_timeout = float(
            self.settings.get("camera_connect_timeout", 2.0)
        )
        self.read_timeout = float(self.settings.get("camera_read_timeout", 5.0))
        self.max_bytes = int(self.settings.get("camera_max_frame_bytes", 8388608))
        self.warmup_frames = int(self.settings.get("camera_warmup_frames", 0))
        self.requested_width = int(self.settings.get("camera_width", 0))
        self.requested_height = int(self.settings.get("camera_height", 0))
        self.requested_fps = float(self.settings.get("camera_fps", 0))

        if self.connect_timeout <= 0 or self.read_timeout <= 0:
            raise CameraError("camera timeouts must be positive")
        if self.max_bytes < 65536:
            raise CameraError("camera_max_frame_bytes is too small")
        if self.warmup_frames < 0:
            raise CameraError("camera_warmup_frames cannot be negative")
        if (
            self.requested_width < 0
            or self.requested_height < 0
            or self.requested_fps < 0
        ):
            raise CameraError("requested camera dimensions and FPS cannot be negative")

        self._session = requests.Session()
        self._capture = None
        self._lock = threading.Lock()

    def close(self):
        with self._lock:
            if self._capture is not None:
                self._capture.release()
                self._capture = None
            self._session.close()

    def capture(self):
        """Return one transformed BGR frame at the camera's native size."""
        with self._lock:
            frame = None
            for _ in range(self.warmup_frames + 1):
                if self._resolved_mode() == "http":
                    frame = self._capture_http()
                else:
                    frame = self._capture_opencv()
            if frame is None:
                raise CameraError("camera returned no frame")
            return self._transform(frame)

    def _resolved_mode(self):
        if self.mode != "auto":
            return self.mode
        if self.source.lower().startswith(("http://", "https://")):
            return "http"
        return "opencv"

    def _capture_http(self):
        try:
            with self._session.get(
                self.source,
                stream=True,
                timeout=(self.connect_timeout, self.read_timeout),
            ) as response:
                response.raise_for_status()
                payload = bytearray()
                for chunk in response.iter_content(chunk_size=16384):
                    if not chunk:
                        continue
                    payload.extend(chunk)
                    start = payload.find(b"\xff\xd8")
                    end = payload.find(b"\xff\xd9", max(start + 2, 0))
                    if start >= 0 and end > start:
                        encoded = np.frombuffer(
                            bytes(payload[start : end + 2]), dtype=np.uint8
                        )
                        frame = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
                        if frame is None:
                            raise CameraError("JPEG frame could not be decoded")
                        return frame
                    if len(payload) > self.max_bytes:
                        raise CameraError(
                            "camera frame exceeded camera_max_frame_bytes"
                        )
        except requests.RequestException as exc:
            raise CameraError("HTTP camera error: %s" % exc)
        raise CameraError("HTTP response did not contain a complete JPEG frame")

    def _capture_opencv(self):
        if self._capture is None or not self._capture.isOpened():
            source = self.source
            if source.isdigit():
                source = int(source)
            self._capture = cv2.VideoCapture(source)
            if not self._capture.isOpened():
                self._capture.release()
                self._capture = None
                raise CameraError("OpenCV cannot open camera_source")
            if self.requested_width > 0:
                self._capture.set(cv2.CAP_PROP_FRAME_WIDTH, self.requested_width)
            if self.requested_height > 0:
                self._capture.set(cv2.CAP_PROP_FRAME_HEIGHT, self.requested_height)
            if self.requested_fps > 0:
                self._capture.set(cv2.CAP_PROP_FPS, self.requested_fps)

        ok, frame = self._capture.read()
        if not ok or frame is None:
            self._capture.release()
            self._capture = None
            time.sleep(0.05)
            raise CameraError("OpenCV camera read failed")
        return frame

    def _transform(self, frame):
        if self.rotation == 90:
            frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        elif self.rotation == 180:
            frame = cv2.rotate(frame, cv2.ROTATE_180)
        elif self.rotation == 270:
            frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)

        if self.flip_x and self.flip_y:
            frame = cv2.flip(frame, -1)
        elif self.flip_x:
            frame = cv2.flip(frame, 1)
        elif self.flip_y:
            frame = cv2.flip(frame, 0)
        return frame
