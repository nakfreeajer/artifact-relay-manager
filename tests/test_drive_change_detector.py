import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from drive_change_detector import (DetectionError, DriveChangeDetector, FixtureProvider,
                                   STATE_SCHEMA, _validate_state)
from project_folder_config import FakeDriveProvider
from project_registry import ProjectRegistry

MODIFIED = "2026-10-21T00:00:00Z"


def metadata(file_id, folder_id, version="1", checksum=None, name="input.bin", parent=None,
             size="128", modified=MODIFIED, mime_type="application/octet-stream"):
    return {"id": file_id, "name": name, "mimeType": mime_type,
            "parents": [folder_id if parent is None else parent], "trashed": False,
            "version": version, "md5Checksum": checksum, "size": size,
            "modifiedTime": modified,
            "webViewLink": f"https://drive.google.com/file/d/{file_id}/view"}


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


def snapshot(items_by_folder, *, fail=False, incomplete=()):
    folders = {}
    for folder_id in ("prompts-a", "reports-a", "prompts-b", "reports-b"):
        folders[folder_id] = {"complete": folder_id not in incomplete, "items": items_by_folder.get(folder_id, [])}
    return FixtureProvider({"folders": folders, "fail": fail})


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

    def test_two_project_arrivals_wait_for_stability_and_preserve_content_updates(self):
        baseline = self.base()
        first = self.detector.scan(snapshot(baseline))
        self.assertEqual(first["newEvents"], [])
        self.assertEqual(first["totalEvents"], 0)

        changed = self.base()
        changed["prompts-a"][0] = metadata("old-a", "prompts-a", version="2", checksum="1" * 32)
        changed["prompts-a"].append(metadata("new-prompt-a", "prompts-a", version="3", checksum="e" * 32))
        changed["reports-b"].append(metadata("moved-report-b", "reports-b", version="4", checksum="f" * 32))
        first_arrival_poll = self.detector.scan(snapshot(changed))
        self.assertEqual([(e["projectId"], e["changeKind"]) for e in first_arrival_poll["newEvents"]],
                         [("project-a", "CONTENT_UPDATED")])
        self.assertEqual(first_arrival_poll["candidateCount"], 2)

        stable = self.detector.scan(snapshot(changed))
        self.assertEqual([(e["projectId"], e["eventType"], e["changeKind"]) for e in stable["newEvents"]],
                         [("project-a", "PROMPT_CHANGED", "ARRIVED"),
                          ("project-b", "REPORT_CHANGED", "ARRIVED")])
        self.assertEqual(stable["candidateCount"], 0)
        self.assertEqual(len({e["eventId"] for e in stable["newEvents"]}), 2)
        self.assertFalse(any("body" in "".join(e.keys()).lower() for e in stable["newEvents"]))

        repeated = self.detector.scan(snapshot(changed))
        self.assertEqual(repeated["newEvents"], [])
        self.assertEqual(repeated["totalEvents"], 3)

    def test_moved_in_direct_child_qualifies_after_stable_observation(self):
        baseline = self.base()
        self.detector.scan(snapshot(baseline))
        arrived = self.base()
        # This ID was known to exist elsewhere; only its new direct-child membership is observed here.
        arrived["reports-b"].append(metadata("existing-elsewhere", "reports-b", version="8", checksum="8" * 32))
        candidate = self.detector.scan(snapshot(arrived))
        self.assertEqual(candidate["newEvents"], [])
        event = self.detector.scan(snapshot(arrived))["newEvents"][0]
        self.assertEqual((event["fileId"], event["projectId"], event["changeKind"]),
                         ("existing-elsewhere", "project-b", "ARRIVED"))

    def test_unstable_candidate_restarts_observation_window(self):
        baseline = self.base()
        self.detector.scan(snapshot(baseline))
        one = self.base()
        one["prompts-a"].append(metadata("unstable", "prompts-a", checksum="1" * 32, size="100"))
        self.assertEqual(self.detector.scan(snapshot(one))["newEvents"], [])
        changed = self.base()
        changed["prompts-a"].append(metadata("unstable", "prompts-a", version="2", checksum="2" * 32, size="101"))
        self.assertEqual(self.detector.scan(snapshot(changed))["newEvents"], [])
        self.assertEqual(self.detector.scan(snapshot(changed))["newEvents"][0]["changeKind"], "ARRIVED")

    def test_rename_metadata_version_change_delete_and_nested_exclusion(self):
        base = self.base()
        self.detector.scan(snapshot(base))
        renamed = self.base()
        renamed["prompts-a"][0] = metadata("old-a", "prompts-a", version="9", checksum="a" * 32, name="renamed.bin")
        self.assertEqual(self.detector.scan(snapshot(renamed))["newEvents"], [])
        removed = self.base()
        removed["prompts-a"] = []
        self.assertEqual(self.detector.scan(snapshot(removed))["newEvents"], [])
        reentered = self.base()
        reentered["prompts-a"][0] = metadata("old-a", "prompts-a", version="9", checksum="a" * 32, name="renamed.bin")
        self.assertEqual(self.detector.scan(snapshot(reentered))["newEvents"], [])
        self.assertEqual(self.detector.scan(snapshot(reentered))["newEvents"][0]["changeKind"], "ARRIVED")
        # Nested descendants are not present in any direct-child listing and cannot trigger.
        self.assertEqual(self.detector.scan(snapshot(self.base()))["newEvents"], [])

    def test_native_and_missing_checksum_items_can_arrive_from_stable_metadata(self):
        baseline = self.base()
        native = metadata("native-arrival", "prompts-a", version="2", checksum=None, size=None,
                          mime_type="application/vnd.google-apps.document")
        native_items = self.base()
        native_items["prompts-a"].append(native)
        self.detector.scan(snapshot(baseline))
        self.assertEqual(self.detector.scan(snapshot(native_items))["newEvents"], [])
        self.assertEqual(self.detector.scan(snapshot(native_items))["newEvents"][0]["fileId"], "native-arrival")

        self.detector = DriveChangeDetector(self.registry, self.root / "missing-checksum.json")
        binary_items = self.base()
        binary_items["reports-a"].append(metadata("no-checksum", "reports-a", checksum=None, size="256"))
        self.detector.scan(snapshot(self.base()))
        self.assertEqual(self.detector.scan(snapshot(binary_items))["newEvents"], [])
        event = self.detector.scan(snapshot(binary_items))["newEvents"][0]
        self.assertEqual((event["fileId"], event["changeKind"]), ("no-checksum", "ARRIVED"))

    def test_unusable_arrival_fingerprint_fails_closed_and_surfaces_ambiguity(self):
        self.detector.scan(snapshot(self.base()))
        items = self.base()
        items["prompts-a"].append(metadata("no-stability", "prompts-a", checksum=None, size=None))
        self.assertEqual(self.detector.scan(snapshot(items))["newEvents"], [])
        again = self.detector.scan(snapshot(items))
        self.assertEqual(again["newEvents"], [])
        state = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertIn("ARRIVAL_STABILITY_METADATA_UNAVAILABLE", [r["reason"] for r in state["ambiguous"]])

    def test_departure_and_reentry_create_new_stable_occurrence_identity_across_restart(self):
        self.detector.scan(snapshot(self.base()))
        present = self.base()
        present["reports-a"].append(metadata("cycles", "reports-a", checksum="9" * 32))
        self.assertEqual(self.detector.scan(snapshot(present))["newEvents"], [])
        first = self.detector.scan(snapshot(present))["newEvents"][0]
        absent = self.base()
        self.detector.scan(snapshot(absent))
        self.assertEqual(self.detector.scan(snapshot(present))["newEvents"], [])
        second = DriveChangeDetector(self.registry, self.state).scan(snapshot(present))["newEvents"][0]
        self.assertNotEqual(first["eventId"], second["eventId"])
        self.assertEqual(second["changeKind"], "ARRIVED")
        state = _validate_state(json.loads(self.state.read_text(encoding="utf-8")))
        item_state = next(folder["files"]["cycles"] for folder in state["folders"].values()
                          if folder["folderId"] == "reports-a")
        self.assertEqual(item_state["arrivalSerial"], 2)
        self.assertEqual(DriveChangeDetector(self.registry, self.state).scan(snapshot(present))["newEvents"], [])

    def test_v1_state_migration_preserves_legacy_event_ids_and_prior_ambiguity(self):
        baseline = self.base()
        folders = {}
        for folder_id, (project, event_type) in {
            "prompts-a": ("project-a", "PROMPT_CHANGED"), "reports-a": ("project-a", "REPORT_CHANGED"),
            "prompts-b": ("project-b", "PROMPT_CHANGED"), "reports-b": ("project-b", "REPORT_CHANGED")}.items():
            files = {item["id"]: {"checksum": item["md5Checksum"], "version": item["version"], "active": True}
                     for item in baseline[folder_id]}
            folders[hashlib.sha256((project + "\0" + folder_id).encode()).hexdigest()] = {
                "projectId": project, "folderId": folder_id, "eventType": event_type,
                "baselineComplete": True, "files": files}
        legacy_id = "legacy-created"
        old_identity = json.dumps(["project-a", "prompts-a", "PROMPT_CHANGED", legacy_id, "CREATED",
                                   "create:" + legacy_id], separators=(",", ":"))
        old_event_id = "m03-" + hashlib.sha256(old_identity.encode()).hexdigest()
        unproven = metadata("old-unproven", "prompts-a", checksum="8" * 32)
        folders[hashlib.sha256(b"project-a\0prompts-a").hexdigest()]["files"]["old-unproven"] = {
            "checksum": unproven["md5Checksum"], "version": unproven["version"], "active": True}
        self.state.write_text(json.dumps({"schemaVersion": 1, "folders": folders,
            "events": [{"projectId": "project-a", "eventId": old_event_id, "eventType": "PROMPT_CHANGED",
                "fileId": legacy_id, "folderId": "prompts-a", "providerVersion": "1",
                "driveUrl": f"https://drive.google.com/file/d/{legacy_id}/view", "detectedAt": "2026-01-01T00:00:00Z",
                "changeKind": "CREATED"}], "eventIdentities": {old_event_id: old_identity},
            "ambiguous": [{"projectId": "project-a", "folderId": "prompts-a", "fileId": "old-unproven",
                           "reason": "NEW_OR_MOVED_IN_UNPROVEN"}]}), encoding="utf-8")
        items = self.base()
        items["prompts-a"].append(unproven)
        first = self.detector.scan(snapshot(items))
        self.assertEqual(first["newEvents"], [])
        self.assertEqual(first["totalEvents"], 1)
        persisted = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(persisted["schemaVersion"], STATE_SCHEMA)
        self.assertEqual(persisted["events"][0]["eventId"], old_event_id)
        arrived = self.detector.scan(snapshot(items))["newEvents"][0]
        self.assertEqual((arrived["fileId"], arrived["changeKind"]), ("old-unproven", "ARRIVED"))

    def test_provider_failure_or_incomplete_listing_leaves_state_unchanged(self):
        with self.assertRaises(DetectionError):
            self.detector.scan(snapshot(self.base(), fail=True))
        with self.assertRaises(DetectionError):
            self.detector.scan(snapshot(self.base(), incomplete=("prompts-a",)))
        self.assertFalse(self.state.exists())
        self.detector.scan(snapshot(self.base()))
        before = self.state.read_bytes()
        with self.assertRaises(DetectionError):
            self.detector.scan(snapshot(self.base(), incomplete=("reports-b",)))
        self.assertEqual(self.state.read_bytes(), before)

    def test_same_file_identity_cannot_bind_to_multiple_projects_or_folders(self):
        items = self.base()
        items["reports-b"].append(metadata("old-a", "reports-b", checksum="e" * 32))
        with self.assertRaises(DetectionError):
            self.detector.scan(snapshot(items))
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

    def test_failed_state_write_keeps_candidate_and_no_events_escape(self):
        self.detector.scan(snapshot(self.base()))
        changed = self.base()
        changed["prompts-a"].append(metadata("new", "prompts-a", version="2", checksum="e" * 32))
        self.assertEqual(self.detector.scan(snapshot(changed))["newEvents"], [])
        before = self.state.read_bytes()
        failing = DriveChangeDetector(self.registry, self.state,
            writer=lambda _p, _b: (_ for _ in ()).throw(OSError("partial")))
        with self.assertRaises(DetectionError):
            failing.scan(snapshot(changed))
        self.assertEqual(self.state.read_bytes(), before)
        self.assertEqual(self.detector.scan(snapshot(changed))["newEvents"][0]["fileId"], "new")

    def test_atomic_replace_failure_keeps_previous_state_after_temp_write(self):
        self.detector.scan(snapshot(self.base()))
        changed = self.base()
        changed["prompts-a"].append(metadata("new", "prompts-a", version="2", checksum="e" * 32))
        self.detector.scan(snapshot(changed))
        before = self.state.read_bytes()
        with patch("drive_change_detector.os.replace", side_effect=OSError("replace denied")):
            with self.assertRaises(DetectionError):
                self.detector.scan(snapshot(changed))
        self.assertEqual(self.state.read_bytes(), before)
        self.assertEqual(list(self.root.glob(".*detector-state.json.*")), [])
        self.assertEqual(self.detector.scan(snapshot(changed))["newEvents"][0]["fileId"], "new")

    def test_restart_reloads_candidate_and_same_arrival_identity(self):
        self.detector.scan(snapshot(self.base()))
        items = self.base()
        items["prompts-a"].append(metadata("arriving", "prompts-a", checksum="e" * 32))
        self.assertEqual(self.detector.scan(snapshot(items))["newEvents"], [])
        first = DriveChangeDetector(self.registry, self.state).scan(snapshot(items))
        event = first["newEvents"][0]
        duplicate = DriveChangeDetector(self.registry, self.state).scan(snapshot(items))
        self.assertEqual(duplicate["newEvents"], [])
        persisted = json.loads(self.state.read_text(encoding="utf-8"))
        self.assertEqual(persisted["events"][0]["eventId"], event["eventId"])

    def test_network_is_not_used_by_fixture_scan(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("network prohibited")):
            self.assertEqual(self.detector.scan(snapshot(self.base()))["newEvents"], [])

    def test_arrival_event_id_and_state_shape_fail_closed(self):
        self.detector.scan(snapshot(self.base()))
        items = self.base()
        items["prompts-a"].append(metadata("event", "prompts-a", checksum="e" * 32))
        self.detector.scan(snapshot(items))
        self.detector.scan(snapshot(items))
        state = json.loads(self.state.read_text(encoding="utf-8"))
        state["events"][-1]["eventId"] = "m03-" + "0" * 64
        self.state.write_text(json.dumps(state), encoding="utf-8")
        with self.assertRaises(DetectionError):
            self.detector.scan(snapshot(items))


if __name__ == "__main__":
    unittest.main()
