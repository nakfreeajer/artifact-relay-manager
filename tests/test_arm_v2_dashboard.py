from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from arm_v2_dashboard import (DashboardApp, DashboardError, _drive_onboarding_transaction,
                              _loopback_endpoint, _status_command, dashboard_snapshot)
import arm_v2_userhost
from arm_v2_userhost import status as host_status
from project_folder_config import FakeDriveProvider
from project_registry import ProjectRegistry, ProjectRegistryError
from tests.test_arm_foreground import KEYS, folder_fixture, snapshots


@unittest.skipUnless(os.name == "nt" and os.environ.get("LOCALAPPDATA"),
                     "dashboard is qualified on an interactive Windows user profile")
class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="arm-m02a-test-", dir=os.environ["LOCALAPPDATA"])
        self.root = Path(self.temp.name)
        self.registry_path = self.root / "projects.json"
        self.detector_path = self.root / "detector.json"
        self.ledger_path = self.root / "ledger.json"
        self.worker_fixture_path = self.root / "worker-fixture.json"
        self.folder_fixture_path = self.root / "folder-fixture.json"
        self.config_path = self.root / "host.json"
        self.worker_fixture_path.write_text(json.dumps(snapshots()), encoding="utf-8")
        self.folder_fixture_path.write_text(json.dumps(folder_fixture()), encoding="utf-8")
        self.registry_path.write_text(json.dumps({"schemaVersion": 2, "projects": [], "folderProjects": []}),
                                      encoding="utf-8")
        self.config_path.write_text(json.dumps({
            "schemaVersion": 1, "registryPath": str(self.registry_path),
            "detectorStatePath": str(self.detector_path), "notificationLedgerPath": str(self.ledger_path),
            "providerFixturePath": str(self.worker_fixture_path),
            "testSecrets": {ref: base64.b64encode(key).decode("ascii") for ref, key in KEYS.items()},
            "intervalSeconds": 1, "stopTimeoutSeconds": 6,
        }), encoding="utf-8")
        self.app = None
        self.tk_root = None

    def tearDown(self):
        if self.app is not None:
            self.app.close()
            self.app = None
        self.temp.cleanup()

    def open_app(self):
        self.tk_root = tk.Tk()
        self.tk_root.withdraw()
        self.app = DashboardApp(self.tk_root, self.config_path, self.folder_fixture_path)
        self.wait_idle()
        return self.app

    def wait_idle(self, timeout=5):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.tk_root.update()
            if self.app is not None and self.app.future is None:
                return
            time.sleep(0.01)
        self.fail("dashboard background operation did not complete")

    def fill_project(self, project_id, root_id, endpoint):
        values = {"displayName": project_id.upper(), "projectId": project_id,
                  "repository": f"owner/{project_id}", "workspace": "",
                  "rootUrl": f"https://drive.google.com/drive/folders/{root_id}",
                  "promptsId": f"prompts-{root_id[-1]}", "reportsId": f"reports-{root_id[-1]}",
                  "endpoint": endpoint, "secretRef": f"test:{project_id}"}
        for key, value in values.items():
            self.app.form[key].set(value)

    def add_through_ui(self, project_id, root_id, endpoint):
        self.fill_project(project_id, root_id, endpoint)
        self.app.add_project()
        self.wait_idle()
        return self.app.latest

    def configure_drive_mode_project(self):
        registry = ProjectRegistry(self.registry_path)
        registry.configure_folder_project(project_id="project-a", display_name="Project A",
            root_url="https://drive.google.com/drive/folders/root-a", prompts_id="prompts-a",
            reports_id="reports-a", endpoint="http://127.0.0.1:49152/notify",
            provider=FakeDriveProvider(folder_fixture()), repository="owner/project-a",
            secret_ref="test:project-a", enabled=True)
        drive_client_path = self.root / "synthetic-client-location.json"
        # The dashboard preflight checks the configured client path only; this file is never read.
        drive_client_path.write_text("{}", encoding="utf-8")
        self.config_path.write_text(json.dumps({
            "schemaVersion": 1, "registryPath": str(self.registry_path),
            "detectorStatePath": str(self.detector_path), "notificationLedgerPath": str(self.ledger_path),
            "providerMode": "drive",
            "testSecrets": {ref: base64.b64encode(key).decode("ascii") for ref, key in KEYS.items()},
            "intervalSeconds": 1, "stopTimeoutSeconds": 6,
        }), encoding="utf-8")
        return drive_client_path

    def test_endpoint_boundary_accepts_loopback_only(self):
        for endpoint in ("http://localhost:8080/notify", "http://127.0.0.1:49152/notify",
                         "http://[::1]:34567/notify"):
            self.assertEqual(_loopback_endpoint(endpoint), endpoint)
        for endpoint in ("https://example.invalid/notify", "http://192.168.1.10:8080/notify",
                         "http://0.0.0.0:8000/notify", "ftp://127.0.0.1:9000/notify",
                         "http://127.0.0.1/notify", "http://user@127.0.0.1:8000/notify"):
            with self.subTest(endpoint=endpoint), self.assertRaises(DashboardError):
                _loopback_endpoint(endpoint)

    def test_v2_enabled_writer_preserves_legacy_and_fails_closed(self):
        registry = ProjectRegistry(self.registry_path)
        # The legacy projects array is a separate M01 contract and is untouched by this v2 writer.
        config = self.root / "legacy-drive.json"
        state = self.root / "legacy-state.json"
        config.write_text(json.dumps({"schemaVersion": 1, "projectId": "legacy-a", "repository": "owner/legacy-a",
            "folderId": "legacy-root", "relayWorkspace": str(self.root / "legacy-workspace"),
            "watcherEndpoint": "http://127.0.0.1:45678/notify", "eventType": "ARTIFACT_CHANGED"}), encoding="utf-8")
        state.write_text("{}", encoding="utf-8")
        registry.add("legacy-a", "Legacy A", config, state)
        legacy_before = registry.load()["projects"]
        registry.configure_folder_project(project_id="project-a", display_name="Project A",
            root_url="https://drive.google.com/drive/folders/root-a", prompts_id="prompts-a",
            reports_id="reports-a", endpoint="http://127.0.0.1:49152/notify",
            provider=FakeDriveProvider(folder_fixture()),
            secret_ref="test:project-a")
        updated = registry.set_folder_project_enabled("project-a", True)
        self.assertEqual(updated["projects"], legacy_before)
        self.assertTrue(updated["folderProjects"][0]["enabled"])
        before_bad = self.registry_path.read_bytes()
        for project_id, enabled in (("missing", True), ("project-a", 1)):
            with self.assertRaises(ProjectRegistryError):
                registry.set_folder_project_enabled(project_id, enabled)
            self.assertEqual(self.registry_path.read_bytes(), before_bad)
        self.registry_path.write_text("{broken", encoding="utf-8")
        with self.assertRaises(ProjectRegistryError):
            registry.set_folder_project_enabled("project-a", False)
        self.assertEqual(self.registry_path.read_text(encoding="utf-8"), "{broken")

    def test_actual_tk_dashboard_add_enable_disable_and_no_implicit_start(self):
        app = self.open_app()
        self.assertEqual(str(app.open_drive_button.cget("state")), "disabled")
        self.assertEqual(host_status(self.config_path)["status"], "STOPPED")
        self.assertEqual(app.latest["projects"], [])
        original = self.registry_path.read_bytes()
        self.fill_project("project-a", "root-a", "http://127.0.0.1:49152/notify")
        app.form["rootUrl"].set("https://drive.google.com/drive/folders/not-a-fixture-root")
        app.add_project()
        self.assertEqual(self.registry_path.read_bytes(), original)
        self.assertIn("rejected", app.notice_text.get().lower())
        self.add_through_ui("project-a", "root-a", "http://127.0.0.1:49152/notify")
        self.add_through_ui("project-b", "root-b", "http://localhost:49153/notify")
        rows = self.app.latest["projects"]
        self.assertEqual([row["projectId"] for row in rows], ["project-a", "project-b"])
        self.assertTrue(all(not row["enabled"] for row in rows))
        self.assertEqual(app.enable_button.cget("text"), "Enable Project")
        self.assertEqual(app.disable_button.cget("text"), "Disable Project")
        self.app.project_table.selection_set("project-a")
        self.tk_root.update()
        registry_before = self.registry_path.read_bytes()
        with patch.object(ProjectRegistry, "dashboard_write", side_effect=ProjectRegistryError("fixture failure")):
            self.app.enable_button.invoke()
        self.assertIn("Project enable rejected", app.notice_text.get())
        self.assertEqual(self.registry_path.read_bytes(), registry_before)
        self.app.enable_button.invoke()
        self.wait_idle()
        self.assertTrue(next(row for row in self.app.latest["projects"] if row["projectId"] == "project-a")["enabled"])
        self.assertIn("Project enabled for monitoring", app.notice_text.get())
        self.app.project_table.selection_set("project-a")
        self.tk_root.update()
        self.app.disable_button.invoke()
        self.wait_idle()
        self.assertFalse(next(row for row in self.app.latest["projects"] if row["projectId"] == "project-a")["enabled"])
        self.assertIn("Project disabled for monitoring", app.notice_text.get())
        registry_before = self.registry_path.read_bytes()
        with patch.object(ProjectRegistry, "dashboard_write", side_effect=ProjectRegistryError("fixture failure")):
            self.app._set_enabled(False)
        self.assertIn("Project disable rejected", app.notice_text.get())
        self.assertEqual(self.registry_path.read_bytes(), registry_before)
        serialized = json.dumps(self.app.latest, sort_keys=True)
        self.assertNotIn("offline-project-a-key", serialized)
        self.assertNotIn("worker-fixture.json", serialized)
        self.assertEqual(host_status(self.config_path)["status"], "STOPPED")

    def test_refresh_keeps_controls_stable_and_reports_queued_control_outcome(self):
        app = self.open_app()
        self.add_through_ui("project-a", "root-a", "http://127.0.0.1:49152/notify")
        app.project_table.selection_set("project-a")
        self.tk_root.update()

        controls = (app.start_button, app.stop_button, app.refresh_button,
                    app.enable_button, app.disable_button, app.pause_all_button,
                    app.resume_all_button, app.pause_project_button,
                    app.resume_project_button, app.edit_button, app.remove_button)
        before = tuple(str(button.cget("state")) for button in controls)
        for _ in range(2):
            app._queue_refresh()
            self.wait_idle()
            self.assertEqual(tuple(str(button.cget("state")) for button in controls), before)
        refresh_started = threading.Event()
        release_refresh = threading.Event()
        actual_snapshot = dashboard_snapshot
        blocked_once = [False]

        def blocked_snapshot(config_path):
            if not blocked_once[0]:
                blocked_once[0] = True
                refresh_started.set()
                if not release_refresh.wait(5):
                    raise RuntimeError("test snapshot gate timed out")
            return actual_snapshot(config_path)

        with patch("arm_v2_dashboard.dashboard_snapshot", side_effect=blocked_snapshot), \
                patch("arm_v2_dashboard._status_command", return_value=(0, {"result": "STARTED", "status": "RUNNING"})) as command:
            app._queue_refresh()
            self.assertTrue(refresh_started.wait(2), "snapshot did not reach the controlled gate")
            during = tuple(str(button.cget("state")) for button in controls)
            self.assertEqual(during, before)

            # Invoke the actual Tk button while a read-only refresh is in flight.
            app.start_button.invoke()
            self.assertIn("queued", app.notice_text.get().lower())
            app.stop_button.invoke()
            self.assertIn("Additional control not queued", app.notice_text.get())
            release_refresh.set()
            self.wait_idle(timeout=8)

        start_calls = [call for call in command.call_args_list if call.args[1] == "start"]
        self.assertEqual(len(start_calls), 1)
        self.assertIn("Monitor started", app.notice_text.get())

    def test_selected_project_survives_three_real_refreshes_and_pause_resume_controls_work(self):
        app = self.open_app()
        registry = ProjectRegistry(self.registry_path)
        provider = FakeDriveProvider(folder_fixture())
        for suffix in ("a", "b"):
            registry.configure_folder_project(project_id=f"project-{suffix}",
                display_name=f"Project {suffix.upper()}",
                root_url=f"https://drive.google.com/drive/folders/root-{suffix}",
                prompts_id=f"prompts-{suffix}", reports_id=f"reports-{suffix}",
                endpoint=f"http://127.0.0.1:{49152 + ord(suffix)}/notify", provider=provider,
                repository=f"owner/project-{suffix}", secret_ref=f"test:project-{suffix}", enabled=True)
        self._queue_snapshot()
        self.wait_idle()
        app.start_button.invoke()
        self.wait_idle(timeout=10)
        self.assertIn(app.latest["host"]["status"], {"RUNNING", "DEGRADED"})
        initial_cycle = app.latest["host"]["cycle"]
        app.project_table.selection_set("project-b")
        deadline = time.monotonic() + 8
        while time.monotonic() < deadline:
            self.tk_root.update()
            if app.future is None and app.latest["host"].get("cycle", 0) >= initial_cycle + 3:
                break
            time.sleep(0.02)
        self.assertGreaterEqual(app.latest["host"].get("cycle", 0), initial_cycle + 3)
        self.assertEqual(app.project_table.selection(), ("project-b",))
        self.assertIn("project-b", app.details.get("1.0", "end"))
        self.assertEqual(str(app.pause_project_button.cget("state")), "normal")
        app.pause_project_button.invoke()
        self.wait_idle(timeout=12)
        self.assertIn("project-b", app.latest["host"]["pausedProjectIds"])
        self.assertEqual(app.project_table.selection(), ("project-b",))
        self.assertIn("Paused: Yes", app.details.get("1.0", "end"))
        app.disable_button.invoke()
        self.wait_idle()
        app.enable_button.invoke()
        self.wait_idle()
        self.assertIn("project-b", app.latest["host"]["pausedProjectIds"],
                      "Start/Stop eligibility must not change Pause/Resume state")
        app.resume_project_button.invoke()
        self.wait_idle(timeout=12)
        self.assertNotIn("project-b", app.latest["host"]["pausedProjectIds"])
        app.stop_button.invoke()
        self.wait_idle(timeout=12)
        self.assertEqual(app.latest["host"]["status"], "STOPPED")

    def test_timed_out_control_notice_reconciles_to_later_worker_acknowledgement(self):
        app = self.open_app()
        request_id = "b" * 32
        app._pending_control_watch = {"requestId": request_id, "command": "pause", "projectId": None}
        app.latest = {"host": {"status": "RUNNING", "cycle": 2, "heartbeatAt": "fixture",
                               "pauseControlStatus": "PENDING", "pendingControl": request_id,
                               "lastAppliedControl": None},
                      "projects": [], "history": [], "pending": 0, "acked": 0}
        app._render()
        self.assertIn("remains pending", app.notice_text.get())
        app.latest["host"].update({"status": "PAUSED", "pauseControlStatus": "IDLE",
                                  "pendingControl": None,
                                  "lastAppliedControl": {"requestId": request_id}})
        app._render()
        self.assertIn("applied after timeout", app.notice_text.get())
        self.assertIsNone(app._pending_control_watch)

    def _queue_snapshot(self):
        self.app._queue_refresh()

    def test_invalid_folder_child_duplicate_and_corrupt_fixture_preserve_registry(self):
        app = self.open_app()
        original = self.registry_path.read_bytes()
        self.fill_project("project-a", "root-a", "http://127.0.0.1:49152/notify")
        self.app.form["reportsId"].set("wrong-child")
        self.app.add_project()
        self.assertEqual(self.registry_path.read_bytes(), original)
        self.assertIn("rejected", self.app.notice_text.get().lower())
        self.add_through_ui("project-a", "root-a", "http://127.0.0.1:49152/notify")
        before = self.registry_path.read_bytes()
        self.add_through_ui("project-a", "root-a", "http://127.0.0.1:49152/notify")
        self.assertEqual(self.registry_path.read_bytes(), before)
        self.fill_project("project-b", "root-b", "http://192.168.1.2:8080/notify")
        self.app.add_project()
        self.assertEqual(self.registry_path.read_bytes(), before)
        self.folder_fixture_path.write_text('{"items":[],"fail":true}', encoding="utf-8")
        self.fill_project("project-b", "root-b", "http://127.0.0.1:49153/notify")
        self.app.add_project()
        self.assertEqual(self.registry_path.read_bytes(), before)

    def test_snapshot_shows_metadata_only_history_and_corrupt_state_fails_closed(self):
        registry = ProjectRegistry(self.registry_path)
        from project_folder_config import FakeDriveProvider
        registry.configure_folder_project(project_id="project-a", display_name="Project A",
            root_url="https://drive.google.com/drive/folders/root-a", prompts_id="prompts-a",
            reports_id="reports-a", endpoint="http://127.0.0.1:49152/notify",
            provider=FakeDriveProvider(folder_fixture()), secret_ref="test:project-a")
        snapshot = dashboard_snapshot(self.config_path)
        serialized = json.dumps(snapshot)
        self.assertIn("architectPromptsFolderId", serialized)
        self.assertNotIn("offline-project-a-key", serialized)
        self.assertNotIn(str(self.root), serialized)
        self.detector_path.write_text("{broken", encoding="utf-8")
        with self.assertRaises(DashboardError):
            dashboard_snapshot(self.config_path)

    def test_automatic_status_snapshot_does_not_spawn_host_cli_process(self):
        registry = ProjectRegistry(self.registry_path)
        registry.configure_folder_project(project_id="project-a", display_name="Project A",
            root_url="https://drive.google.com/drive/folders/root-a", prompts_id="prompts-a",
            reports_id="reports-a", endpoint="http://127.0.0.1:49152/notify",
            provider=FakeDriveProvider(folder_fixture()), secret_ref="test:project-a")

        with patch("arm_v2_dashboard.subprocess.run",
                   side_effect=AssertionError("status refresh must not spawn a process")) as run:
            snapshot = dashboard_snapshot(self.config_path)

        run.assert_not_called()
        self.assertEqual(snapshot["host"]["status"], "STOPPED")
        self.assertEqual(snapshot["projects"][0]["status"], "DISABLED_NOT_POLLED")

    def test_drive_snapshot_is_truthful_and_dashboard_disables_project_mutations(self):
        drive_client_path = self.configure_drive_mode_project()
        event_id = "m03-" + "a" * 64
        detector = {"schemaVersion": 2, "folders": {}, "events": [{
            "projectId": "project-a", "eventId": event_id, "eventType": "PROMPT_CHANGED",
            "changeKind": "ARRIVED", "fileId": "file-a", "detectedAt": "2026-11-06T00:00:00Z",
        }], "eventIdentities": {}, "ambiguous": []}
        ledger = {"schemaVersion": 1, "entries": {event_id: {"status": "PENDING"}}}
        host = {"status": "RUNNING", "cycle": 7, "heartbeatAt": "2026-11-06T00:00:00Z",
                "globalPaused": False, "pausedProjectIds": ["project-a"],
                "recentCycle": {"projects": [{"projectId": "project-a", "status": "OK"}]}}
        with patch.dict(os.environ, {"RELAY_GDRIVE_OAUTH_CLIENT_FILE": str(drive_client_path)}, clear=False), \
                patch("arm_v2_dashboard._state_files", return_value=(detector, ledger)), \
                patch("arm_v2_dashboard.arm_notification.NotificationSender.status",
                      return_value={"pending": 1, "acked": 2, "queued": 3, "total": 6}), \
                patch("arm_v2_dashboard.arm_v2_userhost.status", return_value=host):
            snapshot = dashboard_snapshot(self.config_path)
            app = self.open_app()
            self.assertEqual(snapshot["providerMode"], "drive")
            self.assertEqual(snapshot["host"]["cycle"], 7)
            self.assertEqual(snapshot["projects"][0]["status"], "OK")
            self.assertTrue(snapshot["projects"][0]["paused"])
            self.assertEqual(snapshot["projects"][0]["events"], 1)
            self.assertEqual(snapshot["history"][0]["receiptStatus"], "PENDING")
            self.assertEqual((snapshot["pending"], snapshot["acked"], snapshot["queued"]), (1, 2, 3))
            self.assertIn("Provider mode: Google Drive", app.mode_text.get())
            self.assertIn("Google Drive (read-only)", app.details.get("1.0", "end"))
            self.assertEqual(app.project_table.set("project-a", "status"), "OK")
            self.assertEqual(app.project_table.set("project-a", "paused"), "Yes")
            for button in (app.enable_button, app.disable_button, app.edit_button, app.remove_button,
                           app.add_project_button):
                self.assertEqual(str(button.cget("state")), "disabled")
            self.assertTrue(all(str(entry.cget("state")) == "disabled"
                                for entry in app.project_config_entries))

            before = self.registry_path.read_bytes()
            app.project_table.selection_set("project-a")
            self.tk_root.update()
            app.add_project()
            app._set_enabled(False)
            with patch("arm_v2_dashboard.messagebox.askyesno") as confirm:
                app.edit_selected()
                app.remove_selected()
                confirm.assert_not_called()
            self.assertEqual(self.registry_path.read_bytes(), before)
            self.assertEqual(app.latest["projects"][0]["projectId"], "project-a")

    def test_drive_onboarding_validates_metadata_and_adds_new_project_disabled(self):
        drive_client_path = self.configure_drive_mode_project()
        fake = FakeDriveProvider(folder_fixture())
        with patch.dict(os.environ, {"RELAY_GDRIVE_OAUTH_CLIENT_FILE": str(drive_client_path)}, clear=False), \
                patch("urllib.request.urlopen", side_effect=AssertionError("offline test attempted a network request")):
            app = self.open_app()
            self.assertEqual(str(app.add_project_button.cget("state")), "normal")
            self.assertEqual(str(app._project_entries["rootUrl"].cget("state")), "normal")
            self.assertEqual(str(app._project_entries["promptsId"].cget("state")), "readonly")
            self.assertEqual(str(app._project_entries["reportsId"].cget("state")), "readonly")
            for button in (app.enable_button, app.disable_button, app.edit_button, app.remove_button):
                self.assertEqual(str(button.cget("state")), "disabled")
            self.fill_project("project-c", "root-b", "http://127.0.0.1:49153/notify")
            # Even stale programmatic values cannot override automatic discovery.
            self.app.form["promptsId"].set("stale-prompt-id")
            self.app.form["reportsId"].set("stale-report-id")
            self.app.form["secretRef"].set("test:project-b")
            before = self.registry_path.read_bytes()
            self.app.drive_provider_factory = lambda _registry_path: fake
            self.app.add_project()
            self.wait_idle()

            document = ProjectRegistry(self.registry_path).load()
            project = next(item for item in document["folderProjects"] if item["projectId"] == "project-c")
            self.assertFalse(project["enabled"])
            self.assertEqual(project["architectPromptsFolderId"], "prompts-b")
            self.assertEqual(project["executorReportsFolderId"], "reports-b")
            self.assertIn(b"project-a", before)
            self.assertIn("validated", self.app.notice_text.get().lower())
            self.assertEqual(self.app.form["promptsId"].get(), "prompts-b")
            self.assertEqual(self.app.form["reportsId"].get(), "reports-b")
            self.assertEqual(str(self.app._project_entries["promptsId"].cget("state")), "readonly")
            self.assertEqual(str(self.app.open_drive_button.cget("state")), "normal")
            self.assertEqual(self.app.latest["host"]["status"], "STOPPED")
            self.assertEqual(self.app.latest["projects"][-1]["projectId"], "project-c")
            self.assertEqual(self.app.latest["projects"][-1]["enabled"], False)
            self.assertEqual(host_status(self.config_path)["status"], "STOPPED")

            # Changing the selected root invalidates previously discovered IDs.
            self.app.form["rootUrl"].set("https://drive.google.com/drive/folders/root-a")
            self.assertEqual(self.app.form["promptsId"].get(), "")
            self.assertEqual(self.app.form["reportsId"].get(), "")
            self.assertIn("cleared", self.app.notice_text.get().lower())

    def test_open_google_drive_is_user_initiated_and_described_as_external(self):
        self.configure_drive_mode_project()
        with patch.dict(os.environ, {"RELAY_GDRIVE_OAUTH_CLIENT_FILE": str(
                self.root / "synthetic-client-location.json")}, clear=False):
            app = self.open_app()
            with patch("arm_v2_dashboard.webbrowser.open", return_value=True) as open_url:
                app._open_google_drive()
            open_url.assert_called_once_with("https://drive.google.com/drive/my-drive", new=2)
            self.assertIn("default browser", app.notice_text.get())
            self.assertIn("not an embedded picker", app.notice_text.get())

    def test_drive_onboarding_discovery_rejections_leave_registry_unchanged(self):
        drive_client_path = self.configure_drive_mode_project()
        values = {"displayName": "Project C", "projectId": "project-c", "repository": "owner/project-c",
                  "workspace": "", "rootUrl": "https://drive.google.com/drive/folders/root-b",
                  "endpoint": "http://127.0.0.1:49153/notify", "secretRef": "test:project-b"}
        before = self.registry_path.read_bytes()
        fixtures = []
        missing = folder_fixture()
        missing["items"] = [item for item in missing["items"] if item["id"] != "prompts-b"]
        fixtures.append(("missing", missing))
        duplicate = folder_fixture()
        duplicate["items"].append(dict(next(item for item in duplicate["items"]
                                            if item["id"] == "prompts-b"), id="prompts-b-duplicate"))
        fixtures.append(("duplicate", duplicate))
        wrong_parent = folder_fixture()
        next(item for item in wrong_parent["items"] if item["id"] == "reports-b")["parents"] = ["root-b", "root-a"]
        fixtures.append(("wrong-parent", wrong_parent))
        fixtures.append(("provider-failure", {"items": [], "fail": True}))
        with patch.dict(os.environ, {"RELAY_GDRIVE_OAUTH_CLIENT_FILE": str(drive_client_path)}, clear=False), \
                patch("arm_v2_userhost.status", return_value={"status": "STOPPED"}):
            for name, fixture in fixtures:
                with self.subTest(name=name), self.assertRaises(DashboardError):
                    _drive_onboarding_transaction(self.config_path, values,
                        lambda _path, data=fixture: FakeDriveProvider(data))
                self.assertEqual(self.registry_path.read_bytes(), before)

    def test_drive_onboarding_rejects_duplicate_and_transport_history_without_write(self):
        drive_client_path = self.configure_drive_mode_project()
        values = {"displayName": "Project C", "projectId": "project-c", "repository": "owner/project-c",
                  "workspace": "", "rootUrl": "https://drive.google.com/drive/folders/root-b",
                  "endpoint": "http://127.0.0.1:49153/notify", "secretRef": "test:project-b"}
        before = self.registry_path.read_bytes()
        with patch.dict(os.environ, {"RELAY_GDRIVE_OAUTH_CLIENT_FILE": str(drive_client_path)}, clear=False), \
                patch("arm_v2_userhost.status", return_value={"status": "STOPPED"}):
            with self.assertRaises(DashboardError):
                _drive_onboarding_transaction(self.config_path, values,
                    lambda _path: FakeDriveProvider(folder_fixture()))
            self.assertEqual(self.registry_path.read_bytes(), before)

            duplicate = dict(values, projectId="project-a")
            with self.assertRaises(DashboardError):
                _drive_onboarding_transaction(self.config_path, duplicate,
                    lambda _path: (_ for _ in ()).throw(AssertionError("duplicate must fail before provider access")))
            self.assertEqual(self.registry_path.read_bytes(), before)

            self.detector_path.write_text(json.dumps({"schemaVersion": 2, "folders": {}, "events": [{
                "projectId": "project-a", "eventId": "m03-" + "a" * 64, "eventType": "PROMPT_CHANGED",
                "changeKind": "ARRIVED", "fileId": "existing", "detectedAt": "2026-11-06T00:00:00Z"}],
                "eventIdentities": {}, "ambiguous": []}), encoding="utf-8")
            with self.assertRaises(DashboardError):
                _drive_onboarding_transaction(self.config_path, values,
                    lambda _path: (_ for _ in ()).throw(AssertionError("history must fail before provider access")))
            self.assertEqual(self.registry_path.read_bytes(), before)

    def test_drive_onboarding_refuses_active_userhost_and_concurrent_start_lock(self):
        drive_client_path = self.configure_drive_mode_project()
        values = {"displayName": "Project C", "projectId": "project-c", "repository": "owner/project-c",
                  "workspace": "", "rootUrl": "https://drive.google.com/drive/folders/root-b",
                  "promptsId": "prompts-b", "reportsId": "reports-b",
                  "endpoint": "http://127.0.0.1:49153/notify", "secretRef": "test:project-b"}
        before = self.registry_path.read_bytes()
        with patch.dict(os.environ, {"RELAY_GDRIVE_OAUTH_CLIENT_FILE": str(drive_client_path)}, clear=False), \
                patch("arm_v2_userhost.status", return_value={"status": "RUNNING"}):
            with self.assertRaises(DashboardError):
                _drive_onboarding_transaction(self.config_path, values,
                    lambda _path: (_ for _ in ()).throw(AssertionError("running host must fail before provider access")))
        self.assertEqual(self.registry_path.read_bytes(), before)

        with patch.dict(os.environ, {"RELAY_GDRIVE_OAUTH_CLIENT_FILE": str(drive_client_path)}, clear=False):
            config = arm_v2_userhost.load_config(self.config_path)
        config.control_dir.mkdir(parents=True, exist_ok=True)
        held_start = arm_v2_userhost.SingleInstanceLock(config.start_lock_path)
        self.assertTrue(held_start.acquire())
        try:
            with patch.dict(os.environ, {"RELAY_GDRIVE_OAUTH_CLIENT_FILE": str(drive_client_path)}, clear=False), \
                    patch("arm_v2_userhost.status", return_value={"status": "STOPPED"}):
                with self.assertRaises(DashboardError):
                    _drive_onboarding_transaction(self.config_path, values,
                        lambda _path: (_ for _ in ()).throw(AssertionError("concurrent start must fail before provider access")))
        finally:
            held_start.release()
        self.assertEqual(self.registry_path.read_bytes(), before)

    def test_userhost_controls_preserve_drive_client_path_and_strip_access_token(self):
        drive_client_path = self.configure_drive_mode_project()
        results = [
            (0, {"result": "STARTED", "status": "RUNNING"}),
            (0, {"result": "STOPPED"}),
            (0, {"result": "APPLIED", "command": "PAUSE_GLOBAL"}),
            (0, {"result": "APPLIED", "command": "RESUME_GLOBAL"}),
            (0, {"result": "APPLIED", "command": "PAUSE_PROJECT", "projectId": "project-a"}),
            (0, {"result": "APPLIED", "command": "RESUME_PROJECT", "projectId": "project-a"}),
        ]
        completed = [subprocess.CompletedProcess([], code, json.dumps(payload), "")
                     for code, payload in results]
        commands = (("start", None), ("stop", None), ("pause", None), ("resume", None),
                    ("pause", "project-a"), ("resume", "project-a"))
        with patch.dict(os.environ, {"RELAY_GDRIVE_OAUTH_CLIENT_FILE": str(drive_client_path),
                                     "RELAY_GDRIVE_ACCESS_TOKEN": "synthetic-token-must-not-cross"}, clear=False), \
                patch("arm_v2_dashboard.subprocess.run", side_effect=completed) as run:
            for command, project_id in commands:
                code, payload = _status_command(self.config_path, command, project_id=project_id)
                self.assertEqual(code, 0)
                self.assertIn(payload["result"], {"STARTED", "STOPPED", "APPLIED"})
        self.assertEqual(run.call_count, 6)
        for call, (command, project_id) in zip(run.call_args_list, commands):
            env = call.kwargs["env"]
            self.assertEqual(env["RELAY_GDRIVE_OAUTH_CLIENT_FILE"], str(drive_client_path))
            self.assertNotIn("RELAY_GDRIVE_ACCESS_TOKEN", env)
            argv = call.args[0]
            self.assertIn(command, argv)
            if project_id:
                self.assertEqual(argv[-2:], ["--project-id", project_id])

        # The accepted fixture mode still removes both OAuth environment inputs.
        self.config_path.write_text(json.dumps({
            "schemaVersion": 1, "registryPath": str(self.registry_path),
            "detectorStatePath": str(self.detector_path), "notificationLedgerPath": str(self.ledger_path),
            "providerFixturePath": str(self.worker_fixture_path),
            "testSecrets": {ref: base64.b64encode(key).decode("ascii") for ref, key in KEYS.items()},
            "intervalSeconds": 1, "stopTimeoutSeconds": 6,
        }), encoding="utf-8")
        fixture_result = subprocess.CompletedProcess([], 0, '{"result":"STOPPED"}', "")
        with patch.dict(os.environ, {"RELAY_GDRIVE_OAUTH_CLIENT_FILE": str(drive_client_path),
                                     "RELAY_GDRIVE_ACCESS_TOKEN": "synthetic-token-must-not-cross"}, clear=False), \
                patch("arm_v2_dashboard.subprocess.run", return_value=fixture_result) as fixture_run:
            _status_command(self.config_path, "status")
        fixture_env = fixture_run.call_args.kwargs["env"]
        self.assertNotIn("RELAY_GDRIVE_OAUTH_CLIENT_FILE", fixture_env)
        self.assertNotIn("RELAY_GDRIVE_ACCESS_TOKEN", fixture_env)

    def test_display_name_edit_uses_real_tk_callback_and_preserves_transport_identity(self):
        app = self.open_app()
        self.add_through_ui("project-a", "root-a", "http://127.0.0.1:49152/notify")
        registry = ProjectRegistry(self.registry_path)
        before = registry.show_folder_project("project-a")
        app.project_table.selection_set("project-a")
        self.tk_root.update()
        app.edit_button.invoke()
        dialog = next(child for child in self.tk_root.winfo_children() if isinstance(child, tk.Toplevel))
        def descendants(widget):
            result = []
            for child in widget.winfo_children():
                result.append(child)
                result.extend(descendants(child))
            return result
        widgets = descendants(dialog)
        entries = [child for child in widgets if child.winfo_class() == "TEntry"]
        entry = entries[0]
        entry.delete(0, "end")
        entry.insert(0, "Renamed Project")
        next(child for child in widgets
             if child.winfo_class() == "TButton" and child.cget("text") == "Save").invoke()
        self.wait_idle()
        after = registry.show_folder_project("project-a")
        self.assertEqual(after["displayName"], "Renamed Project")
        for key in before.keys() - {"displayName"}:
            self.assertEqual(after[key], before[key], key)
        self.assertEqual(app.latest["projects"][0]["displayName"], "Renamed Project")

    def test_stale_dashboard_edit_fails_closed_under_shared_write_lock(self):
        app = self.open_app()
        self.add_through_ui("project-a", "root-a", "http://127.0.0.1:49152/notify")
        registry = ProjectRegistry(self.registry_path)
        original = registry.show_folder_project("project-a")["displayName"]
        registry.dashboard_write(lambda: registry.edit_folder_project_display_name(
            "project-a", "Newer Name", expected_display_name=original))
        before = self.registry_path.read_bytes()
        with self.assertRaises(ProjectRegistryError):
            registry.dashboard_write(lambda: registry.edit_folder_project_display_name(
                "project-a", "Stale Name", expected_display_name=original))
        self.assertEqual(self.registry_path.read_bytes(), before)

    def test_guarded_removal_preserves_files_and_refuses_pause_references(self):
        app = self.open_app()
        self.add_through_ui("project-a", "root-a", "http://127.0.0.1:49152/notify")
        self.add_through_ui("project-b", "root-b", "http://127.0.0.1:49153/notify")
        registry = ProjectRegistry(self.registry_path)
        app.project_table.selection_set("project-a")
        self.tk_root.update()
        config_bytes = self.registry_path.read_bytes()
        host = __import__("arm_v2_userhost").load_config(self.config_path)
        ids = [item["projectId"] for item in registry.list_folder_projects()]
        host.pause_store.request("PAUSE_PROJECT", "project-a", ids, "a" * 32)
        paused_bytes = self.registry_path.read_bytes()
        with patch("arm_v2_dashboard.messagebox.askyesno", return_value=True):
            app.remove_button.invoke()
        self.assertEqual(self.registry_path.read_bytes(), paused_bytes)
        self.assertIn("refused", app.notice_text.get().lower())
        self.assertEqual({item["projectId"] for item in registry.list_folder_projects()}, set(ids))
        # A project with no state references can be removed even while another project has a control reference.
        app.project_table.selection_set("project-b")
        self.tk_root.update()
        with patch("arm_v2_dashboard.messagebox.askyesno", return_value=True):
            app.remove_button.invoke()
        self.wait_idle()
        self.assertEqual([item["projectId"] for item in registry.list_folder_projects()], ["project-a"])
        self.assertTrue(self.config_path.exists())
        self.assertTrue(self.folder_fixture_path.exists())
        self.assertNotEqual(self.registry_path.read_bytes(), config_bytes)


if __name__ == "__main__":
    unittest.main()
