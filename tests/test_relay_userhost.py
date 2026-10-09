from __future__ import annotations

import json
import io
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

import project_registry
import relay_userhost


REPO_ROOT = Path(__file__).resolve().parents[1]


class RelayUserHostTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.project_root = self.root / "project"
        self.project_root.mkdir()
        self.workspace = self.project_root / "workspace"
        self.workspace.mkdir()
        self.project_config = self.project_root / "drive-project.json"
        self.project_config.write_text(json.dumps({
            "schemaVersion": 1,
            "projectId": "userhost-test",
            "repository": "owner/repo",
            "folderId": "userhost-folder",
            "relayWorkspace": str(self.workspace),
            "watcherEndpoint": "http://127.0.0.1:49999/",
            "eventType": "ARTIFACT_CHANGED",
        }), encoding="utf-8")
        self.registry_path = self.root / "registry" / "projects.json"
        self.registry = project_registry.ProjectRegistry(self.registry_path)
        self.registry.add("userhost-test", "Userhost Test", self.project_config,
                          self.project_root / "relay-state.json", enabled=False)
        self.oauth_file = self.root / "oauth-client-fixture.json"
        self.oauth_file.write_text('{"fixtureOnly":true}', encoding="utf-8")
        self.log_path = self.root / "logs" / "userhost.jsonl"
        self.log_path.parent.mkdir()
        self.config_path = self.root / "userhost.json"
        self.config = {
            "schemaVersion": 1,
            "pythonExecutable": str(Path(sys.executable).resolve()),
            "supervisorScript": str((REPO_ROOT / "relay_supervisor.py").resolve()),
            "workingDirectory": str(REPO_ROOT.resolve()),
            "registryPath": str(self.registry_path.resolve()),
            "oauthClientFile": str(self.oauth_file.resolve()),
            "logPath": str(self.log_path),
            "lockPath": str(self.root / "userhost.lock"),
            "workerLockPath": str(self.root / "userhost-worker.lock"),
            "stopPath": str(self.root / "userhost.stop"),
            "intervalSeconds": 1,
            "maxCycles": None,
            "stopTimeoutSeconds": 5,
            "logMaxBytes": 1024,
            "logBackups": 2,
        }
        self.write_config()

    def tearDown(self):
        self.temp.cleanup()

    def write_config(self):
        self.config_path.write_text(json.dumps(self.config), encoding="utf-8")

    def cli(self, *args, timeout=15, env=None):
        return subprocess.run(
            [sys.executable, str(REPO_ROOT / "relay_userhost.py"), "--config",
             str(self.config_path.resolve()), *map(str, args)],
            cwd=REPO_ROOT, capture_output=True, text=True, timeout=timeout, env=env,
        )

    def _wait_for_log(self, text, timeout=8):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.log_path.exists() and text in self.log_path.read_text(encoding="utf-8"):
                return
            time.sleep(0.05)
        self.fail(f"timed out waiting for {text}")

    def test_child_environment_overrides_only_child_mapping(self):
        parent = {"RELAY_GDRIVE_OAUTH_CLIENT_FILE": "parent-value",
                  "RELAY_GDRIVE_ACCESS_TOKEN": "parent-token-sentinel", "OTHER": "same"}
        child = relay_userhost.build_child_environment(parent, self.oauth_file)
        self.assertEqual(parent["RELAY_GDRIVE_OAUTH_CLIENT_FILE"], "parent-value")
        self.assertEqual(parent["OTHER"], "same")
        self.assertEqual(child["RELAY_GDRIVE_OAUTH_CLIENT_FILE"], str(self.oauth_file))
        self.assertNotIn("RELAY_GDRIVE_ACCESS_TOKEN", child)
        self.assertEqual(child["PYTHONUNBUFFERED"], "1")

    def test_relative_and_missing_paths_fail_closed(self):
        self.config["pythonExecutable"] = "python.exe"
        self.write_config()
        with self.assertRaisesRegex(relay_userhost.UserHostError, "absolute"):
            relay_userhost.load_config(self.config_path)
        self.config["pythonExecutable"] = str(self.root / "missing-python.exe")
        self.write_config()
        with self.assertRaisesRegex(relay_userhost.UserHostError, "unavailable"):
            relay_userhost.load_config(self.config_path)

    def test_missing_oauth_file_and_invalid_registry_fail_closed(self):
        self.config["oauthClientFile"] = str(self.root / "missing-oauth.json")
        self.write_config()
        with self.assertRaisesRegex(relay_userhost.UserHostError, "OAuth client file is unavailable"):
            relay_userhost.load_config(self.config_path)
        self.config["oauthClientFile"] = str(self.oauth_file)
        self.registry_path.write_text("{broken", encoding="utf-8")
        with self.assertRaisesRegex(relay_userhost.UserHostError, "project registry is invalid"):
            self.write_config()
            relay_userhost.load_config(self.config_path)

    def test_duplicate_and_malformed_launcher_config_fail_closed(self):
        self.config_path.write_text('{"schemaVersion":1,"schemaVersion":1}', encoding="utf-8")
        with self.assertRaisesRegex(relay_userhost.UserHostError, "invalid"):
            relay_userhost.load_config(self.config_path)

    def test_log_path_cannot_alias_relay_state(self):
        state_path = Path(self.registry.show("userhost-test")["statePath"])
        self.config["logPath"] = str(state_path)
        self.write_config()
        with self.assertRaisesRegex(relay_userhost.UserHostError, "conflict with runtime files"):
            relay_userhost.load_config(self.config_path)

    def test_supervisor_output_is_metadata_allowlist_only(self):
        body = "private artifact body must not reach logs"
        raw = json.dumps({
            "cycle": 1, "result": "OK", "enabledProjects": 1,
            "projects": [{"projectId": "userhost-test", "result": "OK", "delivered": 1}],
            "artifactBody": body, "token": "secret", "error": body,
        }).encode("utf-8")
        record = relay_userhost.sanitize_supervisor_line(raw)
        rendered = json.dumps(record)
        self.assertIn("userhost-test", rendered)
        self.assertNotIn(body, rendered)
        self.assertNotIn("secret", rendered)
        self.assertNotIn("artifactBody", rendered)
        self.assertEqual(record["error"], "CHILD_ERROR")

    def test_log_rotation_is_bounded(self):
        emitted = []
        log = relay_userhost.BoundedJsonlLog(self.log_path, 1024, 2, emitted.append)
        for cycle in range(30):
            log.write({"component": "launcher", "result": "CYCLE", "cycle": cycle})
        files = [self.log_path, self.log_path.with_name(self.log_path.name + ".1"),
                 self.log_path.with_name(self.log_path.name + ".2")]
        self.assertLessEqual(sum(p.stat().st_size for p in files if p.exists()), 3 * 1024)
        self.assertTrue(any(p.exists() for p in files[1:]))
        self.assertEqual(len(emitted), 30)

    def test_child_nonzero_exit_status_is_not_reported_as_success(self):
        class FinishedChild:
            def __init__(self):
                self.stdout = io.BytesIO(b'{"cycle":1,"result":"OK"}\n')
                self.stderr = io.BytesIO()
                self.returncode = None

            def poll(self):
                return self.returncode

            def wait(self, timeout=None):
                self.returncode = 17
                return self.returncode

            def terminate(self):
                self.returncode = 2

            def kill(self):
                self.returncode = 2

        child = FinishedChild()
        emitted = []
        with patch("relay_userhost.subprocess.Popen", return_value=child):
            result = relay_userhost.start(self.config_path, emit=emitted.append)
        self.assertEqual(result, 17)
        self.assertTrue(any(r.get("result") == "CHILD_FAILED" and r.get("exitCode") == 17
                            for r in emitted))
        self.assertFalse(any(r.get("result") == "EXITED" for r in emitted))

    def test_dry_run_runs_two_bounded_supervisor_cycles_without_enabling_project(self):
        result = self.cli("start", "--dry-run", "--max-cycles", "2")
        self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
        records = [json.loads(line) for line in self.log_path.read_text(encoding="utf-8").splitlines()]
        cycles = [r for r in records if r.get("component") == "supervisor" and r.get("cycle")]
        self.assertEqual([r["cycle"] for r in cycles], [1, 2])
        self.assertTrue(all(r["result"] == "IDLE" for r in cycles))
        self.assertEqual(self.registry.load()["projects"][0]["enabled"], False)

    def test_dry_run_refuses_enabled_projects_without_starting_child(self):
        self.registry.set_enabled("userhost-test", True)
        result = self.cli("start", "--dry-run", "--max-cycles", "2")
        self.assertEqual(result.returncode, 2)
        self.assertIn("dry-run requires every configured project to be disabled", result.stdout)
        self.assertFalse(self.log_path.exists())

    def test_second_instance_is_refused_and_stop_exits_cleanly(self):
        first = subprocess.Popen(
            [sys.executable, str(REPO_ROOT / "relay_userhost.py"), "--config",
             str(self.config_path.resolve()), "start"],
            cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            self._wait_for_log('"result":"STARTING"')
            self._wait_for_log('"result":"IDLE"')
            second = self.cli("start")
            self.assertEqual(second.returncode, 3, second.stdout + second.stderr)
            self.assertIn("ALREADY_RUNNING", second.stdout)
            self.registry_path.write_text("{corrupt", encoding="utf-8")
            stopped = self.cli("stop", timeout=10)
            self.assertEqual(stopped.returncode, 0, stopped.stdout + stopped.stderr)
            self.assertIn("STOPPED", stopped.stdout)
            self.assertEqual(first.wait(timeout=10), 0)
            first.communicate(timeout=2)
        finally:
            if first.poll() is None:
                self.cli("stop", timeout=10)
                first.wait(timeout=10)
            first.communicate(timeout=2)

    def test_worker_exits_after_launcher_process_crashes(self):
        first = subprocess.Popen(
            [sys.executable, str(REPO_ROOT / "relay_userhost.py"), "--config",
             str(self.config_path.resolve()), "start"],
            cwd=REPO_ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        try:
            self._wait_for_log('"result":"IDLE"')
            first.kill()
            first.wait(timeout=5)
            first.communicate(timeout=2)
            deadline = time.monotonic() + 6
            worker_stopped = False
            while time.monotonic() < deadline:
                lock = relay_userhost.SingleInstanceLock(Path(self.config["workerLockPath"]))
                if lock.acquire():
                    lock.release()
                    worker_stopped = True
                    break
                time.sleep(0.1)
            self.assertTrue(worker_stopped, "orphaned worker retained its one-instance lock")
        finally:
            if first.poll() is None:
                first.kill()
                first.wait(timeout=5)
            first.communicate(timeout=2)

    def test_child_process_gets_oauth_path_without_mutating_parent_environment(self):
        before = os.environ.get("RELAY_GDRIVE_OAUTH_CLIENT_FILE")
        env = os.environ.copy()
        env["RELAY_GDRIVE_OAUTH_CLIENT_FILE"] = "parent-sentinel"
        result = self.cli("start", "--dry-run", "--max-cycles", "1", env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(os.environ.get("RELAY_GDRIVE_OAUTH_CLIENT_FILE"), before)
        self.assertEqual(env["RELAY_GDRIVE_OAUTH_CLIENT_FILE"], "parent-sentinel")


if __name__ == "__main__":
    unittest.main()
