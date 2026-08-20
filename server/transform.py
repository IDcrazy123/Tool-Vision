"""Pixel-to-machine transform models for camera centering."""

import math

import numpy as np


class TransformError(RuntimeError):
    """Raised when camera calibration data is invalid or ill-conditioned."""


class TransformModel:
    """Fit local affine or quadratic movement from measured pixel shifts."""

    def __init__(self):
        self.kind = None
        self.coefficients = None
        self.target = None
        self.frame_width = None
        self.frame_height = None
        self.rms_error = None
        self.condition = None
        self.sample_count = 0

    @property
    def calibrated(self):
        return self.coefficients is not None

    def clear(self):
        self.__init__()

    def fit(self, payload):
        kind = str(payload.get("model", "affine")).lower()
        if kind not in ("affine", "quadratic"):
            raise TransformError("model must be affine or quadratic")
        samples = payload.get("samples") or []
        minimum = 4 if kind == "affine" else 8
        if len(samples) < minimum:
            raise TransformError(
                "%s model requires at least %d samples" % (kind, minimum)
            )

        pixel = []
        machine = []
        for sample in samples:
            if not isinstance(sample, dict):
                raise TransformError("every calibration sample must be an object")
            pixel_delta = sample.get("pixel_delta")
            machine_delta = sample.get("machine_delta")
            if not self._pair(pixel_delta) or not self._pair(machine_delta):
                raise TransformError("every calibration sample needs two deltas")
            try:
                pixel.append([float(pixel_delta[0]), float(pixel_delta[1])])
                machine.append([float(machine_delta[0]), float(machine_delta[1])])
            except (TypeError, ValueError):
                raise TransformError("calibration deltas must be numeric")

        pixel = np.asarray(pixel, dtype=float)
        machine = np.asarray(machine, dtype=float)
        if not np.isfinite(pixel).all() or not np.isfinite(machine).all():
            raise TransformError("calibration deltas must be finite")
        design = self._features(pixel, kind)
        rank = int(np.linalg.matrix_rank(design))
        if rank < design.shape[1]:
            raise TransformError("calibration moves do not span the camera axes")
        condition = float(np.linalg.cond(design))
        max_condition = float(payload.get("max_condition", 1000000.0))
        if max_condition <= 0:
            raise TransformError("max_condition must be positive")
        if not math.isfinite(condition) or condition > max_condition:
            raise TransformError(
                "calibration matrix is ill-conditioned (%.1f)" % condition
            )

        coefficients, _, _, _ = np.linalg.lstsq(design, machine, rcond=None)
        prediction = design @ coefficients
        rms = float(np.sqrt(np.mean(np.square(prediction - machine))))
        max_rms = float(payload.get("max_rms_error", 0.08))
        if max_rms <= 0:
            raise TransformError("max_rms_error must be positive")
        if rms > max_rms:
            raise TransformError(
                "camera calibration RMS error %.4fmm exceeds %.4fmm"
                % (rms, max_rms)
            )

        target = payload.get("target")
        if not self._pair(target):
            raise TransformError("target must contain X and Y pixels")
        try:
            target = np.asarray(target, dtype=float)
        except (TypeError, ValueError):
            raise TransformError("target pixels must be numeric")
        if not np.isfinite(target).all():
            raise TransformError("target pixels must be finite")
        frame_width = int(payload.get("frame_width", 0))
        frame_height = int(payload.get("frame_height", 0))
        if frame_width <= 0 or frame_height <= 0:
            raise TransformError("frame dimensions must be positive")

        self.kind = kind
        self.coefficients = coefficients.T
        self.target = target
        self.frame_width = frame_width
        self.frame_height = frame_height
        self.rms_error = rms
        self.condition = condition
        self.sample_count = len(samples)
        return self.status()

    def correction(self, payload):
        if not self.calibrated:
            raise TransformError("camera transform is not calibrated")
        point = payload.get("point")
        if not self._pair(point):
            raise TransformError("point must contain X and Y pixels")
        try:
            point = np.asarray(point, dtype=float)
        except (TypeError, ValueError):
            raise TransformError("point pixels must be numeric")
        if not np.isfinite(point).all():
            raise TransformError("point pixels must be finite")
        width = int(payload.get("frame_width", 0))
        height = int(payload.get("frame_height", 0))
        if width != self.frame_width or height != self.frame_height:
            raise TransformError(
                "camera resolution changed from %dx%d to %dx%d; recalibrate"
                % (self.frame_width, self.frame_height, width, height)
            )
        pixel_error = self.target - point
        feature = self._features(pixel_error.reshape(1, 2), self.kind)[0]
        move = self.coefficients @ feature
        return {
            "move_x": float(move[0]),
            "move_y": float(move[1]),
            "pixel_error_x": float(pixel_error[0]),
            "pixel_error_y": float(pixel_error[1]),
            "distance_mm": float(np.linalg.norm(move)),
        }

    def status(self):
        return {
            "calibrated": self.calibrated,
            "model": self.kind,
            "frame_width": self.frame_width,
            "frame_height": self.frame_height,
            "target": self.target.tolist() if self.target is not None else None,
            "rms_error": self.rms_error,
            "condition": self.condition,
            "sample_count": self.sample_count,
            "coefficients": (
                self.coefficients.tolist()
                if self.coefficients is not None
                else None
            ),
        }

    @staticmethod
    def _pair(value):
        return isinstance(value, (list, tuple)) and len(value) == 2

    @staticmethod
    def _features(pixel, kind):
        dx = pixel[:, 0]
        dy = pixel[:, 1]
        if kind == "affine":
            return np.column_stack((dx, dy))
        return np.column_stack((dx, dy, dx * dx, dy * dy, dx * dy))
