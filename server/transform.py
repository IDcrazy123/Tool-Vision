"""Robust pixel-to-machine transform used by the camera calibration loop."""

import math

import numpy as np


class TransformError(RuntimeError):
    """Calibration samples do not define a trustworthy 2D transform."""


def _pair(value, name):
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        raise TransformError("%s must contain two numbers" % name)
    try:
        pair = [float(value[0]), float(value[1])]
    except (TypeError, ValueError):
        raise TransformError("%s must contain two numbers" % name)
    if not all(math.isfinite(item) for item in pair):
        raise TransformError("%s must contain finite numbers" % name)
    return pair


class TransformModel:
    """Fit and validate a linear 2D mapping with automatic outlier rejection."""

    SCHEMA_VERSION = 1

    def __init__(self, transform=None):
        self.transform = self._validate_transform(transform) if transform else None

    @property
    def calibrated(self):
        return self.transform is not None

    def clear(self):
        self.transform = None

    def fit(self, payload):
        samples = payload.get("samples")
        if not isinstance(samples, list) or len(samples) < 8:
            raise TransformError("at least 8 calibration samples are required")
        target_ratio = _pair(payload.get("target_ratio", [0.5, 0.5]), "target_ratio")
        if not all(0.0 <= value <= 1.0 for value in target_ratio):
            raise TransformError("target_ratio must be inside the frame")
        try:
            width = int(payload["frame_width"])
            height = int(payload["frame_height"])
        except (KeyError, TypeError, ValueError):
            raise TransformError("frame dimensions are required")
        if width < 64 or height < 64:
            raise TransformError("frame dimensions are too small")

        pixels = []
        machine = []
        for index, sample in enumerate(samples):
            if not isinstance(sample, dict):
                raise TransformError("sample %d must be an object" % index)
            pixels.append(_pair(sample.get("pixel_delta"), "pixel_delta"))
            machine.append(_pair(sample.get("machine_delta"), "machine_delta"))
        pixel_array = np.asarray(pixels, dtype=np.float64)
        machine_array = np.asarray(machine, dtype=np.float64)
        if np.linalg.matrix_rank(pixel_array) < 2:
            raise TransformError("calibration moves do not span both image axes")

        required = max(8, int(math.ceil(len(samples) * 0.75)))
        move_lengths = np.linalg.norm(machine_array, axis=1)
        limits = np.maximum(0.02, move_lengths * 0.20)

        # Seed the fit from every independent pair. Ordinary least squares on
        # all points can be pulled far enough by two gross detections that it
        # rejects good points too. Ten kTAMV positions make this tiny RANSAC-like
        # search deterministic and inexpensive (at most 45 pairs).
        active = None
        best_score = None
        for first in range(len(samples)):
            for second in range(first + 1, len(samples)):
                pair = np.asarray([first, second])
                if np.linalg.matrix_rank(pixel_array[pair]) < 2:
                    continue
                candidate, _, rank, _ = np.linalg.lstsq(
                    pixel_array[pair], machine_array[pair], rcond=None
                )
                if rank < 2:
                    continue
                errors = np.linalg.norm(
                    pixel_array.dot(candidate) - machine_array, axis=1
                )
                inliers = errors <= limits
                score = (int(np.count_nonzero(inliers)), -float(np.sum(errors[inliers])))
                if best_score is None or score > best_score:
                    best_score = score
                    active = inliers
        if active is None or int(np.count_nonzero(active)) < required:
            raise TransformError("more than 25% of calibration points are inconsistent")

        for _ in range(3):
            matrix, _, rank, _ = np.linalg.lstsq(
                pixel_array[active], machine_array[active], rcond=None
            )
            if rank < 2:
                raise TransformError("usable calibration points lost 2D rank")
            residuals = np.linalg.norm(pixel_array.dot(matrix) - machine_array, axis=1)
            # kTAMV discards scale observations that deviate by more than 20%.
            # For a full affine map, relative prediction error is the equivalent
            # directional test, with 0.02 mm allowance for camera quantization.
            next_active = residuals <= limits
            if int(np.count_nonzero(next_active)) < required:
                raise TransformError(
                    "more than 25% of calibration points are inconsistent"
                )
            if np.array_equal(next_active, active):
                break
            active = next_active

        matrix, _, rank, _ = np.linalg.lstsq(
            pixel_array[active], machine_array[active], rcond=None
        )
        if rank < 2 or np.linalg.matrix_rank(matrix) < 2:
            raise TransformError("pixel-to-machine transform is singular")
        condition = float(np.linalg.cond(matrix))
        if not math.isfinite(condition) or condition > 100.0:
            raise TransformError("pixel-to-machine transform is poorly conditioned")

        residuals = np.linalg.norm(
            pixel_array[active].dot(matrix) - machine_array[active], axis=1
        )
        rms = float(math.sqrt(float(np.mean(residuals * residuals))))
        maximum = float(np.max(residuals))
        typical_move = float(np.median(np.linalg.norm(machine_array[active], axis=1)))
        if rms > max(0.025, typical_move * 0.12):
            raise TransformError("camera calibration residual is too large")

        transform = {
            "schema_version": self.SCHEMA_VERSION,
            "frame_width": width,
            "frame_height": height,
            "target_ratio": target_ratio,
            # Row-vector convention: machine_delta = pixel_delta dot matrix.
            "matrix": matrix.tolist(),
            "rms_error_mm": rms,
            "max_error_mm": maximum,
            "condition": condition,
            "used_samples": int(np.count_nonzero(active)),
            "rejected_samples": int(len(samples) - np.count_nonzero(active)),
        }
        self.transform = self._validate_transform(transform)
        return dict(self.transform)

    def correction(self, payload):
        if self.transform is None:
            raise TransformError("camera transform has not been calibrated")
        point = _pair(payload.get("point"), "point")
        try:
            width = int(payload["frame_width"])
            height = int(payload["frame_height"])
        except (KeyError, TypeError, ValueError):
            raise TransformError("frame dimensions are required")
        expected = (self.transform["frame_width"], self.transform["frame_height"])
        if (width, height) != expected:
            raise TransformError(
                "camera resolution changed from %dx%d to %dx%d; rerun setup"
                % (expected[0], expected[1], width, height)
            )
        target = np.asarray(
            [
                self.transform["target_ratio"][0] * width,
                self.transform["target_ratio"][1] * height,
            ],
            dtype=np.float64,
        )
        delta = target - np.asarray(point, dtype=np.float64)
        move = delta.dot(np.asarray(self.transform["matrix"], dtype=np.float64))
        return {
            "move_x": float(move[0]),
            "move_y": float(move[1]),
            "pixel_error": [float(delta[0]), float(delta[1])],
            "distance_mm": float(np.linalg.norm(move)),
        }

    def status(self):
        if not self.transform:
            return {"calibrated": False}
        status = dict(self.transform)
        status["calibrated"] = True
        return status

    @classmethod
    def _validate_transform(cls, transform):
        if not isinstance(transform, dict):
            raise TransformError("transform must be an object")
        if int(transform.get("schema_version", -1)) != cls.SCHEMA_VERSION:
            raise TransformError("unsupported transform schema")
        try:
            width = int(transform["frame_width"])
            height = int(transform["frame_height"])
            target = _pair(transform["target_ratio"], "target_ratio")
            matrix = np.asarray(transform["matrix"], dtype=np.float64)
        except (KeyError, TypeError, ValueError):
            raise TransformError("transform contains invalid values")
        if width < 64 or height < 64 or matrix.shape != (2, 2):
            raise TransformError("transform shape is invalid")
        if not np.all(np.isfinite(matrix)) or np.linalg.matrix_rank(matrix) < 2:
            raise TransformError("transform matrix is singular")
        if not all(0.0 <= value <= 1.0 for value in target):
            raise TransformError("transform target is invalid")
        clean = dict(transform)
        clean.update(
            {
                "frame_width": width,
                "frame_height": height,
                "target_ratio": target,
                "matrix": matrix.tolist(),
            }
        )
        return clean
