from __future__ import annotations

import json
import base64
from contextlib import redirect_stdout
from io import StringIO
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import arm_v2_userhost
from arm_v2_userhost import UserHostError, _emit, _ensure_loopback_registry, _safe_cycle, load_config
from project_folder_config import FakeDriveProvider
from project_registry import ProjectRegistry
from tests.mock_apo import SimulatedApo
from tests.test_arm_foreground import KEYS, folder_fixture, snapshots


class ArmV2UserHostTests(unittest.TestCase):
    def test_provider_mode_is_explicit_and_legacy_config_stays_fixture(self):
        with tempfile.TemporaryDirectory(prefix="arm-userhost-modes-") as raw:
            root = Path(raw).resolve()
            registry = root / "projects.json"
            fixture = root / "provider.json"
            host_config = root / "host.json"
            oauth_client = root / "oauth.json"
            registry.write_text('{"schemaVersion":2,"projects":[],"folderProjects":[]}', encoding="utf-8")
            fixture.write_text('{"folders":{},"fail":false}', encoding="utf-8")
            oauth_client.write_text(json.dumps({"installed": {"client_id": "offline",
                "client_secret": "synthetic", "token_uri": "https://oauth2.googleapis.com/token",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth"}}), encoding="utf-8")
            base = {"schemaVersion": 1, "registryPath": str(registry),
                    "detectorStatePath": str(root / "detector.json"),
                    "notificationLedgerPath": str(root / "ledger.json"),
                    "testSecrets": {"test:project-a": base64.b64encode(b"a" * 32).decode("ascii")},
                    "intervalSeconds": 1, "stopTimeoutSeconds": 2}
            with patch.dict(os.environ, {"LOCALAPPDATA": str(root),
                    "RELAY_GDRIVE_OAUTH_CLIENT_FILE": str(oauth_client)}, clear=False):
                host_config.write_text(json.dumps(dict(base, providerFixturePath=str(fixture))), encoding="utf-8")
                self.assertEqual(load_config(host_config).provider_mode, "fixture")
                host_config.write_text(json.dumps(dict(base, providerMode="drive")), encoding="utf-8")
                drive_config = load_config(host_config)
                self.assertEqual(drive_config.provider_mode, "drive")
                self.assertIsNone(drive_config.fixture_path)
                host_config.write_text(json.dumps(dict(base, providerMode="drive",
                    providerFixturePath=str(fixture))), encoding="utf-8")
                with self.assertRaises(UserHostError):
                    load_config(host_config)
                host_config.write_text(json.dumps(dict(base, providerMode="fixture")), encoding="utf-8")
                with self.assertRaises(UserHostError):
                    load_config(host_config)
                host_config.write_text(json.dumps(dict(base, providerMode="drive",
                    maxMonitorObservations=7)), encoding="utf-8")
                with self.assertRaises(UserHostError):
                    load_config(host_config)
                host_config.write_text(json.dumps(dict(base, providerMode="drive",
                    maxMonitorObservations=6)), encoding="utf-8")
                self.assertEqual(load_config(host_config).max_monitor_observations, 6)
                with patch.dict(os.environ, {"RELAY_GDRIVE_OAUTH_CLIENT_FILE": ""}):
                    with self.assertRaises(UserHostError):
                        load_config(host_config)

    def test_authenticated_drive_provider_reuses_readonly_session_and_monitor_ack_path(self):
        from arm_foreground import ForegroundMonitor
        from project_folder_config import FOLDER_MIME

        with tempfile.TemporaryDirectory(prefix="arm-userhost-drive-provider-") as raw:
            root = Path(raw)
            receiver = SimulatedApo("project-a", KEYS["test:project-a"], root / "receipt.json")
            registry_path = root / "projects.json"
            detector_path = root / "detector.json"
            ledger_path = root / "ledger.json"
            registry = ProjectRegistry(registry_path)
            registry.configure_folder_project(
                project_id="project-a", display_name="Project A",
                root_url="https://drive.google.com/drive/folders/root-a",
                prompts_id="prompts-a", reports_id="reports-a", endpoint=receiver.url,
                provider=FakeDriveProvider(folder_fixture()), repository="owner/project-a",
                secret_ref="test:project-a", enabled=True)
            oauth_client = root / "oauth.json"
            oauth_client.write_text(json.dumps({"installed": {"client_id": "synthetic",
                "client_secret": "synthetic", "token_uri": "https://oauth2.googleapis.com/token",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth"}}), encoding="utf-8")
            session_calls = []

            class Session:
                def access_token(self):
                    session_calls.append("access_token")
                    return "synthetic-memory-only-token"

            class Client:
                def __init__(self, token):
                    self.token = token
                    self.items = snapshots()

                def metadata(self, item_id):
                    return {"id": item_id, "name": "Project A", "mimeType": FOLDER_MIME,
                            "trashed": False, "parents": []}

                def list_children(self, item_id):
                    if item_id == "root-a":
                        return [{"id": "prompts-a", "name": "Architect_Prompts", "mimeType": FOLDER_MIME,
                                 "parents": ["root-a"], "trashed": False},
                                {"id": "reports-a", "name": "Executor_Reports", "mimeType": FOLDER_MIME,
                                 "parents": ["root-a"], "trashed": False}]
                    return self.items["folders"][item_id]["items"]

            try:
                with patch.dict(os.environ, {"RELAY_GDRIVE_OAUTH_CLIENT_FILE": str(oauth_client)}):
                    provider = arm_v2_userhost.AuthenticatedDriveMetadataProvider(
                        registry_path, session_factory=Session, client_factory=Client)
                    client = provider._client()
                    monitor = ForegroundMonitor(registry_path, detector_path, ledger_path,
                        provider=provider, secret_resolver=KEYS.get, interval_seconds=1)
                    baseline = monitor.cycle(1)
                    self.assertEqual(baseline["events"], [])
                    self.assertEqual(receiver.request_count, 0)
                    client.items = snapshots(arrivals=True)
                    monitor.cycle(2)
                    arrival = monitor.cycle(3)
                    self.assertEqual(len(arrival["events"]), 1)
                    event = arrival["events"][0]
                    self.assertEqual((event["projectId"], event["eventType"], event["changeKind"]),
                                     ("project-a", "PROMPT_CHANGED", "ARRIVED"))
                    self.assertEqual(arrival["delivery"]["ackedThisRun"], 1)
                    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
                    self.assertEqual(ledger["entries"][event["eventId"]]["status"], "ACKED")
                    self.assertEqual(receiver.request_count, 1)
                    self.assertEqual(receiver.processed_count, 1)
                    repeated = ForegroundMonitor(registry_path, detector_path, ledger_path,
                        provider=provider, secret_resolver=KEYS.get, interval_seconds=1).cycle(4)
                    self.assertEqual(repeated["events"], [])
                    self.assertEqual(receiver.request_count, 1)
                    with self.assertRaises(UserHostError):
                        provider.list_folder("reports-b")
                    serialized = ledger_path.read_text(encoding="utf-8")
                    self.assertNotIn("synthetic-memory-only-token", serialized)
                    self.assertNotIn("Disposable", serialized)
                    self.assertGreaterEqual(len(session_calls), 8)
            finally:
                receiver.close()

    def test_drive_observation_budget_is_durable_and_fails_closed(self):
        with tempfile.TemporaryDirectory(prefix="arm-userhost-budget-") as raw:
            root = Path(raw).resolve()
            registry = root / "projects.json"
            oauth_client = root / "oauth.json"
            host_config = root / "host.json"
            registry.write_text('{"schemaVersion":2,"projects":[],"folderProjects":[]}', encoding="utf-8")
            oauth_client.write_text("{}", encoding="utf-8")
            values = {"schemaVersion": 1, "registryPath": str(registry),
                "detectorStatePath": str(root / "detector.json"),
                "notificationLedgerPath": str(root / "ledger.json"), "providerMode": "drive",
                "maxMonitorObservations": 6,
                "testSecrets": {"test:project-a": base64.b64encode(b"a" * 32).decode("ascii")},
                "intervalSeconds": 1, "stopTimeoutSeconds": 2}
            host_config.write_text(json.dumps(values), encoding="utf-8")
            with patch.dict(os.environ, {"LOCALAPPDATA": str(root),
                    "RELAY_GDRIVE_OAUTH_CLIENT_FILE": str(oauth_client)}, clear=False):
                config = load_config(host_config)
                budget = arm_v2_userhost._observation_budget(config)
                self.assertEqual(budget["consumed"], 0)
                budget["consumed"] = 4
                arm_v2_userhost._persist_observation_budget(config, budget)
                self.assertEqual(arm_v2_userhost._observation_budget(config)["consumed"], 4)
                corrupt = dict(budget, configDigest="0" * 64)
                config.observation_budget_path.write_text(json.dumps(corrupt), encoding="utf-8")
                with self.assertRaises(UserHostError):
                    arm_v2_userhost._observation_budget(config)
                budget["consumed"] = 6
                arm_v2_userhost._persist_observation_budget(config, budget)
                pause = config.pause_store.initialize([])
                heartbeat = arm_v2_userhost._heartbeat(config, state="STOPPED",
                    worker_id="d" * 32, cycle=6, recent={"cycle": 6}, pause_state=pause)
                arm_v2_userhost._atomic_json(config.heartbeat_path, heartbeat)
                class ExitedWorker:
                    returncode = 0
                    pid = os.getpid()
                self.assertEqual(arm_v2_userhost._bounded_worker_completed(
                    config, ExitedWorker())["reason"], "OBSERVATION_LIMIT")

    def test_drive_mode_authentication_fails_closed_and_destination_allowlist_is_narrow(self):
        from drive_auth import DriveAuthError
        with tempfile.TemporaryDirectory(prefix="arm-userhost-drive-auth-gate-") as raw:
            root = Path(raw)
            oauth_client = root / "oauth.json"
            session_attempts = []
            def session_failure():
                session_attempts.append("protected-session")
                raise DriveAuthError("sanitized offline failure")
            oauth_client.write_text(json.dumps({"installed": {"client_id": "synthetic",
                "client_secret": "synthetic", "token_uri": "https://evil.invalid/token",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth"}}), encoding="utf-8")
            with patch.dict(os.environ, {"RELAY_GDRIVE_OAUTH_CLIENT_FILE": str(oauth_client)}):
                with self.assertRaises(UserHostError):
                    arm_v2_userhost.AuthenticatedDriveMetadataProvider(
                        root / "projects.json", session_factory=session_failure)
                self.assertEqual(session_attempts, [])
                oauth_client.write_text(json.dumps({"installed": {"client_id": "synthetic",
                    "client_secret": "synthetic", "token_uri": "https://oauth2.googleapis.com/token",
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth"}}), encoding="utf-8")
                with self.assertRaises(DriveAuthError):
                    arm_v2_userhost.AuthenticatedDriveMetadataProvider(
                        root / "projects.json", session_factory=session_failure)
                self.assertEqual(session_attempts, ["protected-session"])

        allowed = arm_v2_userhost._provider_network_destination_allowed
        self.assertTrue(allowed("fixture", ("127.0.0.1", 4567)))
        self.assertTrue(allowed("drive", ("::1", 4567)))
        self.assertTrue(allowed("drive", ("www.googleapis.com", 443)))
        self.assertTrue(allowed("drive", ("oauth2.googleapis.com", 443)))
        self.assertFalse(allowed("fixture", ("www.googleapis.com", 443)))
        self.assertFalse(allowed("drive", ("www.googleapis.com", 80)))
        self.assertFalse(allowed("drive", ("192.168.1.5", 443)))
        self.assertFalse(allowed("drive", ("0.0.0.0", 443)))
        self.assertFalse(allowed("drive", ("example.com", 443)))
        token_url_allowed = arm_v2_userhost._google_token_url_allowed
        self.assertTrue(token_url_allowed("https://oauth2.googleapis.com/token"))
        self.assertTrue(token_url_allowed("https://oauth2.googleapis.com:443/token"))
        for url in ("http://oauth2.googleapis.com/token", "https://oauth2.googleapis.com.evil.invalid/token",
                    "https://user@oauth2.googleapis.com/token", "https://oauth2.googleapis.com:444/token",
                    "https://oauth2.googleapis.com/other", "https://oauth2.googleapis.com/token?next=x",
                    "https://oauth2.googleapis.com/token#fragment", "https://example.com/token"):
            with self.subTest(token_url=url):
                self.assertFalse(token_url_allowed(url))

    @unittest.skipUnless(os.name == "nt" and os.environ.get("LOCALAPPDATA"),
                         "drive-mode auth failure is qualified in a current-user Windows profile")
    def test_drive_mode_protected_session_failure_stops_without_fixture_fallback_or_delivery(self):
        from drive_auth import DriveAuthError
        with tempfile.TemporaryDirectory(prefix="arm-userhost-drive-auth-stop-",
                                         dir=os.environ["LOCALAPPDATA"]) as raw:
            root = Path(raw)
            receiver = SimulatedApo("project-a", KEYS["test:project-a"], root / "receiver.json")
            registry_path = root / "projects.json"
            host_path = root / "host.json"
            oauth_client = root / "oauth.json"
            registry = ProjectRegistry(registry_path)
            registry.configure_folder_project(
                project_id="project-a", display_name="Project A",
                root_url="https://drive.google.com/drive/folders/root-a",
                prompts_id="prompts-a", reports_id="reports-a", endpoint=receiver.url,
                provider=FakeDriveProvider(folder_fixture()), repository="owner/project-a",
                secret_ref="test:project-a", enabled=True)
            oauth_client.write_text(json.dumps({"installed": {"client_id": "synthetic",
                "client_secret": "synthetic", "token_uri": "https://oauth2.googleapis.com/token",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth"}}), encoding="utf-8")
            values = {"schemaVersion": 1, "registryPath": str(registry_path),
                "detectorStatePath": str(root / "detector.json"),
                "notificationLedgerPath": str(root / "ledger.json"), "providerMode": "drive",
                "testSecrets": {"test:project-a": base64.b64encode(
                    KEYS["test:project-a"]).decode("ascii")},
                "intervalSeconds": 1, "stopTimeoutSeconds": 2}
            host_path.write_text(json.dumps(values), encoding="utf-8")
            fixture_calls = []
            def fail_session():
                raise DriveAuthError("sanitized fake session failure")
            def forbidden_factory(_path):
                fixture_calls.append(True)
                raise AssertionError("Drive mode must not fall back to fixture")
            try:
                with patch.dict(os.environ, {"RELAY_GDRIVE_OAUTH_CLIENT_FILE": str(oauth_client)}):
                    result = arm_v2_userhost._worker(host_path, session_factory=fail_session,
                        client_factory=lambda _token: self.fail("client must not initialize after auth failure"),
                        fixture_provider_factory=forbidden_factory)
                    self.assertEqual(result, 2)
                    config = arm_v2_userhost.load_config(host_path)
                    heartbeat = arm_v2_userhost._read_json(config.heartbeat_path,
                        arm_v2_userhost.MAX_HEARTBEAT_BYTES)
                    self.assertEqual(heartbeat["state"], "DEGRADED")
                    self.assertEqual(heartbeat["errorClass"], "DriveAuthError")
                    self.assertEqual(fixture_calls, [])
                    self.assertFalse((root / "detector.json").exists())
                    self.assertFalse((root / "ledger.json").exists())
                    self.assertEqual(receiver.request_count, 0)
                    self.assertFalse(arm_v2_userhost._probe_lock(config.worker_lock_path))
                    log = config.log_path.read_text(encoding="utf-8")
                    self.assertNotIn("synthetic", log)
            finally:
                receiver.close()

    @unittest.skipUnless(os.name == "nt" and os.environ.get("LOCALAPPDATA"),
                         "drive-mode worker failure is qualified in a current-user Windows profile")
    def test_drive_token_refresh_failure_during_folder_validation_is_terminal_and_preserves_pending(self):
        from arm_foreground import ForegroundMonitor
        from drive_auth import DriveAuthError
        from tests.test_arm_foreground import SequenceProvider

        with tempfile.TemporaryDirectory(prefix="arm-userhost-refresh-failure-",
                                         dir=os.environ["LOCALAPPDATA"]) as raw:
            root = Path(raw).resolve()
            receiver = SimulatedApo("project-a", KEYS["test:project-a"], root / "receipt.json")
            registry_path = root / "projects.json"
            detector_path = root / "detector.json"
            ledger_path = root / "ledger.json"
            host_path = root / "host.json"
            oauth_client = root / "oauth.json"
            registry = ProjectRegistry(registry_path)
            registry.configure_folder_project(
                project_id="project-a", display_name="Project A",
                root_url="https://drive.google.com/drive/folders/root-a",
                prompts_id="prompts-a", reports_id="reports-a", endpoint=receiver.url,
                provider=FakeDriveProvider(folder_fixture()), repository="owner/project-a",
                secret_ref="test:project-a", enabled=True)
            oauth_client.write_text(json.dumps({"installed": {"client_id": "synthetic-client",
                "client_secret": "synthetic-client-secret",
                "token_uri": "https://oauth2.googleapis.com/token",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth"}}), encoding="utf-8")

            seed_provider = SequenceProvider([snapshots(), snapshots(arrivals=True),
                                              snapshots(arrivals=True)])
            seed_monitor = ForegroundMonitor(registry_path, detector_path, ledger_path,
                provider=seed_provider, secret_resolver=KEYS.get, interval_seconds=1)
            seed_monitor.cycle(1)
            seed_provider.index = 1
            seed_monitor.cycle(2)
            seed_provider.index = 2
            receiver.drop_after_accept = 1
            pending_result = seed_monitor.cycle(3)
            self.assertEqual(pending_result["delivery"]["pendingThisRun"], 1)
            ledger_before = json.loads(ledger_path.read_text(encoding="utf-8"))
            pending = [entry for entry in ledger_before["entries"].values()
                       if entry["status"] == "PENDING"]
            self.assertEqual(len(pending), 1)
            receiver_requests_before = receiver.request_count
            pending_event_id = pending[0]["payload"]["eventId"]

            class RefreshFailureSession:
                def __init__(self):
                    self.access_token_calls = 0

                def access_token(self):
                    self.access_token_calls += 1
                    raise DriveAuthError("synthetic-private-refresh-detail")

            sessions = []

            def session_factory():
                session = RefreshFailureSession()
                sessions.append(session)
                return session

            fixture_fallbacks = []

            def forbidden_fixture_factory(_path):
                fixture_fallbacks.append(True)
                raise AssertionError("Drive mode must not fall back to the fixture provider")

            host_values = {"schemaVersion": 1, "registryPath": str(registry_path),
                "detectorStatePath": str(detector_path), "notificationLedgerPath": str(ledger_path),
                "providerMode": "drive",
                "testSecrets": {"test:project-a": base64.b64encode(
                    KEYS["test:project-a"]).decode("ascii")},
                "intervalSeconds": 1, "stopTimeoutSeconds": 3}
            host_path.write_text(json.dumps(host_values), encoding="utf-8")

            try:
                with patch.dict(os.environ, {"RELAY_GDRIVE_OAUTH_CLIENT_FILE": str(oauth_client)}):
                    result = arm_v2_userhost._worker(host_path, session_factory=session_factory,
                        client_factory=lambda _token: self.fail("Drive client must not initialize after refresh failure"),
                        fixture_provider_factory=forbidden_fixture_factory)

                    self.assertEqual(result, 2)
                    self.assertEqual(len(sessions), 1)
                    self.assertEqual(sessions[0].access_token_calls, 1)
                    self.assertEqual(fixture_fallbacks, [])
                    config = arm_v2_userhost.load_config(host_path)
                    heartbeat = arm_v2_userhost._read_json(
                        config.heartbeat_path, arm_v2_userhost.MAX_HEARTBEAT_BYTES)
                    self.assertEqual(heartbeat["state"], "DEGRADED")
                    self.assertEqual(heartbeat["errorClass"], "DriveAuthError")
                    self.assertEqual(heartbeat["cycle"], 1)
                    self.assertFalse(arm_v2_userhost._probe_lock(config.worker_lock_path))
                    self.assertEqual(receiver.request_count, receiver_requests_before)
                    ledger_after = json.loads(ledger_path.read_text(encoding="utf-8"))
                    self.assertEqual(ledger_after, ledger_before)
                    self.assertEqual(ledger_after["entries"][pending_event_id]["status"], "PENDING")
                    log_text = config.log_path.read_text(encoding="utf-8")
                    self.assertNotIn("synthetic-private-refresh-detail", log_text)
                    self.assertNotIn("synthetic-client-secret", log_text)
                    self.assertNotIn("synthetic-private-refresh-detail", json.dumps(heartbeat))
                    self.assertNotIn("synthetic-client-secret", json.dumps(heartbeat))
            finally:
                receiver.close()

    @unittest.skipUnless(os.name == "nt" and os.environ.get("LOCALAPPDATA"),
                         "drive-mode UserHost worker is qualified in a current-user Windows profile")
    def test_drive_mode_userhost_worker_baselines_delivers_restarts_and_deduplicates_within_budget(self):
        from project_folder_config import FOLDER_MIME

        with tempfile.TemporaryDirectory(prefix="arm-userhost-drive-worker-", dir=os.environ["LOCALAPPDATA"]) as raw:
            root = Path(raw)
            receiver = SimulatedApo("project-a", KEYS["test:project-a"], root / "receiver.json")
            registry_path = root / "projects.json"
            host_path = root / "host.json"
            oauth_client = root / "oauth.json"
            registry = ProjectRegistry(registry_path)
            registry.configure_folder_project(
                project_id="project-a", display_name="Project A",
                root_url="https://drive.google.com/drive/folders/root-a",
                prompts_id="prompts-a", reports_id="reports-a", endpoint=receiver.url,
                provider=FakeDriveProvider(folder_fixture()), repository="owner/project-a",
                secret_ref="test:project-a", enabled=True)
            oauth_client.write_text(json.dumps({"installed": {"client_id": "synthetic",
                "client_secret": "synthetic", "token_uri": "https://oauth2.googleapis.com/token",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth"}}), encoding="utf-8")
            class Session:
                def access_token(self):
                    return "synthetic-memory-only-token"

            class Client:
                def __init__(self, token):
                    if any(name in os.environ for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
                                                            "http_proxy", "https_proxy", "all_proxy")):
                        raise AssertionError("Drive worker must bypass ambient proxy routing")
                    self.token = token
                    self.items = {"prompts-a": snapshots()["folders"]["prompts-a"]["items"]}
                def metadata(self, item_id):
                    return {"id": item_id, "name": "Project A", "mimeType": FOLDER_MIME,
                            "trashed": False, "parents": []}
                def list_children(self, item_id):
                    if item_id == "root-a":
                        return [{"id": "prompts-a", "name": "Architect_Prompts", "mimeType": FOLDER_MIME,
                                 "parents": ["root-a"], "trashed": False},
                                {"id": "reports-a", "name": "Executor_Reports", "mimeType": FOLDER_MIME,
                                 "parents": ["root-a"], "trashed": False}]
                    return self.items.get(item_id, [])

            clients = []
            def client_factory(token):
                client = Client(token)
                clients.append(client)
                return client

            values = {"schemaVersion": 1, "registryPath": str(registry_path),
                "detectorStatePath": str(root / "detector.json"),
                "notificationLedgerPath": str(root / "ledger.json"), "providerMode": "drive",
                "maxMonitorObservations": 6,
                "testSecrets": {"test:project-a": base64.b64encode(
                    KEYS["test:project-a"]).decode("ascii")},
                "intervalSeconds": 1, "stopTimeoutSeconds": 4}
            host_path.write_text(json.dumps(values), encoding="utf-8")
            outcomes = []
            def run_worker():
                outcomes.append(arm_v2_userhost._worker(host_path, session_factory=Session,
                                                        client_factory=client_factory))
            def wait_cycle(number):
                deadline = time.monotonic() + 8
                while time.monotonic() < deadline:
                    try:
                        heartbeat = arm_v2_userhost._read_json(
                            arm_v2_userhost.load_config(host_path).heartbeat_path,
                            arm_v2_userhost.MAX_HEARTBEAT_BYTES)
                        recent = heartbeat.get("recentCycle")
                        if isinstance(recent, dict) and recent.get("cycle", 0) >= number:
                            return heartbeat
                        if heartbeat.get("state") == "DEGRADED":
                            self.fail(f"drive-mode worker degraded before cycle {number}: "
                                      f"errorClass={heartbeat.get('errorClass')}, cycle={heartbeat.get('cycle')}, "
                                      f"recentCycle={heartbeat.get('recentCycle')}")
                    except Exception:
                        if "heartbeat" in locals() and heartbeat.get("state") == "DEGRADED":
                            raise
                    time.sleep(0.05)
                self.fail(f"drive-mode worker did not complete cycle {number}")
            def request_stop():
                config = arm_v2_userhost.load_config(host_path)
                heartbeat = arm_v2_userhost._read_json(config.heartbeat_path,
                    arm_v2_userhost.MAX_HEARTBEAT_BYTES)
                config.stop_path.write_text(json.dumps({"schemaVersion": 1,
                    "stateIdentity": config.state_identity,
                    "workerInstanceId": heartbeat["workerInstanceId"]}), encoding="utf-8")

            try:
                with patch.dict(os.environ, {"RELAY_GDRIVE_OAUTH_CLIENT_FILE": str(oauth_client),
                                               "HTTPS_PROXY": "https://proxy.invalid:8443"}):
                    first = threading.Thread(target=run_worker, daemon=True)
                    first.start()
                    baseline = wait_cycle(1)
                    self.assertEqual(baseline["recentCycle"]["events"], [])
                    self.assertEqual(receiver.request_count, 0)
                    clients[0].items["prompts-a"] = snapshots(arrivals=True)["folders"]["prompts-a"]["items"]
                    wait_cycle(3)
                    deadline = time.monotonic() + 3
                    while time.monotonic() < deadline and receiver.request_count == 0:
                        time.sleep(0.05)
                    self.assertEqual(receiver.request_count, 1)
                    request_stop()
                    first.join(8)
                    self.assertFalse(first.is_alive(), "first drive-mode worker did not stop cleanly")
                    self.assertEqual(outcomes.pop(0), 0)

                    second = threading.Thread(target=run_worker, daemon=True)
                    second.start()
                    restarted = wait_cycle(4)
                    self.assertEqual(restarted["recentCycle"]["events"], [])
                    request_stop()
                    second.join(8)
                    self.assertFalse(second.is_alive(), "restarted drive-mode worker did not stop cleanly")
                    self.assertEqual(outcomes.pop(0), 0)
                    ledger = json.loads((root / "ledger.json").read_text(encoding="utf-8"))
                    arrival = [entry for entry in ledger["entries"].values()
                               if entry["payload"]["eventType"] == "PROMPT_CHANGED"]
                    self.assertEqual(len(arrival), 1,
                        [(entry["payload"].get("eventType"), entry["payload"].get("fileId"),
                          entry["payload"].get("eventId")) for entry in arrival])
                    self.assertEqual(arrival[0]["status"], "ACKED")
                    self.assertEqual(receiver.processed_count, 1)
                    self.assertEqual(receiver.request_count, 1)
                    config = arm_v2_userhost.load_config(host_path)
                    budget = arm_v2_userhost._observation_budget(config)
                    self.assertEqual(budget["consumed"], 4)
                    self.assertEqual(arm_v2_userhost.status(host_path)["status"], "STOPPED")
                    self.assertEqual(os.environ["HTTPS_PROXY"], "https://proxy.invalid:8443")
            finally:
                if "first" in locals() and first.is_alive():
                    request_stop()
                    first.join(6)
                if "second" in locals() and second.is_alive():
                    request_stop()
                    second.join(6)
                receiver.close()

    def test_emit_preserves_json_and_maps_cli_outcomes_to_truthful_exit_codes(self):
        cases = (
            ({"result": "STARTED", "ready": True}, 0),
            ({"result": "STOPPED"}, 0),
            ({"status": "RUNNING"}, 0),
            ({"status": "STOPPED"}, 0),
            ({"result": "ALREADY_RUNNING"}, 3),
            ({"status": "STARTING"}, 1),
            ({"result": "START_FAILED"}, 2),
            ({"result": "STOP_FAILED"}, 2),
            ({"result": "STOP_TIMEOUT"}, 2),
            ({"result": "APPLIED"}, 0),
            ({"status": "PAUSED"}, 0),
            ({"result": "PENDING"}, 1),
            ({"result": "PENDING", "error": "CONTROL_TIMEOUT"}, 2),
            ({"result": "INVALID_OWNER"}, 2),
            ({"status": "DEGRADED"}, 2),
            ({"result": "UNRECOGNIZED"}, 2),
            ({"result": {"malformed": True}}, 2),
        )
        for payload, expected in cases:
            with self.subTest(payload=payload):
                output = StringIO()
                with redirect_stdout(output):
                    actual = _emit(payload)
                self.assertEqual(actual, expected)
                self.assertEqual(json.loads(output.getvalue()), payload)

    @unittest.skipUnless(os.name == "nt" and os.environ.get("LOCALAPPDATA"),
                         "pause ownership is qualified in a current-user Windows profile")
    def test_pause_control_rejects_missing_and_stale_worker_ownership_without_state_write(self):
        with tempfile.TemporaryDirectory(prefix="arm-pause-owner-", dir=os.environ["LOCALAPPDATA"]) as raw:
            root = Path(raw)
            registry = root / "projects.json"
            fixture = root / "fixture.json"
            config_path = root / "host.json"
            registry.write_text(json.dumps({"schemaVersion": 2, "projects": [], "folderProjects": []}),
                                encoding="utf-8")
            fixture.write_text('{"folders":{},"fail":false}', encoding="utf-8")
            config_path.write_text(json.dumps({"schemaVersion": 1, "registryPath": str(registry),
                "detectorStatePath": str(root / "detector.json"),
                "notificationLedgerPath": str(root / "ledger.json"), "providerFixturePath": str(fixture),
                "testSecrets": {"test:project-a": base64.b64encode(b"a" * 32).decode("ascii")},
                "intervalSeconds": 1, "stopTimeoutSeconds": 2}), encoding="utf-8")
            config = load_config(config_path)
            with patch.object(arm_v2_userhost, "_probe_lock", return_value=False):
                self.assertEqual(arm_v2_userhost.pause_control(config_path, "PAUSE_GLOBAL"), 2)
            self.assertFalse(config.pause_store.path.exists())

            config.control_dir.mkdir(parents=True, exist_ok=True)
            stale = arm_v2_userhost._heartbeat(config, state="RUNNING", worker_id="c" * 32,
                cycle=1, recent=None, pause_state=config.pause_store.initialize([]))
            stale["configDigest"] = "0" * 64
            config.heartbeat_path.write_text(json.dumps(stale), encoding="utf-8")
            with patch.object(arm_v2_userhost, "_probe_lock", return_value=True):
                with self.assertRaises(UserHostError):
                    arm_v2_userhost.pause_control(config_path, "PAUSE_GLOBAL")
            self.assertEqual(config.pause_store.path.read_bytes(),
                             json.dumps(config.pause_store.load([]), ensure_ascii=True,
                                        sort_keys=True, separators=(",", ":")).encode("utf-8") + b"\n")

    @unittest.skipUnless(os.name == "nt" and os.environ.get("LOCALAPPDATA"),
                         "pause timeout is qualified in a current-user Windows profile")
    def test_pause_cli_reports_pending_timeout_then_worker_applies_same_request(self):
        with tempfile.TemporaryDirectory(prefix="arm-pause-timeout-", dir=os.environ["LOCALAPPDATA"]) as raw:
            root = Path(raw)
            receiver = SimulatedApo("project-a", KEYS["test:project-a"], root / "receiver.json")
            try:
                registry_path = root / "projects.json"
                fixture_path = root / "provider.json"
                config_path = root / "host.json"
                registry = ProjectRegistry(registry_path)
                registry.configure_folder_project(
                    project_id="project-a", display_name="Project A",
                    root_url="https://drive.google.com/drive/folders/root-a",
                    prompts_id="prompts-a", reports_id="reports-a", endpoint=receiver.url,
                    provider=FakeDriveProvider(folder_fixture()), repository="owner/project-a",
                    secret_ref="test:project-a", enabled=True)
                fixture_path.write_text(json.dumps(snapshots()), encoding="utf-8")
                config_path.write_text(json.dumps({
                    "schemaVersion": 1, "registryPath": str(registry_path),
                    "detectorStatePath": str(root / "detector.json"),
                    "notificationLedgerPath": str(root / "ledger.json"),
                    "providerFixturePath": str(fixture_path),
                    "testSecrets": {"test:project-a": base64.b64encode(
                        KEYS["test:project-a"]).decode("ascii")},
                    "intervalSeconds": 1, "stopTimeoutSeconds": 1,
                }), encoding="utf-8")

                def cli(command):
                    return subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1]
                        / "arm_v2_userhost.py"), "--config", str(config_path), command],
                        cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
                        timeout=15)

                start = cli("start")
                self.assertEqual(start.returncode, 0, start.stdout + start.stderr)
                started = json.loads(start.stdout.strip().splitlines()[-1])
                self.assertEqual(started["result"], "STARTED")
                deadline = time.monotonic() + 12
                while time.monotonic() < deadline and arm_v2_userhost.status(config_path).get("cycle", 0) < 1:
                    time.sleep(0.05)
                self.assertGreaterEqual(arm_v2_userhost.status(config_path).get("cycle", 0), 1)

                receiver.request_received.clear()
                receiver.response_delay_seconds = 1.8
                changed = snapshots(changed=True)
                changed["folders"]["prompts-a"]["items"][0].update(
                    {"md5Checksum": "d" * 32, "version": "4"})
                fixture_path.write_text(json.dumps(changed), encoding="utf-8")
                self.assertTrue(receiver.request_received.wait(10), "changed fixture was not delivered")

                pause = cli("pause")
                self.assertEqual(pause.returncode, 2, pause.stdout + pause.stderr)
                pending = json.loads(pause.stdout.strip().splitlines()[-1])
                self.assertEqual(pending["result"], "PENDING")
                self.assertEqual(pending["error"], "CONTROL_TIMEOUT")
                request_id = pending["requestId"]
                self.assertTrue(request_id)

                deadline = time.monotonic() + 12
                while time.monotonic() < deadline:
                    state = arm_v2_userhost.status(config_path)
                    if state.get("status") == "PAUSED":
                        break
                    time.sleep(0.05)
                self.assertEqual(state.get("status"), "PAUSED", state)
                persisted = arm_v2_userhost.load_config(config_path).pause_store.load(["project-a"])
                self.assertEqual(persisted["lastAppliedRequest"]["requestId"], request_id)
                self.assertIsNone(persisted["pendingRequest"])

                stop = cli("stop")
                self.assertEqual(stop.returncode, 0, stop.stdout + stop.stderr)
                self.assertEqual(json.loads(stop.stdout.strip().splitlines()[-1])["result"], "STOPPED")
            finally:
                try:
                    cfg = arm_v2_userhost.load_config(config_path)
                    if arm_v2_userhost._probe_lock(cfg.worker_lock_path):
                        subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1]
                            / "arm_v2_userhost.py"), "--config", str(config_path), "stop"],
                            capture_output=True, text=True, timeout=12)
                except Exception:
                    pass
                receiver.close()

    def test_cycle_status_is_an_allowlist_and_drops_content_paths_urls_and_secrets(self):
        record = {
            "cycle": 7, "status": "OK", "observation": "SCANNED", "nextDelaySeconds": 10,
            "projects": [{"projectId": "project-a", "status": "OBSERVED", "path": "C:\\private"}],
            "events": [{"projectId": "project-a", "eventId": "m03-" + "a" * 64,
                        "eventType": "PROMPT_CHANGED", "fileId": "prompt-1", "changeKind": "ARRIVED",
                        "driveUrl": "https://private.example/file", "promptBody": "NEVER-LOG-THIS",
                        "secret": "SYNTHETIC-SECRET"}],
            "delivery": {"pending": 1, "acked": 2, "token": "SYNTHETIC-SECRET"},
            "artifactBody": "NEVER-LOG-THIS", "error": "C:\\private\\token.json",
        }
        safe = _safe_cycle(record)
        serialized = json.dumps(safe)
        self.assertEqual(safe["cycle"], 7)
        self.assertEqual(safe["events"][0]["changeKind"], "ARRIVED")
        self.assertEqual(safe["delivery"], {"pending": 1, "acked": 2})
        self.assertNotIn("NEVER-LOG-THIS", serialized)
        self.assertNotIn("SYNTHETIC-SECRET", serialized)
        self.assertNotIn("private", serialized)
        self.assertNotIn("driveUrl", serialized)

    @unittest.skipUnless(os.name == "nt" and os.environ.get("LOCALAPPDATA"),
                         "M05 configuration gate uses current-user Windows local data")
    def test_non_loopback_orchestrator_endpoint_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="arm-m05-policy-", dir=os.environ["LOCALAPPDATA"]) as raw:
            registry_path = Path(raw) / "projects.json"
            registry = ProjectRegistry(registry_path)
            registry.configure_folder_project(
                project_id="project-a", display_name="Project A",
                root_url="https://drive.google.com/drive/folders/root-a",
                prompts_id="prompts-a", reports_id="reports-a",
                endpoint="https://example.invalid/notify", provider=FakeDriveProvider(folder_fixture()),
                repository="owner/project-a", secret_ref="test:project-a", enabled=True)
            with self.assertRaises(UserHostError):
                _ensure_loopback_registry(registry_path)

    @unittest.skipUnless(os.name == "nt" and os.environ.get("LOCALAPPDATA"),
                         "M05 requires a real Windows per-user process boundary")
    def test_real_windows_detached_worker_lifecycle_and_recovery_demo(self):
        root = Path(__file__).resolve().parents[1]
        script = root / "tests" / "arm_v2_userhost_process_demo.py"
        result = subprocess.run([sys.executable, str(script)], cwd=root, capture_output=True,
                                text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr or result.stdout)
        lines = result.stdout.strip().splitlines()
        self.assertTrue(lines, result.stdout)
        report = json.loads(lines[-1])
        self.assertEqual(report["demonstration"], "PASS")
        self.assertTrue(report["controllerExitedWorkerRemainedAlive"])
        self.assertEqual(report["secondStartResult"], "ALREADY_RUNNING")
        self.assertEqual(report["finalPending"], 0)
        self.assertEqual(report["finalAcked"], 3)
        self.assertEqual(report["wrongPidStop"], "REFUSED_NO_STOP_REQUEST")
        self.assertEqual(report["cleanup"], "PASS_NO_WORKER_REMAINS")


if __name__ == "__main__":
    unittest.main()
