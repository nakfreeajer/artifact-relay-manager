import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import drive_auth
import project_registry
import project_supervisor
import relay_windows_service
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
        self.oauth_client_path = self.root / "oauth-client-placeholder.txt"
        # Deliberately not OAuth JSON: service preflight checks only its path.
        self.oauth_client_path.write_text("placeholder; not client data\n", encoding="utf-8")
        self.service_config_path = self.root / "service.json"
        self.write_service_config()

    def tearDown(self):
        self.temp.cleanup()

    def write_service_config(self, *, registry_path=None, oauth_client_file=None, schema_version=1):
        value = {
            "schemaVersion": schema_version,
            "registryPath": str(registry_path or self.registry_path.resolve()),
            "oauthClientFile": str(oauth_client_file or self.oauth_client_path.resolve()),
        }
        self.service_config_path.write_text(json.dumps(value), encoding="utf-8")

    def test_clean_start_stop_reuses_supervisor_with_explicit_config_paths(self):
        session = FakeSession()
        cycle_started = threading.Event()
        seen_sessions = []
        seen_registry_paths = []
        env_seen_by_session = []
        records = []
        original_runner = project_supervisor.run_supervisor

        def session_factory():
            env_seen_by_session.append(os.environ.get("RELAY_GDRIVE_OAUTH_CLIENT_FILE"))
            return session

        def recording_runner(registry_path, **kwargs):
            seen_registry_paths.append(Path(registry_path))
            return original_runner(registry_path, **kwargs)

        def cycle(_entry, shared_session):
            seen_sessions.append(shared_session)
            cycle_started.set()
            return {"observed": 0}

        host = WindowsServiceHost(
            self.service_config_path, interval_seconds=1, session_factory=session_factory,
            supervisor_runner=recording_runner, emit=records.append,
        )
        with patch.object(project_supervisor, "_project_cycle", side_effect=cycle), \
                patch.dict(os.environ, {
                    "LOCALAPPDATA": str(self.root / "unrelated-appdata"),
                    "RELAY_GDRIVE_OAUTH_CLIENT_FILE": "preexisting-process-value",
                }):
            result = []
            worker = threading.Thread(target=lambda: result.append(host.run()))
            worker.start()
            self.assertTrue(cycle_started.wait(2), "supervisor did not complete its first cycle")
            host.request_stop()
            worker.join(2)
            self.assertEqual(os.environ["RELAY_GDRIVE_OAUTH_CLIENT_FILE"], "preexisting-process-value")

        self.assertFalse(worker.is_alive(), "service stop did not wake the supervisor")
        self.assertEqual(result, [0])
        self.assertEqual(seen_sessions, [session])
        self.assertEqual(session.access_calls, 1)
        self.assertEqual(env_seen_by_session, [str(self.oauth_client_path.resolve())])
        self.assertEqual(seen_registry_paths, [self.registry_path.resolve()])
        self.assertEqual(records[-1], {"cycle": 1, "result": "STOPPED"})

    def test_missing_protected_credentials_fail_closed_without_supervisor_start(self):
        records = []
        starts = []

        def unavailable_session():
            raise drive_auth.DriveAuthError("protected session is unavailable")

        host = WindowsServiceHost(
            self.service_config_path, session_factory=unavailable_session,
            supervisor_runner=lambda *_args, **_kwargs: starts.append(True), emit=records.append,
        )
        self.assertEqual(host.run(), 2)
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
            self.service_config_path,
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

    def test_missing_service_config_fails_before_session_or_supervisor(self):
        records = []
        calls = []
        host = WindowsServiceHost(
            self.root / "missing-service.json", session_factory=lambda: calls.append("session"),
            supervisor_runner=lambda *_args, **_kwargs: calls.append("supervisor"), emit=records.append,
        )
        self.assertEqual(host.run(), 2)
        self.assertEqual(calls, [])
        self.assertEqual(records, [{
            "service": "relay", "result": "BLOCKED", "error": "INVALID_SERVICE_CONFIGURATION"
        }])

    def test_malformed_and_noncanonical_service_config_fail_closed(self):
        records = []
        calls = []
        cases = [
            "{",
            json.dumps({"schemaVersion": 2, "registryPath": str(self.registry_path),
                        "oauthClientFile": str(self.oauth_client_path)}),
            json.dumps({"schemaVersion": 1, "registryPath": "relative-registry.json",
                        "oauthClientFile": str(self.oauth_client_path)}),
            json.dumps({"schemaVersion": 1, "registryPath": str(self.root / "missing.json"),
                        "oauthClientFile": str(self.oauth_client_path)}),
            json.dumps({"schemaVersion": 1, "registryPath": str(self.registry_path),
                        "oauthClientFile": str(self.root / "missing-client.json")}),
        ]
        for raw in cases:
            with self.subTest(raw=raw):
                self.service_config_path.write_text(raw, encoding="utf-8")
                records.clear()
                calls.clear()
                host = WindowsServiceHost(
                    self.service_config_path, session_factory=lambda: calls.append("session"),
                    supervisor_runner=lambda *_args, **_kwargs: calls.append("supervisor"),
                    emit=records.append,
                )
                self.assertEqual(host.run(), 2)
                self.assertEqual(calls, [])
                self.assertEqual(records[0]["error"], "INVALID_SERVICE_CONFIGURATION")

    def test_invalid_persisted_registry_fails_before_session_or_supervisor(self):
        self.registry_path.write_text("{}", encoding="utf-8")
        records = []
        calls = []
        host = WindowsServiceHost(
            self.service_config_path, session_factory=lambda: calls.append("session"),
            supervisor_runner=lambda *_args, **_kwargs: calls.append("supervisor"), emit=records.append,
        )
        self.assertEqual(host.run(), 2)
        self.assertEqual(calls, [])
        self.assertEqual(records[0]["error"], "INVALID_SERVICE_CONFIGURATION")

    def test_default_service_config_uses_programdata_not_localappdata(self):
        path = relay_windows_service.default_service_config_path({"PROGRAMDATA": str(self.root)})
        self.assertEqual(path, self.root / "ArtifactRelayManager" / "service.json")
        with self.assertRaises(relay_windows_service.WindowsServiceHostError):
            relay_windows_service.default_service_config_path({})

    def test_pywin32_host_path_is_explicit_and_never_relocated(self):
        win32_package = self.root / "site-packages" / "win32"
        win32_package.mkdir(parents=True)
        module_path = win32_package / "win32service.pyd"
        service_host = win32_package / "pythonservice.exe"
        module_path.write_bytes(b"module marker")
        service_host.write_bytes(b"service host marker")
        self.assertEqual(relay_windows_service.resolve_service_host_path(module_path), service_host)
        self.assertEqual(service_host.read_bytes(), b"service host marker")
        with self.assertRaises(relay_windows_service.WindowsServiceHostError):
            relay_windows_service.resolve_service_host_path(self.root / "missing" / "win32service.pyd")

    def test_registration_without_account_safe_setup_is_blocked(self):
        for command in ("install", "update"):
            with self.subTest(command=command), self.assertRaises(SystemExit) as caught:
                relay_windows_service.reject_implicit_service_registration([command])
            self.assertIn("LocalSystem", str(caught.exception))
        relay_windows_service.reject_implicit_service_registration(["status"])

    def test_installed_modules_import_from_scm_like_working_directory(self):
        source_root = Path(__file__).resolve().parents[1]
        with (source_root / "pyproject.toml").open("rb") as stream:
            import tomllib
            module_names = tomllib.load(stream)["tool"]["setuptools"]["py-modules"]
        user_base = self.root / "isolated-user-base"
        isolated_site = user_base / f"Python{sys.version_info.major}{sys.version_info.minor}" / "site-packages"
        isolated_site.mkdir(parents=True)
        for module_name in module_names:
            shutil.copyfile(source_root / f"{module_name}.py", isolated_site / f"{module_name}.py")
        env = os.environ.copy()
        env.pop("PYTHONPATH", None)
        env.pop("PYTHONNOUSERSITE", None)
        env["PYTHONUSERBASE"] = str(user_base)
        system_directory = Path(os.environ["WINDIR"]) / "System32"
        process = subprocess.run(
            [sys.executable, "-c", (
                "import os, relay_windows_service, site; "
                "assert os.getcwd().casefold() == os.path.join(os.environ['WINDIR'],'System32').casefold(); "
                "assert os.path.commonpath([relay_windows_service.__file__.casefold(), "
                "site.getusersitepackages().casefold()]) == site.getusersitepackages().casefold(); "
                "print('SCM_LIKE_IMPORT_OK')"
            )], cwd=system_directory, env=env, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(process.returncode, 0, process.stderr)
        self.assertEqual(process.stdout.strip(), "SCM_LIKE_IMPORT_OK")


if __name__ == "__main__":
    unittest.main()
