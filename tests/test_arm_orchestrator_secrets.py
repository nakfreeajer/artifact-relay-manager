from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from pathlib import Path
import ssl
import tempfile
import unittest
from unittest.mock import patch

import arm_notification
import arm_v2_userhost
from arm_notification import NotificationError, NotificationSender, _canonical_json
from urllib.request import HTTPSHandler
from arm_orchestrator_secrets import OrchestratorSecretError, OrchestratorSecretStore
from project_registry import ProjectRegistry
from project_folder_config import FakeDriveProvider
from tests.test_arm_notification import NotificationFixture, KEY_A
from tests.test_arm_foreground import folder_fixture

REMOTE = "https://notify.example.com/v1/arm"
REMOTE_REF = "orchestrator:project-a"
REMOTE_KEY = b"offline-synthetic-remote-hmac-key-32-bytes"


class SyntheticProtector:
    """Reversible test-only transform; never used for production secrets."""
    def protect(self, plaintext: bytes, entropy: bytes) -> bytes:
        return bytes(value ^ entropy[index % len(entropy)] for index, value in enumerate(plaintext))

    def unprotect(self, ciphertext: bytes, entropy: bytes) -> bytes:
        return self.protect(ciphertext, entropy)


class FakeResponse:
    status = 200

    def __init__(self, body, signature):
        self.body = body
        self.headers = {"X-ARM-Ack-Signature": signature}

    def read(self, limit):
        return self.body[:limit]

    def close(self):
        pass


class FakeOpener:
    def __init__(self, secret, *, wrong_ack=False):
        self.secret = secret
        self.wrong_ack = wrong_ack
        self.requests = []

    def open(self, request, timeout):
        self.requests.append(request)
        payload = json.loads(request.data.decode("utf-8"))
        ack = {"projectId": payload["projectId"], "eventId": payload["eventId"]}
        if self.wrong_ack:
            ack["eventId"] = "wrong-event"
        body = _canonical_json(ack)
        signature = hmac.new(self.secret, body, hashlib.sha256).hexdigest()
        return FakeResponse(body, signature)


class OrchestratorSecretStoreTests(NotificationFixture):
    def test_create_only_secret_is_bound_to_project_reference_and_destination(self):
        document = self.registry.load()
        project = next(p for p in document["folderProjects"] if p["projectId"] == "project-a")
        project["orchestratorEndpoint"] = REMOTE
        project["orchestratorSecretRef"] = REMOTE_REF
        self.registry._write_document(document)
        protector = SyntheticProtector()
        store = OrchestratorSecretStore(protector=protector, local_app_data=self.root)
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.root)}):
            path = store.provision("project-a", REMOTE, REMOTE_REF, REMOTE_KEY,
                                   registry_path=self.registry_path, ledger_path=self.ledger_path)
        self.assertEqual(store.resolve("project-a", REMOTE, REMOTE_REF), REMOTE_KEY)
        self.assertNotIn(REMOTE_KEY, path.read_bytes())
        with self.assertRaises(OrchestratorSecretError):
            store.resolve("project-b", REMOTE, REMOTE_REF)
        with self.assertRaises(OrchestratorSecretError):
            store.resolve("project-a", "https://other.example.com/v1/arm", REMOTE_REF)
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.root)}):
            with self.assertRaises(OrchestratorSecretError):
                store.provision("project-a", REMOTE, REMOTE_REF, REMOTE_KEY,
                                registry_path=self.registry_path, ledger_path=self.ledger_path)

    def test_transport_history_blocks_key_provisioning(self):
        self.sender().dispatch()
        document = self.registry.load()
        project = next(p for p in document["folderProjects"] if p["projectId"] == "project-a")
        project["orchestratorEndpoint"] = REMOTE
        project["orchestratorSecretRef"] = REMOTE_REF
        self.registry._write_document(document)
        store = OrchestratorSecretStore(protector=SyntheticProtector(), local_app_data=self.root)
        with patch.dict(os.environ, {"LOCALAPPDATA": str(self.root)}):
            with self.assertRaisesRegex(OrchestratorSecretError, "history"):
                store.provision("project-a", REMOTE, REMOTE_REF, REMOTE_KEY,
                                registry_path=self.registry_path, ledger_path=self.ledger_path)

    def test_remote_secret_missing_or_corrupt_fails_closed(self):
        store = OrchestratorSecretStore(protector=SyntheticProtector(), local_app_data=self.root)
        with self.assertRaises(OrchestratorSecretError):
            store.resolve("project-a", REMOTE, REMOTE_REF)
        path, _entropy = store._path("project-a", REMOTE, REMOTE_REF)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"corrupt")
        with self.assertRaises(OrchestratorSecretError):
            store.resolve("project-a", REMOTE, REMOTE_REF)


class RemoteNotificationTests(NotificationFixture):
    def _remote_registry(self):
        document = self.registry.load()
        project = next(p for p in document["folderProjects"] if p["projectId"] == "project-a")
        project["orchestratorEndpoint"] = REMOTE
        project["orchestratorSecretRef"] = REMOTE_REF
        self.registry._write_document(document)

    def test_opt_in_remote_delivery_signs_metadata_and_accepts_matching_ack(self):
        self._remote_registry()
        calls = []
        opener = FakeOpener(REMOTE_KEY)
        sender = NotificationSender(
            self.registry_path, self.detector_path, self.ledger_path,
            secret_resolver=self.keys.get,
            project_secret_resolver=lambda ref, project_id, destination:
                calls.append((ref, project_id, destination)) or REMOTE_KEY,
            allow_remote_https=True, opener_factory=lambda *handlers: opener, clock=self.clock)
        result = sender.dispatch(project_ids=["project-a"])
        self.assertEqual(result["ackedThisRun"], 1)
        self.assertEqual(calls, [(REMOTE_REF, "project-a", REMOTE)])
        request = opener.requests[0]
        payload = json.loads(request.data.decode("utf-8"))
        self.assertEqual(set(payload), arm_notification.EVENT_PAYLOAD_KEYS)
        self.assertEqual(request.full_url, REMOTE)
        self.assertEqual(request.get_header("X-arm-request-signature"),
                         hmac.new(REMOTE_KEY, request.data, hashlib.sha256).hexdigest())
        self.assertNotIn("content", payload)
        entry = json.loads(self.ledger_path.read_text(encoding="utf-8"))["entries"][payload["eventId"]]
        self.assertEqual(entry["status"], "ACKED")
        self.assertEqual(entry["destination"], REMOTE)
        self.assertEqual(entry["secretRef"], REMOTE_REF)
        self.assertNotIn(REMOTE_KEY.decode("ascii"), self.ledger_path.read_text(encoding="utf-8"))
        self.assertEqual(self.b.request_count, 0)

    def test_invalid_remote_ack_remains_durably_pending_and_restart_reuses_identity(self):
        self._remote_registry()
        opener = FakeOpener(REMOTE_KEY, wrong_ack=True)
        def sender(factory):
            return NotificationSender(
                self.registry_path, self.detector_path, self.ledger_path,
                secret_resolver=self.keys.get,
                project_secret_resolver=lambda ref, project_id, destination: REMOTE_KEY,
                allow_remote_https=True, opener_factory=factory, clock=self.clock)
        failed = sender(lambda *handlers: opener).dispatch(project_ids=["project-a"])
        self.assertEqual(failed["pendingThisRun"], 1)
        ledger = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        event_id, entry = next(iter(ledger["entries"].items()))
        self.assertEqual(entry["status"], "PENDING")
        self.assertIsNone(entry["receipt"])
        self.clock.advance(10)
        successful_opener = FakeOpener(REMOTE_KEY)
        resumed = sender(lambda *handlers: successful_opener).dispatch(project_ids=["project-a"])
        self.assertEqual(resumed["ackedThisRun"], 1)
        first_payload = json.loads(opener.requests[0].data.decode("utf-8"))
        resumed_payload = json.loads(successful_opener.requests[0].data.decode("utf-8"))
        self.assertEqual(first_payload["eventId"], event_id)
        self.assertEqual(resumed_payload["eventId"], event_id)
        final = json.loads(self.ledger_path.read_text(encoding="utf-8"))["entries"][event_id]
        self.assertEqual(final["status"], "ACKED")
        self.assertEqual(final["attemptCount"], 2)

    def test_secret_reference_change_with_pending_event_fails_before_transport(self):
        self._remote_registry()
        failing_opener = FakeOpener(REMOTE_KEY, wrong_ack=True)
        first = NotificationSender(
            self.registry_path, self.detector_path, self.ledger_path, secret_resolver=self.keys.get,
            project_secret_resolver=lambda *_: REMOTE_KEY, allow_remote_https=True,
            opener_factory=lambda *handlers: failing_opener, clock=self.clock)
        first.dispatch(project_ids=["project-a"])
        ledger_before = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        event_id, entry = next(iter(ledger_before["entries"].items()))
        self.assertEqual(entry["status"], "PENDING")
        self.assertEqual(entry["secretRef"], REMOTE_REF)
        document = self.registry.load()
        project = next(p for p in document["folderProjects"] if p["projectId"] == "project-a")
        project["orchestratorSecretRef"] = "orchestrator:rotated"
        self.registry._write_document(document)
        calls = []
        resumed = NotificationSender(
            self.registry_path, self.detector_path, self.ledger_path, secret_resolver=self.keys.get,
            project_secret_resolver=lambda *args: calls.append(args) or REMOTE_KEY,
            allow_remote_https=True, opener_factory=lambda *handlers: failing_opener, clock=self.clock)
        with self.assertRaises(NotificationError):
            resumed.dispatch(project_ids=["project-a"])
        self.assertEqual(calls, [])
        ledger_after = json.loads(self.ledger_path.read_text(encoding="utf-8"))
        self.assertEqual(ledger_after["entries"][event_id], entry)

    def test_default_mode_rejects_remote_and_transport_policy_blocks_unsafe_hosts(self):
        self._remote_registry()
        with self.assertRaises(NotificationError):
            self.sender().dispatch(project_ids=["project-a"])
        for value in ("http://notify.example.com/notify", "https://127.0.0.1/notify",
                      "https://notify.example.com:444/notify", "https://user@notify.example.com/notify",
                      "https://printer.local/notify",
                      "https://notify..example.com/notify", "https://notify.example.com/notify?next=x"):
            with self.subTest(value=value), self.assertRaises(NotificationError):
                arm_notification.validate_notification_destination(value, allow_remote_https=True)
        self.assertEqual(arm_notification.validate_notification_destination(REMOTE, allow_remote_https=True), REMOTE)

    def test_remote_http_opener_disables_ambient_proxy_and_redirects(self):
        self._remote_registry()
        seen = {}
        opener = FakeOpener(REMOTE_KEY)
        def capture(*handlers):
            seen["handlers"] = handlers
            return opener
        sender = NotificationSender(
            self.registry_path, self.detector_path, self.ledger_path, secret_resolver=self.keys.get,
            project_secret_resolver=lambda *_: REMOTE_KEY, allow_remote_https=True,
            opener_factory=capture, clock=self.clock)
        sender.dispatch(project_ids=["project-a"])
        handlers = seen["handlers"]
        proxy = next(handler for handler in handlers if isinstance(handler, arm_notification.ProxyHandler))
        self.assertEqual(proxy.proxies, {})
        self.assertTrue(any(isinstance(handler, arm_notification._NoRedirect) for handler in handlers))
        actual_opener = arm_notification.build_opener(*handlers)
        https = next(handler for handler in actual_opener.handlers if isinstance(handler, HTTPSHandler))
        self.assertEqual(https._context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(https._context.check_hostname)

    def test_remote_destination_change_with_pending_event_is_rejected(self):
        self._remote_registry()
        failing_opener = FakeOpener(REMOTE_KEY, wrong_ack=True)
        initial = NotificationSender(
            self.registry_path, self.detector_path, self.ledger_path, secret_resolver=self.keys.get,
            project_secret_resolver=lambda *_: REMOTE_KEY, allow_remote_https=True,
            opener_factory=lambda *handlers: failing_opener, clock=self.clock)
        initial.dispatch(project_ids=["project-a"])
        document = self.registry.load()
        project = next(p for p in document["folderProjects"] if p["projectId"] == "project-a")
        project["orchestratorEndpoint"] = "https://alternate.example.net/v1/arm"
        self.registry._write_document(document)
        changed = NotificationSender(
            self.registry_path, self.detector_path, self.ledger_path, secret_resolver=self.keys.get,
            project_secret_resolver=lambda *_: REMOTE_KEY, allow_remote_https=True,
            opener_factory=lambda *handlers: self.fail("transport must not be reached"), clock=self.clock)
        with self.assertRaises(NotificationError):
            changed.dispatch(project_ids=["project-a"])


class UserHostRemoteModeTests(unittest.TestCase):
    def test_remote_mode_is_explicit_drive_only_and_destination_pins_public_dns_name(self):
        with tempfile.TemporaryDirectory(prefix="arm-remote-host-") as raw:
            root = Path(raw).resolve()
            registry_path = root / "projects.json"
            registry_path.write_text('{"schemaVersion":2,"projects":[],"folderProjects":[]}', encoding="utf-8")
            oauth_path = root / "oauth.json"
            oauth_path.write_text("{}", encoding="utf-8")
            host_path = root / "host.json"
            common = {"schemaVersion": 1, "registryPath": str(registry_path),
                "detectorStatePath": str(root / "detector.json"),
                "notificationLedgerPath": str(root / "ledger.json"), "testSecrets": {},
                "intervalSeconds": 1, "stopTimeoutSeconds": 2,
                "notificationTransportMode": "https-remote"}
            host_path.write_text(json.dumps(dict(common, providerMode="drive")), encoding="utf-8")
            with patch.dict(os.environ, {"LOCALAPPDATA": str(root),
                    "RELAY_GDRIVE_OAUTH_CLIENT_FILE": str(oauth_path)}, clear=False):
                config = arm_v2_userhost.load_config(host_path)
                self.assertTrue(config.allow_remote_https)
                self.assertFalse(config.test_secrets)
                host_path.write_text(json.dumps(dict(common, providerMode="drive",
                    maxMonitorObservations=1)), encoding="utf-8")
                self.assertEqual(arm_v2_userhost.load_config(host_path).max_monitor_observations, 1)
                host_path.write_text(json.dumps(dict(common, providerMode="fixture",
                    providerFixturePath=str(oauth_path))), encoding="utf-8")
                with self.assertRaises(arm_v2_userhost.UserHostError):
                    arm_v2_userhost.load_config(host_path)
        allowed = arm_v2_userhost._provider_network_destination_allowed
        self.assertTrue(allowed("drive", ("notify.example.com", 443), {("notify.example.com", 443)}))
        self.assertFalse(allowed("drive", ("evil.example.com", 443), {("notify.example.com", 443)}))
        self.assertTrue(arm_v2_userhost._all_public_dns_results([
            (2, 1, 6, "", ("93.184.216.34", 443))]))
        for address in ("127.0.0.1", "10.0.0.1", "192.168.2.3", "::1", "169.254.1.1"):
            with self.subTest(address=address):
                self.assertFalse(arm_v2_userhost._all_public_dns_results([
                    (2, 1, 6, "", (address, 443))]))

    def test_userhost_passes_project_bound_resolver_without_network_activity(self):
        with tempfile.TemporaryDirectory(prefix="arm-remote-worker-") as raw:
            root = Path(raw).resolve()
            registry_path = root / "projects.json"
            registry = ProjectRegistry(registry_path)
            registry.configure_folder_project(
                project_id="project-a", display_name="Project A",
                root_url="https://drive.google.com/drive/folders/root-a",
                prompts_id="prompts-a", reports_id="reports-a", endpoint=REMOTE,
                provider=FakeDriveProvider(folder_fixture()), repository="owner/project-a",
                secret_ref=REMOTE_REF, enabled=True)
            oauth_path = root / "oauth.json"
            oauth_path.write_text(json.dumps({"installed": {"client_id": "synthetic",
                "client_secret": "synthetic", "token_uri": "https://oauth2.googleapis.com/token",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth"}}), encoding="utf-8")
            config_path = root / "host.json"
            config_path.write_text(json.dumps({"schemaVersion": 1, "providerMode": "drive",
                "notificationTransportMode": "https-remote", "registryPath": str(registry_path),
                "detectorStatePath": str(root / "detector.json"),
                "notificationLedgerPath": str(root / "ledger.json"), "maxMonitorObservations": 1,
                "testSecrets": {}, "intervalSeconds": 1, "stopTimeoutSeconds": 2}), encoding="utf-8")
            resolutions = []
            class Store:
                def resolve(self, project_id, destination, reference):
                    resolutions.append((project_id, destination, reference))
                    return REMOTE_KEY
            class Session:
                def access_token(self):
                    raise AssertionError("Drive token must not be requested by this offline wiring test")
            class Monitor:
                def __init__(self, _registry, _detector, _ledger, **kwargs):
                    self.interval_seconds = 1
                    project = registry.list_folder_projects()[0]
                    self.key = kwargs["project_secret_resolver"](
                        project["orchestratorSecretRef"], project["projectId"], project["orchestratorEndpoint"])
                def cycle(self, cycle, *, paused_project_ids):
                    return {"cycle": cycle, "status": "OK", "observation": "SCANNED",
                        "projects": [{"projectId": "project-a", "status": "OBSERVED"}],
                        "events": [], "delivery": {"pending": 0, "acked": 0, "queued": 0,
                            "total": 0, "attempted": 0, "deduplicated": 0},
                        "nextDelaySeconds": 1}
            original_connect = arm_v2_userhost.socket.create_connection
            original_getaddrinfo = arm_v2_userhost.socket.getaddrinfo
            with patch.dict(os.environ, {"LOCALAPPDATA": str(root),
                    "RELAY_GDRIVE_OAUTH_CLIENT_FILE": str(oauth_path)}, clear=False), \
                 patch.object(arm_v2_userhost, "ForegroundMonitor", Monitor):
                result = arm_v2_userhost._worker(config_path, session_factory=Session,
                    client_factory=lambda token: None, secret_store_factory=Store)
                host_status = arm_v2_userhost.status(config_path)["status"]
            self.assertEqual(result, 0)
            self.assertEqual(resolutions, [("project-a", REMOTE, REMOTE_REF)] * 3)
            self.assertEqual(host_status, "STOPPED")
            self.assertIs(arm_v2_userhost.socket.create_connection, original_connect)
            self.assertIs(arm_v2_userhost.socket.getaddrinfo, original_getaddrinfo)


if __name__ == "__main__":
    unittest.main()
