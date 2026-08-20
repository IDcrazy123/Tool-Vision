"""Versioned HTTP API for Tool Vision."""

import argparse
import logging
from logging.handlers import RotatingFileHandler
import os
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

import cv2
from flask import Flask, Response, jsonify, request
from waitress import serve

from . import __version__
from .camera import CameraError, CameraSource
from .detection import DetectionError, NozzleDetector
from .transform import TransformError, TransformModel


class ServiceState:
    def __init__(self, logger):
        self.log = logger
        self.lock = threading.RLock()
        self.camera = None
        self.detector = None
        self.settings = {}
        self.model = TransformModel()
        self.jobs = {}
        self.active_job = None
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.latest_jpeg = None
        self.latest_observation = None

    def configure(self, settings):
        with self.lock:
            if self.active_job is not None:
                raise DetectionError(
                    "cannot reconfigure while a detection job is running"
                )

        camera = CameraSource(settings, self.log)
        try:
            detector = NozzleDetector(settings, self.log)
        except Exception:
            camera.close()
            raise

        with self.lock:
            if self.active_job is not None:
                old_camera = None
                rejected = True
            else:
                old_camera = self.camera
                self.camera = camera
                self.detector = detector
                self.settings = dict(settings)
                self.model.clear()
                self.latest_jpeg = None
                self.latest_observation = None
                rejected = False

        if rejected:
            camera.close()
            raise DetectionError(
                "cannot reconfigure while a detection job is running"
            )
        if old_camera is not None:
            old_camera.close()

    def start_detection(self):
        with self.lock:
            if self.camera is None or self.detector is None:
                raise DetectionError("vision server is not configured")
            if self.active_job is not None:
                raise DetectionError("another detection job is already running")
            job_id = uuid.uuid4().hex
            self.jobs[job_id] = {
                "job_id": job_id,
                "state": "queued",
                "created": time.time(),
                "result": None,
                "error": None,
            }
            self.active_job = job_id
            self._trim_jobs()
            self.executor.submit(self._run_detection, job_id)
            return dict(self.jobs[job_id])

    def _run_detection(self, job_id):
        with self.lock:
            self.jobs[job_id]["state"] = "running"
            self.jobs[job_id]["started"] = time.time()
            camera = self.camera
            detector = self.detector
        try:
            result = detector.detect_stable(camera, self._store_frame)
            with self.lock:
                self.latest_observation = result
                self.jobs[job_id]["state"] = "complete"
                self.jobs[job_id]["result"] = result
        except Exception as exc:
            self.log.exception("detection job %s failed", job_id)
            with self.lock:
                self.jobs[job_id]["state"] = "error"
                self.jobs[job_id]["error"] = str(exc)
        finally:
            with self.lock:
                self.jobs[job_id]["finished"] = time.time()
                self.active_job = None

    def _store_frame(self, frame):
        ok, encoded = cv2.imencode(".jpg", frame)
        if ok:
            with self.lock:
                self.latest_jpeg = encoded.tobytes()

    def _trim_jobs(self):
        if len(self.jobs) <= 50:
            return
        finished = [
            item
            for item in self.jobs.values()
            if item["state"] in ("complete", "error")
        ]
        for item in sorted(finished, key=lambda entry: entry["created"])[:10]:
            self.jobs.pop(item["job_id"], None)

    def health(self):
        with self.lock:
            frame = None
            if self.latest_observation:
                frame = {
                    "width": self.latest_observation["frame_width"],
                    "height": self.latest_observation["frame_height"],
                }
            return {
                "version": __version__,
                "configured": self.camera is not None,
                "busy": self.active_job is not None,
                "camera_frame": frame,
                "transform": self.model.status(),
            }


def create_app(log_directory=None):
    app = Flask(__name__)
    logger = logging.getLogger("tool_vision")
    logger.setLevel(logging.INFO)
    if not logger.handlers:
        log_directory = log_directory or os.environ.get(
            "TOOL_VISION_LOG_DIR", os.path.join(os.getcwd(), "logs")
        )
        os.makedirs(log_directory, exist_ok=True)
        handler = RotatingFileHandler(
            os.path.join(log_directory, "tool_vision.log"),
            maxBytes=2 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        )
        logger.addHandler(handler)
        logger.addHandler(logging.StreamHandler())

    state = ServiceState(logger)
    app.config["TOOL_VISION_STATE"] = state

    def json_body():
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            raise ValueError("request body must be a JSON object")
        return payload

    def error_response(exc, status=400):
        return jsonify({"ok": False, "error": str(exc)}), status

    @app.get("/api/v1/health")
    def health():
        return jsonify({"ok": True, **state.health()})

    @app.post("/api/v1/config")
    def configure():
        try:
            state.configure(json_body())
            return jsonify({"ok": True, **state.health()})
        except (TypeError, ValueError, CameraError, DetectionError) as exc:
            return error_response(exc)

    @app.post("/api/v1/jobs/detect")
    def start_detection():
        try:
            return jsonify({"ok": True, "job": state.start_detection()}), 202
        except DetectionError as exc:
            return error_response(exc, 409)

    @app.get("/api/v1/jobs/<job_id>")
    def get_job(job_id):
        with state.lock:
            job = state.jobs.get(job_id)
            if job is None:
                return error_response("unknown detection job", 404)
            return jsonify({"ok": True, "job": dict(job)})

    @app.post("/api/v1/model")
    def fit_model():
        try:
            with state.lock:
                result = state.model.fit(json_body())
            return jsonify({"ok": True, "transform": result})
        except (TypeError, ValueError, TransformError) as exc:
            return error_response(exc)

    @app.delete("/api/v1/model")
    def clear_model():
        with state.lock:
            state.model.clear()
        return jsonify({"ok": True})

    @app.post("/api/v1/offset")
    def calculate_offset():
        try:
            with state.lock:
                result = state.model.correction(json_body())
            return jsonify({"ok": True, "correction": result})
        except (TypeError, ValueError, TransformError) as exc:
            return error_response(exc)

    @app.get("/api/v1/frame")
    def latest_frame():
        with state.lock:
            frame = state.latest_jpeg
        if frame is None:
            return error_response("no processed frame is available", 404)
        return Response(frame, mimetype="image/jpeg")

    @app.get("/")
    def index():
        return jsonify(
            {
                "name": "Tool Vision",
                "version": __version__,
                "health": "/api/v1/health",
                "latest_frame": "/api/v1/frame",
            }
        )

    return app


def main():
    parser = argparse.ArgumentParser(description="Tool Vision host service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8085)
    parser.add_argument("--log-dir", default=None)
    args = parser.parse_args()
    serve(create_app(args.log_dir), host=args.host, port=args.port, threads=4)


if __name__ == "__main__":
    main()
