import json
import tempfile
import unittest
from pathlib import Path

from klippy.extras.tool_vision_state import StateError, StateStore, atomic_write_json


class StateStoreTests(unittest.TestCase):
    def test_missing_file_returns_clean_schema_two_state(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(str(Path(directory) / "state.json"), "3.0.0")
            state = store.load(reference_tool=2)
            self.assertEqual(state["schema_version"], 2)
            self.assertEqual(state["reference_tool"], 2)

    def test_taught_stations_survive_atomic_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            store = StateStore(str(path), "3.0.0")
            state = store.empty()
            state["stations"] = {
                "camera": {"position": [100, 50, 8], "safe_z": 15},
                "switch": {
                    "position": [70, 10, 9],
                    "safe_z": 15,
                    "trigger_z": 7.25,
                },
            }
            state["vision"] = {"profile": {"schema_version": 1}}
            store.save(state)
            loaded = store.load()
            self.assertEqual(loaded["stations"]["switch"]["trigger_z"], 7.25)
            self.assertEqual(loaded["stations"]["camera"]["position"], [100.0, 50.0, 8.0])
            self.assertFalse(Path(str(path) + ".tmp").exists())

    def test_old_schema_is_not_silently_misread(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            path.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
            with self.assertRaises(StateError):
                StateStore(str(path), "3.0.0").load()

    def test_nonfinite_position_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            store = StateStore(str(Path(directory) / "state.json"), "3.0.0")
            state = store.empty()
            state["stations"]["camera"] = {
                "position": [0, float("nan"), 2],
                "safe_z": 5,
            }
            with self.assertRaises(StateError):
                store.save(state)

    def test_result_writer_replaces_existing_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "result.json"
            atomic_write_json(str(path), {"value": 1})
            atomic_write_json(str(path), {"value": 2})
            self.assertEqual(json.loads(path.read_text())["value"], 2)


if __name__ == "__main__":
    unittest.main()
