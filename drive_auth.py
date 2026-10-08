"""Ephemeral installed-app authentication for bounded Drive reads."""
from __future__ import annotations

import os
import json
import logging
from pathlib import Path
from typing import Any

import relay

SCOPE = "https://www.googleapis.com/auth/drive.readonly"


class DriveAuthError(relay.RelayError):
    """Sanitized OAuth bootstrap failure."""


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate OAuth client JSON key")
        result[key] = value
    return result


def get_access_token(*, flow_class: Any = None, request_class: Any = None) -> str:
    """Authenticate in the system browser and return an in-memory token only."""
    client_file = os.environ.get("RELAY_GDRIVE_OAUTH_CLIENT_FILE")
    if not client_file:
        raise DriveAuthError("RELAY_GDRIVE_OAUTH_CLIENT_FILE is not set")
    if not Path(client_file).is_file():
        raise DriveAuthError("OAuth client file is unavailable")
    try:
        client_config = json.loads(Path(client_file).read_text(encoding="utf-8"), object_pairs_hook=_unique_pairs)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        raise DriveAuthError("OAuth client file is invalid") from None
    if (not isinstance(client_config, dict) or set(client_config) != {"installed"}
            or not isinstance(client_config.get("installed"), dict)):
        raise DriveAuthError("OAuth client file must contain an installed desktop client")

    if flow_class is None:
        try:
            from google_auth_oauthlib.flow import InstalledAppFlow
        except ImportError:
            raise DriveAuthError("Google OAuth dependencies are not installed") from None
        flow_class = InstalledAppFlow

    oauth_logger = logging.getLogger("google_auth_oauthlib.flow")
    previous_log_level = oauth_logger.level
    oauth_logger.setLevel(logging.CRITICAL)
    try:
        flow = flow_class.from_client_config(client_config, scopes=[SCOPE])
        credentials = flow.run_local_server(
            host="127.0.0.1", port=0, open_browser=True,
            authorization_prompt_message="Complete Google Drive read-only authorization in your system browser.",
            success_message="Authorization complete. You may close this browser tab.",
        )
        if not getattr(credentials, "valid", False) and getattr(credentials, "refresh_token", None):
            if request_class is None:
                from google.auth.transport.requests import Request
                request_class = Request
            credentials.refresh(request_class())
        token = getattr(credentials, "token", None)
        if not getattr(credentials, "valid", False) or not isinstance(token, str) or not token:
            raise DriveAuthError("OAuth did not provide a valid access token")
        return token
    except DriveAuthError:
        raise
    except Exception:
        # Library exceptions can include authorization responses or credentials.
        raise DriveAuthError("Google Drive authorization failed or was cancelled") from None
    finally:
        oauth_logger.setLevel(previous_log_level)
