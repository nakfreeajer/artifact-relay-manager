from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from arm_v2_userhost import UserHostError, _ensure_loopback_registry, _safe_cycle
from project_folder_config import FakeDriveProvider
from project_registry import ProjectRegistry
from tests.test_arm_foreground import folder_fixture


class ArmV2UserHostTests(unittest.TestCase):
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
