"""ToolVision host service.

OpenCV/NumPy work runs here instead of in Klipper. The API uses short requests
plus a single-worker job queue so Klipper can poll without blocking its reactor
for an entire camera-detection timeout.
"""

import argparse
import logging
import os
import threading
import time
import uuid
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

import cv2
from flask import Flask, Response, jsonify, request
from werkzeug.exceptions import HTTPException

try:
    from . import __version__ as VERSION
    from .camera import CameraError, CameraSource, resolve_camera
    from .detection import DetectionError, NozzleDetector
    from .transform import TransformError, TransformModel
except ImportError:  # pragma: no cover - direct script execution
    VERSION = "3.2.1"
    from camera import CameraError, CameraSource, resolve_camera
    from detection import DetectionError, NozzleDetector
    from transform import TransformError, TransformModel

class ServiceState:
    """Thread-safe ownership of one camera and one serial detection queue."""

    def __init__(self, logger=None):
        self.log = logger or logging.getLogger("tool_vision")
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="vision")
        self.camera = None
        self.camera_descriptor = None
        self.detector = None
        self.transform = TransformModel()
        self.settings = {}
        self.jobs = OrderedDict()
        self.active_job = None
        self.latest_jpeg = None

    def close(self):
        with self.lock:
            if self.camera is not None:
                self.camera.close()
            self.camera = None
        self.executor.shutdown(wait=False, cancel_futures=True)

    def configure(self, settings):
        if not isinstance(settings, dict):
            raise CameraError("configuration body must be an object")
        with self.lock:
            if self.active_job is not None:
                raise DetectionError("camera is busy with job %s" % self.active_job)

        descriptor = resolve_camera(settings)
        candidate = CameraSource(
            descriptor,
            timeout=float(settings.get("read_timeout", 5.0)),
        )
        try:
            frame = candidate.capture()
        except Exception:
            candidate.close()
            raise
        profile = settings.get("profile")
        transform = settings.get("transform")
        detector = NozzleDetector(profile) if profile else NozzleDetector()
        model = TransformModel(transform) if transform else TransformModel()

        with self.lock:
            previous = self.camera
            self.camera = candidate
            self.camera_descriptor = descriptor
            self.detector = detector
            self.transform = model
            self.settings = dict(settings)
            self._store_frame(frame)
            if previous is not None:
                previous.close()
        return self.health()

    def start_job(self, kind):
        if kind not in ("learn", "detect"):
            raise DetectionError("unknown job type '%s'" % kind)
        with self.lock:
            if self.camera is None or self.detector is None:
                raise DetectionError("camera service has not been configured")
            if self.active_job is not None:
                raise DetectionError("camera is busy with job %s" % self.active_job)
            if kind == "detect" and self.detector.profile is None:
                raise DetectionError("camera detector has not been taught")
            job_id = uuid.uuid4().hex
            self.jobs[job_id] = {
                "id": job_id,
                "kind": kind,
                "status": "queued",
                "created": time.time(),
            }
            self.active_job = job_id
            self._trim_jobs()
            self.executor.submit(self._run_job, job_id, kind)
            return dict(self.jobs[job_id])

    def get_job(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            return dict(job) if job else None

    def fit_transform(self, payload):
        with self.lock:
            if self.active_job is not None:
                raise TransformError("camera is busy with job %s" % self.active_job)
            transform = self.transform.fit(payload)
            return {"transform": transform}

    def correction(self, payload):
        with self.lock:
            return {"correction": self.transform.correction(payload)}

    def clear_transform(self):
        with self.lock:
            self.transform.clear()
        return {"ok": True}

    def health(self):
        with self.lock:
            descriptor = None
            if self.camera_descriptor is not None:
                descriptor = {
                    key: self.camera_descriptor.get(key)
                    for key in ("name", "location", "discovered", "uid", "rotation")
                    if key in self.camera_descriptor
                }
            profile = dict(self.detector.profile) if self.detector and self.detector.profile else None
            return {
                "ok": True,
                "version": VERSION,
                "configured": self.camera is not None,
                "camera": descriptor,
                "profile": profile,
                "transform": self.transform.status(),
                "active_job": self.active_job,
                "has_preview": self.latest_jpeg is not None,
            }

    def _run_job(self, job_id, kind):
        with self.lock:
            self.jobs[job_id]["status"] = "running"
            self.jobs[job_id]["started"] = time.time()
            camera = self.camera
            detector = self.detector
        try:
            if kind == "learn":
                result = detector.learn(camera, frame_callback=self._store_frame)
            else:
                result = {"observation": detector.detect_stable(
                    camera, frame_callback=self._store_frame
                )}
            with self.lock:
                self.jobs[job_id].update(
                    {"status": "complete", "result": result, "finished": time.time()}
                )
        except Exception as exc:
            self.log.exception("camera job %s failed", job_id)
            with self.lock:
                self.jobs[job_id].update(
                    {"status": "error", "error": str(exc), "finished": time.time()}
                )
        finally:
            with self.lock:
                if self.active_job == job_id:
                    self.active_job = None

    def _store_frame(self, frame):
        ok, encoded = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 88])
        if ok:
            with self.lock:
                self.latest_jpeg = encoded.tobytes()

    def _trim_jobs(self):
        while len(self.jobs) > 40:
            key, job = next(iter(self.jobs.items()))
            if key == self.active_job or job.get("status") in ("queued", "running"):
                break
            self.jobs.popitem(last=False)


def create_app(log_directory=None):
    app = Flask(__name__)
    logger = logging.getLogger("tool_vision")
    if log_directory:
        os.makedirs(log_directory, exist_ok=True)
        if not any(isinstance(handler, logging.FileHandler) for handler in logger.handlers):
            handler = logging.FileHandler(
                os.path.join(log_directory, "tool-vision.log"), encoding="utf-8"
            )
            handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)s %(message)s")
            )
            logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    state = ServiceState(logger)
    app.config["TOOL_VISION_STATE"] = state

    def body():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise DetectionError("request body must be a JSON object")
        return payload

    @app.errorhandler(CameraError)
    @app.errorhandler(DetectionError)
    @app.errorhandler(TransformError)
    def expected_error(exc):
        return jsonify({"ok": False, "error": str(exc)}), 400

    @app.errorhandler(Exception)
    def unexpected_error(exc):
        if isinstance(exc, HTTPException):
            return exc
        logger.exception("unhandled API error")
        return jsonify({"ok": False, "error": "internal service error"}), 500

    @app.get("/api/v2/health")
    def health():
        return jsonify(state.health())

    @app.post("/api/v2/config")
    def configure():
        return jsonify(state.configure(body()))

    @app.post("/api/v2/jobs/<kind>")
    def start_job(kind):
        return jsonify(state.start_job(kind)), 202

    @app.get("/api/v2/jobs/<job_id>")
    def get_job(job_id):
        job = state.get_job(job_id)
        if job is None:
            return jsonify({"ok": False, "error": "job not found"}), 404
        return jsonify(job)

    @app.post("/api/v2/transform/fit")
    def fit_transform():
        return jsonify(state.fit_transform(body()))

    @app.post("/api/v2/transform/correction")
    def correction():
        return jsonify(state.correction(body()))

    @app.delete("/api/v2/transform")
    def clear_transform():
        return jsonify(state.clear_transform())

    @app.get("/api/v2/frame")
    def frame():
        with state.lock:
            jpeg = state.latest_jpeg
        if jpeg is None:
            return jsonify({"ok": False, "error": "no frame captured"}), 404
        return Response(jpeg, mimetype="image/jpeg")

    @app.get("/")
    def index():
        return jsonify(
            {
                "name": "ToolVision host service",
                "version": VERSION,
                "health": "/api/v2/health",
                "preview": "/api/v2/frame",
            }
        )

    return app


def main():
    parser = argparse.ArgumentParser(description="ToolVision camera service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8085)
    parser.add_argument("--log-directory", default=None)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    from waitress import serve

    serve(create_app(args.log_directory), host=args.host, port=args.port, threads=4)


if __name__ == "__main__":
    main()
