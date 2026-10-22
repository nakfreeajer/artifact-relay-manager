from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from arm_pause_state import PauseStateError, PauseStateStore


class PauseStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.store = PauseStateStore(self.root, "a" * 64, "b" * 64)
        self.projects = ["project-a", "project-b"]
        self.worker_id = "c" * 32

    def tearDown(self):
        self.temp.cleanup()

    def test_global_and_project_requests_apply_atomically_and_reload(self):
        state = self.store.initialize(self.projects)
        self.assertFalse(state["globalPaused"])
        request_id, state = self.store.request("PAUSE_PROJECT", "project-b", self.projects, self.worker_id)
        self.assertEqual(state["pendingRequest"]["requestId"], request_id)
        self.assertFalse(state["pausedProjectIds"])
        state, changed = self.store.apply_pending(self.projects, "d" * 32)
        self.assertTrue(changed)
        self.assertEqual(state["pausedProjectIds"], ["project-b"])
        self.assertEqual(state["lastAppliedRequest"]["requestId"], request_id)
        self.assertEqual(self.store.load(self.projects), state)

        global_id, _ = self.store.request("PAUSE_GLOBAL", None, self.projects, self.worker_id)
        state, changed = self.store.apply_pending(self.projects, "d" * 32)
        self.assertTrue(changed)
        self.assertTrue(state["globalPaused"])
        self.assertEqual(state["lastAppliedRequest"]["requestId"], global_id)

        resume_id, _ = self.store.request("RESUME_GLOBAL", None, self.projects, self.worker_id)
        state, _ = self.store.apply_pending(self.projects, "d" * 32)
        self.assertFalse(state["globalPaused"])
        self.assertEqual(state["pausedProjectIds"], ["project-b"])
        self.assertEqual(state["lastAppliedRequest"]["requestId"], resume_id)

    def test_invalid_project_and_overlapping_pending_control_do_not_mutate(self):
        self.store.initialize(self.projects)
        before = self.store.path.read_bytes()
        with self.assertRaises(PauseStateError):
            self.store.request("PAUSE_PROJECT", "missing", self.projects, self.worker_id)
        self.assertEqual(self.store.path.read_bytes(), before)
        self.store.request("PAUSE_PROJECT", "project-b", self.projects, self.worker_id)
        pending = self.store.path.read_bytes()
        with self.assertRaises(PauseStateError):
            self.store.request("RESUME_GLOBAL", None, self.projects, self.worker_id)
        self.assertEqual(self.store.path.read_bytes(), pending)

    def test_corrupt_cross_config_and_removed_project_states_fail_closed(self):
        self.store.initialize(self.projects)
        self.store.path.write_text("{broken", encoding="utf-8")
        with self.assertRaises(PauseStateError):
            self.store.load(self.projects)

        self.store.path.write_text(json.dumps({"schemaVersion": 1, "stateIdentity": "x" * 64,
            "configDigest": "b" * 64, "globalPaused": False, "pausedProjectIds": [],
            "pendingRequest": None, "lastAppliedRequest": None}), encoding="utf-8")
        with self.assertRaises(PauseStateError):
            self.store.load(self.projects)

        state = {"schemaVersion": 1, "stateIdentity": "a" * 64, "configDigest": "b" * 64,
                 "globalPaused": False, "pausedProjectIds": ["project-b"],
                 "pendingRequest": None, "lastAppliedRequest": None}
        self.store.path.write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaises(PauseStateError):
            self.store.load(["project-a"])


if __name__ == "__main__":
    unittest.main()
