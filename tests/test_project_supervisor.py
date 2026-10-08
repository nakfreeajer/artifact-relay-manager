import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import drive_adapter
import drive_auth
import drive_monitor
import project_supervisor
import relay
from project_registry import ProjectRegistry


class FakeSession:
    def __init__(self, fail_refreshes=0):
        self.fail_refreshes = fail_refreshes
        self.refresh_calls = 0
        self.access_calls = 0
        self.valid = False

    def access_token(self):
        self.access_calls += 1
        if not self.valid:
            self.refresh()
        return "memory-only-test-token"

    def refresh(self):
        self.refresh_calls += 1
        if self.fail_refreshes:
            self.fail_refreshes -= 1
            raise drive_auth.DriveAuthError("test refresh failure")
        self.valid = True
        return "memory-only-test-token"


class ProjectSupervisorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.registry_path = self.root / "registry.json"
        self.registry = ProjectRegistry(self.registry_path)
        self.configs = {}
        self.states = {}
        self.workspaces = {}

    def tearDown(self):
        self.temp.cleanup()

    def add(self, project_id, enabled=True):
        workspace = self.root / ("workspace-" + project_id)
        config_path = self.root / ("config-" + project_id + ".json")
        state_path = self.root / ("state-" + project_id + ".json")
        config = {"schemaVersion": 1, "projectId": project_id, "repository": "owner/repo",
                  "folderId": "folder-" + project_id, "relayWorkspace": str(workspace),
                  "watcherEndpoint": "http://127.0.0.1:49152/", "eventType": "ARTIFACT_CHANGED"}
        config_path.write_text(json.dumps(config), encoding="utf-8")
        self.registry.add(project_id, project_id.upper(), config_path, state_path, enabled=enabled)
        self.configs[project_id] = config_path
        self.states[project_id] = state_path
        self.workspaces[project_id] = workspace
        return {"projectId": project_id, "configPath": config_path.resolve().as_posix(),
                "statePath": state_path.resolve().as_posix(), "enabled": enabled}

    def run_it(self, cycles, runner, *, session=None, session_factory=None, sleeper=None, registry_factory=ProjectRegistry):
        records = []
        if session_factory is None:
            session_factory = lambda: session
        if sleeper is None:
            sleeper = lambda _seconds: None
        code = project_supervisor.run_supervisor(
            self.registry_path, interval_seconds=1, max_cycles=cycles,
            session_factory=session_factory, cycle_runner=runner,
            registry_factory=registry_factory, sleeper=sleeper, emit=records.append,
        )
        self.assertEqual(code, 0)
        return records

    def test_zero_enabled_is_idle_without_session_state_or_io(self):
        self.add("disabled", enabled=False)
        factory_calls = []
        runner_calls = []
        records = self.run_it(1, lambda *_: runner_calls.append(True),
                              session_factory=lambda: factory_calls.append(True))
        self.assertEqual(records, [{"cycle": 1, "result": "IDLE", "enabledProjects": 0, "projects": []}])
        self.assertEqual(factory_calls, [])
        self.assertEqual(runner_calls, [])
        self.assertFalse(self.states["disabled"].exists())

    def test_two_projects_run_once_in_order_with_their_own_paths(self):
        self.add("b")
        self.add("a")
        seen = []
        session = FakeSession()
        def runner(entry, shared):
            seen.append((entry["projectId"], entry["configPath"], entry["statePath"], shared))
            return {"observed": 1, "delivered": 1}
        records = self.run_it(1, runner, session=session)
        self.assertEqual([item[0] for item in seen], ["a", "b"])
        self.assertEqual(seen[0][1], self.configs["a"].resolve().as_posix())
        self.assertEqual(seen[0][2], self.states["a"].resolve().as_posix())
        self.assertEqual(seen[1][1], self.configs["b"].resolve().as_posix())
        self.assertEqual(seen[1][2], self.states["b"].resolve().as_posix())
        self.assertIs(seen[0][3], seen[1][3])
        self.assertEqual(records[0]["result"], "OK")

    def test_one_shared_auth_session_refreshes_once_across_projects_and_cycles(self):
        self.add("a")
        self.add("b")
        session = FakeSession()
        instances = []
        def factory():
            instances.append(session)
            return session
        def runner(_entry, shared):
            self.assertEqual(shared.access_token(), "memory-only-test-token")
            return {"observed": 0}
        self.run_it(2, runner, session_factory=factory)
        self.assertEqual(instances, [session])
        self.assertEqual(session.refresh_calls, 1)
        self.assertEqual(session.access_calls, 4)

    def test_project_local_failure_does_not_stop_next_project(self):
        self.add("a")
        self.add("b")
        seen = []
        def runner(entry, _session):
            seen.append(entry["projectId"])
            if entry["projectId"] == "a":
                raise drive_adapter.DriveError("provider identity mismatch")
            return {"observed": 1, "delivered": 1}
        record = self.run_it(1, runner, session=FakeSession())[0]
        self.assertEqual(seen, ["a", "b"])
        self.assertEqual(record["result"], "DEGRADED")
        self.assertEqual([p["result"] for p in record["projects"]], ["DEGRADED", "OK"])
        self.assertEqual(record["projects"][0]["error"], "PROJECT_UNAVAILABLE")

    def test_watcher_unavailable_keeps_same_pending_event_while_next_project_runs(self):
        self.add("a")
        self.add("b")
        config_a = drive_adapter._load_drive_config(self.configs["a"])
        workspace = config_a["_workspace"]
        (workspace / ".relay-project.json").write_text(json.dumps({
            "schemaVersion": 1, "projectId": "a", "repository": "owner/repo",
        }), encoding="utf-8")
        body = workspace / "artifact.bin"
        body.write_bytes(b"supervisor pending artifact")
        core_path = workspace / ".relay-core-config.json"
        core_path.write_text(json.dumps(config_a["_coreConfig"]), encoding="utf-8")
        fixture = workspace / "observation.json"
        fixture.write_text(json.dumps({"providerItemId": "drive-item-a", "providerVersion": "4",
            "eventType": "ARTIFACT_CHANGED", "taskId": None, "artifactPath": body.name}), encoding="utf-8")
        event_id, first_result = relay.process(core_path, self.states["a"], fixture)
        self.assertEqual(first_result, "pending")
        seen = []
        def runner(entry, session):
            seen.append(entry["projectId"])
            if entry["projectId"] == "a":
                return drive_monitor.run_cycle(self.configs["a"], self.states["a"], config_a, session,
                    poller=lambda *_a, **_kw: [], retryer=relay.retry_pending)
            return {"observed": 1, "delivered": 1}
        record = self.run_it(1, runner, session=FakeSession())[0]
        saved = relay.state(self.states["a"], "a")["events"][event_id]
        self.assertEqual(seen, ["a", "b"])
        self.assertEqual(saved["status"], "pending")
        self.assertEqual(saved["event"]["eventId"], event_id)
        self.assertEqual(record["projects"][0]["pending"], 1)
        self.assertEqual(record["projects"][1]["delivered"], 1)

    def test_shared_auth_failure_skips_remaining_projects_and_retries_next_cycle(self):
        self.add("a")
        self.add("b")
        session = FakeSession(fail_refreshes=1)
        seen = []
        def runner(entry, shared):
            seen.append(entry["projectId"])
            shared.access_token()
            return {"observed": 1}
        records = self.run_it(2, runner, session=session)
        self.assertEqual(seen, ["a", "a", "b"])
        self.assertEqual(session.refresh_calls, 2)
        self.assertEqual(records[0]["result"], "DEGRADED")
        self.assertEqual(records[0]["projects"][1]["error"], "AUTH_UNAVAILABLE")
        self.assertEqual(records[1]["result"], "OK")

    def test_missing_protected_session_never_bootstraps_and_retries_on_next_cycle(self):
        self.add("a")
        self.add("b")
        attempts = []
        session = FakeSession()
        def factory():
            attempts.append(True)
            if len(attempts) == 1:
                raise drive_auth.DriveAuthError("protected session unavailable")
            return session
        seen = []
        def runner(entry, _shared):
            seen.append(entry["projectId"])
            return {"observed": 0}
        records = self.run_it(2, runner, session_factory=factory)
        self.assertEqual(len(attempts), 2)
        self.assertEqual(seen, ["a", "b"])
        self.assertEqual(records[0]["projects"][1]["error"], "AUTH_UNAVAILABLE")
        self.assertEqual(records[1]["result"], "OK")

    def test_registry_corruption_processes_zero_and_recovers_after_repair(self):
        self.add("a")
        original = self.registry_path.read_bytes()
        self.registry_path.write_text("{bad", encoding="utf-8")
        seen = []
        def recover(_delay):
            self.registry_path.write_bytes(original)
        records = self.run_it(2, lambda e, _s: (seen.append(e["projectId"]) or {"observed": 0}),
                              session=FakeSession(), sleeper=recover)
        self.assertEqual(records[0]["result"], "DEGRADED")
        self.assertEqual(records[0]["error"], "REGISTRY_INVALID")
        self.assertEqual(records[0]["projects"], [])
        self.assertEqual(seen, ["a"])

    def test_registry_failure_uses_bounded_backoff_and_valid_load_resets_it(self):
        self.add("a")
        records = []
        delays = []
        valid_bytes = self.registry_path.read_bytes()
        self.registry_path.write_text("not-json", encoding="utf-8")
        def recover(delay):
            delays.append(delay)
            if len(delays) == 2:
                self.registry_path.write_bytes(valid_bytes)
        project_supervisor.run_supervisor(self.registry_path, interval_seconds=1, max_cycles=3,
            session_factory=lambda: FakeSession(), cycle_runner=lambda *_: {"observed": 0},
            sleeper=recover, emit=records.append)
        self.assertEqual(delays, [1, 2])
        self.assertEqual([r["result"] for r in records], ["DEGRADED", "DEGRADED", "OK"])

    def _dynamic(self, initial, mutate):
        for project_id, enabled in initial:
            self.add(project_id, enabled)
        seen = []
        def runner(entry, _session):
            seen.append(entry["projectId"])
            return {"observed": 0}
        calls = 0
        def sleeper(_delay):
            nonlocal calls
            calls += 1
            if calls == 1:
                mutate()
        records = self.run_it(2, runner, session=FakeSession(), sleeper=sleeper)
        return seen, records

    def test_dynamic_disable_applies_next_cycle(self):
        seen, records = self._dynamic([("a", True)], lambda: self.registry.set_enabled("a", False))
        self.assertEqual(seen, ["a"])
        self.assertEqual(records[1]["result"], "IDLE")

    def test_dynamic_enable_applies_next_cycle(self):
        self.add("a", enabled=False)
        seen = []
        def runner(entry, _session):
            seen.append(entry["projectId"])
            return {"observed": 0}
        records = self.run_it(2, runner, session=FakeSession(),
                              sleeper=lambda _delay: self.registry.set_enabled("a", True))
        self.assertEqual(seen, ["a"])
        self.assertEqual(records[0]["result"], "IDLE")
        self.assertEqual(records[1]["result"], "OK")

    def test_dynamic_add_and_remove_apply_next_cycle_and_preserve_removed_files(self):
        self.add("a")
        seen = []
        def runner(entry, _session):
            seen.append(entry["projectId"])
            return {"observed": 0}
        self.run_it(2, runner, session=FakeSession(), sleeper=lambda _delay: self.add("b"))
        self.assertEqual(seen, ["a", "a", "b"])
        seen.clear()
        self.run_it(2, runner, session=FakeSession(),
                    sleeper=lambda _delay: self.registry.remove("a"))
        self.assertEqual(seen, ["a", "b", "b"])
        self.assertTrue(self.configs["a"].is_file())
        self.assertTrue(self.workspaces["a"].is_dir())
        self.assertFalse(self.states["a"].exists())

    def test_metadata_only_output_and_graceful_stop(self):
        self.add("a")
        def runner(_entry, _session):
            raise drive_adapter.DriveError("access_token=secret artifact-body watcher-payload")
        def interrupt(_delay):
            raise KeyboardInterrupt
        records = []
        project_supervisor.run_supervisor(self.registry_path, interval_seconds=1, max_cycles=None,
            session_factory=lambda: FakeSession(), cycle_runner=runner, sleeper=interrupt, emit=records.append)
        self.assertEqual(records[-1], {"cycle": 1, "result": "STOPPED"})
        serialized = json.dumps(records)
        for secret in ("access_token", "secret", "artifact-body", "watcher-payload"):
            self.assertNotIn(secret, serialized)
        self.assertTrue(self.configs["a"].is_file())
        self.assertTrue(self.registry_path.is_file())

    def test_cli_empty_registry_runs_idle_without_oauth(self):
        env = {**__import__("os").environ, "LOCALAPPDATA": str(self.root / "appdata")}
        env.pop("RELAY_GDRIVE_OAUTH_CLIENT_FILE", None)
        env.pop("RELAY_GDRIVE_ACCESS_TOKEN", None)
        proc = subprocess.run([sys.executable, "relay_supervisor.py", "--registry", str(self.registry_path),
                              "run", "--max-cycles", "1"], capture_output=True, text=True, env=env, timeout=10)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(json.loads(proc.stdout), {"cycle": 1, "enabledProjects": 0, "projects": [], "result": "IDLE"})
        self.assertFalse((self.root / "appdata" / "ArtifactRelayManager").exists())

    def test_cli_missing_default_registry_location_is_sanitized(self):
        with patch.dict(os.environ, {"LOCALAPPDATA": ""}):
            with patch("sys.argv", ["relay_supervisor.py", "run", "--max-cycles", "1"]):
                with patch("builtins.print") as output:
                    self.assertEqual(__import__("relay_supervisor").main(), 2)
        emitted = json.loads(output.call_args.args[0])
        self.assertEqual(emitted, {"error": "LOCALAPPDATA is unavailable; supply --registry"})


if __name__ == "__main__":
    unittest.main()
