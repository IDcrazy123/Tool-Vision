"""Camera discovery and native-resolution frame capture.

Moonraker owns webcam metadata; Crowsnest or another external service owns the
actual stream. This module deliberately has no printer-motion responsibility.
"""

import json
import math
import os
import re
import urllib.parse
import urllib.request

# OpenCV reads this setting before decoding. Apply the project resource ceiling
# before importing cv2; the explicit post-decode check below remains the final
# guard when another module imported OpenCV first.
try:
    from .limits import MAX_FRAME_PIXELS
except ImportError:  # pragma: no cover - direct script execution
    from limits import MAX_FRAME_PIXELS

try:
    _configured_opencv_limit = int(
        os.environ.get("OPENCV_IO_MAX_IMAGE_PIXELS", MAX_FRAME_PIXELS)
    )
except ValueError:
    _configured_opencv_limit = MAX_FRAME_PIXELS
os.environ["OPENCV_IO_MAX_IMAGE_PIXELS"] = str(
    min(max(1, _configured_opencv_limit), MAX_FRAME_PIXELS)
)

import cv2
import numpy as np


class CameraError(RuntimeError):
    """A camera could not be selected or read safely."""


ALIGNMENT_WORDS = (
    "nozzle",
    "tool",
    "align",
    "alignment",
    "ktamv",
    "toolvision",
)


def _http_json(url, timeout):
    request = urllib.request.Request(
        url, headers={"Accept": "application/json", "User-Agent": "ToolVision/3"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise CameraError("cannot query Moonraker webcams: %s" % exc)


def _camera_label(camera):
    name = str(camera.get("name") or "unnamed")
    location = str(camera.get("location") or "unknown")
    return "%s (%s)" % (name, location)


def choose_camera(cameras, requested_name=None):
    """Choose deterministically; never guess from Moonraker list order."""
    enabled = [item for item in cameras if item.get("enabled", True)]
    if not enabled:
        raise CameraError("Moonraker has no enabled webcam")

    if requested_name:
        matches = [
            item
            for item in enabled
            if str(item.get("name", "")).casefold() == requested_name.casefold()
        ]
        if len(matches) == 1:
            return matches[0]
        available = ", ".join(_camera_label(item) for item in enabled)
        raise CameraError(
            "camera_name '%s' not found; available: %s"
            % (requested_name, available)
        )

    if len(enabled) == 1:
        return enabled[0]

    preferred = []
    for item in enabled:
        label = "%s %s" % (item.get("name", ""), item.get("location", ""))
        words = set(re.findall(r"[a-z0-9]+", label.casefold()))
        if words.intersection(ALIGNMENT_WORDS):
            preferred.append(item)
    if len(preferred) == 1:
        return preferred[0]

    available = ", ".join(_camera_label(item) for item in enabled)
    raise CameraError(
        "camera discovery is ambiguous; set camera_name or camera_source. "
        "Enabled cameras: %s" % available
    )


def _camera_url(value, moonraker_url):
    if not value:
        return None
    parsed = urllib.parse.urlparse(str(value))
    if parsed.scheme:
        return str(value)

    # Moonraker defines relative webcam URLs as services on the same host at
    # port 80, not at Moonraker's usual API port 7125.
    moonraker = urllib.parse.urlparse(moonraker_url)
    host = moonraker.hostname or "127.0.0.1"
    if ":" in host and not host.startswith("["):
        host = "[%s]" % host
    origin = "%s://%s" % (moonraker.scheme or "http", host)
    return urllib.parse.urljoin(origin, str(value))


def resolve_camera(settings):
    """Return a normalized camera descriptor from config or Moonraker."""
    explicit = settings.get("camera_source")
    if explicit not in (None, ""):
        return {
            "name": "explicit",
            "location": "configured",
            "source": explicit,
            "flip_horizontal": False,
            "flip_vertical": False,
            "rotation": 0,
            "discovered": False,
        }

    moonraker_url = str(
        settings.get("moonraker_url") or "http://127.0.0.1:7125"
    ).rstrip("/")
    payload = _http_json(
        moonraker_url + "/server/webcams/list",
        float(settings.get("connect_timeout", 3.0)),
    )
    result = payload.get("result", payload)
    cameras = result.get("webcams", []) if isinstance(result, dict) else []
    if not isinstance(cameras, list):
        raise CameraError("Moonraker returned an invalid webcam list")
    camera = choose_camera(cameras, settings.get("camera_name"))
    source = _camera_url(camera.get("snapshot_url"), moonraker_url)
    if not source:
        source = _camera_url(camera.get("stream_url"), moonraker_url)
    if not source:
        raise CameraError("selected camera has no snapshot_url or stream_url")

    try:
        rotation = int(camera.get("rotation", 0) or 0)
    except (TypeError, ValueError):
        raise CameraError("Moonraker camera rotation is invalid")
    if rotation not in (0, 90, 180, 270):
        raise CameraError("Moonraker camera rotation must be 0, 90, 180, or 270")
    return {
        "name": str(camera.get("name") or "unnamed"),
        "location": str(camera.get("location") or "unknown"),
        "source": source,
        "flip_horizontal": bool(camera.get("flip_horizontal", False)),
        "flip_vertical": bool(camera.get("flip_vertical", False)),
        "rotation": rotation,
        "discovered": True,
        "uid": camera.get("uid"),
    }


class CameraSource:
    """Capture a frame without resizing it."""

    NETWORK_SCHEMES = frozenset(("rtsp", "rtmp", "rtp", "udp", "tcp", "srt"))

    def __init__(
        self,
        descriptor,
        timeout=5.0,
        max_bytes=12 * 1024 * 1024,
        max_pixels=MAX_FRAME_PIXELS,
    ):
        self.descriptor = dict(descriptor)
        try:
            self.source = self.descriptor["source"]
            self.timeout = float(timeout)
            self.max_bytes = int(max_bytes)
            self.max_pixels = int(max_pixels)
        except (KeyError, TypeError, ValueError):
            raise CameraError("camera source limits are invalid")
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise CameraError("camera timeout must be a positive finite value")
        if self.max_bytes <= 0 or self.max_pixels <= 0:
            raise CameraError("camera resource limits must be positive")
        self.capture_device = None

    def close(self):
        if self.capture_device is not None:
            self.capture_device.release()
            self.capture_device = None

    def capture(self):
        if self._is_http_source():
            frame = self._capture_http()
        else:
            frame = self._capture_opencv()
        frame = self._apply_metadata(frame)
        self._validate_decoded_frame(frame)
        return frame

    def _is_http_source(self):
        return isinstance(self.source, str) and self.source.lower().startswith(
            ("http://", "https://")
        )

    def _capture_http(self):
        request = urllib.request.Request(
            self.source,
            headers={
                "Accept": "image/jpeg,image/png,multipart/x-mixed-replace,*/*",
                "User-Agent": "ToolVision/3",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                buffer = bytearray()
                jpeg = None
                while len(buffer) <= self.max_bytes:
                    chunk = response.read(min(65536, self.max_bytes + 1 - len(buffer)))
                    if not chunk:
                        break
                    buffer.extend(chunk)
                    start = buffer.find(b"\xff\xd8")
                    end = buffer.find(b"\xff\xd9", start + 2) if start >= 0 else -1
                    if start >= 0 and end >= 0:
                        jpeg = bytes(buffer[start : end + 2])
                        break
                data = jpeg if jpeg is not None else bytes(buffer)
        except Exception as exc:
            raise CameraError(
                "cannot read selected camera '%s' (%s)"
                % (self.descriptor.get("name", "camera"), type(exc).__name__)
            )
        if len(data) > self.max_bytes:
            raise CameraError("camera frame exceeds the safety byte limit")
        try:
            frame = cv2.imdecode(
                np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR
            )
        except cv2.error:
            raise CameraError(
                "camera image decoder rejected the frame or its pixel limit"
            )
        if frame is None:
            raise CameraError("camera response is not a decodable image")
        return frame

    def _capture_opencv(self):
        source = self.source
        if isinstance(source, str) and source.strip().isdigit():
            source = int(source.strip())
        if self.capture_device is None:
            if self._is_network_opencv_source(source):
                # OpenCV documents OPEN/READ_TIMEOUT as open-only properties
                # supported by FFmpeg/GStreamer. Do not pass them to local V4L
                # devices, whose backends may reject unknown constructor params.
                timeout_ms = max(1, int(round(self.timeout * 1000.0)))
                self.capture_device = cv2.VideoCapture()
                opened = self.capture_device.open(
                    source,
                    cv2.CAP_ANY,
                    [
                        cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,
                        timeout_ms,
                        cv2.CAP_PROP_READ_TIMEOUT_MSEC,
                        timeout_ms,
                    ],
                )
                if not opened:
                    self.close()
                    raise CameraError(
                        "OpenCV cannot open selected network camera '%s'"
                        % self.descriptor.get("name", "camera")
                    )
            else:
                self.capture_device = cv2.VideoCapture(source)
        if not self.capture_device.isOpened():
            self.close()
            raise CameraError(
                "OpenCV cannot open selected camera '%s'"
                % self.descriptor.get("name", "camera")
            )
        ok, frame = self.capture_device.read()
        if not ok or frame is None:
            self.close()
            raise CameraError("OpenCV camera returned no frame")
        return frame

    def _is_network_opencv_source(self, source):
        if not isinstance(source, str):
            return False
        return urllib.parse.urlparse(source).scheme.casefold() in self.NETWORK_SCHEMES

    def _validate_decoded_frame(self, frame):
        if frame is None or not hasattr(frame, "shape") or len(frame.shape) != 3:
            raise CameraError("camera returned an invalid decoded frame")
        if frame.shape[2] != 3 or getattr(frame, "dtype", None) != np.uint8:
            raise CameraError("camera frame must contain 8-bit BGR pixels")
        pixels = int(frame.shape[0]) * int(frame.shape[1])
        if pixels > self.max_pixels:
            raise CameraError(
                "camera frame exceeds the safety pixel limit (%d > %d)"
                % (pixels, self.max_pixels)
            )

    def _apply_metadata(self, frame):
        if self.descriptor.get("flip_horizontal"):
            frame = cv2.flip(frame, 1)
        if self.descriptor.get("flip_vertical"):
            frame = cv2.flip(frame, 0)
        rotation = self.descriptor.get("rotation", 0)
        if rotation == 90:
            frame = cv2.rotate(frame, cv2.ROTATE_90_CLOCKWISE)
        elif rotation == 180:
            frame = cv2.rotate(frame, cv2.ROTATE_180)
        elif rotation == 270:
            frame = cv2.rotate(frame, cv2.ROTATE_90_COUNTERCLOCKWISE)
        return frame
