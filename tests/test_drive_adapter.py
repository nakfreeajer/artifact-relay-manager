import hashlib
import http.server
import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import drive_adapter
import relay


class DriveHandler(http.server.BaseHTTPRequestHandler):
    files = {}
    identity_ids = ["identity"]
    identity_bytes = b""
    auth_expected = "test-token"
    fail = False
    fail_status = 503
    calls = []
    after_media = None

    def do_GET(self):
        type(self).calls.append((self.path, self.headers.get("Authorization")))
        if self.headers.get("Authorization") != "Bearer " + type(self).auth_expected:
            return self.send_error(401)
        if type(self).fail:
            return self.send_error(type(self).fail_status)
        parsed = urlsplit(self.path)
        params = parse_qs(parsed.query)
        if parsed.path.endswith("/files"):
            name_query = "name = '.relay-project.json'" in params.get("q", [""])[0]
            files = []
            ids = type(self).identity_ids if name_query else list(type(self).files)
            for file_id in ids:
                item = type(self).files.get(file_id)
                if item:
                    files.append({key: value for key, value in item.items() if key != "data"})
            return self.respond(json.dumps({"files": files}).encode(), "application/json")
        file_id = parsed.path.rsplit("/", 1)[-1]
        if file_id not in type(self).files:
            return self.send_error(404)
        item = type(self).files[file_id]
        if params.get("alt") == ["media"]:
            data = type(self).identity_bytes if file_id == "identity" else item.get("data", b"")
            if file_id != "identity" and type(self).after_media is not None:
                type(self).after_media(file_id)
            return self.respond(data, "application/octet-stream")
        return self.respond(json.dumps({key: value for key, value in item.items() if key != "data"}).encode(), "application/json")

    def respond(self, body, mime):
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


class WatcherHandler(http.server.BaseHTTPRequestHandler):
    events = []

    def do_POST(self):
        body = self.rfile.read(int(self.headers["Content-Length"]))
        self.events.append(json.loads(body))
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"disposition":"RECEIVED"}')

    def log_message(self, *_args):
        pass


class DriveAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.workspace = self.root / "relay-workspace"
        self.config_path = self.root / "drive-project.json"
        self.state_path = self.root / "state.json"
        self.folder = "folder-1"
        DriveHandler.files = {
            self.folder: {"id": self.folder, "name": "root", "mimeType": drive_adapter.FOLDER_MIME, "parents": [], "trashed": False},
            "identity": {"id": "identity", "name": ".relay-project.json", "mimeType": "application/json", "parents": [self.folder], "trashed": False, "version": "1", "size": "70", "capabilities": {"canDownload": True}},
            "artifact-1": {"id": "artifact-1", "name": "input.bin", "mimeType": "application/octet-stream", "parents": [self.folder], "trashed": False, "version": "10", "size": "7", "capabilities": {"canDownload": True}, "data": b"caf\xc3\xa9\r\n"},
        }
        DriveHandler.identity_ids = ["identity"]
        DriveHandler.identity_bytes = self.identity("project-1", "example/repo")
        DriveHandler.auth_expected = "test-token"
        DriveHandler.fail = False
        DriveHandler.fail_status = 503
        DriveHandler.calls = []
        DriveHandler.after_media = None
        WatcherHandler.events = []
        self.drive, self.drive_thread = self.start_server(DriveHandler)
        self.watcher, self.watcher_thread = self.start_server(WatcherHandler)
        self.api_base = f"http://127.0.0.1:{self.drive.server_port}/drive/v3"
        self.config = {"schemaVersion": 1, "projectId": "project-1", "repository": "example/repo", "folderId": self.folder,
                       "relayWorkspace": str(self.workspace), "watcherEndpoint": f"http://127.0.0.1:{self.watcher.server_port}/", "eventType": "PROMPT_READY"}
        self.write_config()

    def start_server(self, handler):
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        return server, thread

    def identity(self, project, repository):
        return json.dumps({"schemaVersion": 1, "projectId": project, "repository": repository}, separators=(",", ":")).encode()

    def write_config(self):
        self.config_path.write_text(json.dumps(self.config), encoding="utf-8")

    def poll(self, **kwargs):
        return drive_adapter.poll_drive(self.config_path, self.state_path, token="test-token", api_base_url=self.api_base, **kwargs)

    def script_cli(self, *, bootstrap_oauth=False, extra_env=None):
        DriveHandler.files["artifact-1"]["data"] = b"body-secret"
        DriveHandler.files["artifact-1"]["size"] = str(len(b"body-secret"))
        env = os.environ.copy()
        env.pop("RELAY_GDRIVE_OAUTH_CLIENT_FILE", None)
        if bootstrap_oauth:
            DriveHandler.auth_expected = "subprocess-token-secret"
            bootstrap = self.root / "subprocess-bootstrap"
            bootstrap.mkdir(exist_ok=True)
            (bootstrap / "sitecustomize.py").write_text(
                "import sys, types\n"
                "package = types.ModuleType('google_auth_oauthlib')\npackage.__path__ = []\n"
                "flow_module = types.ModuleType('google_auth_oauthlib.flow')\n"
                "class _Credentials:\n    valid = True\n    token = 'subprocess-token-secret'\n"
                "class _Flow:\n    def run_local_server(self, **kwargs): return _Credentials()\n"
                "class _InstalledAppFlow:\n    @classmethod\n    def from_client_config(cls, config, scopes): return _Flow()\n"
                "flow_module.InstalledAppFlow = _InstalledAppFlow\npackage.flow = flow_module\n"
                "sys.modules['google_auth_oauthlib'] = package\n"
                "sys.modules['google_auth_oauthlib.flow'] = flow_module\n",
                encoding="utf-8",
            )
            client_file = self.root / "oauth-client.json"
            client_file.write_text(json.dumps({"installed": {"client_id": "test-client", "client_secret": "oauth-client-secret", "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token"}}), encoding="utf-8")
            env["RELAY_GDRIVE_OAUTH_CLIENT_FILE"] = str(client_file)
            env["PYTHONPATH"] = str(bootstrap) + os.pathsep + env.get("PYTHONPATH", "")
        if extra_env:
            env.update(extra_env)
        return subprocess.run(
            [sys.executable, "relay.py", "--config", str(self.config_path), "qualify-drive",
             "--qualification-file-id", "artifact-1", "--api-base-url", self.api_base],
            capture_output=True, text=True, env=env, timeout=15,
        )

    def tearDown(self):
        for server in (self.drive, self.watcher):
            server.shutdown()
            server.server_close()
        self.temp.cleanup()

    def test_valid_identity_stages_exact_bytes_and_delivers(self):
        result = self.poll()
        self.assertEqual(result[0]["result"], "delivered")
        staged = self.workspace / "staged" / hashlib.sha256(b"project-1").hexdigest() / hashlib.sha256(b"artifact-1").hexdigest() / "10.bin"
        self.assertEqual(staged.read_bytes(), b"caf\xc3\xa9\r\n")
        event = WatcherHandler.events[0]
        self.assertEqual(event["artifact"]["byteLength"], 7)
        self.assertEqual(event["artifact"]["sha256"], hashlib.sha256(b"caf\xc3\xa9\r\n").hexdigest())
        self.assertIsNone(event["taskId"])

    def test_project_id_mismatch_stops_before_delivery(self):
        DriveHandler.identity_bytes = self.identity("wrong-project", "example/repo")
        with self.assertRaises(drive_adapter.DriveError): self.poll()
        self.assertFalse(WatcherHandler.events)

    def test_repository_mismatch_stops_before_delivery(self):
        DriveHandler.identity_bytes = self.identity("project-1", "other/repo")
        with self.assertRaises(drive_adapter.DriveError): self.poll()
        self.assertFalse(WatcherHandler.events)

    def test_missing_duplicate_and_malformed_identity_fail_closed(self):
        for ids, content in (([], DriveHandler.identity_bytes), (["identity", "identity"], DriveHandler.identity_bytes), (["identity"], b"{")):
            with self.subTest(ids=ids, content=content[:1]):
                DriveHandler.identity_ids = ids
                DriveHandler.identity_bytes = content
                with self.assertRaises(drive_adapter.DriveError): self.poll()
                self.assertFalse(WatcherHandler.events)

    def test_native_identity_document_is_hard_stop(self):
        DriveHandler.files["identity"]["mimeType"] = "application/vnd.google-apps.document"
        with self.assertRaises(drive_adapter.DriveError): self.poll()
        self.assertFalse(WatcherHandler.events)

    def test_exact_unicode_and_line_endings(self):
        DriveHandler.files["artifact-lf"] = {"id": "artifact-lf", "name": "lf", "mimeType": "text/plain", "parents": [self.folder], "trashed": False, "version": "2", "size": "6", "capabilities": {"canDownload": True}, "data": "naïve\n".encode()}
        DriveHandler.files["artifact-lf"]["size"] = str(len(DriveHandler.files["artifact-lf"]["data"]))
        self.poll()
        crlf = WatcherHandler.events[0]["artifact"]["sha256"]
        lf_event = next(e for e in WatcherHandler.events if e["artifact"]["artifactId"] == "artifact-lf")
        self.assertNotEqual(crlf, lf_event["artifact"]["sha256"])
        path = self.workspace / "staged" / hashlib.sha256(b"project-1").hexdigest() / hashlib.sha256(b"artifact-lf").hexdigest() / "2.bin"
        self.assertEqual(path.read_bytes(), "naïve\n".encode())

    def test_same_version_deduplicates_new_version_creates_event(self):
        first = self.poll()[0]
        repeated = self.poll()[0]
        self.assertEqual(first["eventId"], repeated["eventId"])
        self.assertEqual(repeated["result"], "deduplicated")
        self.assertEqual(len(WatcherHandler.events), 1)
        DriveHandler.files["artifact-1"]["version"] = "11"
        DriveHandler.files["artifact-1"]["data"] = b"updated"
        DriveHandler.files["artifact-1"]["size"] = "7"
        newer = self.poll()[0]
        self.assertNotEqual(first["eventId"], newer["eventId"])
        self.assertEqual(len(WatcherHandler.events), 2)

    def test_workspace_file_skipped_without_export(self):
        DriveHandler.files["doc-1"] = {"id": "doc-1", "name": "native", "mimeType": "application/vnd.google-apps.document", "parents": [self.folder], "trashed": False, "version": "2", "size": "100", "capabilities": {"canDownload": True}}
        result = self.poll()
        self.assertEqual(next(x["result"] for x in result if x.get("fileId") == "doc-1"), "skipped_workspace_file")
        self.assertEqual(len(WatcherHandler.events), 1)

    def test_oversized_blocked_before_delivery(self):
        DriveHandler.files["big"] = {"id": "big", "name": "big", "mimeType": "application/octet-stream", "parents": [self.folder], "trashed": False, "version": "2", "size": str(relay.MAX_BYTES + 1), "capabilities": {"canDownload": True}, "data": b""}
        result = self.poll()
        self.assertEqual(next(x["result"] for x in result if x.get("fileId") == "big"), "blocked_oversized")
        self.assertEqual(len(WatcherHandler.events), 1)
        self.assertNotIn("big", [event["artifact"]["artifactId"] for event in WatcherHandler.events])

    def test_auth_and_http_failures_never_deliver(self):
        with self.assertRaises(drive_adapter.DriveError): drive_adapter.poll_drive(self.config_path, self.state_path, token="wrong", api_base_url=self.api_base)
        self.assertFalse(WatcherHandler.events)
        DriveHandler.fail = True
        with self.assertRaises(drive_adapter.DriveError): self.poll()
        self.assertFalse(WatcherHandler.events)

    def test_same_size_version_race_fails_before_staging_or_delivery(self):
        def change_version(file_id):
            item = DriveHandler.files[file_id]
            item["version"] = "11"
            item["data"] = b"updated"
        DriveHandler.after_media = change_version
        with self.assertRaises(drive_adapter.DriveError): self.poll()
        self.assertFalse(WatcherHandler.events)
        self.assertFalse(self.state_path.exists())
        staged = self.workspace / "staged" / hashlib.sha256(b"project-1").hexdigest() / hashlib.sha256(b"artifact-1").hexdigest() / "10.bin"
        self.assertFalse(staged.exists())

    def test_post_download_parent_and_state_races_fail_closed(self):
        changes = (
            ("moved", lambda item: item.update(parents=["other-folder"])),
            ("trashed", lambda item: item.update(trashed=True)),
            ("workspace", lambda item: item.update(mimeType="application/vnd.google-apps.document")),
            ("not-downloadable", lambda item: item.update(capabilities={"canDownload": False})),
        )
        for name, change in changes:
            with self.subTest(name=name):
                DriveHandler.files["artifact-1"].update({"mimeType": "application/octet-stream", "parents": [self.folder], "trashed": False, "capabilities": {"canDownload": True}, "version": "10", "size": "7", "data": b"caf\xc3\xa9\r\n"})
                DriveHandler.after_media = lambda file_id, change=change: change(DriveHandler.files[file_id])
                with self.assertRaises(drive_adapter.DriveError): self.poll()
                self.assertFalse(WatcherHandler.events)
                self.assertFalse(self.state_path.exists())
        DriveHandler.after_media = None

    def test_identity_change_after_staging_aborts_before_delivery(self):
        DriveHandler.after_media = lambda _file_id: setattr(DriveHandler, "identity_bytes", self.identity("changed-project", "example/repo"))
        with self.assertRaises(drive_adapter.DriveError): self.poll()
        self.assertFalse(WatcherHandler.events)
        self.assertFalse(self.state_path.exists())

    def test_test_api_override_rejects_remote_host(self):
        with self.assertRaises(drive_adapter.DriveError): drive_adapter.DriveClient("test-token", "https://example.com")

    def test_read_only_qualification_hashes_designated_exact_raw_bytes_without_event_state(self):
        result = drive_adapter.qualify_drive(self.config_path, "artifact-1", "test-token", self.api_base)
        self.assertEqual(result, {
            "projectId": "project-1", "folderId": self.folder, "qualificationFileId": "artifact-1",
            "version": "10", "byteLength": 7, "sha256": hashlib.sha256(b"caf\xc3\xa9\r\n").hexdigest(),
            "mimeType": "application/octet-stream", "result": "QUALIFIED_READ_ONLY",
        })
        self.assertFalse(self.state_path.exists())
        self.assertFalse(WatcherHandler.events)
        self.assertFalse((self.workspace / "staged").exists())

    def test_qualification_rejects_outside_folder_and_invalid_designated_items(self):
        DriveHandler.files["outside"] = {"id": "outside", "name": "outside", "mimeType": "application/octet-stream", "parents": ["elsewhere"], "trashed": False, "version": "1", "size": "1", "capabilities": {"canDownload": True}, "data": b"x"}
        with self.assertRaises(drive_adapter.DriveError):
            drive_adapter.qualify_drive(self.config_path, "outside", "test-token", self.api_base)
        cases = (
            ("folder", {"mimeType": drive_adapter.FOLDER_MIME}),
            ("native", {"mimeType": "application/vnd.google-apps.document"}),
            ("trashed", {"trashed": True}),
            ("not-downloadable", {"capabilities": {"canDownload": False}}),
            ("oversized", {"size": str(relay.MAX_BYTES + 1)}),
        )
        for name, changes in cases:
            with self.subTest(name=name):
                original = dict(DriveHandler.files["artifact-1"])
                DriveHandler.files["artifact-1"].update(changes)
                with self.assertRaises(drive_adapter.DriveError):
                    drive_adapter.qualify_drive(self.config_path, "artifact-1", "test-token", self.api_base)
                DriveHandler.files["artifact-1"] = original
        self.assertFalse(WatcherHandler.events)
        self.assertFalse(self.state_path.exists())

    def test_qualification_rejects_artifact_version_and_project_identity_races(self):
        DriveHandler.after_media = lambda file_id: DriveHandler.files[file_id].update(version="11")
        with self.assertRaises(drive_adapter.DriveError):
            drive_adapter.qualify_drive(self.config_path, "artifact-1", "test-token", self.api_base)
        self.assertFalse(WatcherHandler.events)
        self.assertFalse(self.state_path.exists())
        DriveHandler.files["artifact-1"]["version"] = "10"
        DriveHandler.after_media = lambda _file_id: setattr(DriveHandler, "identity_bytes", self.identity("other-project", "example/repo"))
        with self.assertRaises(drive_adapter.DriveError):
            drive_adapter.qualify_drive(self.config_path, "artifact-1", "test-token", self.api_base)
        DriveHandler.after_media = None
        self.assertFalse(WatcherHandler.events)
        self.assertFalse(self.state_path.exists())

    def test_qualification_cli_outputs_metadata_only_and_uses_ephemeral_token(self):
        from contextlib import redirect_stdout
        import io

        output = io.StringIO()
        args = ["relay.py", "--config", str(self.config_path), "qualify-drive", "--qualification-file-id", "artifact-1", "--api-base-url", self.api_base]
        DriveHandler.auth_expected = "access-token-secret"
        with patch("sys.argv", args), patch("drive_auth.get_access_token", return_value="access-token-secret"), redirect_stdout(output):
            self.assertEqual(relay.main(), 0)
        rendered = output.getvalue()
        payload = json.loads(rendered)
        self.assertEqual(payload["result"], "QUALIFIED_READ_ONLY")
        self.assertNotIn("access-token-secret", rendered)
        self.assertNotIn("caf\u00e9", rendered)
        self.assertFalse(self.state_path.exists())
        self.assertFalse(WatcherHandler.events)

    def test_script_cli_catches_http_403_without_traceback_or_sensitive_data(self):
        DriveHandler.fail = True
        DriveHandler.fail_status = 403
        result = self.script_cli(bootstrap_oauth=True)
        combined = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("relay error: Google Drive API returned HTTP 403", result.stderr)
        self.assertNotIn("Traceback", combined)
        for secret in ("subprocess-token-secret", "oauth-client-secret", "authorization-code-secret", "body-secret"):
            self.assertNotIn(secret, combined)

    def test_script_cli_missing_oauth_client_is_sanitized(self):
        result = self.script_cli()
        combined = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("relay error: RELAY_GDRIVE_OAUTH_CLIENT_FILE is not set", result.stderr)
        self.assertNotIn("Traceback", combined)

    def test_script_cli_success_still_qualifies_with_metadata_only_output(self):
        result = self.script_cli(bootstrap_oauth=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        output = json.loads(result.stdout)
        self.assertEqual(output["result"], "QUALIFIED_READ_ONLY")
        self.assertEqual(output["byteLength"], len(b"body-secret"))
        self.assertNotIn("subprocess-token-secret", result.stdout + result.stderr)
        self.assertNotIn("caf\u00e9", result.stdout + result.stderr)
        self.assertFalse(self.state_path.exists())
        self.assertFalse(WatcherHandler.events)

    def test_outside_root_never_processed_and_trashed_ignored(self):
        DriveHandler.files["outside"] = {"id": "outside", "name": "outside", "mimeType": "application/octet-stream", "parents": ["other-folder"], "trashed": False, "version": "4", "size": "7", "capabilities": {"canDownload": True}, "data": b"outside"}
        DriveHandler.files["trashed"] = {"id": "trashed", "name": "trash", "mimeType": "application/octet-stream", "parents": [self.folder], "trashed": True, "version": "1", "size": "5", "capabilities": {"canDownload": True}, "data": b"trash"}
        self.poll()
        self.assertEqual(len(WatcherHandler.events), 1)
        self.assertEqual(WatcherHandler.events[0]["artifact"]["artifactId"], "artifact-1")

    def test_no_token_or_artifact_body_in_cli_output(self):
        result = subprocess.run([sys.executable, "relay.py", "--config", str(self.config_path), "--state", str(self.state_path), "poll-drive", "--api-base-url", self.api_base], capture_output=True, text=True, env={**os.environ, "RELAY_GDRIVE_ACCESS_TOKEN": "test-token"})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("test-token", result.stdout + result.stderr)
        self.assertNotIn("café", result.stdout + result.stderr)

    def test_pending_drive_event_retries_same_id_after_restart(self):
        watcher_port = self.watcher.server_port
        self.watcher.shutdown(); self.watcher.server_close()
        first = self.poll()[0]
        self.assertEqual(first["result"], "pending")
        core_config = self.workspace / ".relay-core-config.json"
        new_watcher = http.server.ThreadingHTTPServer(("127.0.0.1", watcher_port), WatcherHandler)
        threading.Thread(target=new_watcher.serve_forever, daemon=True).start()
        retry_result = relay.retry(core_config, self.state_path)
        self.assertEqual(retry_result, [(first["eventId"], "delivered")])
        self.assertEqual(WatcherHandler.events[-1]["eventId"], first["eventId"])
        new_watcher.shutdown(); new_watcher.server_close()


if __name__ == "__main__":
    unittest.main()
