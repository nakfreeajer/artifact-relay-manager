"""Run the requested fresh-process Relay CLI lifecycle demonstration."""
import http.server
import json
import subprocess
import sys
import tempfile
import threading
from pathlib import Path


class Watcher(http.server.BaseHTTPRequestHandler):
    events = []

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        event = json.loads(body)
        self.events.append(event)
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"disposition":"RECEIVED"}')

    def log_message(self, *_args):
        pass


def run(*args, expected=0):
    result = subprocess.run([sys.executable, "relay.py", *map(str, args)], capture_output=True, text=True)
    if result.returncode != expected:
        raise RuntimeError(f"CLI rc={result.returncode}; stdout={result.stdout}; stderr={result.stderr}")
    return result.stdout.strip()


def main():
    Watcher.events = []
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        fixture_root = root / "fixture"
        fixture_root.mkdir()
        (fixture_root / ".relay-project.json").write_text(json.dumps({"schemaVersion": 1, "projectId": "demo", "repository": "example/relay"}))
        (fixture_root / "artifact.txt").write_bytes(b"exact bytes\r\n")
        fixture = root / "observation.json"
        fixture.write_text(json.dumps({"providerItemId": "item-1", "providerVersion": "version-1", "eventType": "ARTIFACT_CHANGED", "taskId": None, "artifactPath": "artifact.txt"}))
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Watcher)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        config = root / "config.json"
        state = root / "state.json"
        base = {"schemaVersion": 1, "projectId": "demo", "repository": "example/relay", "fixtureRoot": str(fixture_root)}
        try:
            config.write_text(json.dumps({**base, "watcherEndpoint": f"http://127.0.0.1:{server.server_port}/"}))
            first = json.loads(run("--config", config, "--state", state, "process", fixture))
            duplicate = json.loads(run("--config", config, "--state", state, "process", fixture))
            if first["result"] != "delivered" or duplicate != {"eventId": first["eventId"], "result": "deduplicated"} or len(Watcher.events) != 1:
                raise AssertionError("first delivery/deduplication proof failed")
            observation = json.loads(fixture.read_text())
            observation["providerVersion"] = "version-2"
            fixture.write_text(json.dumps(observation))
            server.shutdown()
            config.write_text(json.dumps({**base, "watcherEndpoint": "http://127.0.0.1:1/"}))
            pending_text = run("--config", config, "--state", state, "process", fixture, expected=2)
            pending = json.loads(pending_text)
            if pending["result"] != "pending" or pending["eventId"] == first["eventId"]:
                raise AssertionError("unavailable endpoint did not preserve a new pending event")
            config.write_text(json.dumps({**base, "watcherEndpoint": f"http://127.0.0.1:{server.server_port}/"}))
            server.server_close()
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Watcher)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            config.write_text(json.dumps({**base, "watcherEndpoint": f"http://127.0.0.1:{server.server_port}/"}))
            retried = json.loads(run("--config", config, "--state", state, "retry"))[0]
            if retried != {"eventId": pending["eventId"], "result": "delivered"} or Watcher.events[-1]["eventId"] != pending["eventId"]:
                raise AssertionError("fresh retry did not deliver the same event identity")
            print(json.dumps({"first": first, "duplicate": duplicate, "unavailable": pending, "freshRetry": retried, "watcherDeliveries": len(Watcher.events)}, sort_keys=True))
        finally:
            server.shutdown()
            server.server_close()


if __name__ == "__main__":
    main()
