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


def _finite_scalar(value, name, minimum=None, strict=False):
    try:
        result = float(value)
    except (TypeError, ValueError):
        raise TransformError("%s must be a finite number" % name)
    if not math.isfinite(result):
        raise TransformError("%s must be a finite number" % name)
    if minimum is not None:
        invalid = result <= minimum if strict else result < minimum
        if invalid:
            relation = "greater than" if strict else "at least"
            raise TransformError("%s must be %s %.3f" % (name, relation, minimum))
    return result


class TransformModel:
    """Fit and validate a linear 2D mapping with automatic outlier rejection."""

    SCHEMA_VERSION = 2
    MAX_SAMPLES = 64
    # Contour coordinates originate from integer image samples even though
    # OpenCV returns a subpixel enclosing-circle center. Treat half a pixel as
    # the irreducible quantization radius instead of claiming zero noise when
    # cached/static frames return identical centers.
    PIXEL_NOISE_FLOOR = 0.5

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
        if len(samples) > self.MAX_SAMPLES:
            raise TransformError(
                "too many calibration samples; maximum is %d" % self.MAX_SAMPLES
            )
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
        sample_stability = []
        for index, sample in enumerate(samples):
            if not isinstance(sample, dict):
                raise TransformError("sample %d must be an object" % index)
            pixels.append(_pair(sample.get("pixel_delta"), "pixel_delta"))
            machine.append(_pair(sample.get("machine_delta"), "machine_delta"))
            sample_stability.append(
                _finite_scalar(
                    sample.get("stability_px"),
                    "sample %d stability_px" % index,
                    minimum=0.0,
                )
            )
        base_stability = _finite_scalar(
            payload.get("base_stability_px"),
            "base_stability_px",
            minimum=0.0,
        )
        max_uncertainty = _finite_scalar(
            payload.get("max_uncertainty_mm"),
            "max_uncertainty_mm",
            minimum=0.0,
            strict=True,
        )
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
                candidate, _, rank, _ = self._lstsq(
                    pixel_array[pair], machine_array[pair]
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
            matrix, _, rank, _ = self._lstsq(
                pixel_array[active], machine_array[active]
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

        matrix, _, rank, _ = self._lstsq(
            pixel_array[active], machine_array[active]
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
        residual_limit = max(0.025, typical_move * 0.12)
        if rms > residual_limit:
            raise TransformError("camera calibration residual is too large")

        # Training residual alone is optimistic. Refit without each accepted
        # point and predict that held-out observation so a high-leverage point
        # cannot validate itself.
        cross_validation_errors = []
        active_indices = np.flatnonzero(active)
        for held_index in active_indices:
            training = active.copy()
            training[held_index] = False
            held_matrix, _, held_rank, _ = self._lstsq(
                pixel_array[training], machine_array[training]
            )
            if held_rank < 2:
                raise TransformError("held-out calibration fit lost 2D rank")
            prediction = pixel_array[held_index].dot(held_matrix)
            cross_validation_errors.append(
                float(np.linalg.norm(prediction - machine_array[held_index]))
            )
        cross_validation_rms = float(
            math.sqrt(float(np.mean(np.square(cross_validation_errors))))
        )
        if cross_validation_rms > residual_limit:
            raise TransformError("held-out camera calibration error is too large")

        base_noise = max(self.PIXEL_NOISE_FLOOR, base_stability)
        delta_noise = np.asarray(
            [
                math.hypot(
                    base_noise,
                    max(self.PIXEL_NOISE_FLOOR, sample_stability[index]),
                )
                for index in range(len(samples))
            ],
            dtype=np.float64,
        )
        pixel_noise = float(np.max(delta_noise[active]))
        pixel_to_machine_gain = float(np.linalg.norm(matrix, ord=2))
        estimated_uncertainty = pixel_noise * pixel_to_machine_gain
        if (
            not math.isfinite(estimated_uncertainty)
            or estimated_uncertainty > max_uncertainty
        ):
            raise TransformError(
                "camera sensitivity cannot resolve %.4f mm target uncertainty "
                "(estimated %.4f mm); improve focus/resolution or move the "
                "camera closer"
                % (max_uncertainty, estimated_uncertainty)
            )

        transform = {
            "schema_version": self.SCHEMA_VERSION,
            "frame_width": width,
            "frame_height": height,
            "target_ratio": target_ratio,
            # Row-vector convention: machine_delta = pixel_delta dot matrix.
            "matrix": matrix.tolist(),
            "rms_error_mm": rms,
            "max_error_mm": maximum,
            "cross_validation_rms_mm": cross_validation_rms,
            "condition": condition,
            "pixel_noise_px": pixel_noise,
            "pixel_to_machine_gain_mm_per_px": pixel_to_machine_gain,
            "estimated_uncertainty_mm": estimated_uncertainty,
            "max_uncertainty_mm": max_uncertainty,
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
            "estimated_uncertainty_mm": self.transform[
                "estimated_uncertainty_mm"
            ],
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
        try:
            schema_version = int(transform.get("schema_version", -1))
        except (TypeError, ValueError):
            raise TransformError("unsupported transform schema")
        if schema_version != cls.SCHEMA_VERSION:
            raise TransformError("unsupported transform schema")
        try:
            width = int(transform["frame_width"])
            height = int(transform["frame_height"])
            target = _pair(transform["target_ratio"], "target_ratio")
            matrix = np.asarray(transform["matrix"], dtype=np.float64)
            estimated_uncertainty = _finite_scalar(
                transform["estimated_uncertainty_mm"],
                "estimated_uncertainty_mm",
                minimum=0.0,
            )
            max_uncertainty = _finite_scalar(
                transform["max_uncertainty_mm"],
                "max_uncertainty_mm",
                minimum=0.0,
                strict=True,
            )
            pixel_noise = _finite_scalar(
                transform["pixel_noise_px"],
                "pixel_noise_px",
                minimum=cls.PIXEL_NOISE_FLOOR,
            )
            reported_gain = _finite_scalar(
                transform["pixel_to_machine_gain_mm_per_px"],
                "pixel_to_machine_gain_mm_per_px",
                minimum=0.0,
                strict=True,
            )
            rms_error = _finite_scalar(
                transform["rms_error_mm"], "rms_error_mm", minimum=0.0
            )
            max_error = _finite_scalar(
                transform["max_error_mm"], "max_error_mm", minimum=0.0
            )
            cross_validation_rms = _finite_scalar(
                transform["cross_validation_rms_mm"],
                "cross_validation_rms_mm",
                minimum=0.0,
            )
            used_samples = int(transform["used_samples"])
            rejected_samples = int(transform["rejected_samples"])
        except (KeyError, TypeError, ValueError):
            raise TransformError("transform contains invalid values")
        if width < 64 or height < 64 or matrix.shape != (2, 2):
            raise TransformError("transform shape is invalid")
        if not np.all(np.isfinite(matrix)) or np.linalg.matrix_rank(matrix) < 2:
            raise TransformError("transform matrix is singular")
        condition = float(np.linalg.cond(matrix))
        if not math.isfinite(condition) or condition > 100.0:
            raise TransformError("transform matrix is poorly conditioned")
        calculated_gain = float(np.linalg.norm(matrix, ord=2))
        if not math.isclose(
            reported_gain, calculated_gain, rel_tol=1e-9, abs_tol=1e-12
        ):
            raise TransformError("transform sensitivity evidence is inconsistent")
        calculated_uncertainty = pixel_noise * calculated_gain
        if not math.isclose(
            estimated_uncertainty,
            calculated_uncertainty,
            rel_tol=1e-9,
            abs_tol=1e-12,
        ):
            raise TransformError("transform uncertainty evidence is inconsistent")
        if estimated_uncertainty > max_uncertainty:
            raise TransformError("transform uncertainty exceeds its safety limit")
        total_samples = used_samples + rejected_samples
        if (
            used_samples < 8
            or rejected_samples < 0
            or total_samples > cls.MAX_SAMPLES
            or used_samples < int(math.ceil(total_samples * 0.75))
        ):
            raise TransformError("transform sample evidence is invalid")
        if max_error + 1e-12 < rms_error:
            raise TransformError("transform residual evidence is inconsistent")
        if not all(0.0 <= value <= 1.0 for value in target):
            raise TransformError("transform target is invalid")
        clean = dict(transform)
        clean.update(
            {
                "frame_width": width,
                "frame_height": height,
                "target_ratio": target,
                "matrix": matrix.tolist(),
                "condition": condition,
                "pixel_noise_px": pixel_noise,
                "pixel_to_machine_gain_mm_per_px": calculated_gain,
                "estimated_uncertainty_mm": estimated_uncertainty,
                "max_uncertainty_mm": max_uncertainty,
                "rms_error_mm": rms_error,
                "max_error_mm": max_error,
                "cross_validation_rms_mm": cross_validation_rms,
                "used_samples": used_samples,
                "rejected_samples": rejected_samples,
            }
        )
        return clean

    @staticmethod
    def _lstsq(pixel_array, machine_array):
        try:
            return np.linalg.lstsq(pixel_array, machine_array, rcond=None)
        except np.linalg.LinAlgError as exc:
            raise TransformError("camera transform solver did not converge: %s" % exc)
