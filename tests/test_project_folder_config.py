import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from project_folder_config import FakeDriveProvider, FolderConfigError, build_project, canonical_folder_url
from project_registry import ProjectRegistry, ProjectRegistryError


def fixture(root="root-a", prompts="prompts-a", reports="reports-a", *, project_id="project-a"):
    return {"items": [
        {"id": root, "name": "Project root", "mimeType": "application/vnd.google-apps.folder",
         "parents": [], "trashed": False, "projectId": project_id},
        {"id": prompts, "name": "Architect_Prompts", "mimeType": "application/vnd.google-apps.folder",
         "parents": [root], "trashed": False},
        {"id": reports, "name": "Executor_Reports", "mimeType": "application/vnd.google-apps.folder",
         "parents": [root], "trashed": False},
    ]}


def build(project_id="project-a", provider=None, root_id="root-a", prompts_id=None, reports_id=None,
          root_url=None, endpoint="https://orchestrator.example/v1/notify", **kwargs):
    data = provider or fixture(root_id)
    return build_project(project_id, project_id.upper(), root_url or f"https://drive.google.com/drive/folders/{root_id}",
                         prompts_id, reports_id, endpoint, FakeDriveProvider(data), **kwargs)


class ProjectFolderConfigTests(unittest.TestCase):
    def test_two_project_cli_configuration_view_validation_and_reload(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            registry = root / "projects.json"
            data = {"items": fixture("root-a", "prompts-a", "reports-a")["items"] +
                    fixture("root-b", "prompts-b", "reports-b", project_id="project-b")["items"]}
            provider_path = root / "provider.json"
            provider_path.write_text(json.dumps(data), encoding="utf-8")
            for suffix, project_id, root_id, endpoint in (
                ("a", "project-a", "root-a", "https://apo-a.example/notify"),
                ("b", "project-b", "root-b", "https://apo-b.example/notify"),
            ):
                proc = subprocess.run([sys.executable, "relay_projects.py", "--registry", str(registry),
                    "configure", "--project-id", project_id, "--display-name", f"Project {suffix.upper()}",
                    "--root-url", f"https://drive.google.com/drive/folders/{root_id}",
                    "--orchestrator-endpoint", endpoint, "--provider-fixture", str(provider_path),
                    "--repository", f"owner/repo-{suffix}", "--workspace", str(root / f"workspace-{suffix}")],
                    capture_output=True, text=True, timeout=15)
                self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
                configured = json.loads(proc.stdout)["project"]
                self.assertEqual(configured["driveRootId"], root_id)
                self.assertEqual(configured["orchestratorEndpoint"], endpoint)
                self.assertFalse(configured["enabled"])
            first = subprocess.run([sys.executable, "relay_projects.py", "--registry", str(registry),
                "show", "project-a"], capture_output=True, text=True, timeout=15)
            self.assertEqual(first.returncode, 0, first.stderr)
            entry = json.loads(first.stdout)["project"]
            self.assertEqual(entry["architectPromptsFolderId"], "prompts-a")
            self.assertEqual(entry["executorReportsFolderId"], "reports-a")
            self.assertEqual(entry["architectPromptsFolderUrl"], "https://drive.google.com/drive/folders/prompts-a")
            self.assertEqual(entry["executorReportsFolderUrl"], "https://drive.google.com/drive/folders/reports-a")
            validate = subprocess.run([sys.executable, "relay_projects.py", "--registry", str(registry),
                "validate", "--provider-fixture", str(provider_path)], capture_output=True,
                text=True, timeout=15)
            self.assertEqual(validate.returncode, 0, validate.stderr)
            projects = json.loads(validate.stdout)["folderProjects"]
            self.assertEqual([item["projectId"] for item in projects], ["project-a", "project-b"])
            self.assertEqual([item["driveRootId"] for item in projects], ["root-a", "root-b"])
            self.assertEqual([item["orchestratorEndpoint"] for item in projects],
                             ["https://apo-a.example/notify", "https://apo-b.example/notify"])
            reloaded = ProjectRegistry(registry).load()
            self.assertEqual(reloaded["folderProjects"], projects)

    def test_url_endpoint_and_project_identity_fail_closed(self):
        for url in ("http://drive.google.com/drive/folders/root-a",
                    "https://evil.example/drive/folders/root-a",
                    "https://drive.google.com/drive/folders/root-a?next=evil",
                    "https://drive.google.com.evil.example/drive/folders/root-a"):
            with self.subTest(url=url), self.assertRaises(FolderConfigError):
                build(root_url=url)
        for endpoint in ("ftp://apo.example/", "https://user:pass@apo.example/", "https://apo.example/?token=x",
                         "http://10.0.0.1:8080/"):
            with self.subTest(endpoint=endpoint), self.assertRaises(FolderConfigError):
                build(endpoint=endpoint)
        with self.assertRaises(FolderConfigError):
            build(provider=fixture(project_id="project-b"))

    def test_missing_duplicate_wrong_mime_misparented_and_trashed_children_fail(self):
        base = fixture()
        mutations = []
        mutations.append(base["items"][:2])
        mutations.append(base["items"] + [dict(base["items"][1])])
        wrong_mime = json.loads(json.dumps(base))
        wrong_mime["items"][1]["mimeType"] = "text/plain"
        mutations.append(wrong_mime["items"])
        wrong_parent = json.loads(json.dumps(base))
        wrong_parent["items"][1]["parents"] = ["other-root"]
        mutations.append(wrong_parent["items"])
        trashed = json.loads(json.dumps(base))
        trashed["items"][1]["trashed"] = True
        mutations.append(trashed["items"])
        for items in mutations:
            with self.subTest(items=items), self.assertRaises(FolderConfigError):
                build(provider={"items": items})

    def test_duplicate_root_and_overlap_across_projects_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            registry = ProjectRegistry(Path(temp) / "projects.json")
            a = build()
            registry._write_document({"schemaVersion": 2, "projects": [], "folderProjects": [a]})
            second_provider = FakeDriveProvider(fixture("root-a", "prompts-b", "reports-b", project_id="project-b"))
            with self.assertRaises(ProjectRegistryError):
                registry.configure_folder_project(project_id="project-b", display_name="Project B",
                    root_url="https://drive.google.com/drive/folders/root-a", prompts_id=None,
                    reports_id=None, endpoint="https://apo.example/", provider=second_provider)

    def test_duplicate_workspace_across_folder_projects_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            shared_workspace = str(Path(temp) / "workspace")
            registry = ProjectRegistry(Path(temp) / "projects.json")
            first = build(workspace=shared_workspace)
            registry._write_document({"schemaVersion": 2, "projects": [], "folderProjects": [first]})
            second_fixture = fixture("root-b", "prompts-b", "reports-b", project_id="project-b")
            with self.assertRaises(ProjectRegistryError):
                registry.configure_folder_project(project_id="project-b", display_name="Project B",
                    root_url="https://drive.google.com/drive/folders/root-b", prompts_id=None,
                    reports_id=None, endpoint="https://apo.example/", provider=FakeDriveProvider(second_fixture),
                    workspace=shared_workspace)

    def test_bad_provider_and_tampered_config_fail_closed(self):
        with self.assertRaises(FolderConfigError):
            build(provider={"items": [], "fail": True})
        config = build()
        config["executorReportsFolderId"] = "wrong-id"
        with self.assertRaises(FolderConfigError):
            from project_folder_config import validate_project
            validate_project(config, FakeDriveProvider(fixture()))

    def test_standard_account_scoped_drive_url_is_canonicalized(self):
        self.assertEqual(canonical_folder_url(
            "https://drive.google.com/drive/u/0/folders/root-a?usp=drive_link"),
            ("root-a", "https://drive.google.com/drive/folders/root-a"))

    def test_configuration_and_validation_make_no_http_calls(self):
        with tempfile.TemporaryDirectory() as temp:
            registry = ProjectRegistry(Path(temp) / "projects.json")
            with patch("urllib.request.urlopen", side_effect=AssertionError("network access prohibited")) as open_url:
                registry.configure_folder_project(project_id="project-a", display_name="Project A",
                    root_url="https://drive.google.com/drive/folders/root-a", prompts_id=None,
                    reports_id=None, endpoint="https://apo.example/", provider=FakeDriveProvider(fixture()))
                registry.validate_folder_projects(FakeDriveProvider(fixture()))
            open_url.assert_not_called()

    def test_legacy_registry_loads_without_destructive_migration_and_corruption_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "projects.json"
            legacy = {"schemaVersion": 1, "projects": []}
            path.write_text(json.dumps(legacy), encoding="utf-8")
            before = path.read_bytes()
            self.assertEqual(ProjectRegistry(path).load(), {"schemaVersion": 2, "projects": [], "folderProjects": []})
            self.assertEqual(path.read_bytes(), before)
            path.write_text("{corrupt", encoding="utf-8")
            with self.assertRaises(ProjectRegistryError):
                ProjectRegistry(path).load()

    def test_v1_operational_entry_is_preserved_when_two_folder_config_is_added(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            config_path = root / "legacy-drive.json"
            config_path.write_text(json.dumps({"schemaVersion": 1, "projectId": "legacy-project",
                "repository": "owner/legacy", "folderId": "legacy-root", "relayWorkspace": str(root / "workspace"),
                "watcherEndpoint": "http://127.0.0.1:49152/", "eventType": "ARTIFACT_CHANGED"}), encoding="utf-8")
            entry = {"projectId": "legacy-project", "displayName": "Legacy",
                     "configPath": config_path.resolve().as_posix(),
                     "statePath": (root / "state.json").resolve().as_posix(), "enabled": False}
            path = root / "projects.json"
            path.write_text(json.dumps({"schemaVersion": 1, "projects": [entry]}), encoding="utf-8")
            original = path.read_bytes()
            registry = ProjectRegistry(path)
            self.assertEqual(registry.load()["projects"], [entry])
            self.assertEqual(path.read_bytes(), original)
            registry.configure_folder_project(project_id="project-a", display_name="Project A",
                root_url="https://drive.google.com/drive/folders/root-a", prompts_id=None,
                reports_id=None, endpoint="https://apo.example/",
                provider=FakeDriveProvider(fixture()))
            saved = registry.load()
            self.assertEqual(saved["projects"], [entry])
            self.assertEqual(saved["folderProjects"][0]["projectId"], "project-a")


if __name__ == "__main__":
    unittest.main()
