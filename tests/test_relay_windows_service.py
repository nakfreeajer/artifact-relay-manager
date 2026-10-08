import json
import os
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import drive_auth
import project_registry
import project_supervisor
from relay_windows_service import WindowsServiceHost


class FakeSession:
    def __init__(self):
        self.access_calls = 0

    def access_token(self):
        self.access_calls += 1
        return "in-memory-test-token"


class RelayWindowsServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.registry_path = self.root / "registry.json"
        config_path = self.root / "config.json"
        config_path.write_text(json.dumps({
            "schemaVersion": 1,
            "projectId": "service-test",
            "repository": "owner/repo",
            "folderId": "folder-service-test",
            "relayWorkspace": str(self.root / "workspace"),
            "watcherEndpoint": "http://127.0.0.1:49152/",
            "eventType": "ARTIFACT_CHANGED",
        }), encoding="utf-8")
        project_registry.ProjectRegistry(self.registry_path).add(
            "service-test", "Service test", config_path, self.root / "state.json"
        )

    def tearDown(self):
        self.temp.cleanup()

    def test_clean_start_stop_reuses_existing_supervisor_and_session(self):
        session = FakeSession()
        cycle_started = threading.Event()
        seen_sessions = []
        records = []

        def cycle(_entry, shared_session):
            seen_sessions.append(shared_session)
            cycle_started.set()
            return {"observed": 0}

        host = WindowsServiceHost(
            self.registry_path, interval_seconds=1, session_factory=lambda: session, emit=records.append
        )
        with patch.object(project_supervisor, "_project_cycle", side_effect=cycle):
            result = []
            worker = threading.Thread(target=lambda: result.append(host.run()))
            worker.start()
            self.assertTrue(cycle_started.wait(2), "supervisor did not complete its first cycle")
            host.request_stop()
            worker.join(2)

        self.assertFalse(worker.is_alive(), "service stop did not wake the supervisor")
        self.assertEqual(result, [0])
        self.assertEqual(seen_sessions, [session])
        self.assertEqual(session.access_calls, 1)
        self.assertEqual(records[-1], {"cycle": 1, "result": "STOPPED"})

    def test_missing_protected_credentials_fail_closed_without_supervisor_start(self):
        records = []
        starts = []
        client_file = self.root / "oauth-client.json"
        client_file.write_text(json.dumps({"installed": {
            "client_id": "service-test-client",
            "client_secret": "test-only-secret",
            "token_uri": "https://oauth.example.invalid/token",
            "auth_uri": "https://oauth.example.invalid/authorize",
        }}), encoding="utf-8")
        with patch.dict(os.environ, {
            "RELAY_GDRIVE_OAUTH_CLIENT_FILE": str(client_file),
            "LOCALAPPDATA": str(self.root / "empty-appdata"),
        }):
            host = WindowsServiceHost(
                self.registry_path,
                session_factory=drive_auth.DriveAuthSession,
                supervisor_runner=lambda *_args, **_kwargs: starts.append(True),
                emit=records.append,
            )
            result = host.run()
        self.assertEqual(result, 2)
        self.assertEqual(starts, [])
        self.assertEqual(records, [{
            "service": "relay", "result": "BLOCKED", "error": "PROTECTED_SESSION_UNAVAILABLE"
        }])

    def test_incompatible_service_identity_dpapi_failure_fails_before_monitoring(self):
        class OtherWindowsIdentitySession:
            def access_token(self):
                raise drive_auth.DriveAuthError("DPAPI current-user session cannot be decrypted")

        records = []
        starts = []
        host = WindowsServiceHost(
            self.registry_path,
            session_factory=OtherWindowsIdentitySession,
            supervisor_runner=lambda *_args, **_kwargs: starts.append(True),
            emit=records.append,
        )
        self.assertEqual(host.run(), 2)
        self.assertEqual(starts, [])
        self.assertEqual(records, [{
            "service": "relay", "result": "BLOCKED", "error": "PROTECTED_SESSION_UNAVAILABLE"
        }])
        self.assertNotIn("DPAPI", json.dumps(records))


if __name__ == "__main__":
    unittest.main()
