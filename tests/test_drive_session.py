import hashlib
import http.server
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

import drive_auth
import drive_session
from tests.test_drive_auth import FakeCredentials, FakeFlow, FakeProtector


class SessionDriveHandler(http.server.BaseHTTPRequestHandler):
    token = "subprocess-access-token-secret"
    project_id = "artifact-relay-manager"
    repository = "nakfreeajer/artifact-relay-manager"
    folder_id = "folder-session"
    artifact_body = b"session artifact body\r\n"
    identity_body = b""
    calls = []

    def do_GET(self):
        type(self).calls.append((self.path, self.headers.get("Authorization") == "Bearer " + type(self).token))
        if self.headers.get("Authorization") != "Bearer " + type(self).token:
            return self.send_error(401)
        parsed = urlsplit(self.path)
        params = parse_qs(parsed.query)
        if parsed.path.endswith("/files"):
            name_query = "name = '.relay-project.json'" in params.get("q", [""])[0]
            items = [self.identity_metadata()] if name_query else [self.identity_metadata(), self.artifact_metadata()]
            return self.respond(json.dumps({"files": items}).encode(), "application/json")
        file_id = parsed.path.rsplit("/", 1)[-1]
        if file_id == type(self).folder_id:
            return self.respond(json.dumps({"id": file_id, "name": "fixture-root", "mimeType": "application/vnd.google-apps.folder", "parents": [], "trashed": False}).encode(), "application/json")
        if file_id == "identity":
            if params.get("alt") == ["media"]:
                return self.respond(type(self).identity_body, "application/octet-stream")
            return self.respond(json.dumps(self.identity_metadata()).encode(), "application/json")
        if file_id == "artifact-session":
            if params.get("alt") == ["media"]:
                return self.respond(type(self).artifact_body, "text/plain")
            return self.respond(json.dumps(self.artifact_metadata()).encode(), "application/json")
        return self.send_error(404)

    @classmethod
    def identity_metadata(cls):
        return {"id": "identity", "name": ".relay-project.json", "mimeType": "application/json",
                "parents": [cls.folder_id], "trashed": False, "version": "1",
                "size": str(len(cls.identity_body)), "capabilities": {"canDownload": True}}

    @classmethod
    def artifact_metadata(cls):
        return {"id": "artifact-session", "name": "qualification.txt", "mimeType": "text/plain",
                "parents": [cls.folder_id], "trashed": False, "version": "3",
                "size": str(len(cls.artifact_body)), "capabilities": {"canDownload": True}}

    def respond(self, body, mime):
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


class DriveSessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.appdata = self.root / "local-app-data"
        self.client_dir = self.root / "client"
        self.client_dir.mkdir()
        self.marker_dir = self.root / "markers"
        self.marker_dir.mkdir()
        self.client_file = self.client_dir / "oauth-client.json"
        self.client_config = {"installed": {
            "client_id": "session-test-client.apps.googleusercontent.com", "client_secret": "fake-client-secret",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token",
        }}
        self.client_file.write_text(json.dumps(self.client_config), encoding="utf-8")
        SessionDriveHandler.identity_body = json.dumps({
            "schemaVersion": 1, "projectId": SessionDriveHandler.project_id,
            "repository": SessionDriveHandler.repository,
        }, separators=(",", ":")).encode()
        SessionDriveHandler.calls = []
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), SessionDriveHandler)
        self.server_thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.server_thread.start()
        self.api_base = f"http://127.0.0.1:{self.server.server_port}/drive/v3"
        self.config_path = self.root / "drive-project.json"
        self.workspace = self.root / "relay-workspace"
        self.config_path.write_text(json.dumps({
            "schemaVersion": 1, "projectId": SessionDriveHandler.project_id,
            "repository": SessionDriveHandler.repository, "folderId": SessionDriveHandler.folder_id,
            "relayWorkspace": str(self.workspace), "watcherEndpoint": "http://127.0.0.1:9/events",
            "eventType": "ARTIFACT_CHANGED",
        }), encoding="utf-8")

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.server_thread.join(timeout=2)
        self.temp.cleanup()

    def make_store(self, client_id="session-test-client.apps.googleusercontent.com", scope=drive_session.SCOPE):
        return drive_session.DriveSessionStore(
            client_id, scope, protector=FakeProtector(), local_app_data=self.appdata,
        )

    def subprocess_env(self, *, refresh_fail=False, rotate=False):
        bootstrap = self.root / "subprocess-bootstrap"
        bootstrap.mkdir(exist_ok=True)
        (bootstrap / "sitecustomize.py").write_text(self._sitecustomize_source(), encoding="utf-8")
        env = os.environ.copy()
        env.update({
            "RELAY_GDRIVE_OAUTH_CLIENT_FILE": str(self.client_file),
            "LOCALAPPDATA": str(self.appdata),
            "RELAY_TEST_MARKER_DIR": str(self.marker_dir),
            "PYTHONPATH": str(bootstrap) + os.pathsep + env.get("PYTHONPATH", ""),
        })
        if refresh_fail:
            env["RELAY_TEST_REFRESH_FAIL"] = "1"
        else:
            env.pop("RELAY_TEST_REFRESH_FAIL", None)
        if rotate:
            env["RELAY_TEST_ROTATE_REFRESH"] = "1"
        else:
            env.pop("RELAY_TEST_ROTATE_REFRESH", None)
        return env

    @staticmethod
    def _sitecustomize_source():
        return '''import hashlib, os, sys, types
import drive_session
class _Protector:
    prefix = b"TESTPROTECTED1"
    def protect(self, plaintext, entropy):
        key = hashlib.sha256(entropy).digest()
        return self.prefix + bytes(v ^ key[i % len(key)] for i, v in enumerate(plaintext))
    def unprotect(self, ciphertext, entropy):
        if not ciphertext.startswith(self.prefix): raise ValueError("invalid test ciphertext")
        key = hashlib.sha256(entropy).digest(); payload = ciphertext[len(self.prefix):]
        return bytes(v ^ key[i % len(key)] for i, v in enumerate(payload))
drive_session.PROTECTOR_FACTORY = _Protector
def _mark(name):
    with open(os.path.join(os.environ["RELAY_TEST_MARKER_DIR"], name), "a", encoding="ascii") as f: f.write("1\\n")
class _Credentials:
    def __init__(self, token=None, refresh_token=None, **kwargs):
        self.token = token; self.refresh_token = refresh_token; self.valid = bool(token)
    def refresh(self, request):
        _mark("refresh-count")
        if os.environ.get("RELAY_TEST_REFRESH_FAIL"): raise RuntimeError("provider-body-secret access-token-secret")
        self.token = "subprocess-access-token-secret"; self.valid = True
        if os.environ.get("RELAY_TEST_ROTATE_REFRESH"): self.refresh_token = "rotated-refresh-secret"
class _Request: pass
class _Flow:
    def run_local_server(self, **kwargs):
        _mark("browser-flow-count")
        return _Credentials("subprocess-access-token-secret", "subprocess-refresh-token-secret")
class _InstalledAppFlow:
    @classmethod
    def from_client_config(cls, config, scopes): return _Flow()
def _module(name, package=False):
    value = types.ModuleType(name)
    if package: value.__path__ = []
    sys.modules[name] = value
    return value
google = _module("google", True)
google_auth = _module("google.auth", True); google.auth = google_auth
transport = _module("google.auth.transport", True); google_auth.transport = transport
requests = _module("google.auth.transport.requests"); requests.Request = _Request; transport.requests = requests
oauth2 = _module("google.oauth2", True); google.oauth2 = oauth2
credentials = _module("google.oauth2.credentials"); credentials.Credentials = _Credentials; oauth2.credentials = credentials
oauth = _module("google_auth_oauthlib", True)
flow = _module("google_auth_oauthlib.flow"); flow.InstalledAppFlow = _InstalledAppFlow; oauth.flow = flow
'''

    def run_cli(self, command, *, extra_args=(), env=None):
        args = [sys.executable, "relay.py", "--config", str(self.config_path)]
        if command and command[0] == "poll-drive":
            args.extend(["--state", str(self.root / "relay-state.json")])
        args.extend(command)
        if command and command[0] in ("qualify-drive", "poll-drive"):
            args.extend(["--api-base-url", self.api_base])
        return subprocess.run(args, capture_output=True, text=True, env=env or self.subprocess_env(), timeout=20)

    def marker_count(self, name):
        path = self.marker_dir / name
        return len(path.read_text(encoding="ascii").splitlines()) if path.exists() else 0

    def test_first_subprocess_persists_protected_token_and_fresh_subprocess_reuses_it(self):
        store = self.make_store()
        self.assertFalse(store.path.exists())
        env = self.subprocess_env()
        first = self.run_cli(["qualify-drive", "--qualification-file-id", "artifact-session"], env=env)
        self.assertEqual(first.returncode, 0, first.stderr)
        first_result = json.loads(first.stdout)
        self.assertEqual(first_result["result"], "QUALIFIED_READ_ONLY")
        self.assertEqual(first_result["byteLength"], len(SessionDriveHandler.artifact_body))
        self.assertEqual(self.marker_count("browser-flow-count"), 1)
        self.assertEqual(self.marker_count("refresh-count"), 0)
        self.assertTrue(store.path.is_file())
        protected = store.path.read_bytes()
        for secret in (b"subprocess-access-token-secret", b"subprocess-refresh-token-secret", b"fake-client-secret", b"authorization-code"):
            self.assertNotIn(secret, protected)

        path_before = store.path
        second = self.run_cli(["qualify-drive", "--qualification-file-id", "artifact-session"], env=env)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(json.loads(second.stdout)["result"], "QUALIFIED_READ_ONLY")
        self.assertEqual(self.marker_count("browser-flow-count"), 1, "fresh process unexpectedly launched browser OAuth")
        self.assertEqual(self.marker_count("refresh-count"), 1)
        self.assertEqual(self.make_store().path, path_before)
        self.assertNotIn("subprocess-access-token-secret", second.stdout + second.stderr)
        self.assertNotIn(SessionDriveHandler.artifact_body.decode().strip(), second.stdout + second.stderr)

    def test_poll_drive_uses_protected_session_across_fresh_processes(self):
        env = self.subprocess_env()
        first = self.run_cli(["poll-drive"], env=env)
        self.assertEqual(first.returncode, 0, first.stderr)
        first_event = json.loads(first.stdout)[0]
        self.assertEqual(first_event["result"], "pending")
        self.assertEqual(self.marker_count("browser-flow-count"), 1)
        state = json.loads((self.root / "relay-state.json").read_text(encoding="utf-8"))
        self.assertEqual(len(state["events"]), 1)

        second = self.run_cli(["poll-drive"], env=env)
        self.assertEqual(second.returncode, 0, second.stderr)
        second_event = json.loads(second.stdout)[0]
        self.assertEqual(second_event["eventId"], first_event["eventId"])
        self.assertEqual(self.marker_count("browser-flow-count"), 1)
        self.assertEqual(self.marker_count("refresh-count"), 1)
        state = json.loads((self.root / "relay-state.json").read_text(encoding="utf-8"))
        self.assertEqual(len(state["events"]), 1)

    def test_client_and_scope_identity_do_not_share_protected_session(self):
        first = self.make_store()
        first.save_refresh_token("unit-refresh-token")
        same_identity = self.make_store()
        other_client = self.make_store("different.apps.googleusercontent.com")
        other_scope = self.make_store(scope="https://www.googleapis.com/auth/drive.file")
        self.assertEqual(first.path, same_identity.path)
        self.assertNotEqual(first.path, other_client.path)
        self.assertNotEqual(first.path, other_scope.path)
        self.assertNotIn(first.client_id, str(first.path))
        self.assertEqual(same_identity.load_refresh_token(), "unit-refresh-token")
        self.assertIsNone(other_client.load_refresh_token())
        self.assertIsNone(other_scope.load_refresh_token())
        other_client.path.parent.mkdir(parents=True, exist_ok=True)
        other_client.path.write_bytes(first.path.read_bytes())
        with self.assertRaises(drive_session.SessionStoreError):
            other_client.load_refresh_token()

    @unittest.skipUnless(os.name == "nt", "Windows DPAPI is available only on Windows")
    def test_windows_dpapi_round_trip_uses_optional_entropy(self):
        protector = drive_session.WindowsDpapi()
        plaintext = b"non-secret DPAPI round-trip check"
        entropy = b"Artifact Relay Google Drive scope test"
        ciphertext = protector.protect(plaintext, entropy)
        self.assertNotEqual(ciphertext, plaintext)
        self.assertEqual(protector.unprotect(ciphertext, entropy), plaintext)
        with self.assertRaises(drive_session.SessionStoreError):
            protector.unprotect(ciphertext, b"different client/scope binding")

    def test_corrupt_protected_session_fails_closed_without_browser_or_traceback(self):
        store = self.make_store()
        store.path.parent.mkdir(parents=True, exist_ok=True)
        store.path.write_bytes(b"tampered-session")
        result = self.run_cli(["qualify-drive", "--qualification-file-id", "artifact-session"], env=self.subprocess_env())
        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("relay error: protected Drive session is invalid", result.stderr)
        self.assertNotIn("Traceback", output)
        self.assertEqual(self.marker_count("browser-flow-count"), 0)
        self.assertNotIn("subprocess-refresh-token-secret", output)
        self.assertTrue(store.path.exists(), "corrupt session was silently removed")

    def test_refresh_failure_is_sanitized_and_preserves_session_without_browser(self):
        store = self.make_store()
        store.save_refresh_token("subprocess-refresh-token-secret")
        before = store.path.read_bytes()
        result = self.run_cli(["qualify-drive", "--qualification-file-id", "artifact-session"],
                              env=self.subprocess_env(refresh_fail=True))
        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("relay error: Google Drive session refresh failed", result.stderr)
        self.assertNotIn("Traceback", output)
        self.assertNotIn("provider-body-secret", output)
        self.assertNotIn("subprocess-refresh-token-secret", output)
        self.assertEqual(self.marker_count("browser-flow-count"), 0)
        self.assertEqual(store.path.read_bytes(), before)

    def test_rotated_refresh_token_replaces_protected_file_atomically(self):
        store = self.make_store()
        store.save_refresh_token("old-refresh-token")
        before = store.path.read_bytes()

        class RotatingCredentials:
            valid = False
            token = None
            refresh_token = "old-refresh-token"

            def __init__(self, **_kwargs):
                self.valid = False
                self.token = None
                self.refresh_token = "old-refresh-token"

            def refresh(self, _request):
                self.token = "rotated-access-token"
                self.refresh_token = "new-refresh-token"
                self.valid = True

        with patch.dict(os.environ, {
            "RELAY_GDRIVE_OAUTH_CLIENT_FILE": str(self.client_file), "LOCALAPPDATA": str(self.appdata),
        }):
            token = drive_auth.get_access_token(
                credentials_class=RotatingCredentials, request_class=lambda: object(), session_store=store,
            )
        self.assertEqual(token, "rotated-access-token")
        self.assertEqual(store.load_refresh_token(), "new-refresh-token")
        self.assertNotEqual(store.path.read_bytes(), before)
        self.assertEqual(list(store.path.parent.glob(".session-*.tmp")), [])

    def test_reset_cli_is_idempotent_local_only_and_next_run_bootstraps_again(self):
        store = self.make_store()
        store.save_refresh_token("subprocess-refresh-token-secret")
        other_store = self.make_store("other.apps.googleusercontent.com")
        other_store.save_refresh_token("other-refresh-token")
        sentinel = store.path.parent / "keep-me.bin"
        sentinel.write_bytes(b"unrelated")
        env = self.subprocess_env()
        before_calls = len(SessionDriveHandler.calls)

        first_reset = self.run_cli(["reset-drive-auth"], env=env)
        self.assertEqual(first_reset.returncode, 0, first_reset.stderr)
        self.assertEqual(json.loads(first_reset.stdout), {"removed": True, "result": "RESET"})
        second_reset = self.run_cli(["reset-drive-auth"], env=env)
        self.assertEqual(second_reset.returncode, 0, second_reset.stderr)
        self.assertEqual(json.loads(second_reset.stdout), {"removed": False, "result": "RESET"})
        self.assertFalse(store.path.exists())
        self.assertTrue(other_store.path.exists())
        self.assertEqual(sentinel.read_bytes(), b"unrelated")
        self.assertEqual(len(SessionDriveHandler.calls), before_calls, "reset contacted Drive")

        after_reset = self.run_cli(["qualify-drive", "--qualification-file-id", "artifact-session"], env=env)
        self.assertEqual(after_reset.returncode, 0, after_reset.stderr)
        self.assertEqual(self.marker_count("browser-flow-count"), 1)
        self.assertTrue(store.path.exists())


if __name__ == "__main__":
    unittest.main()
