import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import project_registry
from project_registry import ProjectRegistry, ProjectRegistryError


class ProjectRegistryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.registry_path = self.root / "registry" / "projects.json"
        self.registry = ProjectRegistry(self.registry_path)
        self.project_root = self.root / "project-a"
        self.project_root.mkdir()
        self.config_path = self.project_root / "drive-project.json"
        self.state_path = self.project_root / "state.json"
        self.workspace = self.project_root / "workspace"
        self.config("project-a", "folder-a", self.workspace)
        self.state_path.write_text("state fixture", encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def config(self, project_id, folder_id, workspace, *, repository="owner/repo", endpoint="http://127.0.0.1:49152/"):
        path = self.project_root / (project_id + "-drive.json")
        value = {"schemaVersion": 1, "projectId": project_id, "repository": repository,
                 "folderId": folder_id, "relayWorkspace": str(workspace),
                 "watcherEndpoint": endpoint, "eventType": "ARTIFACT_CHANGED"}
        path.write_text(json.dumps(value), encoding="utf-8")
        if project_id == "project-a":
            self.config_path = path
        return path

    def add_default(self, **kwargs):
        return self.registry.add("project-a", "Project A", self.config_path, self.state_path, **kwargs)

    def cli(self, *args, env=None):
        proc = subprocess.run([sys.executable, "relay_projects.py", "--registry", str(self.registry_path), *map(str, args)],
                              capture_output=True, text=True, env=env, timeout=15)
        return proc

    def test_missing_registry_is_empty_without_creation(self):
        self.assertEqual(self.registry.load(), {"schemaVersion": 1, "projects": []})
        self.assertFalse(self.registry_path.exists())

    def test_add_canonical_metadata_and_deterministic_serialization(self):
        self.add_default()
        first = self.registry_path.read_bytes()
        self.assertTrue(first.endswith(b"\n"))
        document = json.loads(first)
        entry = document["projects"][0]
        self.assertEqual(set(document), {"schemaVersion", "projects"})
        self.assertEqual(set(entry), {"projectId", "displayName", "configPath", "statePath", "enabled"})
        self.assertEqual(entry["configPath"], self.config_path.resolve().as_posix())
        self.assertEqual(entry["statePath"], self.state_path.resolve().as_posix())
        self.assertEqual(self.registry_path.read_bytes(), first)
        for forbidden in (b"client_secret", b"access_token", b"refresh_token", b"authorization_code"):
            self.assertNotIn(forbidden, first)
        self.assertEqual(self.registry.show("project-a"), entry)

    def test_stable_ordering_on_write(self):
        config_b = self.config("project-b", "folder-b", self.root / "workspace-b")
        self.registry.add("project-b", "Project B", config_b, self.root / "state-b.json")
        self.add_default()
        self.assertEqual([entry["projectId"] for entry in self.registry.list()], ["project-a", "project-b"])
        self.assertEqual([entry["projectId"] for entry in json.loads(self.registry_path.read_text(encoding="utf-8"))["projects"]],
                         ["project-a", "project-b"])

    def test_cli_persistence_across_processes_and_metadata_only_output(self):
        add = self.cli("add", "--project-id", "project-a", "--display-name", "Project A",
                       "--config", self.config_path, "--state", self.state_path)
        self.assertEqual(add.returncode, 0, add.stderr)
        listing = self.cli("list")
        showing = self.cli("show", "project-a")
        self.assertEqual(listing.returncode, 0, listing.stderr)
        self.assertEqual(showing.returncode, 0, showing.stderr)
        self.assertEqual(json.loads(listing.stdout)["projects"][0], json.loads(showing.stdout)["project"])
        for output in (add.stdout, listing.stdout, showing.stdout):
            self.assertNotIn("client_secret", output)
            self.assertNotIn("token", output.lower())
            self.assertNotIn("folder-a", output)

    def test_disable_then_enable_revalidates_and_preserves_other_fields(self):
        self.add_default()
        before = dict(self.registry.show("project-a"))
        self.registry.set_enabled("project-a", False)
        disabled = self.registry.show("project-a")
        self.assertFalse(disabled["enabled"])
        self.assertEqual({k: v for k, v in disabled.items() if k != "enabled"},
                         {k: v for k, v in before.items() if k != "enabled"})
        self.registry.set_enabled("project-a", True)
        self.assertTrue(self.registry.show("project-a")["enabled"])
        bytes_before = self.registry_path.read_bytes()
        config_value = json.loads(self.config_path.read_text(encoding="utf-8"))
        config_value["projectId"] = "drifted"
        self.config_path.write_text(json.dumps(config_value), encoding="utf-8")
        with self.assertRaises(ProjectRegistryError):
            self.registry.set_enabled("project-a", False)
        self.assertEqual(self.registry_path.read_bytes(), bytes_before)

    def test_remove_only_removes_entry_and_preserves_referenced_files(self):
        self.add_default()
        self.registry.remove("project-a")
        self.assertEqual(self.registry.list(), [])
        self.assertTrue(self.config_path.is_file())
        self.assertTrue(self.state_path.is_file())
        self.assertTrue(self.workspace.is_dir())
        with self.assertRaises(ProjectRegistryError):
            self.registry.remove("project-a")

    def test_project_id_mismatch_preserves_registry(self):
        self.add_default()
        before = self.registry_path.read_bytes()
        other_config = self.root / "wrong.json"
        value = json.loads(self.config_path.read_text(encoding="utf-8"))
        value["projectId"] = "wrong"
        other_config.write_text(json.dumps(value), encoding="utf-8")
        with self.assertRaises(ProjectRegistryError):
            self.registry.add("project-b", "Project B", other_config, self.root / "other-state.json")
        self.assertEqual(self.registry_path.read_bytes(), before)

    def test_duplicate_project_id_rejected(self):
        self.add_default()
        with self.assertRaises(ProjectRegistryError):
            self.registry.add("project-a", "Again", self.config_path, self.root / "other-state.json")

    def test_duplicate_config_path_alias_rejected(self):
        self.add_default()
        alias = self.project_root / "nested" / ".." / self.config_path.name
        with self.assertRaises(ProjectRegistryError):
            self.registry.add("project-b", "Project B", alias, self.root / "other-state.json")

    def test_duplicate_state_path_alias_rejected(self):
        self.add_default()
        alias = self.project_root / "nested" / ".." / self.state_path.name
        config_b = self.config("project-b", "folder-b", self.root / "workspace-b")
        with self.assertRaises(ProjectRegistryError):
            self.registry.add("project-b", "Project B", config_b, alias)

    def test_duplicate_workspace_rejected(self):
        self.add_default()
        config_b = self.config("project-b", "folder-b", self.workspace)
        with self.assertRaises(ProjectRegistryError):
            self.registry.add("project-b", "Project B", config_b, self.root / "state-b.json")

    def test_duplicate_folder_id_rejected(self):
        self.add_default()
        config_b = self.config("project-b", "folder-a", self.root / "workspace-b")
        with self.assertRaises(ProjectRegistryError):
            self.registry.add("project-b", "Project B", config_b, self.root / "state-b.json")

    def test_same_repository_and_watcher_are_allowed_when_isolation_fields_differ(self):
        self.add_default()
        config_b = self.config("project-b", "folder-b", self.root / "workspace-b")
        self.registry.add("project-b", "Project B", config_b, self.root / "state-b.json")
        self.assertEqual([p["projectId"] for p in self.registry.list()], ["project-a", "project-b"])

    def test_malformed_unknown_wrong_type_duplicate_key_and_duplicate_entry_fail_closed(self):
        corruptions = [
            b"{",
            b'{"schemaVersion":1,"projects":[],"extra":1}',
            b'{"schemaVersion":true,"projects":[]}',
            b'{"schemaVersion":1,"projects":[],"projects":[]}',
        ]
        self.add_default()
        valid_entry = json.loads(self.registry_path.read_text(encoding="utf-8"))["projects"][0]
        corruptions.extend([
            (json.dumps({"schemaVersion": 1, "projects": [{**valid_entry, "extra": 1}]})).encode(),
            (json.dumps({"schemaVersion": 1, "projects": [{**valid_entry, "enabled": 1}]})).encode(),
            (json.dumps({"schemaVersion": 1, "projects": [valid_entry, valid_entry]})).encode(),
        ])
        for raw in corruptions:
            with self.subTest(raw=raw[:40]):
                self.registry_path.write_bytes(raw)
                with self.assertRaises(ProjectRegistryError):
                    self.registry.list()
                self.assertEqual(self.registry_path.read_bytes(), raw)

    def test_missing_or_invalid_referenced_config_fails_closed(self):
        self.add_default()
        raw = json.loads(self.registry_path.read_text(encoding="utf-8"))
        raw["projects"][0]["configPath"] = (self.root / "missing.json").resolve().as_posix()
        self.registry_path.write_text(json.dumps(raw), encoding="utf-8")
        with self.assertRaises(ProjectRegistryError):
            self.registry.validate()

    def test_atomic_replace_failure_preserves_previous_registry(self):
        self.add_default()
        previous = self.registry_path.read_bytes()
        config_b = self.config("project-b", "folder-b", self.root / "workspace-b")
        with patch.object(project_registry.os, "replace", side_effect=OSError("simulated")):
            with self.assertRaises(ProjectRegistryError):
                self.registry.add("project-b", "Project B", config_b, self.root / "state-b.json")
        self.assertEqual(self.registry_path.read_bytes(), previous)
        self.assertEqual(self.registry.list()[0]["projectId"], "project-a")
        self.assertEqual(list(self.registry_path.parent.glob(".projects.json.*")), [])

    def test_operations_make_no_network_or_watcher_calls_and_do_not_touch_session(self):
        session = self.root / "protected-session.bin"
        session.write_bytes(b"sentinel-protected-session")
        with patch("urllib.request.urlopen", side_effect=AssertionError("unexpected network")) as urlopen:
            self.registry.list()
            self.registry.validate()
            self.add_default()
            self.registry.show("project-a")
            self.registry.set_enabled("project-a", False)
            self.registry.set_enabled("project-a", True)
            self.registry.remove("project-a")
        urlopen.assert_not_called()
        self.assertEqual(session.read_bytes(), b"sentinel-protected-session")

    def test_default_location_requires_localappdata(self):
        self.assertEqual(project_registry.default_registry_path({"LOCALAPPDATA": "C:/Users/test/AppData/Local"}),
                         Path("C:/Users/test/AppData/Local/ArtifactRelayManager/projects.json"))
        with self.assertRaises(ProjectRegistryError):
            project_registry.default_registry_path({})

    def test_registry_path_rejects_unc(self):
        with self.assertRaises(ProjectRegistryError):
            ProjectRegistry(r"\\server\share\projects.json")

    def test_cli_add_disabled_then_validate_disable_enable(self):
        add = self.cli("add", "--project-id", "project-a", "--display-name", "Project A",
                       "--config", self.config_path, "--state", self.state_path, "--disabled")
        self.assertEqual(add.returncode, 0, add.stderr)
        validate = self.cli("validate", "project-a")
        self.assertFalse(json.loads(validate.stdout)["projects"][0]["enabled"])
        self.assertEqual(self.cli("disable", "project-a").returncode, 0)
        self.assertEqual(self.cli("enable", "project-a").returncode, 0)
        self.assertTrue(json.loads(self.cli("show", "project-a").stdout)["project"]["enabled"])


if __name__ == "__main__":
    unittest.main()
