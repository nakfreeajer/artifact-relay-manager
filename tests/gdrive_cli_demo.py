"""Fake Drive + fake Watcher CLI proof using separate Relay invocations."""
import json
import os
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_drive_adapter import DriveHandler, WatcherHandler
import http.server


def start(handler, port=0):
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def invoke(*args, expected=0):
    result = subprocess.run([sys.executable, "relay.py", *map(str, args)], capture_output=True, text=True,
                            env={**os.environ, "RELAY_GDRIVE_ACCESS_TOKEN": "test-token"})
    if result.returncode != expected:
        raise RuntimeError(f"CLI rc={result.returncode}; stderr={result.stderr}")
    return result.stdout.strip()


def main():
    DriveHandler.files = {
        "folder-1": {"id": "folder-1", "name": "root", "mimeType": "application/vnd.google-apps.folder", "parents": [], "trashed": False},
        "identity": {"id": "identity", "name": ".relay-project.json", "mimeType": "application/json", "parents": ["folder-1"], "trashed": False, "version": "1", "size": "1", "capabilities": {"canDownload": True}},
        "artifact-1": {"id": "artifact-1", "name": "artifact", "mimeType": "application/octet-stream", "parents": ["folder-1"], "trashed": False, "version": "10", "size": "12", "capabilities": {"canDownload": True}, "data": b"demo bytes\r\n"},
    }
    DriveHandler.identity_ids = ["identity"]
    DriveHandler.identity_bytes = json.dumps({"schemaVersion": 1, "projectId": "demo", "repository": "example/repo"}).encode()
    DriveHandler.fail = False
    DriveHandler.auth_expected = "test-token"
    WatcherHandler.events = []
    drive = start(DriveHandler)
    watcher = start(WatcherHandler)
    try:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            workspace = root / "relay-workspace"
            config = root / "drive-project.json"
            state = root / "state.json"
            values = {"schemaVersion": 1, "projectId": "demo", "repository": "example/repo", "folderId": "folder-1",
                      "relayWorkspace": str(workspace), "watcherEndpoint": f"http://127.0.0.1:{watcher.server_port}/", "eventType": "ARTIFACT_CHANGED"}
            config.write_text(json.dumps(values))
            base = f"http://127.0.0.1:{drive.server_port}/drive/v3"
            first = json.loads(invoke("--config", config, "--state", state, "poll-drive", "--api-base-url", base))[0]
            duplicate = json.loads(invoke("--config", config, "--state", state, "poll-drive", "--api-base-url", base))[0]
            if first["result"] != "delivered" or duplicate["result"] != "deduplicated" or first["eventId"] != duplicate["eventId"] or len(WatcherHandler.events) != 1:
                raise AssertionError("Drive CLI first delivery/deduplication failed")
            DriveHandler.files["artifact-1"]["version"] = "11"
            watcher_port = watcher.server_port
            watcher.shutdown()
            watcher.server_close()
            config.write_text(json.dumps(values))
            pending = json.loads(invoke("--config", config, "--state", state, "poll-drive", "--api-base-url", base))[0]
            if pending["result"] != "pending":
                raise AssertionError("Drive CLI did not preserve unavailable delivery")
            retry_config = workspace / ".relay-core-config.json"
            watcher = start(WatcherHandler, watcher_port)
            retried = json.loads(invoke("--config", retry_config, "--state", state, "retry"))[0]
            if retried["eventId"] != pending["eventId"] or retried["result"] != "delivered" or WatcherHandler.events[-1]["eventId"] != pending["eventId"]:
                raise AssertionError("Drive CLI retry identity changed")
            print(json.dumps({"first": first, "duplicate": duplicate, "pending": pending, "retry": retried}, sort_keys=True))
    finally:
        drive.shutdown(); drive.server_close()
        watcher.shutdown(); watcher.server_close()


if __name__ == "__main__":
    main()
