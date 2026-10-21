"""Repeatable two-project offline sender/receipt/restart demonstration."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from drive_change_detector import DriveChangeDetector, FixtureProvider
from project_folder_config import FakeDriveProvider
from project_registry import ProjectRegistry
from mock_apo import SimulatedApo

KEY_A = b"offline-demo-project-a-secret-key"
KEY_B = b"offline-demo-project-b-secret-key"
WORKER = '''
import json, os, socket, sys
from arm_notification import NotificationSender
allowed = {"127.0.0.1", "::1", "localhost"}
original = socket.create_connection
def guarded(address, *args, **kwargs):
    if address[0] not in allowed:
        raise OSError("offline demo blocked non-loopback network access")
    return original(address, *args, **kwargs)
socket.create_connection = guarded
keys = {"test:project-a": bytes.fromhex(os.environ["ARM_DEMO_KEY_A"]),
        "test:project-b": bytes.fromhex(os.environ["ARM_DEMO_KEY_B"])}
sender = NotificationSender(sys.argv[1], sys.argv[2], sys.argv[3],
    secret_resolver=lambda ref: keys.get(ref), clock=lambda: float(os.environ["ARM_DEMO_NOW"]))
print(json.dumps(sender.dispatch(), sort_keys=True))
'''


def _registry_fixture():
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


def _provider_fixture(changed):
    folders = {}
    for suffix in ("a", "b"):
        for kind in ("prompts", "reports"):
            folder_id = f"{kind}-{suffix}"
            file_id = f"file-{kind}-{suffix}"
            changed_item = changed and ((suffix == "a" and kind == "prompts")
                                       or (suffix == "b" and kind == "reports"))
            folders[folder_id] = {"complete": True, "items": [{
                "id": file_id, "name": f"fixture-{file_id}.txt", "mimeType": "text/plain",
                "parents": [folder_id], "trashed": False, "version": "2" if changed_item else "1",
                "md5Checksum": "b" * 32 if changed_item else "a" * 32,
                "webViewLink": f"https://drive.google.com/file/d/{file_id}/view",
            }]}
    return {"folders": folders, "creationEvidence": [], "fail": False}


def main():
    with tempfile.TemporaryDirectory(prefix="arm-m04-demo-") as raw_temp:
        root = Path(raw_temp)
        with ExitStack() as stack:
            apo_a = stack.enter_context(SimulatedApo("project-a", KEY_A, root / "apo-a-receipts.json"))
            apo_b = stack.enter_context(SimulatedApo("project-b", KEY_B, root / "apo-b-receipts.json"))
            registry_path = root / "projects.json"
            detector_path = root / "m03-detector.json"
            ledger_path = root / "notification-ledger.json"
            registry = ProjectRegistry(registry_path)
            provider = FakeDriveProvider(_registry_fixture())
            for suffix, receiver in (("a", apo_a), ("b", apo_b)):
                registry.configure_folder_project(
                    project_id=f"project-{suffix}", display_name=f"Project {suffix.upper()}",
                    root_url=f"https://drive.google.com/drive/folders/root-{suffix}",
                    prompts_id=f"prompts-{suffix}", reports_id=f"reports-{suffix}",
                    endpoint=receiver.url, provider=provider,
                    repository=f"owner/project-{suffix}", secret_ref=f"test:project-{suffix}", enabled=True)
            detector = DriveChangeDetector(registry_path, detector_path)
            detector.scan(FixtureProvider(_provider_fixture(False)))
            created = detector.scan(FixtureProvider(_provider_fixture(True)))["newEvents"]
            assert len(created) == 2
            event_by_project = {event["projectId"]: event for event in created}
            assert event_by_project["project-a"]["eventType"] == "PROMPT_CHANGED"
            assert event_by_project["project-b"]["eventType"] == "REPORT_CHANGED"

            # APO B durably accepts the report event, then drops the response.
            apo_b.drop_after_accept = 1
            now = 1_800_000_000.0

            def invoke():
                env = os.environ.copy()
                env.update({"ARM_DEMO_KEY_A": KEY_A.hex(), "ARM_DEMO_KEY_B": KEY_B.hex(),
                            "ARM_DEMO_NOW": str(now)})
                result = subprocess.run([sys.executable, "-c", WORKER, str(registry_path),
                    str(detector_path), str(ledger_path)], cwd=REPO_ROOT,
                    env=env, capture_output=True, text=True, timeout=15)
                if result.returncode != 0:
                    raise RuntimeError("offline sender child failed: " + result.stderr[-1000:])
                return json.loads(result.stdout)

            first = invoke()
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            event_b_id = event_by_project["project-b"]["eventId"]
            pending_id = next(event_id for event_id, item in ledger["entries"].items()
                              if item["status"] == "PENDING")
            assert pending_id == event_b_id
            assert apo_b.processed_count == 1
            print(json.dumps({"step": "first_invocation", "result": first,
                              "projectAEventId": event_by_project["project-a"]["eventId"],
                              "projectBEventId": event_b_id, "projectBPendingAfterAmbiguousTimeout": pending_id,
                              "receiverBProcessedUnique": apo_b.processed_count}, sort_keys=True))

            now += 2
            second = invoke()  # new Python process reloads the durable ledger and retries same ID
            ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            assert ledger["entries"][event_b_id]["status"] == "ACKED"
            assert ledger["entries"][event_b_id]["attemptCount"] == 2
            assert ledger["entries"][event_b_id]["receipt"]["eventId"] == event_b_id
            assert apo_b.processed_count == 1
            print(json.dumps({"step": "fresh_process_retry", "result": second,
                              "retriedEventId": event_b_id, "sameIdentity": True,
                              "receiverBRequests": apo_b.request_count,
                              "receiverBProcessedUnique": apo_b.processed_count}, sort_keys=True))

            before = (apo_a.request_count, apo_b.request_count)
            duplicate = invoke()
            after = (apo_a.request_count, apo_b.request_count)
            assert before == after
            assert duplicate["deduplicated"] == 2
            assert duplicate["pending"] == 0 and duplicate["acked"] == 2
            print(json.dumps({"step": "duplicate_scan_restart", "result": duplicate,
                              "receiverRequestsUnchanged": before == after,
                              "finalStatus": {"pending": 0, "acked": 2, "total": 2},
                              "externalNetwork": "BLOCKED_BY_CHILD_GUARD",
                              "googleDriveOAuthRealApoCdb": "NONE"}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
