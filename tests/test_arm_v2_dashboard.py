from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import tempfile
import time
import tkinter as tk
import unittest

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
        self.app.enable_button.invoke()
        self.wait_idle()
        self.assertTrue(next(row for row in self.app.latest["projects"] if row["projectId"] == "project-a")["enabled"])
        self.app.project_table.selection_set("project-a")
        self.app.disable_button.invoke()
        self.wait_idle()
        self.assertFalse(next(row for row in self.app.latest["projects"] if row["projectId"] == "project-a")["enabled"])
        serialized = json.dumps(self.app.latest, sort_keys=True)
        self.assertNotIn("offline-project-a-key", serialized)
        self.assertNotIn("worker-fixture.json", serialized)
        self.assertEqual(host_status(self.config_path)["status"], "STOPPED")

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


if __name__ == "__main__":
    unittest.main()
