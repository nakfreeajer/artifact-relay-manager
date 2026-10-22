"""Visible Windows Tk dashboard qualification using only local fixtures/loopback APOs."""
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
from arm_v2_dashboard import DashboardApp
from arm_v2_userhost import load_config, status as host_status, stop as host_stop
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
    snapshot = app.latest if isinstance(app.latest, dict) else {}
    host = snapshot.get("host", {})
    recent = host.get("recentCycle", {}) if isinstance(host.get("recentCycle"), dict) else {}
    summary = {"hostStatus": host.get("status"), "cycle": host.get("cycle"),
               "observation": recent.get("observation"),
               "observationErrorClass": recent.get("observationErrorClass"),
               "deliveryErrorClass": recent.get("deliveryErrorClass"),
               "history": [{"projectId": item["projectId"], "eventType": item["eventType"],
                            "changeKind": item["changeKind"], "receiptStatus": item["receiptStatus"]}
                           for item in snapshot.get("history", [])]}
    raise AssertionError("dashboard demonstration timed out: " +
                         json.dumps(summary, sort_keys=True, separators=(",", ":")))


def _new_app(config, folders):
    root = tk.Tk()
    app = DashboardApp(root, config, folders)
    _wait(app, lambda: app.future is None)
    return app


def _add(app, project_id, root_id, endpoint, *, prompts=None, reports=None):
    values = {"displayName": f"Project {project_id[-1].upper()}", "projectId": project_id,
              "repository": f"owner/{project_id}", "workspace": "",
              "rootUrl": f"https://drive.google.com/drive/folders/{root_id}",
              "promptsId": prompts or f"prompts-{project_id[-1]}",
              "reportsId": reports or f"reports-{project_id[-1]}",
              "endpoint": endpoint, "secretRef": f"test:{project_id}"}
    for key, value in values.items():
        app.form[key].set(value)
    app.add_project()
    _wait(app, lambda: app.future is None)


def _select(app, project_id):
    app.project_table.selection_set(project_id)


def _toggle(app, project_id, enabled):
    _select(app, project_id)
    (app.enable_button if enabled else app.disable_button).invoke()
    _wait(app, lambda: app.future is None)


def _close(app):
    app.close()
    app.root.update_idletasks()


def _child_reattach(config_path, folder_fixture_path):
    code = r'''import json, sys, tkinter as tk
from arm_v2_dashboard import DashboardApp
root=tk.Tk(); app=DashboardApp(root, sys.argv[1], sys.argv[2])
def finish():
    if app.future is not None:
        root.after(50, finish); return
    before=app.latest["host"].get("pid")
    app.start_button.invoke()
    def finish_start():
        if app.future is not None:
            root.after(50, finish_start); return
        host=app.latest["host"] if app.latest else {}
        print(json.dumps({"status":host.get("status"),"pid":host.get("pid"),"cycle":host.get("cycle"),
                          "samePid":before==host.get("pid"),"startMessage":app.notice_text.get()}),flush=True)
        app.close()
    root.after(50,finish_start)
root.after(50,finish); root.mainloop()
'''
    result = subprocess.run([sys.executable, "-c", code, str(config_path), str(folder_fixture_path)],
                            cwd=ROOT, capture_output=True, text=True, timeout=15,
                            env={key: value for key, value in os.environ.items()
                                 if key not in {"RELAY_GDRIVE_ACCESS_TOKEN", "RELAY_GDRIVE_OAUTH_CLIENT_FILE"}})
    if result.returncode != 0:
        raise AssertionError("fresh dashboard reattach process failed")
    return json.loads(result.stdout.strip().splitlines()[-1])


def main():
    if os.name != "nt" or not os.environ.get("LOCALAPPDATA"):
        raise SystemExit("visible Tk qualification requires Windows current-user LocalAppData")
    output = {}
    worker_started = False
    app = None
    with tempfile.TemporaryDirectory(prefix="arm-m02a-visible-", dir=os.environ["LOCALAPPDATA"]) as raw, ExitStack() as stack:
        def cleanup():
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
        root = Path(raw)
        registry_path = root / "projects.json"
        detector_path = root / "detector.json"
        ledger_path = root / "ledger.json"
        worker_fixture = root / "worker-fixture.json"
        folder_fixture_path = root / "folder-validation.json"
        config_path = root / "host-config.json"
        _write(worker_fixture, snapshots())
        _write(folder_fixture_path, folder_fixture())

        # Seed one unrelated M01 legacy project and prove v2 dashboard writes preserve it.
        legacy_config = root / "legacy-drive.json"
        legacy_state = root / "legacy-state.json"
        _write(legacy_config, {"schemaVersion": 1, "projectId": "legacy-project",
            "repository": "owner/legacy-project", "folderId": "legacy-root",
            "relayWorkspace": str(root / "legacy-workspace"),
            "watcherEndpoint": "http://127.0.0.1:49001/notify", "eventType": "ARTIFACT_CHANGED"})
        _write(legacy_state, {})
        registry = ProjectRegistry(registry_path)
        registry.add("legacy-project", "Legacy project", legacy_config, legacy_state)
        legacy_before = json.loads(registry_path.read_text(encoding="utf-8"))["projects"]

        apo_a = stack.enter_context(SimulatedApo("project-a", KEYS["test:project-a"], root / "apo-a.json"))
        apo_b = stack.enter_context(SimulatedApo("project-b", KEYS["test:project-b"], root / "apo-b.json"))
        _write(config_path, {"schemaVersion": 1, "registryPath": str(registry_path),
            "detectorStatePath": str(detector_path), "notificationLedgerPath": str(ledger_path),
            "providerFixturePath": str(worker_fixture),
            "testSecrets": {ref: base64.b64encode(key).decode("ascii") for ref, key in KEYS.items()},
            "intervalSeconds": 1, "stopTimeoutSeconds": 8})

        app = _new_app(config_path, folder_fixture_path)
        assert app.latest["host"]["status"] == "STOPPED"
        assert host_status(config_path)["status"] == "STOPPED"  # opening/refreshing does not spawn
        before_bad_add = registry_path.read_bytes()
        _add(app, "project-a", "missing-root", apo_a.url)
        assert registry_path.read_bytes() == before_bad_add
        _add(app, "project-a", "root-a", apo_a.url, reports="wrong-report-child")
        assert registry_path.read_bytes() == before_bad_add

        _add(app, "project-a", "root-a", apo_a.url)
        after_a = registry_path.read_bytes()
        _add(app, "project-a", "root-a", apo_a.url)
        assert registry_path.read_bytes() == after_a
        _write(folder_fixture_path, {"items": [], "fail": True})
        _add(app, "project-b", "root-b", apo_b.url)
        assert registry_path.read_bytes() == after_a
        _write(folder_fixture_path, folder_fixture())
        _add(app, "project-b", "root-b", apo_b.url)
        assert [item["projectId"] for item in app.latest["projects"]] == ["project-a", "project-b"]
        assert all(not item["enabled"] for item in app.latest["projects"])

        _toggle(app, "project-a", True)
        _toggle(app, "project-b", True)
        registry_after_enable = ProjectRegistry(registry_path).load()
        assert registry_after_enable["projects"] == legacy_before
        assert all(item["enabled"] for item in registry_after_enable["folderProjects"])
        app.close()
        app = None

        app = _new_app(config_path, folder_fixture_path)
        assert [item["projectId"] for item in app.latest["projects"]] == ["project-a", "project-b"]
        assert all(item["enabled"] for item in app.latest["projects"])
        app.start_button.invoke()
        _wait(app, lambda: app.future is None and app.latest is not None
              and app.latest["host"].get("status") in {"RUNNING", "DEGRADED"})
        worker_started = True
        worker_pid = app.latest["host"].get("pid")
        assert app.latest["pending"] == 0 and app.latest["acked"] == 0
        initial = host_status(config_path)
        assert initial["status"] in {"RUNNING", "DEGRADED"} and initial["pid"] == worker_pid
        registry_while_running = registry_path.read_bytes()
        _add(app, "project-c", "root-a", apo_a.url)
        assert registry_path.read_bytes() == registry_while_running
        assert "rejected" in app.notice_text.get().lower()

        app.close()  # UI close does not stop the independent M05 worker.
        app = None
        after_close = host_status(config_path)
        assert after_close["pid"] == worker_pid and after_close["status"] in {"RUNNING", "DEGRADED"}
        attached = _child_reattach(config_path, folder_fixture_path)
        assert attached["pid"] == worker_pid and attached["status"] in {"RUNNING", "DEGRADED"}
        assert attached["samePid"] and "Existing monitor attached" in attached["startMessage"]
        output["reattach"] = {"sameWorkerPid": attached["samePid"],
                              "reattachedStatus": attached["status"], "cycle": attached["cycle"],
                              "duplicateWorker": False}

        # UI close/reopen did not create another monitor. Reopen in the visible parent window.
        app = _new_app(config_path, folder_fixture_path)
        _wait(app, lambda: app.latest["host"].get("cycle", 0) >= 1)
        apo_b.drop_after_accept = 1
        changed = snapshots(changed=True)
        _write(worker_fixture, changed)
        _wait(app, lambda: any(event["changeKind"] == "CONTENT_UPDATED"
                               for event in app.latest["history"]), timeout=15)
        _wait(app, lambda: apo_a.processed_count >= 1, timeout=8)
        acked_counts = (apo_a.request_count, apo_b.request_count)
        cycle_after_ack = app.latest["host"].get("cycle", 0)
        _wait(app, lambda: app.latest["host"].get("cycle", 0) >= cycle_after_ack + 2, timeout=8)
        assert (apo_a.request_count, apo_b.request_count) == acked_counts
        arrivals = snapshots(arrivals=True, changed=True)
        _write(worker_fixture, arrivals)
        _wait(app, lambda: any(event["changeKind"] == "ARRIVED" and event["projectId"] == "project-b"
                               for event in app.latest["history"]), timeout=15)
        _wait(app, lambda: any(event["projectId"] == "project-b" and event["status"] == "PENDING"
            for event in _read_ledger(load_config(config_path).ledger_path)["entries"].values()), timeout=8)
        pending_event = next(event for event in _read_ledger(load_config(config_path).ledger_path)["entries"].values()
                             if event["projectId"] == "project-b" and event["status"] == "PENDING")
        assert pending_event["status"] == "PENDING"
        pending_id = pending_event["eventId"]
        b_requests_before_disable = apo_b.request_count

        _toggle(app, "project-b", False)
        doc = ProjectRegistry(registry_path).load()
        assert next(item for item in doc["folderProjects"] if item["projectId"] == "project-b")["enabled"] is False
        assert doc["projects"] == legacy_before
        preserved = _read_ledger(load_config(config_path).ledger_path)["entries"][pending_id]
        assert preserved["status"] == "PENDING" and preserved["eventId"] == pending_id
        cycle_before_a_change = app.latest["host"].get("cycle", 0)
        updated_a = snapshots(changed=True)
        item_a = updated_a["folders"]["prompts-a"]["items"][0]
        item_a["md5Checksum"] = "d" * 32
        item_a["version"] = "3"
        _write(worker_fixture, updated_a)
        _wait(app, lambda: app.latest["host"].get("cycle", 0) >= cycle_before_a_change + 1
              and any(event["projectId"] == "project-a" and event["changeKind"] == "CONTENT_UPDATED"
                      for event in app.latest["history"])
              and apo_a.processed_count >= 2, timeout=15)
        _wait(app, lambda: app.latest["host"].get("cycle", 0) >= cycle_before_a_change + 3, timeout=8)
        assert apo_b.request_count == b_requests_before_disable
        assert apo_b.processed_count == 1
        output["disableIsolation"] = {"projectBStatus": next(item["status"] for item in app.latest["projects"]
                                    if item["projectId"] == "project-b"),
                                    "pendingSameEventId": pending_id,
                                    "projectBRequestsAfterDisable": apo_b.request_count - b_requests_before_disable,
                                    "projectAContinued": apo_a.processed_count >= 2,
                                    "legacyProjectsUnchanged": True}

        app.stop_button.invoke()
        _wait(app, lambda: app.future is None and app.latest is not None
              and app.latest["host"].get("status") == "STOPPED", timeout=15)
        worker_started = False
        detector_after_stop = load_config(config_path).detector_path.read_bytes()
        ledger_after_stop = load_config(config_path).ledger_path.read_bytes()
        app.close()
        app = None
        app = _new_app(config_path, folder_fixture_path)
        assert app.latest["host"]["status"] == "STOPPED"
        assert load_config(config_path).detector_path.read_bytes() == detector_after_stop
        assert load_config(config_path).ledger_path.read_bytes() == ledger_after_stop
        registry_after_stop = registry_path.read_bytes()
        _add(app, "project-c", "root-a", apo_a.url)
        assert registry_path.read_bytes() == registry_after_stop
        assert "rejected" in app.notice_text.get().lower()
        app.close()
        app = None

        # Corrupt transport state must be visible and disables controls; it cannot start a worker.
        registry_before_corrupt = registry_path.read_bytes()
        ledger_path.write_text("{broken", encoding="utf-8")
        app = _new_app(config_path, folder_fixture_path)
        assert app.latest is None and app.last_error == "LOCAL_STATE_INVALID"
        assert str(app.start_button.cget("state")) == "disabled"
        app.start_button.invoke()
        assert host_status(config_path)["status"] == "STOPPED"
        assert registry_path.read_bytes() == registry_before_corrupt
        output["corruptState"] = "visible fail-closed UI; no worker started; registry unchanged"
        app.close()
        app = None
        output["outcome"] = "PASS_VISIBLE_WINDOWS_DASHBOARD_OFFLINE"
        output["projects"] = ["project-a", "project-b"]
        output["pendingRetryPreservedEventId"] = pending_id
        output["legacyProjectCount"] = len(legacy_before)
        output["receivers"] = {"projectAUnique": apo_a.processed_count,
                                "projectBUnique": apo_b.processed_count,
                                "projectBRequestCount": apo_b.request_count}
        output["temporaryStateBytes"] = {"detector": len(detector_after_stop),
                                          "ledger": len(ledger_after_stop)}

    print(json.dumps(output, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
