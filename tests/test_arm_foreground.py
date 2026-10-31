from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from arm_foreground import ForegroundMonitor
from drive_auth import DriveAuthError
from drive_change_detector import FixtureProvider
from project_folder_config import FakeDriveProvider
from project_registry import ProjectRegistry, ProjectRegistryError
from tests.mock_apo import SimulatedApo


KEYS = {"test:project-a": b"offline-project-a-key-32-bytes!!",
        "test:project-b": b"offline-project-b-key-32-bytes!!"}
MODIFIED = "2026-10-21T00:00:00Z"


def folder_fixture():
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


def snapshots(*, arrivals=False, changed=False, extra_prompts=0):
    folders = {}
    for suffix in ("a", "b"):
        for kind in ("prompts", "reports"):
            folder_id = f"{kind}-{suffix}"
            file_id = f"existing-{kind}-{suffix}"
            checksum = "b" * 32 if changed and suffix == "a" and kind == "prompts" else "a" * 32
            version = "2" if checksum == "b" * 32 else "1"
            items = [{"id": file_id, "name": file_id + ".txt", "mimeType": "text/plain",
                "parents": [folder_id], "trashed": False, "version": version, "size": "20",
                "modifiedTime": MODIFIED, "md5Checksum": checksum,
                "webViewLink": f"https://drive.google.com/file/d/{file_id}/view"}]
            if arrivals and suffix == "a" and kind == "prompts":
                new_id = "new-prompt-a"
            elif arrivals and suffix == "b" and kind == "reports":
                new_id = "moved-in-report-b"
            else:
                new_id = None
            if new_id:
                items.append({"id": new_id, "name": new_id + ".txt", "mimeType": "text/plain",
                    "parents": [folder_id], "trashed": False, "version": "3", "size": "24",
                    "modifiedTime": "2026-10-21T00:00:05Z", "md5Checksum": "c" * 32,
                    "webViewLink": f"https://drive.google.com/file/d/{new_id}/view"})
                if suffix == "a" and kind == "prompts":
                    for index in range(extra_prompts):
                        extra_id = f"extra-prompt-a-{index}"
                        items.append({"id": extra_id, "name": extra_id + ".txt", "mimeType": "text/plain",
                            "parents": [folder_id], "trashed": False, "version": "1", "size": "24",
                            "modifiedTime": "2026-10-21T00:00:05Z", "md5Checksum": "d" * 32,
                            "webViewLink": f"https://drive.google.com/file/d/{extra_id}/view"})
            folders[folder_id] = {"complete": True, "items": items}
    return {"folders": folders, "fail": False}


class SequenceProvider:
    def __init__(self, sequence):
        self.sequence = sequence
        self.index = 0
        self.calls = []
        self.fail_folder = None

    def list_folder(self, folder_id):
        self.calls.append((self.index, folder_id))
        if folder_id == self.fail_folder:
            raise ValueError("synthetic incomplete provider listing")
        return FixtureProvider(self.sequence[self.index]).list_folder(folder_id)


class FakeClock:
    def __init__(self, value=1_800_000_000.0):
        self.value = value

    def __call__(self):
        return self.value

    def advance(self, seconds):
        self.value += seconds


class ForegroundMonitorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.clock = FakeClock()
        self.apo_a = SimulatedApo("project-a", KEYS["test:project-a"], self.root / "apo-a.json")
        self.apo_b = SimulatedApo("project-b", KEYS["test:project-b"], self.root / "apo-b.json")
        self.registry_path = self.root / "projects.json"
        self.detector_path = self.root / "detector.json"
        self.ledger_path = self.root / "ledger.json"
        self.registry = ProjectRegistry(self.registry_path)
        provider = FakeDriveProvider(folder_fixture())
        for suffix, apo in (("a", self.apo_a), ("b", self.apo_b)):
            self.registry.configure_folder_project(project_id=f"project-{suffix}",
                display_name=f"Project {suffix.upper()}",
                root_url=f"https://drive.google.com/drive/folders/root-{suffix}",
                prompts_id=f"prompts-{suffix}", reports_id=f"reports-{suffix}",
                endpoint=apo.url, provider=provider, repository=f"owner/project-{suffix}",
                secret_ref=f"test:project-{suffix}", enabled=True)

    def tearDown(self):
        self.apo_a.close()
        self.apo_b.close()
        self.temp.cleanup()

    def monitor(self, provider, *, sleeper=lambda _seconds: None, interval=10, max_backoff=300):
        return ForegroundMonitor(self.registry_path, self.detector_path, self.ledger_path,
            provider=provider, secret_resolver=KEYS.get, clock=self.clock, sleeper=sleeper,
            interval_seconds=interval, max_backoff_seconds=max_backoff)

    def test_two_project_loop_arrival_content_ack_timeout_restart_and_dedupe(self):
        provider = SequenceProvider([snapshots(), snapshots(arrivals=True, changed=True),
                                     snapshots(arrivals=True, changed=True)])

        def sleep_and_next(_seconds):
            if provider.index == 0:
                self.assertEqual((self.apo_a.request_count, self.apo_b.request_count), (0, 0))
            provider.index += 1
            self.clock.advance(10)

        self.apo_b.drop_after_accept = 1
        first = self.monitor(provider, sleeper=sleep_and_next).run(max_cycles=3, emit=None)
        self.assertEqual(first["status"], "COMPLETED")
        self.assertEqual(first["cycles"][0]["events"], [])
        self.assertEqual(first["cycles"][1]["events"][0]["changeKind"], "CONTENT_UPDATED")
        arrivals = first["cycles"][2]["events"]
        self.assertEqual({event["changeKind"] for event in arrivals}, {"ARRIVED"})
        self.assertEqual({event["projectId"] for event in arrivals}, {"project-a", "project-b"})
        event_b = next(event for event in arrivals if event["projectId"] == "project-b")
        self.assertEqual(event_b["fileId"], "moved-in-report-b")
        self.assertEqual(first["cycles"][2]["delivery"]["pendingThisRun"], 1)

        ledger_before_restart = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        self.assertEqual(ledger_before_restart["entries"][event_b["eventId"]]["status"], "PENDING")
        self.assertEqual(self.apo_b.processed_count, 1)
        self.clock.advance(10)  # stop interval plus persisted retry backoff
        provider.index = 2
        restarted = self.monitor(provider).run(max_cycles=1, start_cycle=4, emit=None)
        self.assertEqual(restarted["cycles"][0]["delivery"]["ackedThisRun"], 1)
        self.assertEqual(restarted["cycles"][0]["events"], [])
        ledger_after_restart = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        self.assertEqual(ledger_after_restart["entries"][event_b["eventId"]]["status"], "ACKED")
        self.assertEqual(ledger_after_restart["entries"][event_b["eventId"]]["attemptCount"], 2)
        self.assertEqual(self.apo_b.processed_count, 1)
        self.assertEqual(self.apo_b.request_count, 2)
        self.assertEqual(self.apo_a.processed_count, 2)  # update and arrival
        final = self.monitor(provider).cycle(5)
        self.assertEqual(final["delivery"]["pending"], 0)
        self.assertEqual(final["delivery"]["acked"], 3)
        self.assertEqual(final["delivery"]["deduplicated"], 3)
        self.assertEqual(self.apo_a.request_count, 2)
        self.assertEqual(self.apo_b.request_count, 2)

    def test_incomplete_b_scan_is_atomic_and_existing_a_pending_event_still_retries(self):
        provider = SequenceProvider([snapshots(), snapshots(arrivals=True), snapshots(arrivals=True),
                                     snapshots(arrivals=True)])
        monitor = self.monitor(provider)
        monitor.cycle(1)
        provider.index = 1
        monitor.cycle(2)
        self.apo_a.drop_after_accept = 1
        provider.index = 2
        cycle = monitor.cycle(3)
        a_arrival = next(event for event in cycle["events"] if event["projectId"] == "project-a")
        state_before = self.detector_path.read_bytes()
        self.assertEqual(json.loads(self.ledger_path.read_text(encoding="utf-8"))["entries"][a_arrival["eventId"]]["status"], "PENDING")

        self.clock.advance(10)
        provider.index = 3
        provider.fail_folder = "reports-b"
        degraded = monitor.cycle(4)
        self.assertEqual(degraded["status"], "DEGRADED")
        self.assertEqual(degraded["observation"], "DEGRADED_ATOMIC_SCAN")
        self.assertTrue(all(item["status"] == "DEGRADED_ATOMIC_SCAN" for item in degraded["projects"]))
        self.assertEqual(degraded["events"], [])
        self.assertEqual(self.detector_path.read_bytes(), state_before)
        self.assertEqual(self.apo_a.processed_count, 1)
        self.assertEqual(self.apo_a.request_count, 2)

    def test_per_project_dispatch_cap_keeps_b_progressing_behind_multiple_a_events(self):
        base = snapshots()
        arrivals = snapshots(arrivals=True, extra_prompts=1)
        provider = SequenceProvider([base, arrivals, arrivals, arrivals])
        monitor = self.monitor(provider)
        monitor.cycle(1)
        provider.index = 1
        monitor.cycle(2)
        provider.index = 2
        third = monitor.cycle(3)
        self.assertEqual(len(third["events"]), 3)
        self.assertEqual(self.apo_a.processed_count, 1)
        self.assertEqual(self.apo_b.processed_count, 1)
        self.assertEqual(self.apo_b.request_count, 1)

        a_entries = [entry for entry in json.loads(self.ledger_path.read_text(encoding="utf-8"))["entries"].values()
                     if entry["projectId"] == "project-a"]
        self.assertEqual(sum(entry["status"] == "ACKED" for entry in a_entries), 1)
        self.assertEqual(sum(entry["status"] == "PENDING" for entry in a_entries), 1)
        provider.index = 3
        self.clock.advance(10)
        fourth = monitor.cycle(4)
        self.assertEqual(fourth["delivery"]["ackedThisRun"], 1)
        self.assertEqual(self.apo_a.processed_count, 2)
        self.assertEqual(self.apo_b.processed_count, 1)

    def test_disabled_project_is_neither_polled_nor_dispatched(self):
        document = json.loads(self.registry_path.read_text(encoding="utf-8"))
        document["folderProjects"] = [dict(item, enabled=(item["projectId"] == "project-a"))
                                      for item in document["folderProjects"]]
        self.registry_path.write_text(json.dumps(document), encoding="utf-8")
        provider = SequenceProvider([snapshots()])
        result = self.monitor(provider).cycle(1)
        self.assertEqual({folder for _cycle, folder in provider.calls}, {"prompts-a", "reports-a"})
        self.assertIn({"projectId": "project-b", "status": "DISABLED_NOT_POLLED"}, result["projects"])
        state = json.loads(self.detector_path.read_text(encoding="utf-8"))
        self.assertEqual({record["projectId"] for record in state["folders"].values()}, {"project-a"})
        self.assertEqual(self.apo_a.request_count + self.apo_b.request_count, 0)

    def test_fatal_provider_authentication_failure_stops_before_pending_dispatch(self):
        class ExpiredSessionProvider:
            fatal_error_types = (DriveAuthError,)
            def list_folder(self, _folder_id):
                raise DriveAuthError("sanitized token refresh failure")

        with self.assertRaises(DriveAuthError):
            self.monitor(ExpiredSessionProvider()).cycle(1)
        self.assertEqual(self.apo_a.request_count + self.apo_b.request_count, 0)
        self.assertFalse(self.detector_path.exists())
        self.assertFalse(self.ledger_path.exists())

    def test_per_project_pause_suppresses_scan_and_dispatch_while_peer_progresses(self):
        provider = SequenceProvider([snapshots(), snapshots(arrivals=True, changed=True),
                                     snapshots(arrivals=True, changed=True), snapshots(arrivals=True, changed=True)])
        monitor = self.monitor(provider)
        monitor.cycle(1)
        self.apo_b.drop_after_accept = 1
        provider.index = 1
        monitor.cycle(2)
        provider.index = 2
        event_cycle = monitor.cycle(3)
        event_b = next(event for event in event_cycle["events"] if event["projectId"] == "project-b")
        self.assertEqual(event_cycle["delivery"]["pendingThisRun"], 1)
        before_ledger = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        before_b = before_ledger["entries"][event_b["eventId"]]
        self.assertEqual(before_b["status"], "PENDING")
        self.clock.advance(10)

        state_before = json.loads(self.detector_path.read_text(encoding="utf-8"))
        b_folders_before = {key: value for key, value in state_before["folders"].items()
                            if value["projectId"] == "project-b"}
        calls_before = len(provider.calls)
        b_requests_before = self.apo_b.request_count
        updated = snapshots(arrivals=True, changed=True)
        a_file = updated["folders"]["prompts-a"]["items"][0]
        a_file.update({"md5Checksum": "d" * 32, "version": "4"})
        provider.sequence.append(updated)
        provider.index = 3
        paused = monitor.cycle(4, paused_project_ids=["project-b"])
        self.assertEqual(next(item["status"] for item in paused["projects"]
                              if item["projectId"] == "project-b"), "PAUSED_NOT_POLLED")
        new_calls = [folder for _index, folder in provider.calls[calls_before:]]
        self.assertEqual(new_calls, ["prompts-a", "reports-a"])
        after_state = json.loads(self.detector_path.read_text(encoding="utf-8"))
        b_folders_after = {key: value for key, value in after_state["folders"].items()
                           if value["projectId"] == "project-b"}
        self.assertEqual(b_folders_after, b_folders_before)
        after_b = json.loads(self.ledger_path.read_text(encoding="utf-8"))["entries"][event_b["eventId"]]
        self.assertEqual(after_b["status"], "PENDING")
        self.assertEqual(after_b["attemptCount"], before_b["attemptCount"])
        self.assertEqual(self.apo_b.request_count, b_requests_before)
        self.assertGreaterEqual(self.apo_a.processed_count, 2)

        all_state_before = self.detector_path.read_bytes()
        all_ledger_before = self.ledger_path.read_bytes()
        calls_before = len(provider.calls)
        requests_before = (self.apo_a.request_count, self.apo_b.request_count)
        all_paused = monitor.cycle(5, paused_project_ids=["project-a", "project-b"])
        self.assertTrue(all(item["status"] == "PAUSED_NOT_POLLED" for item in all_paused["projects"]))
        self.assertEqual(all_paused["delivery"], None)
        self.assertEqual(len(provider.calls), calls_before)
        self.assertEqual(self.detector_path.read_bytes(), all_state_before)
        self.assertEqual(self.ledger_path.read_bytes(), all_ledger_before)
        self.assertEqual((self.apo_a.request_count, self.apo_b.request_count), requests_before)
        with self.assertRaises(ProjectRegistryError):
            monitor.cycle(6, paused_project_ids=["missing-project"])

    def test_provider_errors_use_bounded_exponential_sleep_without_busy_loop(self):
        provider = SequenceProvider([snapshots()] * 4)
        provider.fail_folder = "reports-b"
        sleeps = []
        monitor = self.monitor(provider, sleeper=lambda seconds: (sleeps.append(seconds), self.clock.advance(seconds)),
                               interval=10, max_backoff=25)
        result = monitor.run(max_cycles=4, emit=None)
        self.assertEqual(result["status"], "COMPLETED")
        self.assertEqual(sleeps, [10, 20, 25])
        self.assertEqual([cycle["nextDelaySeconds"] for cycle in result["cycles"]], [10, 20, 25, 25])
        self.assertEqual(self.apo_a.request_count + self.apo_b.request_count, 0)

    def test_ctrl_c_stops_at_cycle_boundary_and_persisted_state_restarts(self):
        provider = SequenceProvider([snapshots(), snapshots(arrivals=True)])

        def interrupt(_seconds):
            raise KeyboardInterrupt

        stopped = self.monitor(provider, sleeper=interrupt).run(max_cycles=3, emit=None)
        self.assertEqual(stopped["status"], "STOPPED")
        self.assertTrue(self.detector_path.exists())
        provider.index = 1
        resumed = self.monitor(provider).cycle(1)
        self.assertEqual(resumed["events"], [])
        self.assertGreaterEqual(json.loads(self.detector_path.read_text(encoding="utf-8"))["folders"].__len__(), 4)

    def test_malformed_shared_registry_fails_before_provider_or_delivery(self):
        self.registry_path.write_text("{broken", encoding="utf-8")
        provider = SequenceProvider([snapshots()])
        with self.assertRaises(ProjectRegistryError):
            self.monitor(provider).cycle(1)
        self.assertEqual(provider.calls, [])
        self.assertEqual(self.apo_a.request_count + self.apo_b.request_count, 0)


if __name__ == "__main__":
    unittest.main()
