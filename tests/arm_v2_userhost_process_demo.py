"""Real Windows process-boundary M05 demo; all provider/receiver data is synthetic."""
from __future__ import annotations

import base64
import ctypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from arm_v2_userhost import _process_creation_time, _process_is_alive, _read_json, _sid_for_process, load_config, status
from project_folder_config import FakeDriveProvider
from project_registry import ProjectRegistry
from tests.mock_apo import SimulatedApo
from tests.test_arm_foreground import KEYS, folder_fixture, snapshots
from relay_userhost import SingleInstanceLock


CLI_TRACE_PATH = os.environ.get("ARM_M05_TEST_TRACE_PATH")
CLI_TRACE = []
CLI_TRACE_LOCK = threading.Lock()


def _diagnostic_text(value: str | bytes, config: Path) -> str:
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="replace")
    for private in (str(config.parent), str(config),
                    str(config.parent / "not-a-real-oauth-client.json"),
                    "M05_TEST_SENTINEL_NOT_A_CREDENTIAL"):
        value = value.replace(private, "<LOCAL_TEST_VALUE>")
    for secret in KEYS.values():
        value = value.replace(base64.b64encode(secret).decode("ascii"), "<TEST_KEY>")
        try:
            value = value.replace(secret.decode("utf-8"), "<TEST_KEY>")
        except UnicodeDecodeError:
            pass
    return value


def _record_cli(config: Path, command: str, started: str, *, exit_code: int | None,
                stdout: str | bytes, stderr: str | bytes, payload: dict | None,
                timed_out: bool = False) -> None:
    item = {
        "command": command,
        "configIdentity": _config_identity(config),
        "startedAt": started,
        "finishedAt": datetime.now(timezone.utc).isoformat(),
        "exitCode": exit_code,
        "timedOut": timed_out,
        "json": payload,
        "stdout": _diagnostic_text(stdout, config),
        "stderr": _diagnostic_text(stderr, config),
    }
    pid = payload.get("pid") if isinstance(payload, dict) else None
    if isinstance(pid, int) and pid > 0:
        observation = {"pid": pid, "alive": _process_is_alive(pid)}
        if observation["alive"]:
            observation["processCreationTime"] = _process_creation_time(pid)
            observation["userIdentity"] = _sid_for_process(pid)
        item["process"] = observation
    with CLI_TRACE_LOCK:
        item["index"] = len(CLI_TRACE) + 1
        CLI_TRACE.append(item)
        if CLI_TRACE_PATH:
            trace_path = Path(CLI_TRACE_PATH)
            trace_path.parent.mkdir(parents=True, exist_ok=True)
            temporary = trace_path.with_name(trace_path.name + ".tmp")
            temporary.write_text(json.dumps({"invocations": CLI_TRACE}, sort_keys=True, indent=2) + "\n",
                                 encoding="utf-8")
            temporary.replace(trace_path)


def _config_identity(config: Path) -> str:
    try:
        return load_config(config).state_identity
    except Exception:
        return "UNAVAILABLE"


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")


def cli(config: Path, command: str, *, timeout: float = 20.0) -> dict:
    env = dict(os.environ)
    # Deliberate sentinels prove the worker child does not inherit OAuth inputs.
    env["RELAY_GDRIVE_ACCESS_TOKEN"] = "M05_TEST_SENTINEL_NOT_A_CREDENTIAL"
    env["RELAY_GDRIVE_OAUTH_CLIENT_FILE"] = str(config.parent / "not-a-real-oauth-client.json")
    started = datetime.now(timezone.utc).isoformat()
    try:
        result = subprocess.run([sys.executable, str(ROOT / "arm_v2_userhost.py"),
                                 "--config", str(config), command], cwd=ROOT,
                                capture_output=True, text=True, timeout=timeout, env=env)
    except subprocess.TimeoutExpired as exc:
        _record_cli(config, command, started, exit_code=None, stdout=exc.stdout or b"",
                    stderr=exc.stderr or b"", payload=None, timed_out=True)
        raise
    try:
        value = json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        _record_cli(config, command, started, exit_code=result.returncode,
                    stdout=result.stdout, stderr=result.stderr, payload=None)
        raise AssertionError(f"CLI {command} returned malformed output: {result.returncode}") from None
    _record_cli(config, command, started, exit_code=result.returncode,
                stdout=result.stdout, stderr=result.stderr, payload=value)
    if command in {"start", "status", "stop"} and result.returncode not in (0, 1, 2, 3):
        raise AssertionError(f"CLI {command} failed unexpectedly with exit {result.returncode}")
    return {**value, "_exit": result.returncode}


def wait_for(config: Path, predicate, timeout: float = 20.0) -> dict:
    deadline = time.monotonic() + timeout
    last = {}
    while time.monotonic() < deadline:
        last = status(config)
        if predicate(last):
            return last
        time.sleep(0.08)
    raise AssertionError(f"timed out waiting for worker state: {last}")


def abrupt_exit(config: Path, pid: int) -> None:
    cfg = load_config(config)
    heartbeat = _read_json(cfg.heartbeat_path, 32768)
    if heartbeat.get("pid") != pid or not _process_is_alive(pid):
        raise AssertionError("refusing abrupt-failure simulation without exact worker ownership")
    if (_sid_for_process(pid) != heartbeat.get("userIdentity")
            or _process_creation_time(pid) != heartbeat.get("processCreationTime")):
        raise AssertionError("worker process identity changed before abrupt-failure simulation")
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32)
    kernel32.OpenProcess.restype = ctypes.c_void_p
    kernel32.TerminateProcess.argtypes = (ctypes.c_void_p, ctypes.c_uint32)
    kernel32.TerminateProcess.restype = ctypes.c_int
    kernel32.CloseHandle.argtypes = (ctypes.c_void_p,)
    kernel32.CloseHandle.restype = ctypes.c_int
    handle = kernel32.OpenProcess(0x0001 | 0x1000, False, pid)  # TERMINATE | QUERY_LIMITED_INFORMATION
    if not handle:
        raise AssertionError("could not open verified test worker")
    try:
        if not kernel32.TerminateProcess(handle, 73):
            raise AssertionError("could not simulate abrupt exit of verified test worker")
    finally:
        kernel32.CloseHandle(handle)


def main() -> int:
    if os.name != "nt" or not os.environ.get("LOCALAPPDATA"):
        raise RuntimeError("M05 process-lifetime demo requires Windows and LOCALAPPDATA")
    appdata = Path(os.environ["LOCALAPPDATA"])
    if not appdata.is_dir():
        raise RuntimeError("LOCALAPPDATA is unavailable")
    root_context = tempfile.TemporaryDirectory(prefix="arm-m05-", dir=appdata)
    root = Path(root_context.name)
    try:
        apo_a = SimulatedApo("project-a", KEYS["test:project-a"], root / "apo-a.json")
        apo_b = SimulatedApo("project-b", KEYS["test:project-b"], root / "apo-b.json")
        try:
            registry_path = root / "projects.json"
            detector_path = root / "detector.json"
            ledger_path = root / "ledger.json"
            fixture_path = root / "provider.json"
            config_path = root / "host.json"
            registry = ProjectRegistry(registry_path)
            provider = FakeDriveProvider(folder_fixture())
            for suffix, receiver in (("a", apo_a), ("b", apo_b)):
                registry.configure_folder_project(
                    project_id=f"project-{suffix}", display_name=f"Project {suffix.upper()}",
                    root_url=f"https://drive.google.com/drive/folders/root-{suffix}",
                    prompts_id=f"prompts-{suffix}", reports_id=f"reports-{suffix}",
                    endpoint=receiver.url, provider=provider, repository=f"owner/project-{suffix}",
                    secret_ref=f"test:project-{suffix}", enabled=True)
            write_json(fixture_path, snapshots())
            config = {
                "schemaVersion": 1, "registryPath": str(registry_path),
                "detectorStatePath": str(detector_path), "notificationLedgerPath": str(ledger_path),
                "providerFixturePath": str(fixture_path),
                "testSecrets": {ref: base64.b64encode(key).decode("ascii") for ref, key in KEYS.items()},
                "intervalSeconds": 2, "stopTimeoutSeconds": 8,
            }
            write_json(config_path, config)

            stopped = cli(config_path, "status")
            assert stopped["status"] == "STOPPED" and stopped["_exit"] == 0, stopped
            start = cli(config_path, "start")
            assert start["result"] == "STARTED" and start["ready"] is True and start["_exit"] == 0
            worker_pid = start["pid"]
            assert not _process_is_alive(start["controllerPid"]), "start controller did not exit"
            first = wait_for(config_path, lambda s: s.get("status") in {"RUNNING", "DEGRADED"}
                             and s.get("cycle", 0) >= 1)
            assert first["pid"] == worker_pid and _process_is_alive(worker_pid)
            healthy_status = cli(config_path, "status")
            assert healthy_status["status"] == "RUNNING" and healthy_status["_exit"] == 0
            initial_receiver_counts = (apo_a.request_count, apo_b.request_count)

            # Two racing manual starts are rejected without starting a second scanner.
            concurrent = []
            barrier = threading.Barrier(3)

            def racing_start():
                barrier.wait()
                concurrent.append(cli(config_path, "start"))

            threads = [threading.Thread(target=racing_start) for _ in range(2)]
            for thread in threads:
                thread.start()
            barrier.wait()
            for thread in threads:
                thread.join(timeout=10)
            assert len(concurrent) == 2 and all(
                item["result"] == "ALREADY_RUNNING" and item["_exit"] == 3 for item in concurrent)
            assert status(config_path)["pid"] == worker_pid
            assert (apo_a.request_count, apo_b.request_count) == initial_receiver_counts

            # A checksum-proven content update, then stable prompt/report arrivals.
            write_json(fixture_path, snapshots(changed=True))
            content_cycle = wait_for(config_path, lambda s: any(
                e.get("changeKind") == "CONTENT_UPDATED" for e in (s.get("recentCycle") or {}).get("events", [])))
            write_json(fixture_path, snapshots(arrivals=True, changed=True))
            candidate_cycle = content_cycle["cycle"]
            wait_for(config_path, lambda s: s.get("cycle", 0) >= candidate_cycle + 1)
            apo_b.drop_after_accept = 1
            arrival_cycle = wait_for(config_path, lambda s: (s.get("recentCycle") or {}).get("delivery", {}).get("pending") == 1,
                                     timeout=20)
            b_event = next(event for event in arrival_cycle["recentCycle"]["events"]
                           if event["projectId"] == "project-b" and event["changeKind"] == "ARRIVED")
            event_id = b_event["eventId"]
            assert b_event["eventType"] == "REPORT_CHANGED" and b_event["fileId"] == "moved-in-report-b"
            assert apo_b.processed_count == 1

            detector_before_stop = detector_path.read_bytes()
            ledger_before_stop = ledger_path.read_bytes()
            stop = cli(config_path, "stop")
            assert stop["result"] == "STOPPED" and stop["_exit"] == 0 and not _process_is_alive(worker_pid)
            assert detector_path.read_bytes() == detector_before_stop
            pending_ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
            assert pending_ledger["entries"][event_id]["status"] == "PENDING"
            assert ledger_path.exists() and ledger_before_stop

            # New controller and worker load the same detector/ledger and retry the same ID.
            restart = cli(config_path, "start")
            assert restart["result"] == "STARTED" and restart["pid"] != worker_pid
            recovered = wait_for(config_path, lambda s: (
                (s.get("recentCycle") or {}).get("delivery", {}).get("pending") == 0
                and (s.get("recentCycle") or {}).get("delivery", {}).get("acked", 0) >= 3), timeout=15)
            ledger_after = json.loads(ledger_path.read_text(encoding="utf-8"))
            assert ledger_after["entries"][event_id]["status"] == "ACKED"
            assert ledger_after["entries"][event_id]["attemptCount"] == 2
            assert apo_b.processed_count == 1 and apo_b.request_count == 2
            b_requests = apo_b.request_count
            a_requests = apo_a.request_count
            wait_for(config_path, lambda s: s.get("cycle", 0) >= recovered["cycle"] + 1)
            assert apo_a.request_count == a_requests and apo_b.request_count == b_requests

            # Incomplete B listing degrades atomically, preserving the exact detector snapshot.
            detector_snapshot = detector_path.read_bytes()
            write_json(fixture_path, {"folders": {}, "fail": True})
            degraded = wait_for(config_path, lambda s: (s.get("recentCycle") or {}).get("observation") == "DEGRADED_ATOMIC_SCAN")
            assert degraded["status"] == "DEGRADED"
            assert detector_path.read_bytes() == detector_snapshot and apo_b.request_count == b_requests

            # Disable B and prove the cycle reports it unpolled.
            document = registry.load()
            project_b = next(item for item in document["folderProjects"] if item["projectId"] == "project-b")
            project_b["enabled"] = False
            registry._write_document(document)
            write_json(fixture_path, snapshots(arrivals=True, changed=True))
            disabled = wait_for(config_path, lambda s: any(
                item.get("projectId") == "project-b" and item.get("status") == "DISABLED_NOT_POLLED"
                for item in (s.get("recentCycle") or {}).get("projects", [])))
            assert disabled["status"] == "RUNNING" and apo_b.request_count == b_requests

            graceful = cli(config_path, "stop")
            assert graceful["result"] == "STOPPED"

            # A mismatched PID cannot be used as a stop authority.
            ownership_config_path = root / "ownership-host.json"
            ownership_config = dict(config)
            ownership_config["detectorStatePath"] = str(root / "ownership-detector.json")
            ownership_config["notificationLedgerPath"] = str(root / "ownership-ledger.json")
            write_json(ownership_config_path, ownership_config)
            ownership_start = cli(ownership_config_path, "start")
            assert ownership_start["result"] == "STARTED"
            ownership_host = load_config(ownership_config_path)
            genuine_heartbeat = _read_json(ownership_host.heartbeat_path, 32768)
            forged_heartbeat = dict(genuine_heartbeat)
            forged_heartbeat["pid"] = os.getpid()
            write_json(ownership_host.heartbeat_path, forged_heartbeat)
            refused_status = cli(ownership_config_path, "status")
            refused_stop = cli(ownership_config_path, "stop")
            assert refused_status["result"] == "DEGRADED" and refused_status["_exit"] == 2
            assert refused_stop["result"] == "DEGRADED" and refused_stop["_exit"] == 2
            assert not ownership_host.stop_path.exists(), "unverified PID received no stop request"
            write_json(ownership_host.heartbeat_path, genuine_heartbeat)
            owned_stop = cli(ownership_config_path, "stop")
            assert owned_stop["result"] == "STOPPED" and owned_stop["_exit"] == 0

            # A fresh but identity-valid stale heartbeat degrades without raising in status().
            stale_heartbeat = dict(genuine_heartbeat)
            stale_heartbeat["pid"] = os.getpid()
            stale_heartbeat["userIdentity"] = _sid_for_process(os.getpid())
            stale_heartbeat["processCreationTime"] = _process_creation_time(os.getpid())
            stale_heartbeat["heartbeatAt"] = "2000-01-01T00:00:00+00:00"
            write_json(ownership_host.heartbeat_path, stale_heartbeat)
            stale_lock = SingleInstanceLock(ownership_host.worker_lock_path)
            assert stale_lock.acquire()
            try:
                stale_status = cli(ownership_config_path, "status")
                assert stale_status["status"] == "DEGRADED"
                assert stale_status["heartbeatHealth"] == "STALE" and stale_status["_exit"] == 2
            finally:
                stale_lock.release()

            # Invalid offline key binding fails startup and releases the worker lock.
            failure_config_path = root / "failure-host.json"
            failure_config = dict(config)
            failure_config["detectorStatePath"] = str(root / "failure-detector.json")
            failure_config["notificationLedgerPath"] = str(root / "failure-ledger.json")
            failure_config["testSecrets"] = {"test:unrelated": base64.b64encode(b"unrelated-test-key-32-bytes!!").decode("ascii")}
            write_json(failure_config_path, failure_config)
            failed_start = cli(failure_config_path, "start")
            assert failed_start["result"] == "START_FAILED" and failed_start["_exit"] == 2
            assert status(failure_config_path)["status"] == "STOPPED"

            # Hold only the startup lock to produce a deterministic informative STARTING status.
            starting_config_path = root / "starting-host.json"
            starting_config = dict(config)
            starting_config["detectorStatePath"] = str(root / "starting-detector.json")
            starting_config["notificationLedgerPath"] = str(root / "starting-ledger.json")
            write_json(starting_config_path, starting_config)
            starting_host = load_config(starting_config_path)
            starting_host.control_dir.mkdir(parents=True, exist_ok=True)
            starting_lock = SingleInstanceLock(starting_host.start_lock_path)
            assert starting_lock.acquire()
            try:
                starting_status = cli(starting_config_path, "status")
                assert starting_status["status"] == "STARTING" and starting_status["_exit"] == 1
            finally:
                starting_lock.release()

            # Hold a known startup lock to force STOP_TIMEOUT without a timing race or worker.
            timeout_config_path = root / "timeout-host.json"
            timeout_config = dict(config)
            timeout_config["detectorStatePath"] = str(root / "timeout-detector.json")
            timeout_config["notificationLedgerPath"] = str(root / "timeout-ledger.json")
            timeout_config["stopTimeoutSeconds"] = 1
            write_json(timeout_config_path, timeout_config)
            timeout_host = load_config(timeout_config_path)
            timeout_host.control_dir.mkdir(parents=True, exist_ok=True)
            timeout_lock = SingleInstanceLock(timeout_host.start_lock_path)
            assert timeout_lock.acquire()
            try:
                timed_stop = cli(timeout_config_path, "stop", timeout=5)
                assert timed_stop["result"] == "STOP_TIMEOUT"
                assert timed_stop["phase"] == "STARTING" and timed_stop["_exit"] == 2
            finally:
                timeout_lock.release()

            malformed_config_path = root / "malformed-host.json"
            malformed_config_path.write_text("{", encoding="utf-8")
            malformed_status = cli(malformed_config_path, "status")
            assert malformed_status["result"] == "DEGRADED" and malformed_status["_exit"] == 2

            # Abruptly fail only an independently identity-verified worker; OS lock releases.
            crash_start = cli(config_path, "start")
            assert crash_start["result"] == "STARTED", crash_start
            crash_pid = crash_start["pid"]
            abrupt_exit(config_path, crash_pid)
            wait_for(config_path, lambda s: s["status"] == "STOPPED", timeout=5)
            stale_lock_file = load_config(config_path).worker_lock_path.exists()
            assert stale_lock_file, "expected the unlocked OS lock file to remain as stale metadata"
            recovered_start = cli(config_path, "start")
            assert recovered_start["result"] == "STARTED"
            final = cli(config_path, "stop")
            assert final["result"] == "STOPPED" and final["_exit"] == 0
            assert not _process_is_alive(recovered_start["pid"])
            safe_stopped = cli(config_path, "stop")
            assert safe_stopped["result"] == "STOPPED" and safe_stopped["_exit"] == 0
            control = load_config(config_path)
            log_bytes = control.log_path.read_bytes() if control.log_path.exists() else b""
            for secret in KEYS.values():
                assert base64.b64encode(secret) not in log_bytes and secret not in log_bytes
            assert b"https://" not in log_bytes and str(root).encode("utf-8") not in log_bytes
            assert b"M05_TEST_SENTINEL_NOT_A_CREDENTIAL" not in log_bytes

            print(json.dumps({
                "demonstration": "PASS", "platform": "windows",
                "controllerExitedWorkerRemainedAlive": True,
                "secondStartCommands": 2,
                "secondStartResult": "ALREADY_RUNNING", "stopResult": stop["result"],
                "contentUpdateEvent": next(e["eventId"] for e in content_cycle["recentCycle"]["events"]
                                            if e["changeKind"] == "CONTENT_UPDATED"),
                "arrivals": [{"projectId": e["projectId"], "eventType": e["eventType"],
                              "changeKind": e["changeKind"], "eventId": e["eventId"]}
                             for e in arrival_cycle["recentCycle"]["events"]],
                "pendingSameEventAfterStop": event_id,
                "restartRetrySameEventId": ledger_after["entries"][event_id]["eventId"],
                "retryAttempts": ledger_after["entries"][event_id]["attemptCount"],
                "receiverUniqueBEvents": apo_b.processed_count,
                "receiverBRequests": apo_b.request_count,
                "finalPending": recovered["recentCycle"]["delivery"].get("pending"),
                "finalAcked": recovered["recentCycle"]["delivery"].get("acked"),
                "incompleteBScan": "DEGRADED_ATOMIC_SCAN_STATE_UNCHANGED",
                "disabledB": "NOT_POLLED", "abruptExit": "VERIFIED_WORKER_ONLY_OS_LOCK_RELEASED",
                "wrongPidStop": "REFUSED_NO_STOP_REQUEST", "failedStartupCleanup": "PASS_NO_ORPHAN",
                "sanitizedLogScan": "PASS_NO_BODY_KEYS_URL_OR_PRIVATE_PATH",
                "staleLockFileRecovery": "PASS", "oauthOrDriveApi": "NONE",
                "externalNetwork": "BLOCKED_BY_WORKER_GUARD", "realApo": "NONE",
                "controllerCli": "start/status/stop", "cleanup": "PASS_NO_WORKER_REMAINS",
                "exitCodeProofs": {
                    "STARTED": start["_exit"], "RUNNING": healthy_status["_exit"],
                    "duplicateStart": concurrent[0]["_exit"], "START_FAILED": failed_start["_exit"],
                    "STARTING": starting_status["_exit"], "STOP_TIMEOUT": timed_stop["_exit"],
                    "invalidConfig": malformed_status["_exit"], "degradedStatus": refused_status["_exit"],
                    "staleStatus": stale_status["_exit"],
                    "successfulStop": final["_exit"], "alreadyStopped": safe_stopped["_exit"]
                }
            }, sort_keys=True))
        finally:
            # Do not leave a worker if an earlier assertion fails.
            try:
                if status(config_path).get("status") in {"RUNNING", "DEGRADED", "STARTING"}:
                    cli(config_path, "stop", timeout=12)
            except Exception:
                pass
            apo_a.close()
            apo_b.close()
    finally:
        root_context.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
