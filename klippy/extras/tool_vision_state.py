"""Validated, atomic persistence for ToolVision learned setup and results."""

import json
import math
import os
import time


class StateError(RuntimeError):
    """Learned state is corrupt or from an unsupported schema."""


def _number(value, name):
    try:
        value = float(value)
    except (TypeError, ValueError):
        raise StateError("%s must be a number" % name)
    if not math.isfinite(value):
        raise StateError("%s must be finite" % name)
    return value


def _position(value, name):
    if not isinstance(value, (list, tuple)) or len(value) < 3:
        raise StateError("%s must contain XYZ" % name)
    return [_number(value[index], "%s[%d]" % (name, index)) for index in range(3)]


def atomic_write_json(path, payload):
    """Replace a JSON file atomically so power loss cannot leave half a file."""
    parent = os.path.dirname(path)
    if parent and not os.path.isdir(parent):
        os.makedirs(parent, exist_ok=True)
    temporary = path + ".tmp"
    with open(temporary, "w") as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


class StateStore:
    SCHEMA_VERSION = 2

    def __init__(self, path, version):
        self.path = os.path.expanduser(path)
        self.version = version

    def empty(self, reference_tool=0):
        return {
            "schema_version": self.SCHEMA_VERSION,
            "tool_vision_version": self.version,
            "reference_tool": int(reference_tool),
            "stations": {},
            "vision": {},
        }

    def load(self, reference_tool=0):
        if not self.path or not os.path.isfile(self.path):
            return self.empty(reference_tool)
        try:
            with open(self.path, "r") as handle:
                payload = json.load(handle)
        except (OSError, ValueError) as exc:
            raise StateError("cannot read learned state: %s" % exc)
        return self.validate(payload)

    def save(self, payload):
        clean = self.validate(payload)
        clean["tool_vision_version"] = self.version
        clean["updated"] = time.time()
        atomic_write_json(self.path, clean)
        return clean

    def validate(self, payload):
        if not isinstance(payload, dict):
            raise StateError("learned state must be an object")
        if int(payload.get("schema_version", -1)) != self.SCHEMA_VERSION:
            raise StateError("unsupported learned-state schema")
        try:
            reference_tool = int(payload.get("reference_tool", 0))
        except (TypeError, ValueError):
            raise StateError("reference_tool must be an integer")
        if reference_tool < 0:
            raise StateError("reference_tool must not be negative")
        stations = payload.get("stations", {})
        vision = payload.get("vision", {})
        if not isinstance(stations, dict) or not isinstance(vision, dict):
            raise StateError("stations and vision must be objects")

        clean_stations = {}
        camera = stations.get("camera")
        if camera is not None:
            if not isinstance(camera, dict):
                raise StateError("camera station must be an object")
            clean_stations["camera"] = dict(camera)
            clean_stations["camera"]["position"] = _position(
                camera.get("position"), "camera.position"
            )
            clean_stations["camera"]["safe_z"] = _number(
                camera.get("safe_z"), "camera.safe_z"
            )

        switch = stations.get("switch")
        if switch is not None:
            if not isinstance(switch, dict):
                raise StateError("switch station must be an object")
            clean_stations["switch"] = dict(switch)
            clean_stations["switch"]["position"] = _position(
                switch.get("position"), "switch.position"
            )
            clean_stations["switch"]["safe_z"] = _number(
                switch.get("safe_z"), "switch.safe_z"
            )
            clean_stations["switch"]["trigger_z"] = _number(
                switch.get("trigger_z"), "switch.trigger_z"
            )

        clean = dict(payload)
        clean.update(
            {
                "schema_version": self.SCHEMA_VERSION,
                "reference_tool": reference_tool,
                "stations": clean_stations,
                "vision": dict(vision),
            }
        )
        return clean
