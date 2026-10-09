"""Ignored-workspace, two-cycle, offline launcher qualification."""
from __future__ import annotations

import http.server
import json
import subprocess
import sys
import threading
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from project_registry import ProjectRegistry


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / ".agent-work/milestones/RELAY.WINDOWS.USERHOST.1A/evidence/qualification"


class MockWatcher(http.server.BaseHTTPRequestHandler):
    posts = 0
    health_checks = 0

    def do_GET(self):
        type(self).health_checks += 1
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def do_POST(self):
        type(self).posts += 1
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"disposition":"RECEIVED"}')

    def log_message(self, *_args):
        pass


def main() -> int:
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    project = EVIDENCE / "approved-project"
    workspace = project / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    config_path = project / "drive-project.json"
    state_path = project / "relay-state.json"
    registry_path = EVIDENCE / "registry" / "projects.json"
    registry_path.parent.mkdir(parents=True, exist_ok=True)
    registry_path.unlink(missing_ok=True)
    config_path.write_text(json.dumps({
        "schemaVersion": 1,
        "projectId": "artifact-relay-manager",
        "repository": "nakfreeajer/artifact-relay-manager",
        "folderId": "1u1aOENrZR5EyFL4We8Q0OcB_Sq6YD2QH",
        "relayWorkspace": str(workspace.resolve()),
        "watcherEndpoint": "http://127.0.0.1:1/placeholder",
        "eventType": "ARTIFACT_CHANGED",
    }), encoding="utf-8")

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), MockWatcher)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    endpoint = f"http://127.0.0.1:{server.server_port}/events"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["watcherEndpoint"] = endpoint
    config_path.write_text(json.dumps(config), encoding="utf-8")
    MockWatcher.posts = 0
    MockWatcher.health_checks = 0
    with urllib.request.urlopen(endpoint, timeout=3) as response:
        health_status = response.status

    oauth_path = EVIDENCE / "oauth-client-path-fixture.not-read"
    oauth_path.write_bytes(b"")
    log_path = EVIDENCE / "logs" / "userhost.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.unlink(missing_ok=True)
    for index in (1, 2):
        log_path.with_name(log_path.name + f".{index}").unlink(missing_ok=True)
    host_config = {
        "schemaVersion": 1,
        "pythonExecutable": str(Path(sys.executable).resolve()),
        "supervisorScript": str((ROOT / "relay_supervisor.py").resolve()),
        "workingDirectory": str(ROOT.resolve()),
        "registryPath": str(registry_path.resolve()),
        "oauthClientFile": str(oauth_path.resolve()),
        "logPath": str(log_path.resolve()),
        "lockPath": str((EVIDENCE / "userhost.lock").resolve()),
        "workerLockPath": str((EVIDENCE / "userhost-worker.lock").resolve()),
        "stopPath": str((EVIDENCE / "userhost.stop").resolve()),
        "intervalSeconds": 1,
        "maxCycles": None,
        "stopTimeoutSeconds": 10,
        "logMaxBytes": 16384,
        "logBackups": 2,
    }
    host_config_path = EVIDENCE / "userhost.json"
    host_config_path.write_text(json.dumps(host_config), encoding="utf-8")

    try:
        registry = ProjectRegistry(registry_path)
        registry.add("artifact-relay-manager", "ARM disposable qualification",
                     config_path, state_path, enabled=False)
        command = [sys.executable, str(ROOT / "relay_userhost.py"), "--config",
                   str(host_config_path.resolve()), "start", "--dry-run", "--max-cycles", "2"]
        result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=30)
        records = [json.loads(line) for line in log_path.read_text(encoding="utf-8").splitlines()]
        cycles = [record for record in records if record.get("component") == "supervisor"]
        report = {
            "milestone": "RELAY.WINDOWS.USERHOST.1A",
            "mode": "bounded dry-run; all project entries disabled",
            "exitCode": result.returncode,
            "cycleResults": [{"cycle": record.get("cycle"), "result": record.get("result")}
                             for record in cycles],
            "mockWatcher": {"boundToLoopback": True, "healthStatus": health_status,
                            "healthChecks": MockWatcher.health_checks,
                            "postDeliveries": MockWatcher.posts},
            "driveCalls": 0,
            "oauthClientContentsRead": False,
            "browserOAuth": False,
            "protectedSessionAccess": False,
            "taskOrServiceRegistration": False,
            "result": "PASS" if result.returncode == 0 and [r.get("cycle") for r in cycles] == [1, 2]
                                and all(r.get("result") == "IDLE" for r in cycles)
                                and health_status == 200 and MockWatcher.health_checks == 1
                                and MockWatcher.posts == 0 else "FAIL",
        }
        evidence_file = EVIDENCE / "qualification.json"
        evidence_file.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"command": "python relay_userhost.py --config <ignored userhost.json> start --dry-run --max-cycles 2",
                          "result": report["result"], "exitCode": result.returncode,
                          "cycleResults": report["cycleResults"],
                          "watcherHealthStatus": health_status,
                          "watcherHealthChecks": MockWatcher.health_checks,
                          "watcherPosts": MockWatcher.posts,
                          "evidence": str(evidence_file.relative_to(ROOT))},
                         sort_keys=True, separators=(",", ":")))
        if result.returncode != 0:
            print(result.stdout)
            print(result.stderr, file=sys.stderr)
        return 0 if report["result"] == "PASS" else 1
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=2)


if __name__ == "__main__":
    raise SystemExit(main())
