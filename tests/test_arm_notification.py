from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from drive_change_detector import DriveChangeDetector, FixtureProvider
from project_folder_config import FakeDriveProvider
from project_registry import ProjectRegistry, ProjectRegistryError
from arm_notification import NotificationError, NotificationSender
sys.path.insert(0, str(Path(__file__).parent))
from mock_apo import SimulatedApo


KEY_A = b"test-only-project-a-key-32-bytes"
KEY_B = b"test-only-project-b-key-32-bytes"


def _folder_fixture():
    items = []
    for suffix in ("a", "b"):
        root = f"root-{suffix}"
        items.extend([
            {"id": root, "name": f"Project {suffix.upper()}", "mimeType": "application/vnd.google-apps.folder",
             "trashed": False, "parents": []},
            {"id": f"prompts-{suffix}", "name": "Architect_Prompts", "mimeType": "application/vnd.google-apps.folder",
             "trashed": False, "parents": [root]},
            {"id": f"reports-{suffix}", "name": "Executor_Reports", "mimeType": "application/vnd.google-apps.folder",
             "trashed": False, "parents": [root]},
        ])
    return {"items": items, "fail": False}


def _change_fixture(changed=False):
    folders = {}
    for suffix in ("a", "b"):
        for kind in ("prompts", "reports"):
            folder_id = f"{kind}-{suffix}"
            file_id = f"file-{kind}-{suffix}"
            old = "a" * 32
            checksum = ("b" if changed and (suffix == "a" and kind == "prompts"
                                                or suffix == "b" and kind == "reports") else "a") * 32
            folders[folder_id] = {"complete": True, "items": [{
                "id": file_id, "name": f"fixture-{file_id}.txt", "mimeType": "text/plain",
                "parents": [folder_id], "trashed": False, "version": "2" if changed and checksum != old else "1",
                "md5Checksum": checksum,
                "webViewLink": f"https://drive.google.com/file/d/{file_id}/view",
            }]}
    return {"folders": folders, "creationEvidence": [], "fail": False}


class FakeClock:
    def __init__(self, value=1_800_000_000.0):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class NotificationFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.clock = FakeClock()
        self.a = SimulatedApo("project-a", KEY_A, self.root / "receiver-a.json")
        self.b = SimulatedApo("project-b", KEY_B, self.root / "receiver-b.json")
        self.registry_path = self.root / "projects.json"
        self.detector_path = self.root / "detector.json"
        self.ledger_path = self.root / "notification-ledger.json"
        self.registry = ProjectRegistry(self.registry_path)
        provider = FakeDriveProvider(_folder_fixture())
        for suffix, server in (("a", self.a), ("b", self.b)):
            self.registry.configure_folder_project(
                project_id=f"project-{suffix}", display_name=f"Project {suffix.upper()}",
                root_url=f"https://drive.google.com/drive/folders/root-{suffix}",
                prompts_id=f"prompts-{suffix}", reports_id=f"reports-{suffix}",
                endpoint=server.url, provider=provider, repository=f"owner/project-{suffix}",
                secret_ref=f"test:project-{suffix}", enabled=True)
        detector = DriveChangeDetector(self.registry_path, self.detector_path)
        detector.scan(FixtureProvider(_change_fixture(False)))
        result = detector.scan(FixtureProvider(_change_fixture(True)))
        self.assertEqual(len(result["newEvents"]), 2)
        self.events = {item["projectId"]: item for item in result["newEvents"]}
        self.keys = {"test:project-a": KEY_A, "test:project-b": KEY_B}

    def tearDown(self):
        self.a.close()
        self.b.close()
        self.temp.cleanup()

    def sender(self, **kwargs):
        return NotificationSender(self.registry_path, self.detector_path, self.ledger_path,
                                  secret_resolver=lambda ref: self.keys.get(ref), clock=self.clock,
                                  **kwargs)

    def event_receiver(self, event_id):
        event = next(item for item in self.events.values() if item["eventId"] == event_id)
        return self.a if event["projectId"] == "project-a" else self.b


class NotificationDeliveryTests(NotificationFixture):
    def test_two_projects_receive_only_their_event_types_and_matching_ack(self):
        result = self.sender().dispatch()
        self.assertEqual(result["ackedThisRun"], 2)
        self.assertEqual(result["pending"], 0)
        self.assertEqual(self.a.processed_count, 1)
        self.assertEqual(self.b.processed_count, 1)
        self.assertEqual(self.a.receipts["receipts"][self.events["project-a"]["eventId"]]["eventType"], "PROMPT_CHANGED")
        self.assertEqual(self.b.receipts["receipts"][self.events["project-b"]["eventId"]]["eventType"], "REPORT_CHANGED")
        ledger = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        for event in self.events.values():
            receipt = ledger["entries"][event["eventId"]]["receipt"]
            self.assertEqual(receipt["projectId"], event["projectId"])
            self.assertEqual(receipt["eventId"], event["eventId"])

    def test_duplicate_dispatch_and_fresh_restart_remain_deduplicated(self):
        first = self.sender().dispatch()
        request_counts = (self.a.request_count, self.b.request_count)
        fresh = self.sender().dispatch()
        self.assertEqual(first["ackedThisRun"], 2)
        self.assertEqual(fresh["ackedThisRun"], 0)
        self.assertEqual(fresh["deduplicated"], 2)
        self.assertEqual((self.a.request_count, self.b.request_count), request_counts)
        self.assertEqual(self.sender().status(), {"result": "VALID", "pending": 0, "acked": 2,
                                                   "queued": 2, "total": 2})

    def test_timeout_after_accept_retries_same_event_after_restart_once(self):
        event = self.events["project-b"]
        self.b.drop_after_accept = 1
        first = self.sender().dispatch()
        self.assertEqual(first["pending"], 1)
        entry = json.loads(self.ledger_path.read_text(encoding="utf-8"))["entries"][event["eventId"]]
        self.assertEqual(entry["status"], "PENDING")
        self.assertEqual(entry["attemptCount"], 1)
        self.assertEqual(self.b.processed_count, 1)
        self.clock.advance(2)
        second = self.sender().dispatch()
        entry = json.loads(self.ledger_path.read_text(encoding="utf-8"))["entries"][event["eventId"]]
        self.assertEqual(entry["status"], "ACKED")
        self.assertEqual(entry["attemptCount"], 2)
        self.assertEqual(entry["receipt"]["eventId"], event["eventId"])
        self.assertEqual(second["acked"], 2)
        self.assertEqual(self.b.request_count, 2)
        self.assertEqual(self.b.processed_count, 1)

    def test_retry_is_deferred_and_exponential_with_a_hard_cap(self):
        event_id = sorted(item["eventId"] for item in self.events.values())[0]
        receiver = self.event_receiver(event_id)
        receiver.mode = "server_error"
        self.sender(retry_base_seconds=3, retry_max_seconds=5).dispatch(limit=1)
        entry = json.loads(self.ledger_path.read_text(encoding="utf-8"))["entries"][event_id]
        self.assertEqual(entry["nextAttemptAt"], self.clock.value + 3)
        before = receiver.request_count
        deferred = self.sender(retry_base_seconds=3, retry_max_seconds=5).dispatch(limit=1)
        self.assertEqual(receiver.request_count, before)
        self.assertEqual(deferred["deferred"], 1)
        self.clock.advance(3)
        receiver.mode = "server_error"
        self.sender(retry_base_seconds=3, retry_max_seconds=5).dispatch(limit=1)
        entry = json.loads(self.ledger_path.read_text(encoding="utf-8"))["entries"][event_id]
        self.assertEqual(entry["nextAttemptAt"], self.clock.value + 5)

    def test_wrong_or_missing_ack_and_receiver_errors_remain_pending(self):
        modes = ("wrong_event", "wrong_project", "missing_ack", "wrong_signature", "server_error", "redirect")
        for index, mode in enumerate(modes):
            if index:
                self.tearDown()
                self.setUp()
            with self.subTest(mode=mode):
                event_id = sorted(item["eventId"] for item in self.events.values())[0]
                receiver = self.event_receiver(event_id)
                receiver.mode = mode
                sender = self.sender()
                sender.dispatch(limit=1)
                entry = json.loads(self.ledger_path.read_text(encoding="utf-8"))["entries"].get(event_id)
                self.assertIsNotNone(entry)
                self.assertEqual(entry["status"], "PENDING")
                self.assertIsNone(entry["receipt"])
                self.clock.advance(600)
                receiver.mode = "normal"
                sender.dispatch(limit=1)
                self.assertEqual(json.loads(self.ledger_path.read_text(encoding="utf-8"))["entries"][event_id]["status"], "ACKED")

    def test_unauthorized_receiver_and_wrong_key_remain_pending(self):
        event_id = sorted(item["eventId"] for item in self.events.values())[0]
        receiver = self.event_receiver(event_id)
        receiver.mode = "unauthorized"
        self.sender().dispatch(limit=1)
        entry = json.loads(self.ledger_path.read_text(encoding="utf-8"))["entries"][event_id]
        self.assertEqual(entry["status"], "PENDING")
        self.clock.advance(600)
        project = next(item for item in self.events.values() if item["eventId"] == event_id)["projectId"]
        ref = "test:" + project
        self.keys[ref] = b"incorrect-test-key-material-32-bytes"
        self.sender().dispatch(limit=1)
        self.assertEqual(json.loads(self.ledger_path.read_text(encoding="utf-8"))["entries"][event_id]["status"], "PENDING")

    def test_disabled_project_is_not_queued_or_delivered(self):
        document = self.registry.load()
        document["folderProjects"][0]["enabled"] = False
        self.registry._write_document(document)
        result = self.sender().dispatch()
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["queued"], 1)
        self.assertEqual(result["pending"], 0)
        self.assertEqual(self.a.processed_count, 0)
        self.assertEqual(self.b.processed_count, 1)

    def test_project_destination_mismatch_fails_closed_without_delivery(self):
        # First persist pending work with an unavailable endpoint by keeping a future retry deadline.
        event_id = sorted(item["eventId"] for item in self.events.values())[0]
        receiver = self.event_receiver(event_id)
        receiver.mode = "server_error"
        self.sender().dispatch(limit=1)
        before = (self.a.request_count, self.b.request_count)
        ledger = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        ledger["entries"][event_id]["destination"] = "http://127.0.0.1:9/notify"
        self.ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
        with self.assertRaises(NotificationError):
            self.sender().dispatch()
        self.assertEqual((self.a.request_count, self.b.request_count), before)

    def test_changed_configured_destination_fails_closed_and_keeps_pending(self):
        event_id = sorted(item["eventId"] for item in self.events.values())[0]
        self.event_receiver(event_id).mode = "server_error"
        self.sender().dispatch(limit=1)
        before = (self.a.request_count, self.b.request_count)
        document = self.registry.load()
        project_id = next(item for item in self.events.values() if item["eventId"] == event_id)["projectId"]
        project = next(p for p in document["folderProjects"] if p["projectId"] == project_id)
        project["orchestratorEndpoint"] = "http://127.0.0.1:9/notify"
        self.registry._write_document(document)
        with self.assertRaises(NotificationError):
            self.sender().dispatch()
        entry = json.loads(self.ledger_path.read_text(encoding="utf-8"))["entries"][event_id]
        self.assertEqual(entry["status"], "PENDING")
        self.assertEqual((self.a.request_count, self.b.request_count), before)

    def test_invalid_source_or_corrupt_ledger_fails_closed_before_delivery(self):
        source = json.loads(self.detector_path.read_text(encoding="utf-8"))
        source["events"][0]["projectId"] = "other-project"
        self.detector_path.write_text(json.dumps(source), encoding="utf-8")
        with self.assertRaises(NotificationError):
            self.sender().dispatch()
        self.assertEqual(self.a.request_count + self.b.request_count, 0)
        self.detector_path.write_text("{}", encoding="utf-8")
        self.ledger_path.write_text("{broken", encoding="utf-8")
        with self.assertRaises(NotificationError):
            self.sender().dispatch()
        self.assertEqual(self.a.request_count + self.b.request_count, 0)

    def test_semantic_ledger_tampering_fails_closed(self):
        self.sender().dispatch(limit=1)
        ledger = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        event_id = next(iter(ledger["entries"]))
        ledger["entries"][event_id]["payload"]["projectId"] = "project-b" if ledger["entries"][event_id]["projectId"] == "project-a" else "project-a"
        self.ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
        before = (self.a.request_count, self.b.request_count)
        with self.assertRaises(NotificationError):
            self.sender().dispatch()
        self.assertEqual((self.a.request_count, self.b.request_count), before)

    def test_forged_acknowledged_ledger_entry_fails_closed(self):
        self.sender().dispatch(limit=1)
        ledger = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        event_id = next(iter(ledger["entries"]))
        entry = ledger["entries"][event_id]
        entry["status"] = "ACKED"
        entry["receipt"] = {"projectId": entry["projectId"], "eventId": event_id,
                             "destination": entry["destination"], "receivedAt": "2026-10-21T00:00:00Z",
                             "signature": "0" * 64}
        entry["nextAttemptAt"] = None
        self.ledger_path.write_text(json.dumps(ledger), encoding="utf-8")
        before = (self.a.request_count, self.b.request_count)
        with self.assertRaises(NotificationError):
            self.sender().dispatch()
        self.assertEqual((self.a.request_count, self.b.request_count), before)

    def test_initial_atomic_ledger_failure_causes_zero_delivery(self):
        def fail_writer(_path, _data):
            raise OSError("synthetic disk full")
        with self.assertRaises(NotificationError):
            self.sender(writer=fail_writer).dispatch()
        self.assertFalse(self.ledger_path.exists())
        self.assertEqual(self.a.request_count + self.b.request_count, 0)
        # M03 remains the durable source, so a later healthy invocation can enqueue it.
        self.assertEqual(self.sender().dispatch()["acked"], 2)

    def test_ack_write_failure_keeps_durable_pending_and_retry_dedupes_receiver(self):
        event_id = sorted(item["eventId"] for item in self.events.values())[0]
        receiver = self.event_receiver(event_id)
        calls = {"count": 0}
        def fail_after_attempt(path, data):
            calls["count"] += 1
            if calls["count"] == 3:
                raise OSError("synthetic failure persisting ACK")
            from arm_notification import _atomic_write
            _atomic_write(path, data)
        # Writes: new intent, attempt record, ACK record (which fails).
        with self.assertRaises(NotificationError):
            self.sender(writer=fail_after_attempt).dispatch(limit=1)
        entry = json.loads(self.ledger_path.read_text(encoding="utf-8"))["entries"][event_id]
        self.assertEqual(entry["status"], "PENDING")
        self.assertEqual(receiver.processed_count, 1)
        self.clock.advance(10)
        self.sender().dispatch(limit=1)
        self.assertEqual(json.loads(self.ledger_path.read_text(encoding="utf-8"))["entries"][event_id]["status"], "ACKED")
        self.assertEqual(receiver.processed_count, 1)

    def test_payload_and_logs_exclude_content_secrets_and_local_paths(self):
        result = self.sender().dispatch()
        self.assertEqual(result["ackedThisRun"], 2)
        for event in self.events.values():
            receiver = self.a if event["projectId"] == "project-a" else self.b
            receipt = receiver.receipts["receipts"][event["eventId"]]
            self.assertNotIn("body", receipt)
            self.assertNotIn("content", receipt)
            self.assertNotIn("token", receipt)
        raw = self.ledger_path.read_text(encoding="utf-8")
        self.assertNotIn(KEY_A.decode(), raw)
        self.assertNotIn(KEY_B.decode(), raw)
        self.assertNotIn(str(self.root), raw)
        self.assertNotIn("artifact body", raw)

    def test_state_path_aliases_are_rejected(self):
        with self.assertRaises(NotificationError):
            NotificationSender(self.registry_path, self.detector_path, self.detector_path,
                               secret_resolver=lambda ref: self.keys.get(ref), clock=self.clock)


if __name__ == "__main__":
    unittest.main()
