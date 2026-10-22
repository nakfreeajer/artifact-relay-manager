"""Small offline-only Windows dashboard for the accepted ARM v2 user host."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import sys
import tkinter as tk
from tkinter import messagebox, ttk
from urllib.parse import urlsplit

import arm_notification
import arm_v2_userhost
import drive_change_detector
from project_folder_config import FakeDriveProvider, validate_endpoint
from project_registry import ProjectRegistry, ProjectRegistryError


class DashboardError(ValueError):
    """Sanitized dashboard validation/state failure."""


def _loopback_endpoint(value: str) -> str:
    try:
        normalized = validate_endpoint(value)
        parsed = urlsplit(normalized)
        host = parsed.hostname or ""
        loopback = host.casefold() == "localhost" or ipaddress.ip_address(host).is_loopback
    except (ValueError, TypeError):
        loopback = False
        parsed = None
        normalized = value
    if (not loopback or parsed is None or parsed.scheme != "http" or parsed.port is None
            or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise DashboardError("loopback simulated endpoint required")
    return normalized


def _state_files(config):
    detector = (drive_change_detector._empty_state() if not config.detector_path.exists()
                else drive_change_detector._validate_state(
                    drive_change_detector._json_load(config.detector_path)))
    ledger = arm_notification._read_ledger(config.ledger_path)
    return detector, ledger


def _status_command(config_path: Path, command: str, timeout: float = 20.0, project_id: str | None = None):
    env = dict(os.environ)
    env.pop("RELAY_GDRIVE_ACCESS_TOKEN", None)
    env.pop("RELAY_GDRIVE_OAUTH_CLIENT_FILE", None)
    try:
        args = [sys.executable, str(Path(__file__).with_name("arm_v2_userhost.py")),
                "--config", str(config_path), command]
        if project_id is not None:
            args.extend(["--project-id", project_id])
        result = subprocess.run(args,
                                cwd=Path(__file__).parent, capture_output=True, text=True,
                                timeout=timeout, env=env, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise DashboardError("host control did not complete") from None
    try:
        payload = json.loads(result.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        raise DashboardError("host returned invalid status") from None
    allowed_codes = {"start": {0, 2, 3}, "status": {0, 1, 2}, "stop": {0, 2},
                     "pause": {0, 1, 2}, "resume": {0, 1, 2}}[command]
    if result.returncode not in allowed_codes:
        raise DashboardError("host returned an unexpected result")
    return result.returncode, payload


def dashboard_snapshot(config_path: Path):
    """Read local config, host telemetry and validated metadata without network access."""
    try:
        config = arm_v2_userhost.load_config(config_path)
        registry = ProjectRegistry(config.registry_path).load()
        detector, ledger = _state_files(config)
        sender = arm_notification.NotificationSender(config.registry_path, config.detector_path,
            config.ledger_path, secret_resolver=lambda ref: config.test_secrets[ref])
        counts = sender.status()
        _status_code, host = _status_command(Path(config_path), "status")
    except DashboardError:
        raise
    except Exception:
        raise DashboardError("LOCAL_STATE_INVALID") from None

    cycle = host.get("recentCycle") if isinstance(host.get("recentCycle"), dict) else {}
    observed = {item["projectId"]: item["status"] for item in cycle.get("projects", [])
                if isinstance(item, dict) and isinstance(item.get("projectId"), str)}
    cycle_issue = cycle.get("observationErrorClass") or cycle.get("deliveryErrorClass") or "—"
    project_ids = {item["projectId"] for item in registry["folderProjects"]}
    event_counts = {project_id: 0 for project_id in project_ids}
    history = []
    for event in detector["events"]:
        if event["projectId"] not in project_ids:
            raise DashboardError("LOCAL_STATE_INVALID")
        entry = ledger["entries"].get(event["eventId"])
        receipt_status = entry["status"] if entry else "NOT_QUEUED"
        event_counts[event["projectId"]] += 1
        history.append({"detectedAt": event["detectedAt"], "projectId": event["projectId"],
                        "eventType": event["eventType"], "changeKind": event["changeKind"],
                        "fileId": event["fileId"], "eventId": event["eventId"],
                        "receiptStatus": receipt_status})
    history.sort(key=lambda item: item["detectedAt"], reverse=True)
    projects = []
    for project in registry["folderProjects"]:
        paused = host.get("globalPaused", False) or project["projectId"] in host.get("pausedProjectIds", [])
        projects.append({
            "projectId": project["projectId"], "displayName": project["displayName"],
            "repository": project["repository"], "enabled": project["enabled"], "paused": paused,
            "driveRootId": project["driveRootId"], "driveRootUrl": project["driveRootUrl"],
            "architectPromptsFolderId": project["architectPromptsFolderId"],
            "architectPromptsFolderUrl": project["architectPromptsFolderUrl"],
            "executorReportsFolderId": project["executorReportsFolderId"],
            "executorReportsFolderUrl": project["executorReportsFolderUrl"],
            "endpointConfigured": bool(project["orchestratorEndpoint"]),
            "status": observed.get(project["projectId"],
                "DISABLED_NOT_POLLED" if not project["enabled"] else host.get("status", "UNKNOWN")),
            "lastIssue": cycle_issue if observed.get(project["projectId"]) == "DEGRADED_ATOMIC_SCAN"
                or host.get("status") == "DEGRADED" else "—",
            "events": event_counts[project["projectId"]],
        })
    return {
        "projects": projects, "history": history[:100], "host": host,
        "pending": counts["pending"], "acked": counts["acked"],
        "queued": counts["queued"], "total": counts["total"],
        "hasEventHistory": bool(detector["events"] or ledger["entries"]),
    }


class DashboardApp:
    def __init__(self, root: tk.Tk, config_path: Path, folder_validation_fixture: Path):
        if os.name != "nt":
            raise DashboardError("Windows dashboard requires Windows")
        self.root = root
        self.config_path = Path(config_path)
        self.folder_validation_fixture = Path(folder_validation_fixture)
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="arm-dashboard")
        self.future = None
        self.latest = None
        self.last_error = None
        self._pending_control_watch = None
        self._auto_refresh_id = None
        self.status_text = tk.StringVar(value="Loading offline project status…")
        self.notice_text = tk.StringVar(value="FIXTURE / OFFLINE ONLY — NOT LIVE DRIVE / APO")
        self.pending_text = tk.StringVar(value="Pending: —    Acknowledged: —")
        self.form = {key: tk.StringVar() for key in (
            "displayName", "projectId", "repository", "workspace", "rootUrl",
            "promptsId", "reportsId", "endpoint", "secretRef")}
        self.root.title("Artifact Relay Manager — Offline Dashboard")
        self.root.geometry("1200x820")
        self.root.minsize(950, 640)
        self._build()
        self.root.protocol("WM_DELETE_WINDOW", self.close)
        self._queue_refresh()
        self._auto_refresh_id = self.root.after(1000, self._auto_refresh)

    def _build(self):
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Artifact Relay Manager", font=("Segoe UI", 18, "bold")).pack(anchor="w")
        ttk.Label(outer, textvariable=self.notice_text, foreground="#9a3412",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(2, 8))
        controls = ttk.Frame(outer)
        controls.pack(fill="x", pady=(0, 8))
        self.start_button = ttk.Button(controls, text="Start Monitor", command=lambda: self._queue_control("start"))
        self.start_button.pack(side="left", padx=(0, 6))
        self.stop_button = ttk.Button(controls, text="Stop Monitor", command=lambda: self._queue_control("stop"))
        self.stop_button.pack(side="left", padx=6)
        self.refresh_button = ttk.Button(controls, text="Refresh Status", command=self._queue_refresh)
        self.refresh_button.pack(side="left", padx=6)
        self.pause_all_button = ttk.Button(controls, text="Pause All", command=lambda: self._queue_control("pause"))
        self.pause_all_button.pack(side="left", padx=6)
        self.resume_all_button = ttk.Button(controls, text="Resume All", command=lambda: self._queue_control("resume"))
        self.resume_all_button.pack(side="left", padx=6)
        ttk.Label(controls, textvariable=self.status_text, font=("Segoe UI", 10, "bold")).pack(side="left", padx=14)
        ttk.Label(controls, textvariable=self.pending_text).pack(side="right")

        panes = ttk.Panedwindow(outer, orient="horizontal")
        panes.pack(fill="both", expand=True)
        left = ttk.Frame(panes, padding=(0, 0, 8, 0))
        right = ttk.Frame(panes, padding=(8, 0, 0, 0))
        panes.add(left, weight=3)
        panes.add(right, weight=2)
        ttk.Label(left, text="Projects (v2 folderProjects)", font=("Segoe UI", 11, "bold")).pack(anchor="w")
        columns = ("projectId", "displayName", "repository", "enabled", "paused", "status", "events")
        self.project_table = ttk.Treeview(left, columns=columns, show="headings", height=8, selectmode="browse")
        for column, title, width in (("projectId", "Project ID", 115), ("displayName", "Display name", 130),
                                     ("repository", "Repository", 115), ("enabled", "Enabled", 60),
                                     ("paused", "Paused", 60), ("status", "Recent status", 135),
                                     ("events", "Events", 55)):
            self.project_table.heading(column, text=title)
            self.project_table.column(column, width=width, stretch=column in {"displayName", "repository", "status"})
        self.project_table.pack(fill="x", pady=(4, 6))
        row_controls = ttk.Frame(left)
        row_controls.pack(fill="x")
        self.enable_button = ttk.Button(row_controls, text="Start Project", command=lambda: self._set_enabled(True))
        self.enable_button.pack(side="left", padx=(0, 6))
        self.disable_button = ttk.Button(row_controls, text="Stop Project", command=lambda: self._set_enabled(False))
        self.disable_button.pack(side="left", padx=6)
        self.pause_project_button = ttk.Button(row_controls, text="Pause Selected",
            command=lambda: self._queue_selected_control("pause"))
        self.pause_project_button.pack(side="left", padx=6)
        self.resume_project_button = ttk.Button(row_controls, text="Resume Selected",
            command=lambda: self._queue_selected_control("resume"))
        self.resume_project_button.pack(side="left", padx=6)
        self.edit_button = ttk.Button(row_controls, text="Edit Display Name", command=self.edit_selected)
        self.edit_button.pack(side="left", padx=6)
        self.remove_button = ttk.Button(row_controls, text="Remove Selected", command=self.remove_selected)
        self.remove_button.pack(side="left", padx=6)
        ttk.Label(left, text="Selected project details", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(10, 2))
        self.details = tk.Text(left, height=10, wrap="word", state="disabled", font=("Consolas", 9))
        self.details.pack(fill="x")
        ttk.Label(left, text="Recent transport events and receipt status", font=("Segoe UI", 11, "bold")).pack(anchor="w", pady=(10, 2))
        history_columns = ("detectedAt", "projectId", "eventType", "changeKind", "receiptStatus", "eventId")
        self.history = ttk.Treeview(left, columns=history_columns, show="headings", height=9)
        for column, title, width in (("detectedAt", "Observed", 145), ("projectId", "Project", 100),
                                     ("eventType", "Event", 115), ("changeKind", "Change", 100),
                                     ("receiptStatus", "Receipt", 100), ("eventId", "Event ID", 210)):
            self.history.heading(column, text=title)
            self.history.column(column, width=width, stretch=column == "eventId")
        self.history.pack(fill="both", expand=True)

        add = ttk.LabelFrame(right, text="Add disabled project", padding=10)
        add.pack(fill="x")
        descriptions = (("displayName", "Display name"), ("projectId", "Project ID"),
                        ("repository", "Repository / workspace identity (optional)"),
                        ("workspace", "Local workspace (optional)"), ("rootUrl", "Existing Drive root URL"),
                        ("promptsId", "Architect_Prompts folder ID"), ("reportsId", "Executor_Reports folder ID"),
                        ("endpoint", "Loopback simulated APO endpoint"), ("secretRef", "Test secret reference"))
        for row, (key, label) in enumerate(descriptions):
            ttk.Label(add, text=label).grid(row=row, column=0, sticky="w", pady=2)
            ttk.Entry(add, textvariable=self.form[key], width=38).grid(row=row, column=1, sticky="ew", pady=2)
        ttk.Label(add, text="Folder identity validation fixture loaded" if self.folder_validation_fixture.exists()
                  else "Folder validation fixture unavailable", foreground="#475569").grid(
                      row=len(descriptions), column=0, columnspan=2, sticky="w", pady=(4, 0))
        add.columnconfigure(1, weight=1)
        ttk.Button(add, text="Validate and Add Disabled Project", command=self.add_project).grid(
            row=len(descriptions) + 1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Label(right, textvariable=self.notice_text, wraplength=340, foreground="#475569").pack(
            fill="x", pady=(10, 4))
        ttk.Label(right, text="No Drive or Orchestrator connection is made by Refresh.\n"
                  "Project content and local secret values are never shown.", wraplength=340).pack(anchor="w")
        self.project_table.bind("<<TreeviewSelect>>", self._show_selected)

    def _set_controls_busy(self, busy):
        state = "disabled" if busy else "normal"
        for button in (self.start_button, self.stop_button, self.refresh_button,
                       self.pause_all_button, self.resume_all_button,
                       self.pause_project_button, self.resume_project_button):
            button.configure(state=state)
        for button in (self.enable_button, self.disable_button, self.edit_button, self.remove_button):
            button.configure(state=state)

    def _queue_refresh(self):
        if self.future is not None:
            return
        self._set_controls_busy(True)
        self.future = self.executor.submit(dashboard_snapshot, self.config_path)
        self.root.after(50, self._poll_future)

    def _auto_refresh(self):
        if self.future is None:
            self._queue_refresh()
        try:
            if self.root.winfo_exists():
                self._auto_refresh_id = self.root.after(1000, self._auto_refresh)
        except tk.TclError:
            return

    def _queue_control(self, command, project_id=None):
        if self.future is not None:
            return
        self._set_controls_busy(True)
        self.future = self.executor.submit(_status_command, self.config_path, command,
            max(20, arm_v2_userhost.MAX_STOP_SECONDS + 5), project_id)
        self.last_error = None
        self._pending_command = command
        self._pending_project_id = project_id
        self.root.after(50, self._poll_future)

    def _queue_selected_control(self, command):
        project_id = self._selected_project()
        if not project_id:
            self.notice_text.set("Select a project first.")
            return
        self._queue_control(command, project_id)

    def _poll_future(self):
        future = self.future
        if future is None:
            return
        if not future.done():
            self.root.after(50, self._poll_future)
            return
        self.future = None
        self._set_controls_busy(False)
        try:
            value = future.result()
            if isinstance(value, tuple):
                code, payload = value
                command = getattr(self, "_pending_command", "control")
                project_id = getattr(self, "_pending_project_id", None)
                self.last_error = None
                self.notice_text.set(self._control_message(command, code, payload, project_id))
                if (command in {"pause", "resume"} and payload.get("result") == "PENDING"
                        and payload.get("error") == "CONTROL_TIMEOUT"
                        and isinstance(payload.get("requestId"), str)):
                    self._pending_control_watch = {
                        "requestId": payload["requestId"], "command": command,
                        "projectId": project_id,
                    }
                self._pending_command = None
                self._pending_project_id = None
                self._set_controls_busy(True)
                self.future = self.executor.submit(dashboard_snapshot, self.config_path)
                self.root.after(50, self._poll_future)
                return
            else:
                self.latest = value
                self.last_error = None
        except Exception:
            self.latest = None
            self.last_error = "LOCAL_STATE_INVALID"
            self.notice_text.set("Local configuration or durable state is invalid; no action was taken.")
        self._render()

    @staticmethod
    def _control_message(command, code, payload, project_id=None):
        outcome = payload.get("result", payload.get("status"))
        if command == "start" and code == 3 and outcome == "ALREADY_RUNNING":
            return "Existing monitor attached; no second worker started."
        if command == "start" and code == 0 and outcome == "STARTED":
            if payload.get("status") == "PAUSED":
                return "Monitor started and remains PAUSED until explicit Resume."
            return "Monitor started by the accepted M05 host."
        if command == "stop" and code == 0 and outcome == "STOPPED":
            return "Monitor stopped cleanly; local event state remains durable."
        if command in {"pause", "resume"} and code == 0 and outcome == "APPLIED":
            scope = f"project {project_id}" if project_id else "all projects"
            return f"{scope} {command} applied at a safe monitor boundary."
        if command in {"pause", "resume"} and outcome == "PENDING":
            if payload.get("error") == "CONTROL_TIMEOUT":
                return "Control is still pending at a safe boundary; status refresh will track its outcome."
            return "Another pause control remains pending; no new control was confirmed."
        if command in {"pause", "resume"} and outcome == "INVALID_OWNER":
            return "Pause control rejected because the active worker owner could not be verified."
        if command == "status" and code == 1 and outcome == "STARTING":
            return "Monitor is starting."
        if code == 0 and outcome in {"RUNNING", "STOPPED"}:
            return f"Host status refreshed: {outcome}."
        return "Host control is degraded; inspect the sanitized local status."

    def _render(self):
        if self.latest is None:
            self.status_text.set("ERROR — local state invalid")
            self.pending_text.set("Pending: —    Acknowledged: —")
            self.enable_button.configure(state="disabled")
            self.disable_button.configure(state="disabled")
            self.start_button.configure(state="disabled")
            self.stop_button.configure(state="disabled")
            self.pause_all_button.configure(state="disabled")
            self.resume_all_button.configure(state="disabled")
            self.pause_project_button.configure(state="disabled")
            self.resume_project_button.configure(state="disabled")
            return
        host = self.latest["host"]
        watch = self._pending_control_watch
        if watch:
            applied = host.get("lastAppliedControl")
            if isinstance(applied, dict) and applied.get("requestId") == watch["requestId"]:
                scope = f"project {watch['projectId']}" if watch["projectId"] else "all projects"
                self.notice_text.set(f"{scope} {watch['command']} applied after timeout at a safe monitor boundary.")
                self._pending_control_watch = None
            elif (host.get("pendingControl") == watch["requestId"]
                    or host.get("pauseControlStatus") == "APPLYING"):
                self.notice_text.set("Control remains pending at a safe monitor boundary; status refresh is tracking it.")
            elif host.get("pauseControlStatus") == "PENDING":
                self.notice_text.set("A pause control remains pending; refreshed status cannot confirm this request yet.")
            else:
                self.notice_text.set("Control status refreshed, but this request's final outcome is unavailable.")
                self._pending_control_watch = None
        self.status_text.set(f"Monitor: {host.get('status', 'UNKNOWN')}  |  Cycle: {host.get('cycle', 0)}"
                             f"  |  Heartbeat: {host.get('heartbeatAt', '—')}")
        self.pending_text.set(f"Pending: {self.latest['pending']}    Acknowledged: {self.latest['acked']}")
        current = {row["projectId"]: row for row in self.latest["projects"]}
        selected_project_id = self._selected_project()
        try:
            scroll_position = self.project_table.yview()[0]
        except tk.TclError:
            scroll_position = 0.0
        existing = set(self.project_table.get_children())
        for row_id in existing - set(current):
            self.project_table.delete(row_id)
        for index, project in enumerate(self.latest["projects"]):
            values = (project["projectId"], project["displayName"], project["repository"] or "—",
                      "Yes" if project["enabled"] else "No", "Yes" if project["paused"] else "No",
                      project["status"], project["events"])
            if project["projectId"] in existing:
                self.project_table.item(project["projectId"], values=values)
            else:
                self.project_table.insert("", "end", iid=project["projectId"], values=values)
            self.project_table.move(project["projectId"], "", index)
        for row_id in self.history.get_children():
            self.history.delete(row_id)
        for index, event in enumerate(self.latest["history"]):
            self.history.insert("", "end", iid=f"event-{index}", values=(
                event["detectedAt"], event["projectId"], event["eventType"], event["changeKind"],
                event["receiptStatus"], event["eventId"]))
        if selected_project_id in current:
            self.project_table.selection_set(selected_project_id)
            self.project_table.focus(selected_project_id)
        try:
            self.project_table.yview_moveto(scroll_position)
        except tk.TclError:
            pass
        if selected_project_id in current:
            self._write_details(current[selected_project_id])
        elif current:
            self._write_details(next(iter(current.values())))
        self._update_project_controls()
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="normal")
        active = host.get("status") in {"RUNNING", "PAUSED", "DEGRADED"}
        self.pause_all_button.configure(state="normal" if active else "disabled")
        self.resume_all_button.configure(state="normal" if active else "disabled")
        selected_active = selected_project_id in current and active
        self.pause_project_button.configure(state="normal" if selected_active else "disabled")
        self.resume_project_button.configure(state="normal" if selected_active else "disabled")

    def _write_details(self, project):
        text = (f"Project: {project['displayName']} ({project['projectId']})\n"
                f"Repository: {project['repository'] or '—'}\n"
                f"Enabled: {'Yes' if project['enabled'] else 'No'}\n"
                f"Paused: {'Yes' if project['paused'] else 'No'}\n"
                f"Recent status: {project['status']}\n"
                f"Latest issue class: {project['lastIssue']}\n"
                f"Drive root: {project['driveRootId']}\n  {project['driveRootUrl']}\n"
                f"Architect_Prompts: {project['architectPromptsFolderId']}\n  {project['architectPromptsFolderUrl']}\n"
                f"Executor_Reports: {project['executorReportsFolderId']}\n  {project['executorReportsFolderUrl']}\n"
                f"Orchestrator endpoint: {'loopback simulated endpoint configured' if project['endpointConfigured'] else 'not configured'}\n")
        self.details.configure(state="normal")
        self.details.delete("1.0", "end")
        self.details.insert("1.0", text)
        self.details.configure(state="disabled")

    def _show_selected(self, _event=None):
        self._update_project_controls()
        if not self.latest:
            return
        selected = self.project_table.selection()
        if not selected:
            return
        project = next((item for item in self.latest["projects"] if item["projectId"] == selected[0]), None)
        if project:
            self._write_details(project)

    def _update_project_controls(self):
        selected = self._selected_project()
        project = next((item for item in (self.latest or {}).get("projects", [])
                        if item["projectId"] == selected), None)
        self.enable_button.configure(state="normal" if project and not project["enabled"] else "disabled")
        self.disable_button.configure(state="normal" if project and project["enabled"] else "disabled")
        self.edit_button.configure(state="normal" if project else "disabled")
        self.remove_button.configure(state="normal" if project else "disabled")

    def _selected_project(self):
        selected = self.project_table.selection()
        return selected[0] if selected else None

    def _configuration_gate(self):
        if self.latest is None:
            raise DashboardError("LOCAL_STATE_INVALID")
        config = arm_v2_userhost.load_config(self.config_path)
        host = arm_v2_userhost.status(self.config_path)
        if host.get("status") != "STOPPED":
            raise DashboardError("stop the monitor before changing project identity")
        detector, ledger = _state_files(config)
        if detector["events"] or ledger["entries"]:
            raise DashboardError("project identity changes are blocked after event history exists")
        return config

    def add_project(self):
        try:
            registry = ProjectRegistry(arm_v2_userhost.load_config(self.config_path).registry_path)
            def save():
                config = self._configuration_gate()
                if not self.folder_validation_fixture.is_file():
                    raise DashboardError("folder validation fixture is unavailable")
                provider = FakeDriveProvider.from_path(self.folder_validation_fixture)
                endpoint = _loopback_endpoint(self.form["endpoint"].get().strip())
                secret_ref = self.form["secretRef"].get().strip()
                if secret_ref not in config.test_secrets:
                    raise DashboardError("configured test secret reference is unavailable")
                registry.configure_folder_project(
                    project_id=self.form["projectId"].get().strip(),
                    display_name=self.form["displayName"].get().strip(),
                    root_url=self.form["rootUrl"].get().strip(),
                    prompts_id=self.form["promptsId"].get().strip(),
                    reports_id=self.form["reportsId"].get().strip(), endpoint=endpoint,
                    provider=provider, repository=self.form["repository"].get().strip() or None,
                    workspace=self.form["workspace"].get().strip() or None,
                    secret_ref=secret_ref, enabled=False)
            registry.dashboard_write(save)
            self.notice_text.set("Project validated offline and saved DISABLED.")
            self._queue_refresh()
        except Exception:
            self.notice_text.set("Project rejected; registry was not changed. Check sanitized folder and endpoint fields.")

    def _set_enabled(self, enabled):
        project_id = self._selected_project()
        if not project_id:
            self.notice_text.set("Select a project first.")
            return
        try:
            registry = ProjectRegistry(arm_v2_userhost.load_config(self.config_path).registry_path)
            def change():
                if self.latest is None:
                    raise DashboardError("LOCAL_STATE_INVALID")
                config = arm_v2_userhost.load_config(self.config_path)
                _state_files(config)
                provider = FakeDriveProvider.from_path(self.folder_validation_fixture)
                registry.validate_folder_projects(provider, project_id)
                registry.set_folder_project_enabled(project_id, enabled)
            registry.dashboard_write(change)
            self.notice_text.set("Project started; monitoring eligibility enabled." if enabled
                                 else "Project stopped at the next monitor boundary; durable events were preserved.")
            self._queue_refresh()
        except Exception:
            self.notice_text.set("Project Start/Stop rejected; local state or folder validation failed closed.")

    def edit_selected(self):
        project_id = self._selected_project()
        project = next((row for row in (self.latest or {}).get("projects", [])
                        if row["projectId"] == project_id), None)
        if project is None:
            self.notice_text.set("Select a project first.")
            return
        dialog = tk.Toplevel(self.root)
        dialog.title("Edit project display name")
        dialog.transient(self.root)
        dialog.grab_set()
        value = tk.StringVar(value=project["displayName"])
        ttk.Label(dialog, text="Display name").pack(anchor="w", padx=12, pady=(12, 2))
        entry = ttk.Entry(dialog, textvariable=value, width=42)
        entry.pack(fill="x", padx=12)
        entry.focus_set()
        def save():
            try:
                registry = ProjectRegistry(arm_v2_userhost.load_config(self.config_path).registry_path)
                registry.dashboard_write(lambda: registry.edit_folder_project_display_name(
                    project_id, value.get(), expected_display_name=project["displayName"]))
                self.notice_text.set("Display name saved; identity and transport state were preserved.")
                dialog.destroy()
                self._queue_refresh()
            except Exception:
                self.notice_text.set("Edit refused; project changed or local state is invalid. Refresh and retry.")
                dialog.destroy()
        buttons = ttk.Frame(dialog)
        buttons.pack(fill="x", padx=12, pady=12)
        ttk.Button(buttons, text="Save", command=save).pack(side="right")
        ttk.Button(buttons, text="Cancel", command=dialog.destroy).pack(side="right", padx=6)

    def remove_selected(self):
        project_id = self._selected_project()
        if not project_id:
            self.notice_text.set("Select a project first.")
            return
        if not messagebox.askyesno("Remove project", "Remove this unused project configuration? No files will be deleted.", parent=self.root):
            return
        try:
            registry = ProjectRegistry(arm_v2_userhost.load_config(self.config_path).registry_path)
            def remove_if_unused():
                config = arm_v2_userhost.load_config(self.config_path)
                if arm_v2_userhost.status(self.config_path).get("status") != "STOPPED":
                    raise DashboardError("monitor must be stopped")
                document = registry.load()
                project = next((item for item in document["folderProjects"]
                                if item["projectId"] == project_id), None)
                if project is None or project["enabled"]:
                    raise DashboardError("project is not removable")
                detector, ledger = _state_files(config)
                has_detector_state = (any(event["projectId"] == project_id for event in detector["events"])
                    or any(folder["projectId"] == project_id for folder in detector["folders"].values())
                    or any(item["projectId"] == project_id for item in detector["ambiguous"]))
                if has_detector_state:
                    raise DashboardError("project has detector history")
                if any(entry["projectId"] == project_id for entry in ledger["entries"].values()):
                    raise DashboardError("project has notification history")
                ids = [item["projectId"] for item in document["folderProjects"]]
                pause = config.pause_store.load(ids)
                refs = (pause.get("pendingRequest"), pause.get("lastAppliedRequest"))
                if (project_id in pause["pausedProjectIds"] or any(
                        isinstance(ref, dict) and ref.get("projectId") == project_id for ref in refs)):
                    raise DashboardError("project has pause-control history")
                registry.remove_folder_project(project_id)
            registry.dashboard_write(remove_if_unused)
            self.notice_text.set("Unused project removed. No project or state files were deleted.")
            self._queue_refresh()
        except Exception:
            self.notice_text.set("Removal refused: worker, history, control state, or project validation gate failed.")

    def close(self):
        # Closing the dashboard intentionally leaves the independent M05 worker alone.
        if self._auto_refresh_id is not None:
            try:
                self.root.after_cancel(self._auto_refresh_id)
            except tk.TclError:
                pass
            self._auto_refresh_id = None
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True,
                        help="existing M05 offline host configuration")
    parser.add_argument("--folder-validation-fixture", type=Path, required=True,
                        help="local M01 FakeDriveProvider folder identity fixture")
    args = parser.parse_args(argv)
    if os.name != "nt":
        print("Windows dashboard requires Windows", file=sys.stderr)
        return 2
    try:
        root = tk.Tk()
        DashboardApp(root, args.config, args.folder_validation_fixture)
        root.mainloop()
        return 0
    except (DashboardError, ProjectRegistryError, OSError, tk.TclError):
        print("Dashboard could not open valid local offline configuration", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
