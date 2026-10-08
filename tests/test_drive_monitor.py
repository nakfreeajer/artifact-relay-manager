import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import drive_adapter
import drive_auth
import drive_monitor
import drive_session
import relay

from tests.test_drive_auth import FakeProtector


class MonitorCredentials:
    refreshes = 0
    rotate = False

    def __init__(self, token=None, refresh_token=None, **_kwargs):
        self.token = token
        self.refresh_token = refresh_token
        self.valid = bool(token)

    def refresh(self, _request):
        type(self).refreshes += 1
        self.token = f"monitor-access-{type(self).refreshes}"
        self.valid = True
        if type(self).rotate:
            self.refresh_token = "monitor-rotated-refresh"


class MonitorSession:
    def __init__(self, token="test-access"):
        self.token = token
        self.invalidations = 0
        self.refreshes = 0

    def access_token(self):
        return self.token

    def invalidate(self):
        self.invalidations += 1
        self.token = None

    def refresh(self):
        self.refreshes += 1
        self.token = f"refreshed-{self.refreshes}"
        return self.token


class MonitorWatcher(BaseHTTPRequestHandler):
    available = False
    event_ids = []

    def do_POST(self):
        type(self).event_ids.append(self.headers.get("Idempotency-Key"))
        self.rfile.read(int(self.headers.get("Content-Length", "0")))
        if not type(self).available:
            self.send_response(503)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"disposition":"RECEIVED"}')

    def log_message(self, *_args):
        pass


class MonitorDriveHandler(BaseHTTPRequestHandler):
    token = "test-access"
    folder_id = "folder-1"
    artifact_present = True
    identity_bytes = b""
    methods = []

    @classmethod
    def identity(cls):
        return {"id": "identity", "name": ".relay-project.json", "mimeType": "application/json",
                "parents": [cls.folder_id], "trashed": False, "version": "1",
                "size": str(len(cls.identity_bytes)), "capabilities": {"canDownload": True}}

    @classmethod
    def artifact(cls):
        return {"id": "monitor-artifact", "name": "monitor.txt", "mimeType": "text/plain",
                "parents": [cls.folder_id], "trashed": False, "version": "3",
                "size": str(len(b"monitor exact bytes\r\n")), "capabilities": {"canDownload": True}}

    def _respond(self, body, content_type="application/json", status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        type(self).methods.append(self.command)
        if self.headers.get("Authorization") != "Bearer " + type(self).token:
            return self._respond(b"{}", status=401)
        parsed = urlsplit(self.path)
        params = parse_qs(parsed.query)
        if parsed.path.endswith("/files"):
            is_identity_query = "name = '.relay-project.json'" in params.get("q", [""])[0]
            files = [type(self).identity()] if is_identity_query else [type(self).identity()]
            if not is_identity_query and type(self).artifact_present:
                files.append(type(self).artifact())
            return self._respond(json.dumps({"files": files}).encode())
        file_id = parsed.path.rsplit("/", 1)[-1]
        if file_id == type(self).folder_id:
            return self._respond(json.dumps({
                "id": file_id, "name": "fixture-root", "mimeType": drive_adapter.FOLDER_MIME,
                "parents": [], "trashed": False,
            }).encode())
        if file_id == "identity":
            if params.get("alt") == ["media"]:
                return self._respond(type(self).identity_bytes, "application/octet-stream")
            return self._respond(json.dumps(type(self).identity()).encode())
        if file_id == "monitor-artifact" and type(self).artifact_present:
            if params.get("alt") == ["media"]:
                return self._respond(b"monitor exact bytes\r\n", "text/plain")
            return self._respond(json.dumps(type(self).artifact()).encode())
        return self._respond(b"{}", status=404)

    def log_message(self, *_args):
        pass


class DriveMonitorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.client_file = self.root / "oauth-client.json"
        self.client_file.write_text(json.dumps({"installed": {
            "client_id": "monitor-client", "client_secret": "monitor-secret",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }}), encoding="utf-8")
        self.appdata = self.root / "appdata"
        self.env = patch.dict(os.environ, {
            "RELAY_GDRIVE_OAUTH_CLIENT_FILE": str(self.client_file),
            "LOCALAPPDATA": str(self.appdata),
        })
        self.env.start()
        self.protector_patch = patch.object(drive_session, "PROTECTOR_FACTORY", FakeProtector)
        self.protector_patch.start()
        self.store = drive_session.DriveSessionStore("monitor-client", drive_auth.SCOPE)
        MonitorCredentials.refreshes = 0
        MonitorCredentials.rotate = False
        self.workspace = self.root / "workspace"
        self.config_path = self.root / "drive-project.json"
        self.state_path = self.root / "relay-state.json"
        self.core_config_path = self.workspace / ".relay-core-config.json"
        self.config_path.write_text(json.dumps({
            "schemaVersion": 1, "projectId": "monitor-project", "repository": "owner/repo",
            "folderId": "folder-1", "relayWorkspace": str(self.workspace),
            "watcherEndpoint": "http://127.0.0.1:9/events", "eventType": "ARTIFACT_CHANGED",
        }), encoding="utf-8")
        self.config = {
            "projectId": "monitor-project", "_workspace": self.workspace,
        }

    def tearDown(self):
        self.protector_patch.stop()
        self.env.stop()
        self.temp.cleanup()

    def auth_session(self):
        self.store.save_refresh_token("monitor-refresh-secret")
        return drive_auth.DriveAuthSession(
            request_class=lambda: object(), credentials_class=MonitorCredentials,
            session_store=self.store,
        )

    def test_monitor_requires_existing_session_and_never_bootstraps_browser(self):
        self.workspace.mkdir()
        bootstrap = self.root / "bootstrap"
        bootstrap.mkdir()
        marker = self.root / "browser-flow-called"
        (bootstrap / "sitecustomize.py").write_text(
            "import drive_session, sys, types\n"
            "class P:\n"
            " def protect(self, data, entropy): return b'P'+data\n"
            " def unprotect(self, data, entropy): return data[1:]\n"
            "drive_session.PROTECTOR_FACTORY=P\n"
            "pkg=types.ModuleType('google_auth_oauthlib'); pkg.__path__=[]\n"
            "flow=types.ModuleType('google_auth_oauthlib.flow')\n"
            f"class F:\n def run_local_server(self, **kw): open({str(marker)!r}, 'w').write('called')\n"
            "class I:\n @classmethod\n def from_client_config(cls, *a, **kw): return F()\n"
            "flow.InstalledAppFlow=I; pkg.flow=flow\n"
            "sys.modules['google_auth_oauthlib']=pkg; sys.modules['google_auth_oauthlib.flow']=flow\n",
            encoding="utf-8",
        )
        env = os.environ.copy()
        env.update({"PYTHONPATH": str(bootstrap) + os.pathsep + env.get("PYTHONPATH", ""),
                    "LOCALAPPDATA": str(self.root / "empty-appdata"),
                    "RELAY_GDRIVE_OAUTH_CLIENT_FILE": str(self.client_file)})
        result = subprocess.run([
            sys.executable, "relay.py", "--config", str(self.config_path), "--state", str(self.state_path),
            "monitor-drive", "--interval-seconds", "1", "--max-cycles", "1",
        ], capture_output=True, text=True, env=env, timeout=10)
        combined = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("protected Google Drive session is not initialized", result.stderr)
        self.assertIn("qualify-drive interactively first", result.stderr)
        self.assertNotIn("Traceback", combined)
        self.assertFalse(marker.exists())
        self.assertFalse(self.state_path.exists())
        self.assertNotIn("monitor-secret", combined)

    def test_auth_session_refreshes_once_then_reuses_token_until_invalid(self):
        session = self.auth_session()
        calls = []
        no_retries = lambda *_args, **_kwargs: []
        poller = lambda *_args, token, **_kwargs: calls.append(token) or []
        drive_monitor._cycle(self.config_path, self.state_path, self.config, session, poller, no_retries)
        drive_monitor._cycle(self.config_path, self.state_path, self.config, session, poller, no_retries)
        self.assertEqual(MonitorCredentials.refreshes, 1)
        self.assertEqual(calls, ["monitor-access-1", "monitor-access-1"])
        session.credentials.valid = False
        drive_monitor._cycle(self.config_path, self.state_path, self.config, session, poller, no_retries)
        self.assertEqual(MonitorCredentials.refreshes, 2)
        self.assertEqual(calls[-1], "monitor-access-2")

    def test_rotated_monitor_refresh_token_replaces_protected_session(self):
        session = self.auth_session()
        MonitorCredentials.rotate = True
        session.credentials.valid = False
        session.access_token()
        self.assertEqual(self.store.load_refresh_token(), "monitor-rotated-refresh")

    def test_http_401_invalidates_refreshes_and_retries_cycle_exactly_once(self):
        session = MonitorSession()
        attempts = []
        eid = "relay-stable-event"

        def poller(_config, _state, *, token):
            attempts.append(token)
            if len(attempts) == 1:
                raise drive_adapter.DriveHttpError(401)
            return [{"eventId": eid, "result": "deduplicated"}]

        excluded = []

        def retryer(_config, _state, *, exclude_event_ids):
            excluded.extend(exclude_event_ids)
            return []

        counts = drive_monitor._cycle(self.config_path, self.state_path, self.config, session, poller, retryer)
        self.assertEqual(attempts, ["test-access", "refreshed-1"])
        self.assertEqual(session.invalidations, 1)
        self.assertEqual(session.refreshes, 1)
        self.assertEqual(excluded, [eid])
        self.assertEqual(counts["deduplicated"], 1)

    def test_drive_http_error_exposes_structured_status_and_keeps_sanitized_message(self):
        error = urllib.error.HTTPError("https://drive.invalid", 401, "private response", {}, None)
        with patch("drive_adapter.urllib.request.urlopen", side_effect=error):
            with self.assertRaises(drive_adapter.DriveHttpError) as caught:
                drive_adapter.DriveClient("test-access").request("files", {}, 1024)
        self.assertEqual(caught.exception.status_code, 401)
        self.assertEqual(str(caught.exception), "Google Drive API returned HTTP 401")

    def test_degraded_cycles_use_bounded_backoff_and_reset_after_success(self):
        session = MonitorSession()
        records, sleeps = [], []
        responses = [drive_adapter.DriveHttpError(401), drive_adapter.DriveHttpError(401),
                     drive_adapter.DriveError("Google Drive API request failed"), [],
                     drive_adapter.DriveError("Google Drive API request failed")]

        def poller(*_args, **_kwargs):
            value = responses.pop(0)
            if isinstance(value, Exception):
                raise value
            return value

        def sleeper(delay):
            sleeps.append(delay)

        drive_monitor.run_monitor(
            self.config_path, self.state_path, self.config, session,
            interval_seconds=5, max_cycles=4, poller=poller,
            retryer=lambda *_a, **_kw: [], sleeper=sleeper, emit=records.append,
        )
        self.assertEqual([r["result"] for r in records], ["DEGRADED", "DEGRADED", "OK", "DEGRADED"])
        self.assertEqual([r.get("retryDelaySeconds") for r in records], [1, 2, None, 1])
        self.assertEqual(sleeps, [1, 2, 5])
        self.assertNotIn("Traceback", json.dumps(records))
        self.assertNotIn("secret", json.dumps(records))

    def _make_relay_fixture(self, endpoint):
        self.workspace.mkdir(exist_ok=True)
        fixture_root = self.workspace / "project"
        fixture_root.mkdir(exist_ok=True)
        (fixture_root / ".relay-project.json").write_text(json.dumps({
            "schemaVersion": 1, "projectId": "monitor-project", "repository": "owner/repo",
        }), encoding="utf-8")
        (fixture_root / "artifact.bin").write_bytes(b"monitor exact bytes\r\n")
        self.core_config_path.parent.mkdir(parents=True, exist_ok=True)
        self.core_config_path.write_text(json.dumps({
            "schemaVersion": 1, "projectId": "monitor-project", "repository": "owner/repo",
            "fixtureRoot": str(fixture_root), "watcherEndpoint": endpoint,
        }), encoding="utf-8")
        fixture = fixture_root / "observation.json"
        fixture.write_text(json.dumps({
            "providerItemId": "drive-file-1", "providerVersion": "3", "eventType": "ARTIFACT_CHANGED",
            "taskId": None, "artifactPath": "artifact.bin",
        }), encoding="utf-8")
        return fixture_root, fixture

    def _watcher(self):
        MonitorWatcher.available = False
        MonitorWatcher.event_ids = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), MonitorWatcher)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread, f"http://127.0.0.1:{server.server_port}/events"

    def test_pending_event_retries_after_source_removal_with_same_identity(self):
        server, thread, endpoint = self._watcher()
        MonitorDriveHandler.artifact_present = True
        MonitorDriveHandler.methods = []
        MonitorDriveHandler.identity_bytes = json.dumps({
            "schemaVersion": 1, "projectId": "monitor-project", "repository": "owner/repo",
        }, separators=(",", ":")).encode()
        drive_server = ThreadingHTTPServer(("127.0.0.1", 0), MonitorDriveHandler)
        drive_thread = threading.Thread(target=drive_server.serve_forever, daemon=True)
        drive_thread.start()
        drive_config = json.loads(self.config_path.read_text(encoding="utf-8"))
        drive_config["watcherEndpoint"] = endpoint
        self.config_path.write_text(json.dumps(drive_config), encoding="utf-8")
        live_config = drive_adapter._load_drive_config(self.config_path)
        api_base = f"http://127.0.0.1:{drive_server.server_port}/drive/v3"

        def poller(config_path, state_path, *, token):
            return drive_adapter.poll_drive(config_path, state_path, token=token, api_base_url=api_base)

        records = []

        def between_cycles(_delay):
            MonitorDriveHandler.artifact_present = False
            MonitorWatcher.available = True

        try:
            drive_monitor.run_monitor(
                self.config_path, self.state_path, live_config, MonitorSession(),
                interval_seconds=1, max_cycles=2,
                poller=poller, sleeper=between_cycles, emit=records.append,
            )
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)
            drive_server.shutdown(); drive_server.server_close(); drive_thread.join(timeout=2)
        events = relay.state(self.state_path, "monitor-project")["events"]
        self.assertEqual(len(events), 1)
        eid = next(iter(events))
        self.assertEqual(MonitorWatcher.event_ids, [eid, eid])
        self.assertEqual(events[eid]["status"], "acknowledged")
        self.assertEqual(events[eid]["attempts"], 2)
        self.assertEqual(records[0]["pending"], 1)
        self.assertEqual(records[1]["delivered"], 1)
        self.assertEqual(set(MonitorDriveHandler.methods), {"GET"})

    def test_identity_mismatch_does_not_retry_existing_pending_event(self):
        server, thread, endpoint = self._watcher()
        _fixture_root, fixture = self._make_relay_fixture(endpoint)
        event_id, result = relay.process(self.core_config_path, self.state_path, fixture)
        self.assertEqual(result, "pending")
        initial_hits = list(MonitorWatcher.event_ids)
        MonitorWatcher.available = True
        retry_calls = []
        records = []

        def failed_identity(*_args, **_kwargs):
            raise drive_adapter.DriveError("Drive project/repository identity mismatch")

        try:
            drive_monitor.run_monitor(
                self.config_path, self.state_path, self.config, MonitorSession(),
                interval_seconds=1, max_cycles=1, poller=failed_identity,
                retryer=lambda *a, **kw: retry_calls.append((a, kw)) or [], emit=records.append,
            )
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)
        self.assertEqual(retry_calls, [])
        self.assertEqual(MonitorWatcher.event_ids, initial_hits)
        self.assertEqual(records[0]["result"], "DEGRADED")
        self.assertEqual(relay.state(self.state_path, "monitor-project")["events"][event_id]["status"], "pending")

    def test_unchanged_version_deduplicates_across_successful_cycles(self):
        server, thread, endpoint = self._watcher()
        fixture_root, fixture = self._make_relay_fixture(endpoint)
        MonitorWatcher.available = True

        def poller(_config, state_path, **_kwargs):
            self.assertEqual(relay.readj(fixture_root / ".relay-project.json")["projectId"], "monitor-project")
            event_id, result = relay.process(self.core_config_path, state_path, fixture)
            return [{"eventId": event_id, "result": result}]

        records = []
        try:
            drive_monitor.run_monitor(
                self.config_path, self.state_path, self.config, MonitorSession(),
                interval_seconds=1, max_cycles=2, poller=poller,
                sleeper=lambda _delay: None, emit=records.append,
            )
        finally:
            server.shutdown(); server.server_close(); thread.join(timeout=2)
        self.assertEqual(len(MonitorWatcher.event_ids), 1)
        self.assertEqual(records[0]["delivered"], 1)
        self.assertEqual(records[1]["deduplicated"], 1)
        self.assertEqual(len(relay.state(self.state_path, "monitor-project")["events"]), 1)

    def test_keyboard_interrupt_stops_cleanly_and_preserves_state_and_session(self):
        session = self.auth_session()
        protected_before = self.store.path.read_bytes()
        relay.save(self.state_path, {"schemaVersion": 1, "events": {}})
        state_before = self.state_path.read_bytes()
        records = []

        def interrupt(_delay):
            raise KeyboardInterrupt

        result = drive_monitor.run_monitor(
            self.config_path, self.state_path, self.config, session,
            interval_seconds=1, max_cycles=None, poller=lambda *_a, **_kw: [],
            retryer=lambda *_a, **_kw: [], sleeper=interrupt, emit=records.append,
        )
        self.assertEqual(result, 0)
        self.assertEqual(records[-1]["result"], "STOPPED")
        self.assertEqual(self.store.path.read_bytes(), protected_before)
        self.assertEqual(self.state_path.read_bytes(), state_before)

    def test_interval_and_max_cycles_are_bounded_not_clamped(self):
        with self.assertRaisesRegex(relay.RelayError, "interval-seconds"):
            drive_monitor.run_monitor(self.config_path, self.state_path, self.config, MonitorSession(), interval_seconds=0)
        with self.assertRaisesRegex(relay.RelayError, "interval-seconds"):
            drive_monitor.run_monitor(self.config_path, self.state_path, self.config, MonitorSession(), interval_seconds=3601)
        with self.assertRaisesRegex(relay.RelayError, "max-cycles"):
            drive_monitor.run_monitor(self.config_path, self.state_path, self.config, MonitorSession(), max_cycles=10001)


if __name__ == "__main__":
    unittest.main()
