"""Resolution-independent nozzle detection derived from kTAMV's strategy."""

import math
import time

import cv2
import numpy as np


class DetectionError(RuntimeError):
    """Raised when stable nozzle detection cannot be produced."""


def _bounded(value, low, high):
    return max(low, min(high, value))


def _odd(value, minimum=3):
    value = max(minimum, int(value))
    return value if value % 2 else value + 1


class NozzleDetector:
    """Try multiple preprocessors and require a stable multi-frame result."""

    def __init__(self, settings, logger):
        self.log = logger
        self.settings = dict(settings)
        self.target_x_ratio = float(
            self.settings.get("camera_target_x_ratio", 0.5)
        )
        self.target_y_ratio = float(
            self.settings.get("camera_target_y_ratio", 0.5)
        )
        self.roi = (
            float(self.settings.get("camera_roi_x_min", 0.0)),
            float(self.settings.get("camera_roi_y_min", 0.0)),
            float(self.settings.get("camera_roi_x_max", 1.0)),
            float(self.settings.get("camera_roi_y_max", 1.0)),
        )
        self.gamma = float(self.settings.get("detector_gamma", 1.0))
        self.sensitivity = float(
            self.settings.get("detector_sensitivity", 1.0)
        )
        self.min_area_ratio = float(
            self.settings.get("detector_min_area_ratio", 0.0002)
        )
        self.max_area_ratio = float(
            self.settings.get("detector_max_area_ratio", 0.08)
        )
        self.min_circularity = float(
            self.settings.get("detector_min_circularity", 0.55)
        )
        self.min_convexity = float(
            self.settings.get("detector_min_convexity", 0.45)
        )
        self.min_inertia = float(
            self.settings.get("detector_min_inertia", 0.35)
        )
        self.adaptive_block_size = _odd(
            self.settings.get("detector_adaptive_block_size", 35)
        )
        self.adaptive_c = float(self.settings.get("detector_adaptive_c", 3.0))
        self.blur_size = _odd(self.settings.get("detector_blur_size", 5))
        self.polarity = str(
            self.settings.get("detector_polarity", "auto")
        ).lower()
        self.min_confidence = float(
            self.settings.get("detector_min_confidence", 0.35)
        )
        self.stable_frames = int(
            self.settings.get("detection_stable_frames", 3)
        )
        self.stability_px = float(
            self.settings.get("detection_stability_px", 2.0)
        )
        self.stability_ratio = float(
            self.settings.get("detection_stability_ratio", 0.0)
        )
        self.timeout = float(self.settings.get("detection_timeout", 12.0))
        self.interval = float(
            self.settings.get("detection_frame_interval_ms", 120)
        ) / 1000.0
        self._validate()

    def _validate(self):
        if not (0.0 <= self.target_x_ratio <= 1.0):
            raise DetectionError("camera_target_x_ratio must be between 0 and 1")
        if not (0.0 <= self.target_y_ratio <= 1.0):
            raise DetectionError("camera_target_y_ratio must be between 0 and 1")
        x0, y0, x1, y1 = self.roi
        if not (0.0 <= x0 < x1 <= 1.0 and 0.0 <= y0 < y1 <= 1.0):
            raise DetectionError("camera ROI ratios are invalid")
        if not (0 < self.min_area_ratio < self.max_area_ratio < 1):
            raise DetectionError("detector area ratios are invalid")
        if self.gamma <= 0:
            raise DetectionError("detector_gamma must be positive")
        if self.polarity not in ("auto", "dark", "light"):
            raise DetectionError("detector_polarity must be auto, dark, or light")
        if not 0.25 <= self.sensitivity <= 4.0:
            raise DetectionError("detector_sensitivity must be between 0.25 and 4")
        for name, value in (
            ("detector_min_circularity", self.min_circularity),
            ("detector_min_convexity", self.min_convexity),
            ("detector_min_inertia", self.min_inertia),
            ("detector_min_confidence", self.min_confidence),
        ):
            if not 0.0 <= value <= 1.0:
                raise DetectionError("%s must be between 0 and 1" % name)
        if self.stable_frames < 1 or self.timeout <= 0 or self.interval < 0:
            raise DetectionError("detection stability settings are invalid")
        if self.stability_px < 0 or not 0.0 <= self.stability_ratio <= 1.0:
            raise DetectionError("detection stability tolerances are invalid")

    def detect_stable(self, camera, frame_callback=None):
        """Return a median nozzle center after consecutive stable frames."""
        started = time.monotonic()
        points = []
        observations = []
        last_error = "no candidate"

        while time.monotonic() - started < self.timeout:
            frame = camera.capture()
            observation, annotated = self.detect_frame(frame)
            if frame_callback is not None:
                frame_callback(annotated)

            if observation is None:
                points = []
                observations = []
                last_error = "no candidate passed the detector filters"
            else:
                point = np.array([observation["x"], observation["y"]])
                height, width = frame.shape[:2]
                tolerance = max(
                    self.stability_px,
                    self.stability_ratio * math.hypot(width, height),
                )
                if points:
                    center = np.median(np.asarray(points), axis=0)
                    if float(np.linalg.norm(point - center)) > tolerance:
                        points = []
                        observations = []
                points.append(point)
                observations.append(observation)

                if len(points) >= self.stable_frames:
                    sample = np.asarray(points[-self.stable_frames :])
                    median = np.median(sample, axis=0)
                    spread = np.std(sample, axis=0)
                    best = max(
                        observations[-self.stable_frames :],
                        key=lambda item: item["confidence"],
                    )
                    result = dict(best)
                    result.update(
                        {
                            "x": float(median[0]),
                            "y": float(median[1]),
                            "sample_count": self.stable_frames,
                            "stdev_x": float(spread[0]),
                            "stdev_y": float(spread[1]),
                            "runtime": time.monotonic() - started,
                        }
                    )
                    return result
            if self.interval > 0:
                time.sleep(self.interval)

        raise DetectionError(
            "stable nozzle detection timed out after %.1fs (%s)"
            % (self.timeout, last_error)
        )

    def detect_frame(self, frame):
        """Detect the best nozzle-hole candidate in one native-size frame."""
        if frame is None or frame.ndim != 3:
            raise DetectionError("detector requires a BGR image")
        height, width = frame.shape[:2]
        target = np.array(
            [self.target_x_ratio * width, self.target_y_ratio * height]
        )
        x0 = int(round(self.roi[0] * width))
        y0 = int(round(self.roi[1] * height))
        x1 = int(round(self.roi[2] * width))
        y1 = int(round(self.roi[3] * height))
        roi_frame = frame[y0:y1, x0:x1]
        if roi_frame.size == 0:
            raise DetectionError("configured camera ROI is empty")
        if min(roi_frame.shape[:2]) < 3:
            raise DetectionError("configured camera ROI is too small")

        gray = cv2.cvtColor(roi_frame, cv2.COLOR_BGR2GRAY)
        gray = self._apply_gamma(gray)
        gray = cv2.GaussianBlur(gray, (self.blur_size, self.blur_size), 0)
        masks = self._preprocess(gray)

        frame_area = float(width * height)
        candidates = []
        for profile_name, relax in (("strict", 1.0), ("relaxed", 1.65)):
            for strategy_name, mask in masks:
                candidates.extend(
                    self._candidates(
                        mask,
                        x0,
                        y0,
                        frame_area,
                        target,
                        profile_name,
                        strategy_name,
                        relax,
                        width,
                        height,
                    )
                )
            if candidates:
                break

        annotated = frame.copy()
        self._draw_context(annotated, target, (x0, y0, x1, y1))
        if not candidates:
            return None, annotated

        best = max(candidates, key=lambda item: item["confidence"])
        if best["confidence"] < self.min_confidence:
            return None, annotated
        self._draw_candidate(annotated, best)
        return best, annotated

    def _preprocess(self, gray):
        masks = []
        smallest_dimension = min(gray.shape[:2])
        largest_valid_block = (
            smallest_dimension
            if smallest_dimension % 2
            else smallest_dimension - 1
        )
        adaptive_block_size = min(
            self.adaptive_block_size, largest_valid_block
        )
        dark = self.polarity in ("auto", "dark")
        light = self.polarity in ("auto", "light")
        if dark:
            masks.append(
                (
                    "adaptive-dark",
                    cv2.adaptiveThreshold(
                        gray,
                        255,
                        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                        cv2.THRESH_BINARY_INV,
                        adaptive_block_size,
                        self.adaptive_c,
                    ),
                )
            )
            _, otsu_dark = cv2.threshold(
                gray, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU
            )
            masks.append(("otsu-dark", otsu_dark))
        if light:
            masks.append(
                (
                    "adaptive-light",
                    cv2.adaptiveThreshold(
                        gray,
                        255,
                        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                        cv2.THRESH_BINARY,
                        adaptive_block_size,
                        -self.adaptive_c,
                    ),
                )
            )
            _, otsu_light = cv2.threshold(
                gray, 0, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU
            )
            masks.append(("otsu-light", otsu_light))
        kernel = np.ones((3, 3), np.uint8)
        return [
            (name, cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel))
            for name, mask in masks
        ]

    def _candidates(
        self,
        mask,
        offset_x,
        offset_y,
        frame_area,
        target,
        profile,
        strategy,
        relax,
        width,
        height,
    ):
        contours, _ = cv2.findContours(
            mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        sensitivity = _bounded(self.sensitivity, 0.25, 4.0)
        min_area = frame_area * self.min_area_ratio / (relax * sensitivity)
        max_area = frame_area * self.max_area_ratio * relax * sensitivity
        min_circularity = self.min_circularity / (relax * math.sqrt(sensitivity))
        min_convexity = self.min_convexity / (relax * math.sqrt(sensitivity))
        min_inertia = self.min_inertia / (relax * math.sqrt(sensitivity))
        diagonal = math.hypot(width, height)
        output = []

        for contour in contours:
            area = float(cv2.contourArea(contour))
            if area < min_area or area > max_area:
                continue
            perimeter = float(cv2.arcLength(contour, True))
            if perimeter <= 0:
                continue
            circularity = 4.0 * math.pi * area / (perimeter * perimeter)
            hull_area = float(cv2.contourArea(cv2.convexHull(contour)))
            convexity = area / hull_area if hull_area > 0 else 0.0
            bx, by, bw, bh = cv2.boundingRect(contour)
            inertia = min(bw, bh) / float(max(bw, bh)) if max(bw, bh) else 0.0
            if (
                circularity < min_circularity
                or convexity < min_convexity
                or inertia < min_inertia
            ):
                continue
            moments = cv2.moments(contour)
            if moments["m00"] == 0:
                continue
            x = moments["m10"] / moments["m00"] + offset_x
            y = moments["m01"] / moments["m00"] + offset_y
            distance_score = 1.0 - _bounded(
                float(np.linalg.norm(np.array([x, y]) - target))
                / (0.5 * diagonal),
                0.0,
                1.0,
            )
            shape_score = (
                _bounded(circularity, 0.0, 1.0)
                + _bounded(convexity, 0.0, 1.0)
                + _bounded(inertia, 0.0, 1.0)
            ) / 3.0
            confidence = 0.58 * shape_score + 0.42 * distance_score
            output.append(
                {
                    "x": float(x),
                    "y": float(y),
                    "diameter_px": float(2.0 * math.sqrt(area / math.pi)),
                    "area_px": area,
                    "circularity": circularity,
                    "convexity": convexity,
                    "inertia": inertia,
                    "confidence": confidence,
                    "strategy": strategy,
                    "profile": profile,
                    "frame_width": width,
                    "frame_height": height,
                    "target_x": float(target[0]),
                    "target_y": float(target[1]),
                }
            )
        return output

    def _apply_gamma(self, gray):
        if abs(self.gamma - 1.0) < 1e-6:
            return gray
        inverse = 1.0 / self.gamma
        table = np.array(
            [((value / 255.0) ** inverse) * 255 for value in range(256)]
        ).astype("uint8")
        return cv2.LUT(gray, table)

    @staticmethod
    def _draw_context(frame, target, roi):
        tx, ty = int(round(target[0])), int(round(target[1]))
        cv2.rectangle(
            frame,
            (roi[0], roi[1]),
            (roi[2] - 1, roi[3] - 1),
            (255, 180, 0),
            1,
        )
        cv2.line(frame, (tx - 15, ty), (tx + 15, ty), (255, 255, 255), 1)
        cv2.line(frame, (tx, ty - 15), (tx, ty + 15), (255, 255, 255), 1)

    @staticmethod
    def _draw_candidate(frame, candidate):
        center = (int(round(candidate["x"])), int(round(candidate["y"])))
        radius = max(3, int(round(candidate["diameter_px"] / 2.0)))
        cv2.circle(frame, center, radius, (0, 255, 0), 2, cv2.LINE_AA)
        cv2.circle(frame, center, 2, (0, 0, 255), -1, cv2.LINE_AA)
        text = "%s/%s %.2f" % (
            candidate["profile"],
            candidate["strategy"],
            candidate["confidence"],
        )
        cv2.putText(
            frame,
            text,
            (10, 28),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.65,
            (0, 255, 0),
            2,
            cv2.LINE_AA,
        )
