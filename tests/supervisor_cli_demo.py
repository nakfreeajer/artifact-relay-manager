"""Deterministic ignored-workspace, multi-project supervisor qualification."""
from __future__ import annotations

import hashlib
import http.server
import json
import sys
import shutil
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import drive_adapter
import drive_monitor
import project_supervisor
import relay
from project_registry import ProjectRegistry


class Watcher(http.server.BaseHTTPRequestHandler):
    events = []

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        type(self).events.append(json.loads(body))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"disposition":"RECEIVED"}')

    def log_message(self, *_args):
        pass


class SharedAuthHarness:
    def __init__(self):
        self.access_calls = 0
        self.refresh_calls = 0
        self.valid = False

    def access_token(self):
        self.access_calls += 1
        if not self.valid:
            self.refresh_calls += 1
            self.valid = True
        return "fixture-only-token"


def main():
    evidence = Path(".agent-work/milestones/RELAY.PROJECT.SUPERVISOR.1A/evidence")
    fixture_root = Path(tempfile.mkdtemp(prefix="RELAY.PROJECT.SUPERVISOR.1A-", dir=".agent-work/temp"))
    registry_path = evidence / "multi-project-registry.json"
    registry_path.unlink(missing_ok=True)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Watcher)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    Watcher.events = []
    watcher_url = f"http://127.0.0.1:{server.server_port}/"
    registry = ProjectRegistry(registry_path)
    try:
        for project_id, folder_id in (("project-a", "folder-a"), ("project-b", "folder-b")):
            root = fixture_root / project_id
            workspace = root / "workspace"
            workspace.mkdir(parents=True, exist_ok=True)
            config_path = root / "drive-project.json"
            config_path.write_text(json.dumps({
                "schemaVersion": 1, "projectId": project_id, "repository": "owner/repo",
                "folderId": folder_id, "relayWorkspace": str(workspace),
                "watcherEndpoint": watcher_url, "eventType": "ARTIFACT_CHANGED",
            }), encoding="utf-8")
            registry.add(project_id, project_id.upper(), config_path, root / "relay-state.json")

        auth = SharedAuthHarness()
        instances = []
        def auth_factory():
            instances.append(auth)
            return auth

        project_order = []
        def fixture_cycle(entry, shared_session):
            project_id = entry["projectId"]
            project_order.append(project_id)
            assert shared_session is auth
            shared_session.access_token()
            config_path = Path(entry["configPath"])
            state_path = Path(entry["statePath"])
            config = drive_adapter._load_drive_config(config_path)
            workspace = config["_workspace"]
            (workspace / ".relay-project.json").write_text(json.dumps({
                "schemaVersion": 1, "projectId": project_id, "repository": "owner/repo",
            }), encoding="utf-8")
            body = workspace / "artifact.bin"
            body.write_bytes(("exact fixture bytes for " + project_id).encode("ascii"))
            core_path = workspace / ".relay-core-config.json"
            core_path.write_text(json.dumps(config["_coreConfig"]), encoding="utf-8")
            fixture = workspace / "observation.json"
            fixture.write_text(json.dumps({
                "providerItemId": "provider-item-" + project_id,
                "providerVersion": "version-1", "eventType": "ARTIFACT_CHANGED",
                "taskId": None, "artifactPath": body.name,
            }), encoding="utf-8")
            # The harness supplies one bounded provider observation and uses the
            # accepted monitor's normal one-cycle Relay retry path.
            def fake_poll(_config_path, _state_path, token=None):
                assert token == "fixture-only-token"
                event_id, disposition = relay.process(core_path, state_path, fixture)
                return [{"eventId": event_id, "result": disposition}]
            return drive_monitor.run_cycle(config_path, state_path, config, shared_session,
                poller=fake_poll, retryer=relay.retry_pending)

        cycle_records = []
        state_after_first = {}
        sleep_count = 0
        def between_cycles(_delay):
            nonlocal sleep_count
            sleep_count += 1
            if sleep_count == 1:
                for project_id in ("project-a", "project-b"):
                    state_after_first[project_id] = hashlib.sha256(
                        (fixture_root / project_id / "relay-state.json").read_bytes()
                    ).hexdigest()
                registry.set_enabled("project-a", False)
            elif sleep_count == 2:
                a_state = fixture_root / "project-a" / "relay-state.json"
                assert hashlib.sha256(a_state.read_bytes()).hexdigest() == state_after_first["project-a"]
                registry.set_enabled("project-a", True)

        project_supervisor.run_supervisor(registry_path, interval_seconds=1, max_cycles=3,
            session_factory=auth_factory, cycle_runner=fixture_cycle,
            sleeper=between_cycles, emit=cycle_records.append)

        assert [record["result"] for record in cycle_records] == ["OK", "OK", "OK"]
        assert [[project["projectId"] for project in record["projects"]] for record in cycle_records] == [
            ["project-a", "project-b"], ["project-b"], ["project-a", "project-b"]]
        assert project_order == ["project-a", "project-b", "project-b", "project-a", "project-b"]
        assert instances == [auth]
        assert auth.refresh_calls == 1
        assert len(Watcher.events) == 2, {"events": [(event.get("projectId"), event.get("eventId")) for event in Watcher.events], "cycles": cycle_records}
        event_ids = {event["projectId"]: event["eventId"] for event in Watcher.events}
        assert set(event_ids) == {"project-a", "project-b"}
        assert event_ids["project-a"] != event_ids["project-b"]
        state_counts = {}
        for project_id in ("project-a", "project-b"):
            state = json.loads((fixture_root / project_id / "relay-state.json").read_text(encoding="utf-8"))
            state_counts[project_id] = len(state["events"])
            assert {record["event"]["projectId"] for record in state["events"].values()} == {project_id}
        assert state_counts == {"project-a": 1, "project-b": 1}

        report = {
            "qualification": "LOCAL_MULTI_PROJECT_PASS",
            "cycles": cycle_records,
            "executionOrder": project_order,
            "watcherDeliveryCount": len(Watcher.events),
            "eventIdsByProject": event_ids,
            "stateRecordsByProject": state_counts,
            "sharedAuthInstances": len(instances),
            "sharedAuthRefreshes": auth.refresh_calls,
            "browserOAuthLaunched": False,
            "driveApiCalls": 0,
            "aStateUnchangedWhileDisabled": True,
        }
        (evidence / "multi-project-qualification.json").write_text(
            json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({key: report[key] for key in (
            "qualification", "executionOrder", "watcherDeliveryCount", "sharedAuthInstances",
            "sharedAuthRefreshes", "browserOAuthLaunched", "driveApiCalls",
        )}, sort_keys=True))
    finally:
        server.shutdown()
        server.server_close()
        registry_path.unlink(missing_ok=True)
        shutil.rmtree(fixture_root, ignore_errors=True)


if __name__ == "__main__":
    main()
