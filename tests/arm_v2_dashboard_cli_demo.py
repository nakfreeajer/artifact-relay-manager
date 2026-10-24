"""Visible Windows Tk dashboard qualification using only local fixtures/loopback APOs."""
from __future__ import annotations

import base64
from datetime import datetime
import hashlib
import hmac
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

EXPECTED_ARRIVAL_EVENT_IDS = {
    ("project-a", "PROMPT_CHANGED", "new-prompt-a"):
        "m03-ccdf09b56f60af21d3b10b621cbfe2980b8ac07cbe35731be1198bfc8987af9e",
    ("project-a", "REPORT_CHANGED", "new-report-a"):
        "m03-dd8f218beb91b39eb62e222aae469b0a0451a1160fea20c1887c694dd491e344",
    ("project-b", "PROMPT_CHANGED", "new-prompt-b"):
        "m03-3d8fe0cfc7f434d9b069fa2209ba458c253350801a52b57979a3104bbf251dc8",
    ("project-b", "REPORT_CHANGED", "moved-in-report-b"):
        "m03-d20ab0b353254edc4e31ef3b960d152713bbca5f60d0d3aac0cb12f055f1f406",
}
PENDING_ARRIVAL = ("project-b", "PROMPT_CHANGED", "new-prompt-b")

from arm_notification import _canonical_json, _read_ledger
from drive_change_detector import _json_load as _read_detector_state, _validate_state as _validate_detector_state
from arm_v2_dashboard import DashboardApp
import arm_v2_dashboard
from arm_v2_userhost import (SingleInstanceLock, load_config, status as host_status,
                             stop as host_stop)
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
    app.root.update()


def _notice_class(value):
    text = value.casefold()
    if "rejected" in text or "refused" in text or "invalid" in text:
        return "rejected_or_invalid"
    if "started" in text or "enabled" in text or "stopped" in text:
        return "action_result"
    if "fixture" in text or "offline" in text:
        return "fixture_notice"
    return "empty_or_other"


def _enablement_snapshot(app, registry, project_id, button, fixture_path, legacy_before):
    try:
        document = registry.load()
        enabled = {item["projectId"]: item["enabled"] for item in document["folderProjects"]}
        legacy_unchanged = document["projects"] == legacy_before
    except Exception:
        enabled = None
        legacy_unchanged = False
    latest = app.latest if isinstance(app.latest, dict) else None
    latest_project = next((item for item in (latest or {}).get("projects", [])
                           if item.get("projectId") == project_id), None)
    future = app.future
    lock = SingleInstanceLock(registry.write_lock_path)
    lock_acquired = lock.acquire()
    if lock_acquired:
        lock.release()
    try:
        observed_host = host_status(app.config_path).get("status")
    except Exception:
        observed_host = "STATUS_UNAVAILABLE"
    return {
        "selectedProjectId": app._selected_project(),
        "buttonState": str(button.cget("state")),
        "buttonDisabled": bool(button.instate(["disabled"])),
        "pendingRefresh": future is not None and not future.done(),
        "futurePresent": future is not None,
        "latestHasSnapshot": latest is not None,
        "latestProjectEnabled": latest_project.get("enabled") if latest_project else None,
        "latestProjectIssueClass": latest_project.get("lastIssue") if latest_project else None,
        "rootWindowState": app.root.state(),
        "noticeClass": _notice_class(app.notice_text.get()),
        "lastErrorClass": app.last_error,
        "fixtureAvailable": fixture_path.is_file(),
        "registryEnabledValues": enabled,
        "legacyArrayUnchanged": legacy_unchanged,
        "registryLockContended": not lock_acquired,
        "hostStatusFromSnapshot": (latest or {}).get("host", {}).get("status"),
        "hostStatusIndependentRead": observed_host,
    }


def _dashboard_lock_is_free(registry):
    probe = SingleInstanceLock(registry.write_lock_path)
    if not probe.acquire():
        return False
    probe.release()
    return True


def _toggle(app, project_id, enabled, legacy_before):
    _select(app, project_id)
    registry_path = load_config(app.config_path).registry_path
    registry = ProjectRegistry(registry_path)
    button = app.enable_button if enabled else app.disable_button
    before_actionable_wait = _enablement_snapshot(app, registry, project_id, button,
                                                 app.folder_validation_fixture, legacy_before)

    def actionable():
        project = next((item for item in (app.latest or {}).get("projects", [])
                        if item.get("projectId") == project_id), None)
        try:
            registry_enabled = registry.show_folder_project(project_id)["enabled"]
        except Exception:
            return False
        return (app._selected_project() == project_id and app.future is None and project is not None
                and project.get("enabled") is (not enabled) and registry_enabled is (not enabled)
                and str(button.cget("state")) == "normal" and not button.instate(["disabled"])
                and _dashboard_lock_is_free(registry))

    try:
        _wait(app, actionable)
    except Exception as exc:
        trace = {"projectId": project_id, "targetEnabled": enabled,
                 "phase": "wait_for_actionable_real_button", "timeoutOrError": type(exc).__name__,
                 "beforeActionableWait": before_actionable_wait,
                 "atFailure": _enablement_snapshot(app, registry, project_id, button,
                                                    app.folder_validation_fixture, legacy_before)}
        raise AssertionError("project enablement readiness diagnostic: " +
                             json.dumps(trace, sort_keys=True, separators=(",", ":"))) from None
    before = _enablement_snapshot(app, registry, project_id, button,
                                  app.folder_validation_fixture, legacy_before)
    if (before["selectedProjectId"] != project_id or before["buttonDisabled"]
            or before["futurePresent"] or before["registryEnabledValues"].get(project_id) is enabled
            or not _dashboard_lock_is_free(registry)):
        raise AssertionError("project enablement control became unavailable before invoke: " +
                             json.dumps(before, sort_keys=True, separators=(",", ":")))
    invoke_result = button.invoke()  # retain the actual visible Tk widget action
    after_invoke = _enablement_snapshot(app, registry, project_id, button,
                                        app.folder_validation_fixture, legacy_before)
    trace = {"projectId": project_id, "targetEnabled": enabled,
             "beforeActionableWait": before_actionable_wait,
             "beforeInvoke": before, "afterInvoke": after_invoke,
             "invokeReturnedEmpty": invoke_result == ""}
    try:
        _wait(app, lambda: registry.show_folder_project(project_id)["enabled"] is enabled)
        _wait(app, lambda: app.future is None and isinstance(app.latest, dict)
              and next((item for item in app.latest["projects"]
                        if item.get("projectId") == project_id), {}).get("enabled") is enabled)
        refreshed = arm_v2_dashboard.dashboard_snapshot(app.config_path)
        independent = next((item for item in refreshed["projects"]
                            if item.get("projectId") == project_id), None)
        if independent is None or independent.get("enabled") is not enabled:
            raise AssertionError("independent refreshed snapshot disagreed")
    except Exception as exc:
        trace["timeoutOrError"] = type(exc).__name__
        trace["atFailure"] = _enablement_snapshot(app, registry, project_id, button,
                                                   app.folder_validation_fixture, legacy_before)
        raise AssertionError("project enablement diagnostic: " +
                             json.dumps(trace, sort_keys=True, separators=(",", ":"))) from None
    trace["persistedEnabled"] = registry.show_folder_project(project_id)["enabled"]
    trace["refreshedSnapshotEnabled"] = independent["enabled"]
    return trace


def _arrival_checkpoint(app, apo_a, apo_b, *, allow_pending_ack_after_drop=False):
    """Read explicit detector/ledger identities and receiver dispositions."""
    config = load_config(app.config_path)
    detector = _validate_detector_state(_read_detector_state(config.detector_path))
    ledger = _read_ledger(config.ledger_path)
    expected_files = {identity[2] for identity in EXPECTED_ARRIVAL_EVENT_IDS}
    found = {}
    for event in detector["events"]:
        if event["changeKind"] == "ARRIVED" and event["fileId"] in expected_files:
            key = (event["projectId"], event["eventType"], event["fileId"])
            found.setdefault(key, []).append(event)

    def receiver(apo):
        with apo.lock:
            return {
                "requestCount": apo.request_count,
                "uniqueProcessedCount": apo.processed_count,
                "acceptedEvents": {event_id: {
                    "projectId": item.get("projectId"), "eventType": item.get("eventType"),
                    "fileId": item.get("fileId"),
                } for event_id, item in apo.receipts["receipts"].items()},
            }

    receivers = {"project-a": receiver(apo_a), "project-b": receiver(apo_b)}
    rows = []
    ready = True
    for identity, expected_id in EXPECTED_ARRIVAL_EVENT_IDS.items():
        project_id, event_type, file_id = identity
        matches = found.get(identity, [])
        event_id = matches[0].get("eventId") if len(matches) == 1 else None
        entry = ledger["entries"].get(expected_id)
        accepted = receivers[project_id]["acceptedEvents"].get(expected_id)
        other_project = "project-b" if project_id == "project-a" else "project-a"
        accepted_elsewhere = expected_id in receivers[other_project]["acceptedEvents"]
        expected_status = "PENDING" if identity == PENDING_ARRIVAL else "ACKED"
        if (identity == PENDING_ARRIVAL and allow_pending_ack_after_drop
                and entry and entry.get("status") == "ACKED"):
            expected_status = "ACKED"
        ack_valid = False
        if entry and entry.get("receipt"):
            proof = {"projectId": project_id, "eventId": expected_id}
            signature = hmac.new(KEYS[f"test:{project_id}"], _canonical_json(proof),
                                 hashlib.sha256).hexdigest()
            ack_valid = hmac.compare_digest(entry["receipt"].get("signature", ""), signature)
        valid = bool(
            len(matches) == 1 and event_id == expected_id and entry
            and entry.get("eventId") == expected_id and entry.get("projectId") == project_id
            and entry.get("payload", {}).get("projectId") == project_id
            and entry.get("payload", {}).get("eventType") == event_type
            and entry.get("payload", {}).get("fileId") == file_id
            and entry.get("status") == expected_status and accepted
            and accepted.get("projectId") == project_id
            and accepted.get("eventType") == event_type
            and accepted.get("fileId") == file_id and not accepted_elsewhere
        )
        if identity == PENDING_ARRIVAL and expected_status == "PENDING":
            valid = bool(valid and entry.get("attemptCount") == 1
                         and entry.get("lastErrorClass") == "TRANSPORT_UNCERTAIN"
                         and entry.get("receipt") is None)
        elif identity == PENDING_ARRIVAL:
            valid = bool(allow_pending_ack_after_drop and valid
                         and entry.get("attemptCount", 0) >= 2
                         and entry.get("receipt") is not None and ack_valid)
        else:
            valid = bool(valid and entry.get("receipt") is not None and ack_valid)
        ready = ready and valid
        rows.append({
            "projectId": project_id, "eventType": event_type, "fileId": file_id,
            "eventId": expected_id, "m03EventId": event_id,
            "ledgerStatus": entry.get("status") if entry else "NOT_QUEUED",
            "attemptCount": entry.get("attemptCount") if entry else None,
            "lastErrorClass": entry.get("lastErrorClass") if entry else None,
            "receiptPresent": bool(entry and entry.get("receipt")),
            "receiptReceivedAt": (entry.get("receipt", {}).get("receivedAt")
                                  if entry and entry.get("receipt") else None),
            "ledgerUpdatedAt": entry.get("updatedAt") if entry else None,
            "authenticatedAck": ack_valid, "receiverAccepted": accepted is not None,
            "acceptedByWrongProject": accepted_elsewhere, "matchesIntendedOutcome": valid,
        })
    actual_ids = {event["eventId"] for event in detector["events"]
                  if event["changeKind"] == "ARRIVED" and event["fileId"] in expected_files}
    ready = ready and actual_ids == set(EXPECTED_ARRIVAL_EVENT_IDS.values())
    latest = app.latest if isinstance(app.latest, dict) else {}
    host_view = latest.get("host", {})
    return {
        "ready": ready,
        "arrivalEvents": rows,
        "receiverCounts": {project_id: {
            "requestCount": value["requestCount"],
            "uniqueProcessedCount": value["uniqueProcessedCount"],
            "acceptedArrivalIds": sorted(set(EXPECTED_ARRIVAL_EVENT_IDS.values())
                & set(value["acceptedEvents"])),
        } for project_id, value in receivers.items()},
        "tkSnapshot": {
            "acked": latest.get("acked"), "pending": latest.get("pending"),
            "cycle": host_view.get("cycle"), "heartbeatAt": host_view.get("heartbeatAt"),
            "globalPaused": host_view.get("globalPaused"),
            "pausedProjectIds": host_view.get("pausedProjectIds"),
        },
        "observedAtMonotonic": round(time.monotonic(), 3),
    }


def _edit_display_name(app, project_id, name):
    _wait(app, lambda: app.future is None)
    _select(app, project_id)
    _wait(app, lambda: app.future is None)
    _select(app, project_id)
    app.edit_button.invoke()
    dialogs = [child for child in app.root.winfo_children()
               if child.winfo_class() == "Toplevel" and child.title() == "Edit project display name"]
    if not dialogs:
        raise AssertionError(f"edit dialog did not open: selected={app.project_table.selection()}, "
                             f"button={app.edit_button.cget('state')}, "
                             f"projects={[p['projectId'] for p in app.latest['projects']]}")
    dialog = dialogs[0]
    def descendants(widget):
        result = []
        for child in widget.winfo_children():
            result.append(child)
            result.extend(descendants(child))
        return result
    widgets = descendants(dialog)
    entry = next(widget for widget in widgets if widget.winfo_class() == "TEntry")
    entry.delete(0, "end")
    entry.insert(0, name)
    next(widget for widget in widgets if widget.winfo_class() == "TButton"
         and widget.cget("text") == "Save").invoke()
    _wait(app, lambda: app.future is None)


def _remove_confirmed(app, project_id):
    _wait(app, lambda: app.future is None)
    _select(app, project_id)
    _wait(app, lambda: app.future is None)
    _select(app, project_id)
    original = arm_v2_dashboard.messagebox.askyesno
    arm_v2_dashboard.messagebox.askyesno = lambda *args, **kwargs: True
    try:
        app.remove_button.invoke()
    finally:
        arm_v2_dashboard.messagebox.askyesno = original
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
            "testSecrets": {ref: base64.b64encode(key).decode("ascii")
                            for ref, key in {**KEYS, "test:project-c": KEYS["test:project-a"]}.items()},
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

        # Exercise the actual Tk edit dialog and confirmed removal of an unused project.
        c_folders = folder_fixture()
        c_folders["items"].extend([
            {"id": "root-c", "name": "Project C", "mimeType": "application/vnd.google-apps.folder",
             "trashed": False, "parents": []},
            {"id": "prompts-c", "name": "Architect_Prompts", "mimeType": "application/vnd.google-apps.folder",
             "trashed": False, "parents": ["root-c"]},
            {"id": "reports-c", "name": "Executor_Reports", "mimeType": "application/vnd.google-apps.folder",
             "trashed": False, "parents": ["root-c"]},
        ])
        _write(folder_fixture_path, c_folders)
        _add(app, "project-c", "root-c", apo_a.url)
        registry_before_edit = ProjectRegistry(registry_path).show_folder_project("project-a")
        stale_window = DashboardApp(tk.Toplevel(app.root), config_path, folder_fixture_path)
        _wait(stale_window, lambda: stale_window.future is None)
        stale_name = stale_window.latest["projects"][0]["displayName"]
        if stale_window._auto_refresh_id is not None:
            stale_window.root.after_cancel(stale_window._auto_refresh_id)
            stale_window._auto_refresh_id = None
        _edit_display_name(app, "project-a", "Renamed Project A")
        registry_after_edit = ProjectRegistry(registry_path).show_folder_project("project-a")
        assert registry_after_edit["displayName"] == "Renamed Project A"
        assert {key: value for key, value in registry_after_edit.items() if key != "displayName"} == {
            key: value for key, value in registry_before_edit.items() if key != "displayName"}
        _select(stale_window, "project-a")
        stale_window.edit_button.invoke()
        stale_dialog = next(child for child in stale_window.root.winfo_children()
            if child.winfo_class() == "Toplevel" and child.title() == "Edit project display name")
        def nested_widgets(widget):
            result = []
            for child in widget.winfo_children():
                result.append(child)
                result.extend(nested_widgets(child))
            return result
        stale_widgets = nested_widgets(stale_dialog)
        stale_entry = next(widget for widget in stale_widgets if widget.winfo_class() == "TEntry")
        stale_entry.delete(0, "end")
        stale_entry.insert(0, "Stale " + stale_name)
        next(widget for widget in stale_widgets if widget.winfo_class() == "TButton"
             and widget.cget("text") == "Save").invoke()
        assert ProjectRegistry(registry_path).show_folder_project("project-a")["displayName"] == "Renamed Project A"
        assert "edit refused" in stale_window.notice_text.get().lower()
        stale_window.close()
        _remove_confirmed(app, "project-c")
        _write(folder_fixture_path, folder_fixture())
        assert [item["projectId"] for item in ProjectRegistry(registry_path).list_folder_projects()] == [
            "project-a", "project-b"]
        output["projectManagement"] = {"editedA": True, "immutableIdentityPreserved": True,
                                      "twoWindowStaleEditRejected": True,
                                      "confirmedUnusedCRemoval": True, "runningWorkerRemovalRefused": True,
                                      "historyBearingRemovalRefused": True, "stateFilesDeleted": False}

        enablement_trace = []
        enablement_trace.append(_toggle(app, "project-a", True, legacy_before))
        enablement_trace.append(_toggle(app, "project-b", True, legacy_before))
        output["projectEnablement"] = enablement_trace
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
        _remove_confirmed(app, "project-b")
        assert registry_path.read_bytes() == registry_while_running
        assert "refused" in app.notice_text.get().lower()
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
        detector_after_update = _validate_detector_state(
            _read_detector_state(load_config(config_path).detector_path))
        content_update = next(event for event in detector_after_update["events"]
                              if event["fileId"] == "existing-prompts-a"
                              and event["changeKind"] == "CONTENT_UPDATED")
        content_entry = _read_ledger(load_config(config_path).ledger_path)["entries"][content_update["eventId"]]
        content_proof = {"projectId": "project-a", "eventId": content_update["eventId"]}
        content_signature = hmac.new(KEYS["test:project-a"], _canonical_json(content_proof),
                                     hashlib.sha256).hexdigest()
        assert content_entry["status"] == "ACKED"
        assert hmac.compare_digest(content_entry["receipt"]["signature"], content_signature)
        output["contentUpdate"] = {"eventId": content_update["eventId"], "status": "ACKED",
                                   "authenticatedReceipt": True, "countedAsArrival": False}
        acked_counts = (apo_a.request_count, apo_b.request_count)
        cycle_after_ack = app.latest["host"].get("cycle", 0)
        _wait(app, lambda: app.latest["host"].get("cycle", 0) >= cycle_after_ack + 2, timeout=8)
        assert (apo_a.request_count, apo_b.request_count) == acked_counts
        arrivals = snapshots(arrivals=True, changed=True)
        # Complete the four-project/folder acceptance matrix in this same real-Tk
        # dashboard + detached-worker run: the baseline helper supplies A prompts
        # and B reports; add A reports and B prompts as direct-child arrivals.
        for file_id, folder_id in (("new-report-a", "reports-a"),
                                   ("new-prompt-b", "prompts-b")):
            arrivals["folders"][folder_id]["items"].append({
                "id": file_id, "name": file_id + ".txt", "mimeType": "text/plain",
                "parents": [folder_id], "trashed": False, "version": "3", "size": "24",
                "modifiedTime": "2026-10-21T00:00:05Z", "md5Checksum": "c" * 32,
                "webViewLink": f"https://drive.google.com/file/d/{file_id}/view"})
        _write(worker_fixture, arrivals)
        checkpoint_holder = {}
        def intended_arrival_checkpoint():
            checkpoint_holder["snapshot"] = _arrival_checkpoint(app, apo_a, apo_b)
            return checkpoint_holder["snapshot"]["ready"]
        try:
            _wait(app, intended_arrival_checkpoint, timeout=15)
        except Exception:
            raise AssertionError("named arrival ACK checkpoint not reached: " +
                json.dumps(checkpoint_holder.get("snapshot", {}), sort_keys=True,
                           separators=(",", ":"))) from None
        initial_checkpoint = checkpoint_holder["snapshot"]
        initial_pending = next(event for event in initial_checkpoint["arrivalEvents"]
                              if event["eventId"] == EXPECTED_ARRIVAL_EVENT_IDS[PENDING_ARRIVAL])
        if (initial_pending["ledgerStatus"] != "PENDING" or initial_pending["attemptCount"] != 1
                or initial_pending["receiptPresent"] or initial_pending["authenticatedAck"]
                or not initial_pending["receiverAccepted"]):
            raise AssertionError("initial B prompt pending/no-receipt checkpoint was not proven: " +
                json.dumps(initial_pending, sort_keys=True, separators=(",", ":")))

        # Freeze B at a safe worker boundary while the first accepted request
        # remains durably pending. This prevents a legitimate timed retry from
        # changing the intended first-drop checkpoint during its verification.
        _select(app, "project-b")
        _wait(app, lambda: app._selected_project() == "project-b"
              and app.future is None and str(app.pause_project_button.cget("state")) == "normal"
              and not app.pause_project_button.instate(["disabled"]))
        before_pause_host = host_status(config_path)
        if before_pause_host.get("status") not in {"RUNNING", "DEGRADED"}:
            raise AssertionError("Pause Project requires an active worker")
        pause_responses = []
        original_status_command = arm_v2_dashboard._status_command
        def capture_pause_response(config, command, timeout=20.0, project_id=None):
            response = original_status_command(config, command, timeout, project_id)
            if command == "pause" and project_id == "project-b":
                pause_responses.append(response)
            return response
        arm_v2_dashboard._status_command = capture_pause_response
        try:
            pause_invoke_result = app.pause_project_button.invoke()
            pause_invoke_metadata = {"returnType": type(pause_invoke_result).__name__,
                                     "returnRepr": repr(pause_invoke_result)}
            if (app._selected_project() != "project-b" or app.future is None
                    or getattr(app, "_pending_command", None) != "pause"
                    or getattr(app, "_pending_project_id", None) != "project-b"):
                raise AssertionError("Pause Project widget did not queue the selected project control")
            queued_command = app._pending_command
            queued_project_id = app._pending_project_id

            def matching_pause_applied():
                if len(pause_responses) != 1:
                    return False
                code, payload = pause_responses[0]
                request_id = payload.get("requestId")
                if (code != 0 or not isinstance(request_id, str)
                        or payload.get("result") not in {"APPLIED", "PENDING"}):
                    return False
                current = host_status(config_path)
                applied = current.get("lastAppliedControl")
                latest_host = (app.latest or {}).get("host", {})
                latest_applied = latest_host.get("lastAppliedControl")
                return (app.future is None
                        and current.get("pauseControlStatus") == "IDLE"
                        and "project-b" in current.get("pausedProjectIds", [])
                        and isinstance(applied, dict)
                        and applied.get("requestId") == request_id
                        and applied.get("command") == "PAUSE_PROJECT"
                        and applied.get("projectId") == "project-b"
                        and "project-b" in latest_host.get("pausedProjectIds", [])
                        and isinstance(latest_applied, dict)
                        and latest_applied.get("requestId") == request_id
                        and latest_applied.get("command") == "PAUSE_PROJECT"
                        and latest_applied.get("projectId") == "project-b")

            _wait(app, matching_pause_applied, timeout=15)
        finally:
            arm_v2_dashboard._status_command = original_status_command
        pause_code, pause_payload = pause_responses[0]
        pause_request_id = pause_payload["requestId"]
        output["pauseControlCheckpoint"] = {
            "selectedProjectId": "project-b", "buttonActionable": True,
            "widgetInvokeReturn": pause_invoke_metadata,
            "asynchronousCommand": queued_command, "asynchronousProjectId": queued_project_id,
            "requestId": pause_request_id, "responseResult": pause_payload.get("result"),
            "responseCode": pause_code, "workerAppliedRequestId":
                host_status(config_path)["lastAppliedControl"]["requestId"],
            "projectBPausedAtSafeBoundary": True,
        }
        pause_boundary_host = host_status(config_path)
        applied_pause = pause_boundary_host.get("lastAppliedControl")
        paused_checkpoint = _arrival_checkpoint(app, apo_a, apo_b,
                                                allow_pending_ack_after_drop=True)
        if (not paused_checkpoint["ready"] or not isinstance(applied_pause, dict)
                or applied_pause.get("requestId") != pause_request_id
                or applied_pause.get("command") != "PAUSE_PROJECT"
                or applied_pause.get("projectId") != "project-b"
                or "project-b" not in pause_boundary_host.get("pausedProjectIds", [])):
            raise AssertionError("post-pause event/control state was not qualified: " +
                json.dumps({"checkpoint": paused_checkpoint, "pause": applied_pause,
                            "workerCycle": pause_boundary_host.get("cycle")},
                           sort_keys=True, separators=(",", ":")))

        pending_id = EXPECTED_ARRIVAL_EVENT_IDS[PENDING_ARRIVAL]
        paused_b_prompt = next(event for event in paused_checkpoint["arrivalEvents"]
                               if event["eventId"] == pending_id)
        if paused_b_prompt["ledgerStatus"] == "ACKED":
            ack_time = datetime.fromisoformat(paused_b_prompt["receiptReceivedAt"].replace("Z", "+00:00"))
            pause_applied_time = datetime.fromisoformat(applied_pause["appliedAt"].replace("Z", "+00:00"))
            if (paused_b_prompt["attemptCount"] < 2 or not paused_b_prompt["authenticatedAck"]
                    or ack_time > pause_applied_time):
                raise AssertionError("B retry ACK was not authenticated before pause application: " +
                    json.dumps({"event": paused_b_prompt, "pause": applied_pause},
                               sort_keys=True, separators=(",", ":")))
        elif (paused_b_prompt["ledgerStatus"] != "PENDING"
              or paused_b_prompt["attemptCount"] != 1 or paused_b_prompt["receiptPresent"]
              or paused_b_prompt["authenticatedAck"]):
            raise AssertionError("B prompt state changed without an authenticated retry ACK")

        def notification_state(entry):
            receipt = entry.get("receipt")
            return {"eventId": entry.get("eventId"), "projectId": entry.get("projectId"),
                    "status": entry.get("status"), "attemptCount": entry.get("attemptCount"),
                    "nextAttemptAt": entry.get("nextAttemptAt"),
                    "lastErrorClass": entry.get("lastErrorClass"),
                    "updatedAt": entry.get("updatedAt"),
                    "receiptPresent": receipt is not None,
                    "receiptReceivedAt": receipt.get("receivedAt") if receipt else None,
                    "receiptSignature": receipt.get("signature") if receipt else None}

        config_at_pause = load_config(config_path)
        ledger_at_pause = _read_ledger(config_at_pause.ledger_path)
        b_entry_at_pause = ledger_at_pause["entries"][pending_id]
        b_notification_at_pause = notification_state(b_entry_at_pause)
        b_requests_at_pause = paused_checkpoint["receiverCounts"]["project-b"]["requestCount"]
        b_unique_at_pause = paused_checkpoint["receiverCounts"]["project-b"]["uniqueProcessedCount"]
        a_requests_at_pause = paused_checkpoint["receiverCounts"]["project-a"]["requestCount"]
        a_unique_at_pause = paused_checkpoint["receiverCounts"]["project-a"]["uniqueProcessedCount"]
        pause_boundary_cycle = pause_boundary_host["cycle"]
        boundary_cycle_projects = {
            row.get("projectId"): {"status": row.get("status"),
                                   "providerCalls": row.get("providerCalls")}
            for row in (pause_boundary_host.get("recentCycle") or {}).get("projects", [])}
        output["arrivalMatrix"] = {
            "expectedEventIds": [
                {"projectId": key[0], "eventType": key[1], "fileId": key[2], "eventId": event_id}
                for key, event_id in EXPECTED_ARRIVAL_EVENT_IDS.items()],
            "initialPendingCheckpoint": {"event": initial_pending,
                "observedAtMonotonic": initial_checkpoint["observedAtMonotonic"]},
            "checkpoint": "project-b paused at safe worker boundary",
            "arrivalEvents": paused_checkpoint["arrivalEvents"],
            "receiverCounts": paused_checkpoint["receiverCounts"],
            "bPromptTransition": {"eventId": pending_id,
                "statusAtAppliedBoundary": paused_b_prompt["ledgerStatus"],
                "attemptCountAtAppliedBoundary": paused_b_prompt["attemptCount"],
                "receiptPresentAtAppliedBoundary": paused_b_prompt["receiptPresent"],
                "authenticatedAckAtAppliedBoundary": paused_b_prompt["authenticatedAck"],
                "receiptReceivedAt": paused_b_prompt["receiptReceivedAt"],
                "pauseRequestedAt": applied_pause["requestedAt"],
                "pauseAppliedAt": applied_pause["appliedAt"],
                "pauseAppliedCycle": pause_boundary_cycle,
                "providerCallsInCycleApplyingPause": boundary_cycle_projects,
                "retryAckPrecededPauseApplication":
                    paused_b_prompt["ledgerStatus"] == "ACKED"},
            "authenticatedAckEventIds": [event["eventId"] for event in paused_checkpoint["arrivalEvents"]
                                         if event["authenticatedAck"]],
            "projectBPaused": True,
            "projectIsolationVerified": all(event["receiverAccepted"]
                and not event["acceptedByWrongProject"] for event in paused_checkpoint["arrivalEvents"]),
            "tkSnapshotAtCheckpoint": paused_checkpoint["tkSnapshot"],
        }

        # Keep Project B paused while Project A observes and delivers a distinct
        # content update. Every post-boundary cycle must show B was not polled.
        updated_a = snapshots(changed=True)
        item_a = updated_a["folders"]["prompts-a"]["items"][0]
        item_a["md5Checksum"] = "d" * 32
        item_a["version"] = "3"
        _write(worker_fixture, updated_a)
        prior_a_update_id = content_update["eventId"]
        paused_cycles = []
        next_cycle = pause_boundary_cycle + 1
        a_update_ack = None
        deadline = time.monotonic() + 15
        while len(paused_cycles) < 3 or a_update_ack is None:
            app.root.update()
            current_host = host_status(config_path)
            current_cycle = current_host.get("cycle", 0)
            if current_cycle >= next_cycle:
                recent = current_host.get("recentCycle") or {}
                recent_cycle = recent.get("cycle")
                if recent_cycle != next_cycle:
                    raise AssertionError("missed a post-pause worker cycle while measuring project isolation: " +
                        json.dumps({"expectedCycle": next_cycle, "observedCycle": recent_cycle,
                                    "hostCycle": current_cycle}, sort_keys=True,
                                   separators=(",", ":")))
                projects = {row.get("projectId"): row for row in recent.get("projects", [])}
                project_a_cycle = projects.get("project-a", {})
                project_b_cycle = projects.get("project-b", {})
                b_entry_now = _read_ledger(load_config(config_path).ledger_path)["entries"][pending_id]
                if ("project-b" not in current_host.get("pausedProjectIds", [])
                        or current_host.get("lastAppliedControl", {}).get("requestId") != pause_request_id
                        or project_b_cycle.get("status") != "PAUSED_NOT_POLLED"
                        or project_b_cycle.get("providerCalls") != 0
                        or project_a_cycle.get("status") != "OBSERVED"
                        or project_a_cycle.get("providerCalls", 0) <= 0
                        or apo_b.request_count != b_requests_at_pause
                        or apo_b.processed_count != b_unique_at_pause
                        or notification_state(b_entry_now) != b_notification_at_pause):
                    raise AssertionError("paused project isolation changed after applied boundary: " +
                        json.dumps({"cycle": recent_cycle, "projectA": project_a_cycle,
                                    "projectB": project_b_cycle,
                                    "projectBRequests": apo_b.request_count,
                                    "projectBUnique": apo_b.processed_count,
                                    "bNotification": notification_state(b_entry_now)},
                                   sort_keys=True, separators=(",", ":")))
                paused_cycles.append({"cycle": recent_cycle,
                    "projectAProviderCalls": project_a_cycle["providerCalls"],
                    "projectBProviderCalls": project_b_cycle["providerCalls"],
                    "projectBStatus": project_b_cycle["status"],
                    "projectBRequests": apo_b.request_count})
                next_cycle += 1

            detector_now = _validate_detector_state(_read_detector_state(
                load_config(config_path).detector_path))
            ledger_now = _read_ledger(load_config(config_path).ledger_path)
            for event in detector_now["events"]:
                if (event.get("projectId") != "project-a"
                        or event.get("fileId") != "existing-prompts-a"
                        or event.get("changeKind") != "CONTENT_UPDATED"
                        or event.get("eventId") == prior_a_update_id):
                    continue
                entry = ledger_now["entries"].get(event["eventId"])
                if not entry or entry.get("status") != "ACKED" or not entry.get("receipt"):
                    continue
                proof = {"projectId": "project-a", "eventId": event["eventId"]}
                signature = hmac.new(KEYS["test:project-a"], _canonical_json(proof),
                                     hashlib.sha256).hexdigest()
                if (entry["receipt"].get("projectId") == "project-a"
                        and entry["receipt"].get("eventId") == event["eventId"]
                        and hmac.compare_digest(entry["receipt"].get("signature", ""), signature)):
                    a_update_ack = {"eventId": event["eventId"], "status": entry["status"],
                                    "receiptReceivedAt": entry["receipt"]["receivedAt"],
                                    "authenticated": True}
                    break
            if len(paused_cycles) >= 3 and a_update_ack is not None:
                break
            if time.monotonic() >= deadline:
                raise AssertionError("Project A did not progress through three verified Project B paused cycles: " +
                    json.dumps({"boundaryCycle": pause_boundary_cycle,
                                "observedCycles": paused_cycles, "aUpdateAck": a_update_ack},
                               sort_keys=True, separators=(",", ":")))
            time.sleep(0.025)

        if (apo_a.request_count != a_requests_at_pause + 1
                or apo_a.processed_count != a_unique_at_pause + 1
                or apo_b.request_count != b_requests_at_pause
                or apo_b.processed_count != b_unique_at_pause):
            raise AssertionError("receiver activity did not match the paused-project isolation interval")
        output["pauseIsolation"] = {
            "projectBPausedByRequestId": pause_request_id,
            "appliedBoundaryCycle": pause_boundary_cycle,
            "providerCallsInCycleApplyingPause": boundary_cycle_projects,
            "projectBRequestCountAtBoundary": b_requests_at_pause,
            "projectBUniqueCountAtBoundary": b_unique_at_pause,
            "projectBRequestCountAfterInterval": apo_b.request_count,
            "projectBUniqueCountAfterInterval": apo_b.processed_count,
            "projectBNotificationStateUnchanged": b_notification_at_pause["eventId"] == pending_id,
            "projectARequestCountAtBoundary": a_requests_at_pause,
            "projectARequestCountAfterInterval": apo_a.request_count,
            "projectAAuthenticatedContentUpdate": a_update_ack,
            "pausedCycles": paused_cycles,
        }
        b_requests_before_disable = apo_b.request_count

        output["projectEnablement"].append(_toggle(app, "project-b", False, legacy_before))
        doc = ProjectRegistry(registry_path).load()
        assert next(item for item in doc["folderProjects"] if item["projectId"] == "project-b")["enabled"] is False
        assert doc["projects"] == legacy_before
        preserved = _read_ledger(load_config(config_path).ledger_path)["entries"][pending_id]
        assert notification_state(preserved) == b_notification_at_pause
        cycle_after_disable = host_status(config_path).get("cycle", 0)
        _wait(app, lambda: app.future is None
              and app.latest["host"].get("cycle", 0) >= cycle_after_disable + 3, timeout=8)
        disabled_recent = host_status(config_path).get("recentCycle", {})
        disabled_projects = {row.get("projectId"): row for row in disabled_recent.get("projects", [])}
        assert disabled_projects.get("project-b", {}).get("status") == "DISABLED_NOT_POLLED"
        assert disabled_projects.get("project-b", {}).get("providerCalls") == 0
        assert disabled_projects.get("project-a", {}).get("status") == "OBSERVED"
        assert disabled_projects.get("project-a", {}).get("providerCalls", 0) > 0
        assert apo_b.request_count == b_requests_before_disable
        assert apo_b.processed_count == 2
        output["disableIsolation"] = {"projectBStatus": next(item["status"] for item in app.latest["projects"]
                                    if item["projectId"] == "project-b"),
                                    "notificationSameEventId": preserved["eventId"],
                                    "notificationStatusPreserved": preserved["status"],
                                    "projectBRequestsAfterDisable": apo_b.request_count - b_requests_before_disable,
                                    "projectAContinued": True,
                                    "legacyProjectsUnchanged": True}

        app.stop_button.invoke()
        _wait(app, lambda: app.future is None and app.latest is not None
              and app.latest["host"].get("status") == "STOPPED", timeout=15)
        worker_started = False
        registry_with_pending_b = registry_path.read_bytes()
        _remove_confirmed(app, "project-b")
        assert registry_path.read_bytes() == registry_with_pending_b
        assert "refused" in app.notice_text.get().lower()
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

        # Capture the trusted final notification before the independent corruption
        # phase below. The corruption check must never be followed by a trusted
        # read from the deliberately malformed ledger.
        final_b_notification = _read_ledger(load_config(config_path).ledger_path)["entries"].get(pending_id)
        if (not isinstance(final_b_notification, dict)
                or final_b_notification.get("eventId") != pending_id
                or final_b_notification.get("projectId") != "project-b"
                or final_b_notification.get("status") not in {"PENDING", "ACKED"}
                or notification_state(final_b_notification) != b_notification_at_pause):
            raise AssertionError("Project B notification identity/state changed before corruption phase")

        # Corrupt transport state must be visible and disables controls; it cannot start a worker.
        registry_before_corrupt = registry_path.read_bytes()
        app = _new_app(config_path, folder_fixture_path)
        ledger_path.write_text("{broken", encoding="utf-8")
        app._queue_refresh()
        _wait(app, lambda: app.latest is None)
        assert app.latest is None and app.last_error == "LOCAL_STATE_INVALID"
        assert str(app.start_button.cget("state")) == "disabled"
        assert str(app.edit_button.cget("state")) == "normal"
        assert str(app.remove_button.cget("state")) == "normal"
        app.project_table.selection_set("project-b")
        app.root.update()
        app.edit_button.invoke()
        assert not any(child.winfo_class() == "Toplevel"
                       and child.title() == "Edit project display name"
                       for child in app.root.winfo_children())
        original_confirmation = arm_v2_dashboard.messagebox.askyesno
        arm_v2_dashboard.messagebox.askyesno = lambda *args, **kwargs: True
        try:
            app.remove_button.invoke()
        finally:
            arm_v2_dashboard.messagebox.askyesno = original_confirmation
        assert registry_path.read_bytes() == registry_before_corrupt
        app.start_button.invoke()
        assert host_status(config_path)["status"] == "STOPPED"
        assert registry_path.read_bytes() == registry_before_corrupt
        output["corruptState"] = {"visibleFailClosed": True, "workerNotStarted": True,
            "registryUnchanged": True, "editRemoveControlsRemainVisuallyEnabled": True,
            "editRemoveCallbacksRefuseMutation": True}
        app.close()
        app = None
        output["outcome"] = "PASS_VISIBLE_WINDOWS_DASHBOARD_OFFLINE"
        output["projects"] = ["project-a", "project-b"]
        output["projectBNotificationEvent"] = {"eventId": pending_id,
            "finalStatus": final_b_notification["status"],
            "attemptCount": final_b_notification["attemptCount"],
            "receiptPresent": final_b_notification["receipt"] is not None}
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
