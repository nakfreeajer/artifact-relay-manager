import contextlib
import io
import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import drive_auth


class FakeCredentials:
    valid = True
    token = "access-token-secret"
    refresh_token = "refresh-token-secret"


class FakeFlow:
    calls = []
    credentials = FakeCredentials()
    error = None

    @classmethod
    def from_client_config(cls, config, scopes):
        cls.calls.append((config, scopes))
        return cls()

    def run_local_server(self, **kwargs):
        type(self).calls.append(kwargs)
        type(self).calls.append({"oauthLogLevel": logging.getLogger("google_auth_oauthlib.flow").level})
        if type(self).error:
            raise type(self).error
        return type(self).credentials


class DriveAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.client_file = Path(self.temp.name) / "client.json"
        self.client_file.write_text('{"installed":{"client_id":"test","client_secret":"secret","auth_uri":"https://accounts.google.com/o/oauth2/auth","token_uri":"https://oauth2.googleapis.com/token"}}', encoding="utf-8")
        FakeFlow.calls = []
        FakeFlow.error = None
        self.env = patch.dict(os.environ, {"RELAY_GDRIVE_OAUTH_CLIENT_FILE": str(self.client_file)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_installed_flow_uses_exact_scope_system_browser_and_ephemeral_loopback(self):
        previous_level = logging.getLogger("google_auth_oauthlib.flow").level
        token = drive_auth.get_access_token(flow_class=FakeFlow)
        self.assertEqual(token, "access-token-secret")
        self.assertEqual(FakeFlow.calls[0], ({"installed": {"client_id": "test", "client_secret": "secret", "auth_uri": "https://accounts.google.com/o/oauth2/auth", "token_uri": "https://oauth2.googleapis.com/token"}}, [drive_auth.SCOPE]))
        self.assertEqual(FakeFlow.calls[1]["host"], "127.0.0.1")
        self.assertEqual(FakeFlow.calls[1]["port"], 0)
        self.assertTrue(FakeFlow.calls[1]["open_browser"])
        self.assertEqual(FakeFlow.calls[2]["oauthLogLevel"], logging.CRITICAL)
        self.assertEqual(logging.getLogger("google_auth_oauthlib.flow").level, previous_level)

    def test_missing_client_file_and_dependency_fail_safely(self):
        with patch.dict(os.environ, {"RELAY_GDRIVE_OAUTH_CLIENT_FILE": str(self.client_file.with_name("missing.json"))}):
            with self.assertRaises(drive_auth.DriveAuthError):
                drive_auth.get_access_token(flow_class=FakeFlow)
        real_import = __import__

        def without_oauth(name, *args, **kwargs):
            if name == "google_auth_oauthlib.flow":
                raise ImportError("secret detail")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=without_oauth):
            with self.assertRaisesRegex(drive_auth.DriveAuthError, "dependencies are not installed"):
                drive_auth.get_access_token()

    def test_web_oauth_client_config_is_rejected_before_browser_launch(self):
        self.client_file.write_text('{"web":{"client_id":"test"}}', encoding="utf-8")
        with self.assertRaisesRegex(drive_auth.DriveAuthError, "installed desktop client"):
            drive_auth.get_access_token(flow_class=FakeFlow)
        self.assertEqual(FakeFlow.calls, [])

    def test_duplicate_json_keys_are_rejected_without_disclosing_client_data(self):
        self.client_file.write_text('{"installed":{"client_id":"one"},"installed":{"client_id":"secret"}}', encoding="utf-8")
        with self.assertRaisesRegex(drive_auth.DriveAuthError, "OAuth client file is invalid"):
            drive_auth.get_access_token(flow_class=FakeFlow)
        self.assertEqual(FakeFlow.calls, [])

    def test_auth_failure_text_does_not_expose_response_secrets(self):
        FakeFlow.error = RuntimeError("authorization_code_secret access_token_secret")
        with self.assertRaises(drive_auth.DriveAuthError) as caught:
            drive_auth.get_access_token(flow_class=FakeFlow)
        self.assertNotIn("authorization_code_secret", str(caught.exception))
        self.assertNotIn("access-token-secret", str(caught.exception))

    def test_token_is_returned_only_to_caller_and_never_written_or_printed(self):
        stdout = io.StringIO()
        stderr = io.StringIO()
        before = sorted(str(path.relative_to(self.client_file.parent)) for path in self.client_file.parent.rglob("*"))
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            token = drive_auth.get_access_token(flow_class=FakeFlow)
        after = sorted(str(path.relative_to(self.client_file.parent)) for path in self.client_file.parent.rglob("*"))
        self.assertEqual(token, "access-token-secret")
        self.assertEqual(before, after)
        self.assertNotIn("access-token-secret", stdout.getvalue() + stderr.getvalue())
        self.assertNotIn("refresh-token-secret", stdout.getvalue() + stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
