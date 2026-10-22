from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import tempfile
import time
import tkinter as tk
import unittest
from unittest.mock import patch

from arm_v2_dashboard import DashboardApp, DashboardError, _loopback_endpoint, dashboard_snapshot
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
        self.app.project_table.selection_set("project-a")
        self.tk_root.update()
        self.app.enable_button.invoke()
        self.wait_idle()
        self.assertTrue(next(row for row in self.app.latest["projects"] if row["projectId"] == "project-a")["enabled"])
        self.app.project_table.selection_set("project-a")
        self.tk_root.update()
        self.app.disable_button.invoke()
        self.wait_idle()
        self.assertFalse(next(row for row in self.app.latest["projects"] if row["projectId"] == "project-a")["enabled"])
        serialized = json.dumps(self.app.latest, sort_keys=True)
        self.assertNotIn("offline-project-a-key", serialized)
        self.assertNotIn("worker-fixture.json", serialized)
        self.assertEqual(host_status(self.config_path)["status"], "STOPPED")

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
