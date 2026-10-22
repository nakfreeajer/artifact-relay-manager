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
