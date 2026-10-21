"""Run one bounded offline two-project foreground integration demonstration."""
from __future__ import annotations

import json
import ipaddress
import socket
import sys
import tempfile
from contextlib import ExitStack
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(Path(__file__).parent))

from arm_foreground import ForegroundMonitor
from drive_change_detector import _json_load
from project_folder_config import FakeDriveProvider
from project_registry import ProjectRegistry
from mock_apo import SimulatedApo
from test_arm_foreground import FakeClock, SequenceProvider, snapshots, folder_fixture, KEYS


def main():
    original_create_connection = socket.create_connection

    def loopback_only(address, *args, **kwargs):
        host = address[0]
        try:
            is_loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            is_loopback = host.lower() == "localhost"
        if not is_loopback:
            raise OSError("offline foreground demo blocked non-loopback network access")
        return original_create_connection(address, *args, **kwargs)

    socket.create_connection = loopback_only
    with tempfile.TemporaryDirectory(prefix="arm-m03r3-demo-") as raw_temp:
        root = Path(raw_temp)
        with ExitStack() as stack:
            apo_a = stack.enter_context(SimulatedApo("project-a", KEYS["test:project-a"], root / "apo-a.json"))
            apo_b = stack.enter_context(SimulatedApo("project-b", KEYS["test:project-b"], root / "apo-b.json"))
            registry_path = root / "projects.json"
            detector_path = root / "detector.json"
            ledger_path = root / "ledger.json"
            registry = ProjectRegistry(registry_path)
            fake_folders = FakeDriveProvider(folder_fixture())
            for suffix, receiver in (("a", apo_a), ("b", apo_b)):
                registry.configure_folder_project(project_id=f"project-{suffix}",
                    display_name=f"Project {suffix.upper()}",
                    root_url=f"https://drive.google.com/drive/folders/root-{suffix}",
                    prompts_id=f"prompts-{suffix}", reports_id=f"reports-{suffix}",
                    endpoint=receiver.url, provider=fake_folders,
                    repository=f"owner/project-{suffix}", secret_ref=f"test:project-{suffix}", enabled=True)

            sequence = [snapshots(), snapshots(arrivals=True, changed=True),
                        snapshots(arrivals=True, changed=True)]
            provider = SequenceProvider(sequence)
            clock = FakeClock()

            def sleep_and_advance(seconds):
                clock.advance(seconds)
                provider.index += 1

            apo_b.drop_after_accept = 1
            first_monitor = ForegroundMonitor(registry_path, detector_path, ledger_path,
                provider=provider, secret_resolver=KEYS.get, clock=clock,
                sleeper=sleep_and_advance, interval_seconds=10)
            first_run = first_monitor.run(max_cycles=3, emit=print)
            assert first_run["status"] == "COMPLETED"
            assert first_run["cycles"][0]["events"] == []
            assert first_run["cycles"][1]["events"][0]["changeKind"] == "CONTENT_UPDATED"
            arrivals = first_run["cycles"][2]["events"]
            assert len(arrivals) == 2
            assert {event["changeKind"] for event in arrivals} == {"ARRIVED"}
            assert {event["projectId"] for event in arrivals} == {"project-a", "project-b"}
            event_b = next(event for event in arrivals if event["projectId"] == "project-b")
            assert event_b["fileId"] == "moved-in-report-b"
            ledger = _json_load(ledger_path)
            assert ledger["entries"][event_b["eventId"]]["status"] == "PENDING"
            assert apo_b.processed_count == 1

            # Stop the first foreground process. A new instance reloads the same
            # detector and delivery files after enough time for bounded backoff.
            clock.advance(10)
            provider.index = 2
            restarted_monitor = ForegroundMonitor(registry_path, detector_path, ledger_path,
                provider=provider, secret_resolver=KEYS.get, clock=clock,
                sleeper=sleep_and_advance, interval_seconds=10)
            restart = restarted_monitor.run(max_cycles=1, start_cycle=4, emit=print)
            assert restart["cycles"][0]["events"] == []
            assert restart["cycles"][0]["delivery"]["ackedThisRun"] == 1
            ledger = _json_load(ledger_path)
            assert ledger["entries"][event_b["eventId"]]["status"] == "ACKED"
            assert ledger["entries"][event_b["eventId"]]["attemptCount"] == 2
            assert apo_b.processed_count == 1 and apo_b.request_count == 2

            # B's failed listing must not be treated as an empty folder. M03's
            # documented all-enabled-project transaction holds the whole scan;
            # the already-ACKed A work is deduplicated without another request.
            before_state = detector_path.read_bytes()
            before_requests = (apo_a.request_count, apo_b.request_count)
            provider.fail_folder = "reports-b"
            degraded = restarted_monitor.cycle(5)
            assert degraded["observation"] == "DEGRADED_ATOMIC_SCAN"
            assert degraded["events"] == []
            assert detector_path.read_bytes() == before_state
            assert (apo_a.request_count, apo_b.request_count) == before_requests
            final = restarted_monitor.sender.status()
            assert final["pending"] == 0 and final["acked"] == 3
            assert apo_a.processed_count == 2 and apo_b.processed_count == 1

            print(json.dumps({"demonstration": "PASS", "cycles": 5,
                "baselineEvents": 0,
                "contentUpdateEvent": first_run["cycles"][1]["events"][0]["eventId"],
                "arrivals": [{"projectId": event["projectId"], "eventId": event["eventId"],
                              "eventType": event["eventType"], "changeKind": event["changeKind"],
                              "fileId": event["fileId"]} for event in arrivals],
                "bRetryEventIdSame": True, "bReceiverUniqueProcessed": apo_b.processed_count,
                "deliveryCounts": {"pending": final["pending"], "acked": final["acked"]},
                "bIncompleteListing": "DEGRADED_ATOMIC_SCAN_STATE_UNCHANGED",
                "loopbackReceivers": 2, "externalNetworkGuard": "NON_LOOPBACK_BLOCKED",
                "googleDriveOAuth": "NONE"}, sort_keys=True))
    socket.create_connection = original_create_connection
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
