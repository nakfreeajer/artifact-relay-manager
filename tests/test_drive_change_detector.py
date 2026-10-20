import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from drive_change_detector import (DetectionError, DriveChangeDetector, FixtureProvider,
                                   _validate_state)
from project_folder_config import FakeDriveProvider
from project_registry import ProjectRegistry


def metadata(file_id, folder_id, version="1", checksum=None, name="input.bin", parent=None):
    item = {"id": file_id, "name": name, "mimeType": "application/octet-stream",
            "parents": [folder_id if parent is None else parent], "trashed": False,
            "version": version, "md5Checksum": checksum,
            "webViewLink": f"https://drive.google.com/file/d/{file_id}/view"}
    return item


def registry_document(root, projects=("project-a", "project-b")):
    path = Path(root) / "registry.json"
    registry = ProjectRegistry(path)
    all_items = []
    configs = []
    for project in projects:
        suffix = project[-1]
        root_id, prompts, reports = f"root-{suffix}", f"prompts-{suffix}", f"reports-{suffix}"
        all_items.extend([
            {"id": root_id, "name": project, "mimeType": "application/vnd.google-apps.folder", "parents": [], "trashed": False, "projectId": project},
            {"id": prompts, "name": "Architect_Prompts", "mimeType": "application/vnd.google-apps.folder", "parents": [root_id], "trashed": False},
            {"id": reports, "name": "Executor_Reports", "mimeType": "application/vnd.google-apps.folder", "parents": [root_id], "trashed": False},
        ])
        configs.append((project, root_id))
    provider = FakeDriveProvider({"items": all_items})
    for project, root_id in configs:
        registry.configure_folder_project(project_id=project, display_name=project,
            root_url=f"https://drive.google.com/drive/folders/{root_id}", prompts_id=None,
            reports_id=None, endpoint="https://apo.example/notify", provider=provider,
            repository=f"owner/{project}", enabled=False)
    return path


def snapshot(items_by_folder, creations=(), *, fail=False, incomplete=()):
    folders = {}
    for folder_id in ("prompts-a", "reports-a", "prompts-b", "reports-b"):
        folders[folder_id] = {"complete": folder_id not in incomplete, "items": items_by_folder.get(folder_id, [])}
    evidence = [{"projectId": p, "folderId": f, "fileId": i, "kind": "CREATED_IN_FOLDER"}
                for p, f, i in creations]
    return FixtureProvider({"folders": folders, "creationEvidence": evidence, "fail": fail})


class DriveChangeDetectorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.registry = registry_document(self.root)
        self.state = self.root / "detector-state.json"
        self.detector = DriveChangeDetector(self.registry, self.state)

    def tearDown(self):
        self.temp.cleanup()

    def base(self):
        return {"prompts-a": [metadata("old-a", "prompts-a", checksum="a" * 32)],
                "reports-a": [metadata("old-report-a", "reports-a", checksum="b" * 32)],
                "prompts-b": [metadata("old-b", "prompts-b", checksum="c" * 32)],
                "reports-b": [metadata("old-report-b", "reports-b", checksum="d" * 32)]}

    def test_baseline_create_content_edit_and_duplicate_are_bounded_and_isolated(self):
        baseline = self.base()
        self.assertEqual(self.detector.scan(snapshot(baseline))["newEvents"], [])
        changed = self.base()
        changed["prompts-a"].append(metadata("new-a", "prompts-a", version="2", checksum="e" * 32))
        changed["reports-b"].append(metadata("new-b", "reports-b", version="2", checksum="f" * 32))
        changed["prompts-a"][0] = metadata("old-a", "prompts-a", version="2", checksum="1" * 32)
        result = self.detector.scan(snapshot(changed, [("project-a", "prompts-a", "new-a"),
                                                       ("project-b", "reports-b", "new-b")]))
        self.assertEqual([(e["projectId"], e["eventType"], e["changeKind"]) for e in result["newEvents"]],
                         [("project-a", "PROMPT_CHANGED", "CONTENT_UPDATED"),
                          ("project-a", "PROMPT_CHANGED", "CREATED"),
                          ("project-b", "REPORT_CHANGED", "CREATED")])
        self.assertEqual(len({e["eventId"] for e in result["newEvents"]}), 3)
        self.assertFalse(any("body" in "".join(e.keys()).lower() for e in result["newEvents"]))
        repeated = self.detector.scan(snapshot(changed, [("project-a", "prompts-a", "new-a"),
                                                         ("project-b", "reports-b", "new-b")]))
        self.assertEqual(repeated["newEvents"], [])
        self.assertEqual(repeated["totalEvents"], 3)

    def test_metadata_rename_version_change_and_move_delete_nested_do_not_emit(self):
        base = self.base()
        self.detector.scan(snapshot(base))
        renamed = self.base()
        renamed["prompts-a"][0] = metadata("old-a", "prompts-a", version="9", checksum="a" * 32, name="renamed.bin")
        self.assertEqual(self.detector.scan(snapshot(renamed))["newEvents"], [])
        moved = self.base()
        moved["prompts-a"] = []
        # A recursive fixture item is deliberately absent from direct-child listing.
        moved["reports-b"] = []
        self.assertEqual(self.detector.scan(snapshot(moved))["newEvents"], [])
        back = self.base()
        back["prompts-a"].append(metadata("moved-in", "prompts-a", checksum="9" * 32))
        result = self.detector.scan(snapshot(back))
        self.assertEqual(result["newEvents"], [])
        self.assertGreater(result["ambiguousCount"], 0)

    def test_native_or_missing_checksum_and_unproven_new_child_are_ambiguous(self):
        initial = self.base()
        native = metadata("native", "prompts-a", checksum="a" * 32)
        native["mimeType"] = "application/vnd.google-apps.document"
        initial["prompts-a"] = [native]
        self.detector.scan(snapshot(initial))
        updated = self.base()
        native_update = metadata("native", "prompts-a", version="2", checksum="b" * 32)
        native_update["mimeType"] = "application/vnd.google-apps.document"
        updated["prompts-a"] = [native_update]
        updated["reports-a"].append(metadata("new-unproven", "reports-a"))
        result = self.detector.scan(snapshot(updated))
        self.assertEqual(result["newEvents"], [])
        self.assertGreaterEqual(result["ambiguousCount"], 2)
        repeated = self.detector.scan(snapshot(updated))
        self.assertEqual(repeated["newEvents"], [])
        self.assertEqual(repeated["ambiguousCount"], result["ambiguousCount"])

    def test_provider_failure_and_incomplete_listing_leave_state_unchanged(self):
        with self.assertRaises(DetectionError):
            self.detector.scan(snapshot(self.base(), fail=True))
        with self.assertRaises(DetectionError):
            self.detector.scan(snapshot(self.base(), incomplete=("prompts-a",)))
        self.assertFalse(self.state.exists())

    def test_corrupt_state_fails_closed_and_persisted_identity_mismatch_fails(self):
        self.state.write_text("{bad", encoding="utf-8")
        with self.assertRaises(DetectionError):
            self.detector.scan(snapshot(self.base()))
        self.state.unlink()
        self.detector.scan(snapshot(self.base()))
        state = json.loads(self.state.read_text(encoding="utf-8"))
        state["folders"][next(iter(state["folders"]))]["projectId"] = "other-project"
        self.state.write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaises(DetectionError):
            self.detector.scan(snapshot(self.base()))

    def test_state_cannot_alias_project_registry(self):
        with self.assertRaises(DetectionError):
            DriveChangeDetector(self.registry, self.registry)

    def test_failed_state_write_keeps_previous_state_and_no_events_escape(self):
        self.detector.scan(snapshot(self.base()))
        before = self.state.read_bytes()
        changed = self.base()
        changed["prompts-a"].append(metadata("new", "prompts-a", version="2", checksum="e" * 32))
        failing = DriveChangeDetector(self.registry, self.state, writer=lambda _p, _b: (_ for _ in ()).throw(OSError("partial")))
        with self.assertRaises(DetectionError):
            failing.scan(snapshot(changed, [("project-a", "prompts-a", "new")]))
        self.assertEqual(self.state.read_bytes(), before)
        self.assertEqual(self.detector.scan(snapshot(changed, [("project-a", "prompts-a", "new")]))["newEvents"][0]["fileId"], "new")

    def test_atomic_replace_failure_keeps_previous_state_after_temp_write(self):
        self.detector.scan(snapshot(self.base()))
        before = self.state.read_bytes()
        changed = self.base()
        changed["prompts-a"].append(metadata("new", "prompts-a", version="2", checksum="e" * 32))
        with patch("drive_change_detector.os.replace", side_effect=OSError("replace denied")):
            with self.assertRaises(DetectionError):
                self.detector.scan(snapshot(changed, [("project-a", "prompts-a", "new")]))
        self.assertEqual(self.state.read_bytes(), before)
        self.assertEqual(list(self.root.glob(".*detector-state.json.*")), [])

    def test_restart_reloads_same_identity_without_reemitting(self):
        baseline = self.base()
        self.detector.scan(snapshot(baseline))
        changed = self.base()
        changed["prompts-a"].append(metadata("created", "prompts-a", version="2", checksum="e" * 32))
        created = self.detector.scan(snapshot(changed, [("project-a", "prompts-a", "created")]))["newEvents"][0]
        fresh = DriveChangeDetector(self.registry, self.state)
        retry = fresh.scan(snapshot(changed, [("project-a", "prompts-a", "created")]))
        self.assertEqual(retry["newEvents"], [])
        state = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(state["events"][0]["eventId"], created["eventId"])

    def test_network_is_not_used_by_fixture_scan(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("network prohibited")):
            self.assertEqual(self.detector.scan(snapshot(self.base()))["newEvents"], [])

    def test_event_id_and_state_shape_fail_closed(self):
        self.detector.scan(self._provider_with_event())
        state = json.loads(self.state.read_text(encoding="utf-8"))
        state["events"][0]["eventId"] = "m03-" + "0" * 64
        self.state.write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaises(DetectionError):
            self.detector.scan(snapshot(self.base()))
        state["events"][0]["eventId"] = next(iter(state["eventIdentities"]))
        state["events"][0]["eventType"] = "UNAUTHORIZED_EVENT"
        self.state.write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaises(DetectionError):
            self.detector.scan(snapshot(self.base()))

    def _provider_with_event(self):
        base = self.base()
        self.detector.scan(snapshot(base))
        base["prompts-a"].append(metadata("event", "prompts-a", version="2", checksum="e" * 32))
        return snapshot(base, [("project-a", "prompts-a", "event")])


if __name__ == "__main__":
    unittest.main()
