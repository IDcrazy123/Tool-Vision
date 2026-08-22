"""Automatic native-resolution nozzle detection.

The setup pass learns which preprocessing strategy and nozzle geometry are
stable for this particular camera. Runtime detection therefore needs no user
threshold, ROI, gamma, focus cutoff, or blob-size configuration.
"""

import math
import time

import cv2
import numpy as np


class DetectionError(RuntimeError):
    """The nozzle could not be identified unambiguously."""


STRATEGIES = (
    "adaptive_dark",
    "adaptive_light",
    "otsu_dark",
    "otsu_light",
    "edge",
)


def _odd(value, low=3, high=151):
    value = max(low, min(high, int(round(value))))
    return value if value % 2 else value + 1


def _median(values):
    return float(np.median(np.asarray(values, dtype=np.float64)))


class NozzleDetector:
    """Learn and apply a stable, center-biased nozzle detector."""

    PROFILE_SCHEMA = 1
    LEARN_FRAMES = 5
    STABLE_FRAMES = 3
    FRAME_INTERVAL = 0.20
    DETECT_TIMEOUT = 12.0

    def __init__(self, profile=None):
        self.profile = self._validate_profile(profile) if profile else None

    def learn(self, camera, frame_callback=None):
        """Learn a profile from a burst while the nozzle is near frame center."""
        observations = {name: [] for name in STRATEGIES}
        frame_shape = None
        for index in range(self.LEARN_FRAMES):
            frame = camera.capture()
            self._validate_frame(frame)
            height, width = frame.shape[:2]
            if frame_shape is None:
                frame_shape = (height, width)
            elif frame_shape != (height, width):
                raise DetectionError("camera resolution changed during setup")

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            for strategy in STRATEGIES:
                candidates = self._candidates(gray, strategy)
                chosen = self._choose_untrained(candidates, width, height)
                if chosen is not None:
                    observations[strategy].append(chosen)
            if frame_callback is not None:
                frame_callback(frame)
            if index + 1 < self.LEARN_FRAMES:
                time.sleep(self.FRAME_INTERVAL)

        ranked = []
        for strategy, candidates in observations.items():
            assessment = self._assess_learning(strategy, candidates, frame_shape)
            if assessment is not None:
                ranked.append(assessment)
        if not ranked:
            raise DetectionError(
                "no stable nozzle found near image center; clean the nozzle, "
                "adjust focus/light, then run setup again"
            )
        ranked.sort(key=lambda item: item["quality"], reverse=True)

        # Different preprocessing paths often find the same physical circle.
        # Only reject when two similarly good paths point at different objects.
        if len(ranked) > 1 and ranked[1]["quality"] >= ranked[0]["quality"] - 0.08:
            first = ranked[0]["center"]
            second = ranked[1]["center"]
            tolerance = max(3.0, ranked[0]["diameter_px"] * 0.20)
            if math.hypot(first[0] - second[0], first[1] - second[1]) > tolerance:
                raise DetectionError(
                    "two different center objects look like the nozzle; move the "
                    "nozzle closer to image center and retry"
                )

        best = ranked[0]
        height, width = frame_shape
        profile = {
            "schema_version": self.PROFILE_SCHEMA,
            "strategy": best["strategy"],
            "frame_width": width,
            "frame_height": height,
            "target_ratio": [0.5, 0.5],
            "area_ratio": best["area_ratio"],
            "radius_ratio": best["radius_px"] / float(min(width, height)),
            "min_circularity": max(0.12, best["circularity"] * 0.55),
            "min_convexity": max(0.35, best["convexity"] * 0.65),
        }
        self.profile = self._validate_profile(profile)
        observation = self.detect_stable(camera, frame_callback=frame_callback)
        return {"profile": dict(self.profile), "observation": observation}

    def detect_stable(self, camera, frame_callback=None, timeout=None):
        if self.profile is None:
            raise DetectionError("camera detector has not been taught")
        timeout = self.DETECT_TIMEOUT if timeout is None else float(timeout)
        if not math.isfinite(timeout) or timeout <= 0:
            raise DetectionError("detection timeout must be a positive finite value")
        deadline = time.monotonic() + timeout
        consecutive = []
        last_reason = "no candidate"
        while time.monotonic() < deadline:
            frame = camera.capture()
            self._validate_resolution(frame)
            candidate = self.detect_frame(frame)
            if candidate is None:
                consecutive = []
                last_reason = "no learned-profile candidate"
            else:
                consecutive.append(candidate)
                if len(consecutive) > self.STABLE_FRAMES:
                    consecutive.pop(0)
                if len(consecutive) == self.STABLE_FRAMES:
                    observation = self._stable_observation(consecutive, frame)
                    if observation is not None:
                        if frame_callback is not None:
                            frame_callback(self.annotate(frame, observation))
                        return observation
                    last_reason = "candidate moved between frames"
            if frame_callback is not None:
                frame_callback(frame)
            time.sleep(self.FRAME_INTERVAL)
        raise DetectionError(
            "nozzle detection was not stable within %.1fs (%s)" % (timeout, last_reason)
        )

    def detect_frame(self, frame):
        self._validate_resolution(frame)
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        candidates = self._candidates(gray, self.profile["strategy"])
        return self._choose_profiled(candidates, frame.shape[1], frame.shape[0])

    def annotate(self, frame, observation):
        output = frame.copy()
        width, height = frame.shape[1], frame.shape[0]
        target = (
            int(round(self.profile["target_ratio"][0] * width)),
            int(round(self.profile["target_ratio"][1] * height)),
        )
        center = (int(round(observation["x"])), int(round(observation["y"])))
        radius = max(3, int(round(observation["diameter_px"] / 2.0)))
        cv2.drawMarker(output, target, (0, 255, 255), cv2.MARKER_CROSS, 24, 2)
        cv2.circle(output, center, radius, (0, 255, 0), 2)
        return output

    @staticmethod
    def _validate_frame(frame):
        if frame is None or not hasattr(frame, "shape") or len(frame.shape) < 2:
            raise DetectionError("camera returned an invalid frame")
        if frame.shape[0] < 64 or frame.shape[1] < 64:
            raise DetectionError("camera frame is too small for nozzle detection")
        if len(frame.shape) != 3 or frame.shape[2] != 3:
            raise DetectionError("camera frame must contain three BGR channels")
        if getattr(frame, "dtype", None) != np.uint8:
            raise DetectionError("camera frame must use 8-bit BGR pixels")

    def _validate_resolution(self, frame):
        self._validate_frame(frame)
        if self.profile is None:
            return
        height, width = frame.shape[:2]
        expected = (self.profile["frame_width"], self.profile["frame_height"])
        if (width, height) != expected:
            raise DetectionError(
                "camera resolution changed from %dx%d to %dx%d; rerun camera setup"
                % (expected[0], expected[1], width, height)
            )

    @staticmethod
    def _validate_profile(profile):
        if not isinstance(profile, dict):
            raise DetectionError("detector profile must be an object")
        try:
            schema_version = int(profile.get("schema_version", -1))
        except (TypeError, ValueError):
            raise DetectionError("unsupported detector profile schema")
        if schema_version != NozzleDetector.PROFILE_SCHEMA:
            raise DetectionError("unsupported detector profile schema")
        strategy = profile.get("strategy")
        if strategy not in STRATEGIES:
            raise DetectionError("unknown detector strategy")
        try:
            width = int(profile["frame_width"])
            height = int(profile["frame_height"])
            if not isinstance(profile["target_ratio"], (list, tuple)) or len(
                profile["target_ratio"]
            ) != 2:
                raise ValueError
            target = [float(value) for value in profile["target_ratio"]]
            area = float(profile["area_ratio"])
            radius = float(profile["radius_ratio"])
            circularity = float(profile["min_circularity"])
            convexity = float(profile["min_convexity"])
        except (KeyError, TypeError, ValueError):
            raise DetectionError("detector profile contains invalid values")
        values = target + [area, radius, circularity, convexity]
        if width < 64 or height < 64 or not all(math.isfinite(v) for v in values):
            raise DetectionError("detector profile contains invalid values")
        if not (0 <= target[0] <= 1 and 0 <= target[1] <= 1):
            raise DetectionError("detector target is outside the frame")
        if not (0 < area < 0.25 and 0 < radius < 0.5):
            raise DetectionError("detector geometry is invalid")
        if not (0 < circularity <= 1 and 0 < convexity <= 1):
            raise DetectionError("detector geometry is invalid")
        clean = dict(profile)
        clean.update(
            {
                "frame_width": width,
                "frame_height": height,
                "target_ratio": target,
                "area_ratio": area,
                "radius_ratio": radius,
                "min_circularity": circularity,
                "min_convexity": convexity,
            }
        )
        return clean

    def _assess_learning(self, strategy, candidates, frame_shape):
        if len(candidates) < self.LEARN_FRAMES - 1:
            return None
        height, width = frame_shape
        xs = [item["x"] for item in candidates]
        ys = [item["y"] for item in candidates]
        center = [_median(xs), _median(ys)]
        radii = [item["radius_px"] for item in candidates]
        radius = _median(radii)
        spread = max(
            math.hypot(item["x"] - center[0], item["y"] - center[1])
            for item in candidates
        )
        stability_limit = max(1.5, radius * 0.08)
        if spread > stability_limit:
            return None
        center_distance = math.hypot(center[0] - width / 2.0, center[1] - height / 2.0)
        center_score = max(0.0, 1.0 - center_distance / (0.35 * math.hypot(width, height)))
        completeness = len(candidates) / float(self.LEARN_FRAMES)
        stability = max(0.0, 1.0 - spread / stability_limit)
        circularity = _median([item["circularity"] for item in candidates])
        convexity = _median([item["convexity"] for item in candidates])
        quality = (
            0.28 * completeness
            + 0.28 * stability
            + 0.24 * center_score
            + 0.12 * min(1.0, circularity)
            + 0.08 * min(1.0, convexity)
        )
        return {
            "strategy": strategy,
            "quality": quality,
            "center": center,
            "radius_px": radius,
            "diameter_px": radius * 2.0,
            "area_ratio": _median([item["area_ratio"] for item in candidates]),
            "circularity": circularity,
            "convexity": convexity,
        }

    @staticmethod
    def _choose_untrained(candidates, width, height):
        if not candidates:
            return None
        diagonal = math.hypot(width, height)
        usable = []
        for item in candidates:
            distance = math.hypot(item["x"] - width / 2.0, item["y"] - height / 2.0)
            if distance <= diagonal * 0.30:
                contrast = min(1.0, item["contrast"] / 40.0)
                center = max(0.0, 1.0 - distance / (diagonal * 0.30))
                score = (
                    0.52 * center
                    + 0.22 * item["circularity"]
                    + 0.10 * item["convexity"]
                    + 0.16 * contrast
                )
                usable.append((score, item))
        return max(usable, key=lambda pair: pair[0])[1] if usable else None

    def _choose_profiled(self, candidates, width, height):
        expected_area = self.profile["area_ratio"]
        expected_radius = self.profile["radius_ratio"] * min(width, height)
        target = (
            self.profile["target_ratio"][0] * width,
            self.profile["target_ratio"][1] * height,
        )
        diagonal = math.hypot(width, height)
        ranked = []
        for item in candidates:
            if not (expected_area * 0.30 <= item["area_ratio"] <= expected_area * 3.0):
                continue
            if not (expected_radius * 0.45 <= item["radius_px"] <= expected_radius * 2.2):
                continue
            if item["circularity"] < self.profile["min_circularity"]:
                continue
            if item["convexity"] < self.profile["min_convexity"]:
                continue
            distance = math.hypot(item["x"] - target[0], item["y"] - target[1])
            if distance > diagonal * 0.40:
                continue
            size_error = abs(math.log(max(item["area_ratio"], 1e-12) / expected_area))
            size_score = math.exp(-size_error)
            center_score = max(0.0, 1.0 - distance / (diagonal * 0.40))
            score = (
                0.42 * center_score
                + 0.30 * size_score
                + 0.16 * min(1.0, item["circularity"])
                + 0.12 * min(1.0, item["convexity"])
            )
            candidate = dict(item)
            candidate["confidence"] = max(0.0, min(1.0, score))
            ranked.append(candidate)
        if not ranked:
            return None
        ranked.sort(key=lambda item: item["confidence"], reverse=True)
        best = ranked[0]
        for other in ranked[1:]:
            distance = math.hypot(best["x"] - other["x"], best["y"] - other["y"])
            # RETR_LIST can return inner and outer contours for the same edge.
            # Collapse only candidates whose centers agree relative to their
            # learned-scale radii; two spatially distinct profile matches are
            # ambiguous regardless of which happens to be closer to the target.
            same_object = max(
                2.0, min(best["radius_px"], other["radius_px"]) * 0.25
            )
            if distance > same_object:
                raise DetectionError(
                    "multiple distinct objects match the learned nozzle profile; "
                    "clean the nozzle/view and retry"
                )
        return best

    def _stable_observation(self, candidates, frame):
        xs = [item["x"] for item in candidates]
        ys = [item["y"] for item in candidates]
        x = _median(xs)
        y = _median(ys)
        diameter = _median([item["radius_px"] * 2.0 for item in candidates])
        spread = max(math.hypot(item["x"] - x, item["y"] - y) for item in candidates)
        tolerance = max(1.5, diameter * 0.04)
        if spread > tolerance:
            return None
        focus = self._sharpness(frame, x, y, diameter)
        return {
            "x": x,
            "y": y,
            "diameter_px": diameter,
            "frame_width": int(frame.shape[1]),
            "frame_height": int(frame.shape[0]),
            "confidence": _median([item["confidence"] for item in candidates]),
            "stability_px": spread,
            "sharpness": focus,
            "sharpness_note": "relative metric; stable detection is the acceptance gate",
        }

    @staticmethod
    def _sharpness(frame, x, y, diameter):
        radius = max(8, int(round(diameter)))
        x0 = max(0, int(round(x)) - radius)
        x1 = min(frame.shape[1], int(round(x)) + radius + 1)
        y0 = max(0, int(round(y)) - radius)
        y1 = min(frame.shape[0], int(round(y)) + radius + 1)
        gray = cv2.cvtColor(frame[y0:y1, x0:x1], cv2.COLOR_BGR2GRAY)
        if gray.size < 16:
            return 0.0
        denoised = cv2.GaussianBlur(gray, (3, 3), 0)
        variance = float(cv2.Laplacian(denoised, cv2.CV_64F).var())
        contrast = float(np.std(denoised))
        return variance / max(contrast * contrast, 1.0)

    def _candidates(self, gray, strategy):
        height, width = gray.shape[:2]
        blur_size = _odd(min(width, height) * 0.008, high=15)
        blurred = cv2.GaussianBlur(gray, (blur_size, blur_size), 0)
        if strategy.startswith("adaptive"):
            block = _odd(min(width, height) * 0.10, low=21)
            kind = cv2.THRESH_BINARY_INV if strategy.endswith("dark") else cv2.THRESH_BINARY
            binary = cv2.adaptiveThreshold(
                blurred, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, kind, block, 3
            )
        elif strategy.startswith("otsu"):
            kind = cv2.THRESH_BINARY_INV if strategy.endswith("dark") else cv2.THRESH_BINARY
            _, binary = cv2.threshold(blurred, 0, 255, kind | cv2.THRESH_OTSU)
        elif strategy == "edge":
            median = float(np.median(blurred))
            lower = int(max(0, 0.66 * median))
            upper = int(min(255, max(lower + 1, 1.33 * median)))
            binary = cv2.Canny(blurred, lower, upper)
            binary = cv2.morphologyEx(
                binary, cv2.MORPH_CLOSE, np.ones((3, 3), dtype=np.uint8)
            )
        else:
            raise DetectionError("unknown detector strategy '%s'" % strategy)

        contours = cv2.findContours(binary, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)[-2]
        frame_area = float(width * height)
        minimum_radius = max(3.0, min(width, height) * 0.004)
        maximum_radius = min(width, height) * 0.22
        output = []
        for contour in contours:
            area = float(abs(cv2.contourArea(contour)))
            area_ratio = area / frame_area
            if not (0.00003 <= area_ratio <= 0.16):
                continue
            perimeter = float(cv2.arcLength(contour, True))
            if perimeter <= 0:
                continue
            (x, y), radius = cv2.minEnclosingCircle(contour)
            if not (minimum_radius <= radius <= maximum_radius):
                continue
            circularity = 4.0 * math.pi * area / (perimeter * perimeter)
            hull_area = float(abs(cv2.contourArea(cv2.convexHull(contour))))
            convexity = area / hull_area if hull_area > 0 else 0.0
            if circularity < 0.05 or convexity < 0.20:
                continue
            output.append(
                {
                    "x": float(x),
                    "y": float(y),
                    "radius_px": float(radius),
                    "area_ratio": area_ratio,
                    "circularity": min(1.0, circularity),
                    "convexity": min(1.0, convexity),
                    "contrast": self._local_contrast(gray, x, y, radius),
                }
            )
        return output

    @staticmethod
    def _local_contrast(gray, x, y, radius):
        radius = max(2, int(round(radius)))
        outer = max(radius + 2, int(round(radius * 1.6)))
        x0 = max(0, int(round(x)) - outer)
        x1 = min(gray.shape[1], int(round(x)) + outer + 1)
        y0 = max(0, int(round(y)) - outer)
        y1 = min(gray.shape[0], int(round(y)) + outer + 1)
        crop = gray[y0:y1, x0:x1]
        if crop.size < 16:
            return 0.0
        yy, xx = np.ogrid[: crop.shape[0], : crop.shape[1]]
        cx = x - x0
        cy = y - y0
        distance2 = (xx - cx) ** 2 + (yy - cy) ** 2
        inside = crop[distance2 <= radius * radius]
        ring = crop[(distance2 > radius * radius) & (distance2 <= outer * outer)]
        if inside.size == 0 or ring.size == 0:
            return 0.0
        return abs(float(np.mean(inside)) - float(np.mean(ring)))
