"""Visible Windows qualification for durable ARM pause/resume controls."""
from __future__ import annotations

import base64
import json
import os
from contextlib import ExitStack
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import tkinter as tk

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from arm_notification import _read_ledger
from arm_pause_state import PauseStateStore
from arm_v2_dashboard import DashboardApp
from arm_v2_userhost import _probe_lock, load_config, status as host_status, stop as host_stop
from project_folder_config import FakeDriveProvider
from project_registry import ProjectRegistry
from tests.mock_apo import SimulatedApo
from tests.test_arm_foreground import KEYS, folder_fixture, snapshots


def _write(path: Path, value):
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")


def _wait(app, predicate, timeout=20):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.root.update()
        if predicate():
            return
        time.sleep(0.025)
    host = (app.latest or {}).get("host", {})
    recent = host.get("recentCycle") if isinstance(host.get("recentCycle"), dict) else {}
    raise AssertionError("pause/resume UI did not reach the expected acknowledged state: " + json.dumps({
        "hostStatus": host.get("status"), "cycle": host.get("cycle"),
        "observation": recent.get("observation"),
        "observationErrorClass": recent.get("observationErrorClass"),
        "deliveryErrorClass": recent.get("deliveryErrorClass"),
        "pausedProjectIds": host.get("pausedProjectIds"), "globalPaused": host.get("globalPaused"),
        "notice": app.notice_text.get(), "futurePending": app.future is not None,
        "futureDone": app.future.done() if app.future is not None else None,
        "pendingCommand": getattr(app, "_pending_command", None)}, sort_keys=True))


def _new_app(config, folders):
    root = tk.Tk()
    app = DashboardApp(root, config, folders)
    _wait(app, lambda: app.future is None)
    return app


def _invoke(app, button):
    _wait(app, lambda: app.future is None and str(button.cget("state")) == "normal", 8)
    button.invoke()
    if app.future is None:
        raise AssertionError("dashboard control did not queue a bounded host operation")


def _child_reattach(config_path, folder_fixture_path):
    code = r'''import json, sys, tkinter as tk
from arm_v2_dashboard import DashboardApp
root=tk.Tk(); app=DashboardApp(root, sys.argv[1], sys.argv[2])
def finish():
    if app.future is not None:
        root.after(50, finish); return
    before=app.latest["host"].get("pid")
    before_status=app.latest["host"].get("status")
    app.start_button.invoke()
    def finish_start():
        if app.future is not None:
            root.after(50, finish_start); return
        host=app.latest["host"] if app.latest else {}
        print(json.dumps({"beforeStatus":before_status,"status":host.get("status"),
                          "samePid":before==host.get("pid"),
                          "startMessage":app.notice_text.get()}),flush=True)
        app.close()
    root.after(50,finish_start)
root.after(50,finish); root.mainloop()
'''
    env = {key: value for key, value in os.environ.items()
           if key not in {"RELAY_GDRIVE_ACCESS_TOKEN", "RELAY_GDRIVE_OAUTH_CLIENT_FILE"}}
    result = subprocess.run([sys.executable, "-c", code, str(config_path), str(folder_fixture_path)],
                            cwd=ROOT, capture_output=True, text=True, timeout=25, env=env)
    if result.returncode != 0:
        raise AssertionError("fresh pause dashboard reattach process failed")
    return json.loads(result.stdout.strip().splitlines()[-1])


def _cli(config_path, command, *extra):
    env = {key: value for key, value in os.environ.items()
           if key not in {"RELAY_GDRIVE_ACCESS_TOKEN", "RELAY_GDRIVE_OAUTH_CLIENT_FILE"}}
    result = subprocess.run([sys.executable, str(ROOT / "arm_v2_userhost.py"),
                             "--config", str(config_path), command, *extra],
                            cwd=ROOT, capture_output=True, text=True, timeout=15, env=env)
    lines = result.stdout.strip().splitlines()
    return result.returncode, json.loads(lines[-1]) if lines else {"result": "NO_OUTPUT"}


def _folder_state(path, project_id):
    state = json.loads(path.read_text(encoding="utf-8"))
    return {key: value for key, value in state["folders"].items() if value["projectId"] == project_id}


def _pending_entry(ledger_path, project_id):
    entries = _read_ledger(ledger_path)["entries"].values()
    return next((entry for entry in entries if entry["projectId"] == project_id and entry["status"] == "PENDING"), None)


def _wait_cycles(app, start_cycle, count, project_id=None, expected_calls=None, timeout=12):
    seen = set()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and len(seen) < count:
        app.root.update()
        recent = (app.latest or {}).get("host", {}).get("recentCycle") or {}
        cycle = recent.get("cycle")
        if isinstance(cycle, int) and cycle > start_cycle and cycle not in seen:
            seen.add(cycle)
            project = next((item for item in recent.get("projects", [])
                            if item.get("projectId") == project_id), None)
            if project_id is not None and project is not None and expected_calls is not None:
                if project.get("providerCalls") != expected_calls:
                    raise AssertionError("unexpected provider calls for pause scope")
        time.sleep(0.025)
    if len(seen) < count:
        raise AssertionError("expected monitor cycles were not observed")
    return sorted(seen)


def main():
    if os.name != "nt" or not os.environ.get("LOCALAPPDATA"):
        raise SystemExit("visible Tk pause qualification requires Windows current-user LocalAppData")
    output = {"platform": "windows", "provider": "local-fixture", "receivers": "two loopback simulated APOs"}
    app = None
    worker_started = False
    with tempfile.TemporaryDirectory(prefix="arm-m02b-pause-visible-", dir=os.environ["LOCALAPPDATA"]) as raw, ExitStack() as stack:
        root = Path(raw)
        registry_path, detector_path, ledger_path = root / "projects.json", root / "detector.json", root / "ledger.json"
        worker_fixture, folder_fixture_path, config_path = root / "worker-fixture.json", root / "folder-validation.json", root / "host.json"
        _write(worker_fixture, snapshots())
        _write(folder_fixture_path, folder_fixture())
        registry = ProjectRegistry(registry_path)
        provider = FakeDriveProvider(folder_fixture())
        apo_a = stack.enter_context(SimulatedApo("project-a", KEYS["test:project-a"], root / "apo-a.json"))
        apo_b = stack.enter_context(SimulatedApo("project-b", KEYS["test:project-b"], root / "apo-b.json"))
        for suffix, apo in (("a", apo_a), ("b", apo_b)):
            registry.configure_folder_project(project_id=f"project-{suffix}", display_name=f"Project {suffix.upper()}",
                root_url=f"https://drive.google.com/drive/folders/root-{suffix}", prompts_id=f"prompts-{suffix}",
                reports_id=f"reports-{suffix}", endpoint=apo.url, provider=provider,
                repository=f"owner/project-{suffix}", secret_ref=f"test:project-{suffix}", enabled=True)
        _write(config_path, {"schemaVersion": 1, "registryPath": str(registry_path),
            "detectorStatePath": str(detector_path), "notificationLedgerPath": str(ledger_path),
            "providerFixturePath": str(worker_fixture),
            "testSecrets": {ref: base64.b64encode(key).decode("ascii") for ref, key in KEYS.items()},
            "intervalSeconds": 4, "stopTimeoutSeconds": 8})
        config = load_config(config_path)

        def cleanup():
            nonlocal app
            if app is not None:
                try:
                    app.close()
                except Exception:
                    pass
            if worker_started:
                try:
                    host_stop(config_path)
                except Exception:
                    pass
        stack.callback(cleanup)

        app = _new_app(config_path, folder_fixture_path)
        _invoke(app, app.start_button)
        _wait(app, lambda: app.future is None and app.latest["host"].get("status") in {"RUNNING", "DEGRADED"}, 12)
        worker_started = True
        first_pid = app.latest["host"]["pid"]
        _wait(app, lambda: app.latest["host"].get("cycle", 0) >= 1)
        output["start"] = {"status": app.latest["host"]["status"], "sameWorker": app.latest["host"]["pid"] == first_pid,
                            "globalPaused": app.latest["host"]["globalPaused"]}

        # Selection remains attached to the same project across three real one-second refreshes.
        app.project_table.selection_set("project-b")
        initial_cycle = app.latest["host"]["cycle"]
        _wait_cycles(app, initial_cycle, 3, timeout=20)
        assert app.project_table.selection() == ("project-b",)
        assert "project-b" in app.details.get("1.0", "end")
        assert str(app.pause_project_button.cget("state")) == "normal"
        _invoke(app, app.pause_project_button)
        _wait(app, lambda: app.future is None and "project-b" in app.latest["host"]["pausedProjectIds"], 12)
        assert "safe monitor boundary" in app.notice_text.get()
        _invoke(app, app.resume_project_button)
        _wait(app, lambda: app.future is None and "project-b" not in app.latest["host"]["pausedProjectIds"], 12)
        output["selectionAndControls"] = {"selectedForThreeRefreshes": "project-b",
            "pauseApplied": True, "resumeApplied": True, "detailsRefreshed": "project-b" in app.details.get("1.0", "end")}

        # A is updated and ACKed; B then arrives and the receiver accepts but loses its ACK.
        changed = snapshots(changed=True)
        _write(worker_fixture, changed)
        _wait(app, lambda: any(item["projectId"] == "project-a" and item["changeKind"] == "CONTENT_UPDATED"
                                for item in app.latest["history"])
              and apo_a.processed_count >= 1, 15)
        apo_b.drop_after_accept = 1
        arrivals = snapshots(arrivals=True, changed=True)
        _write(worker_fixture, arrivals)
        _wait(app, lambda: _pending_entry(ledger_path, "project-b") is not None
              and apo_b.request_count >= 1 and apo_b.processed_count >= 1, 18)
        pending_b = _pending_entry(ledger_path, "project-b")
        pending_id = pending_b["eventId"]
        b_requests_at_pending = apo_b.request_count
        b_state_at_pending = _folder_state(detector_path, "project-b")
        app.project_table.selection_set("project-b")
        _invoke(app, app.pause_project_button)
        _wait(app, lambda: app.future is None and "project-b" in app.latest["host"]["pausedProjectIds"], 12)
        assert "safe monitor boundary" in app.notice_text.get()

        # Change both fixture projects. B receives no new fixture listing or dispatch; A continues.
        paused_fixture = snapshots(arrivals=True, changed=True)
        for folder_id, checksum, version in (("reports-b", "e" * 32, "4"), ("prompts-a", "d" * 32, "4")):
            file_meta = paused_fixture["folders"][folder_id]["items"][0]
            file_meta.update({"md5Checksum": checksum, "version": version})
        _write(worker_fixture, paused_fixture)
        start_cycle = app.latest["host"]["cycle"]
        _wait_cycles(app, start_cycle, 3, project_id="project-b", expected_calls=0, timeout=20)
        assert _folder_state(detector_path, "project-b") == b_state_at_pending
        assert _pending_entry(ledger_path, "project-b")["eventId"] == pending_id
        assert apo_b.request_count == b_requests_at_pending, json.dumps({
            "requestsAtPending": b_requests_at_pending, "requestsAfterPause": apo_b.request_count,
            "pendingEntry": _pending_entry(ledger_path, "project-b"),
            "hostStatus": app.latest["host"].get("status"), "notice": app.notice_text.get()}, sort_keys=True)
        assert apo_a.processed_count >= 2
        output["projectPause"] = {"result": "APPLIED", "projectBProviderCallsPerCycle": 0,
            "projectBNewRequests": 0, "pendingEventIdPreserved": pending_id,
            "projectAContinued": True}

        # Global pause freezes all transport while leaving the worker alive and heartbeating.
        _invoke(app, app.pause_all_button)
        _wait(app, lambda: app.future is None and app.latest["host"].get("status") == "PAUSED"
              and app.latest["host"].get("globalPaused") is True, 12)
        global_pid = app.latest["host"]["pid"]
        detector_before_global = detector_path.read_bytes()
        ledger_before_global = ledger_path.read_bytes()
        requests_before_global = (apo_a.request_count, apo_b.request_count)
        fixture_global = snapshots(arrivals=True, changed=True)
        fixture_global["folders"]["prompts-a"]["items"][0].update({"md5Checksum": "f" * 32, "version": "5"})
        fixture_global["folders"]["reports-b"]["items"][0].update({"md5Checksum": "f" * 32, "version": "5"})
        _write(worker_fixture, fixture_global)
        observed_heartbeats = set()
        paused_cycle = app.latest["host"]["cycle"]
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline and len(observed_heartbeats) < 3:
            app.root.update()
            current = host_status(config_path)
            assert current["status"] == "PAUSED" and current["pid"] == global_pid
            assert current["cycle"] == paused_cycle
            observed_heartbeats.add(current["heartbeatAt"])
            time.sleep(0.2)
        assert len(observed_heartbeats) >= 3
        assert detector_path.read_bytes() == detector_before_global
        assert ledger_path.read_bytes() == ledger_before_global
        assert (apo_a.request_count, apo_b.request_count) == requests_before_global
        output["globalPause"] = {"status": "PAUSED", "sameWorkerPid": True,
            "distinctHeartbeats": len(observed_heartbeats), "cycleUnchanged": True,
            "providerAndReceiverStateUnchanged": True}

        _invoke(app, app.stop_button)
        assert app.future is not None
        _wait(app, lambda: app.future is None and app.latest["host"].get("status") == "STOPPED", 15)
        worker_started = False
        assert detector_path.read_bytes() == detector_before_global
        assert ledger_path.read_bytes() == ledger_before_global
        paused_store = config.pause_store.load(["project-a", "project-b"])
        assert paused_store["globalPaused"] and "project-b" in paused_store["pausedProjectIds"]
        stopped_state = config.pause_store.path.read_bytes()
        _invoke(app, app.start_button)
        _wait(app, lambda: app.future is None and app.latest["host"].get("status") == "PAUSED"
              and app.latest["host"].get("globalPaused") is True, 15)
        worker_started = True
        restarted_pid = app.latest["host"]["pid"]
        assert restarted_pid != global_pid
        assert detector_path.read_bytes() == detector_before_global
        assert ledger_path.read_bytes() == ledger_before_global
        assert config.pause_store.path.read_bytes() == stopped_state

        attached = _child_reattach(config_path, folder_fixture_path)
        assert attached["samePid"] and attached["status"] == "PAUSED"
        assert "Existing monitor attached" in attached["startMessage"]
        output["restartAndAttach"] = {"remainedPausedUntilResume": True,
            "secondGuiSameWorker": attached["samePid"], "secondStartDidNotDuplicate": True}

        # Global resume leaves B paused, preserves A's detector baseline, and permits A progress.
        _invoke(app, app.resume_all_button)
        _wait(app, lambda: app.future is None and app.latest["host"].get("status") == "RUNNING"
              and app.latest["host"].get("globalPaused") is False, 12)
        assert "project-b" in app.latest["host"]["pausedProjectIds"]
        _wait(app, lambda: any(item["projectId"] == "project-a" and item["changeKind"] == "CONTENT_UPDATED"
                                for item in app.latest["history"])
              and apo_a.processed_count >= 3, 15)
        assert apo_b.request_count == b_requests_at_pending
        output["globalResume"] = {"projectBRemainedPaused": True, "projectAResumedWithoutRebaseline": True}

        app.project_table.selection_set("project-b")
        _invoke(app, app.resume_project_button)
        _wait(app, lambda: app.future is None and "project-b" not in app.latest["host"]["pausedProjectIds"], 12)
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            app.root.update()
            current_entry = _read_ledger(ledger_path)["entries"][pending_id]
            if current_entry["status"] == "ACKED":
                break
            time.sleep(0.05)
        assert current_entry["status"] == "ACKED" and current_entry["eventId"] == pending_id
        assert current_entry["attemptCount"] >= 2
        assert apo_b.processed_count >= 2
        output["projectResume"] = {"pendingEventIdRetried": pending_id,
            "attemptCount": current_entry["attemptCount"], "acknowledged": True,
            "receiverUniqueEvents": apo_b.processed_count}

        # A pause coexists with enabled=false. Resume must not make a disabled project eligible.
        app.project_table.selection_set("project-a")
        _invoke(app, app.pause_project_button)
        _wait(app, lambda: app.future is None and "project-a" in app.latest["host"]["pausedProjectIds"], 12)
        _invoke(app, app.disable_button)
        _wait(app, lambda: app.future is None and not next(row for row in app.latest["projects"]
              if row["projectId"] == "project-a")["enabled"], 12)
        a_requests_disabled = apo_a.request_count
        _invoke(app, app.resume_project_button)
        _wait(app, lambda: app.future is None and "project-a" not in app.latest["host"]["pausedProjectIds"], 12)
        disabled_fixture = snapshots(arrivals=True, changed=True)
        disabled_fixture["folders"]["prompts-a"]["items"][0].update({"md5Checksum": "9" * 32, "version": "6"})
        _write(worker_fixture, disabled_fixture)
        current_cycle = app.latest["host"]["cycle"]
        _wait_cycles(app, current_cycle, 2, project_id="project-a", expected_calls=0, timeout=14)
        assert apo_a.request_count == a_requests_disabled
        assert not next(row for row in app.latest["projects"] if row["projectId"] == "project-a")["enabled"]
        _invoke(app, app.enable_button)
        _wait(app, lambda: app.future is None and next(row for row in app.latest["projects"]
              if row["projectId"] == "project-a")["enabled"], 12)
        _wait(app, lambda: apo_a.request_count > a_requests_disabled, 15)
        output["disabledResume"] = {"disabledAfterResume": True, "providerCallsWhileDisabled": 0,
            "deliveryAfterExplicitEnable": True}

        # Invalid project and stopped/stale ownership cannot mutate persisted pause state.
        state_before_invalid = config.pause_store.path.read_bytes()
        invalid_code, invalid_result = _cli(config_path, "pause", "--project-id", "missing-project")
        assert invalid_code == 2 and config.pause_store.path.read_bytes() == state_before_invalid
        _invoke(app, app.stop_button)
        _wait(app, lambda: app.future is None and app.latest["host"].get("status") == "STOPPED", 15)
        worker_started = False
        state_before_owner = config.pause_store.path.read_bytes()
        owner_code, owner_result = _cli(config_path, "pause")
        assert owner_code == 2 and owner_result["result"] == "INVALID_OWNER"
        assert config.pause_store.path.read_bytes() == state_before_owner
        output["failClosedControls"] = {"invalidProjectExit": invalid_code,
            "invalidOwnerExit": owner_code, "noPauseStateMutation": True}

        # A corrupt pause file blocks a fresh worker before any provider call or send.
        config.pause_store.path.write_text("{broken", encoding="utf-8")
        detector_before_corrupt, ledger_before_corrupt = detector_path.read_bytes(), ledger_path.read_bytes()
        counts_before_corrupt = (apo_a.request_count, apo_b.request_count)
        start_code, start_result = _cli(config_path, "start")
        assert start_code == 2 and start_result["result"] == "DEGRADED"
        assert not _probe_lock(config.worker_lock_path)
        assert detector_path.read_bytes() == detector_before_corrupt
        assert ledger_path.read_bytes() == ledger_before_corrupt
        assert (apo_a.request_count, apo_b.request_count) == counts_before_corrupt
        output["corruptPauseState"] = {"startRejectedBeforeWorker": True,
            "providerAndReceiverSideEffects": 0, "exit": start_code}
        output["cleanup"] = "PASS_NO_WORKER_REMAINS"

    output["outcome"] = "PASS_VISIBLE_WINDOWS_PAUSE_RESUME_OFFLINE"
    print(json.dumps(output, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
