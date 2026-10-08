"""Ephemeral installed-app authentication for bounded Drive reads."""
from __future__ import annotations

import os
import json
import logging
from pathlib import Path
from typing import Any

import relay
import drive_session

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


def _client_config() -> dict:
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
    client = client_config["installed"]
    if any(not isinstance(client.get(key), str) or not client[key]
           for key in ("client_id", "client_secret", "token_uri", "auth_uri")):
        raise DriveAuthError("OAuth client file is missing required desktop client fields")
    return client_config


def get_access_token(*, flow_class: Any = None, request_class: Any = None,
                     credentials_class: Any = None, session_store: Any = None) -> str:
    """Return a refreshed in-memory token, bootstrapping and protecting refresh token once."""
    client_config = _client_config()
    client = client_config["installed"]
    try:
        store = session_store if session_store is not None else drive_session.DriveSessionStore(client["client_id"], SCOPE)
        refresh_token = store.load_refresh_token()
    except drive_session.SessionStoreError as exc:
        raise DriveAuthError(str(exc)) from None
    if refresh_token is None:
        try:
            store.ensure_protector()
        except drive_session.SessionStoreError as exc:
            raise DriveAuthError(str(exc)) from None

    oauth_logger = logging.getLogger("google_auth_oauthlib.flow")
    previous_log_level = oauth_logger.level
    oauth_logger.setLevel(logging.CRITICAL)
    try:
        if request_class is None:
            try:
                from google.auth.transport.requests import Request
            except ImportError:
                raise DriveAuthError("Google OAuth dependencies are not installed") from None
            request_class = Request
        if refresh_token is not None:
            if credentials_class is None:
                try:
                    from google.oauth2.credentials import Credentials
                except ImportError:
                    raise DriveAuthError("Google OAuth dependencies are not installed") from None
                credentials_class = Credentials
            try:
                credentials = credentials_class(
                    token=None, refresh_token=refresh_token, token_uri=client["token_uri"],
                    client_id=client["client_id"], client_secret=client["client_secret"], scopes=[SCOPE],
                )
            except (TypeError, ValueError):
                raise DriveAuthError("Google Drive session credentials are invalid") from None
            try:
                credentials.refresh(request_class())
            except Exception:
                raise DriveAuthError("Google Drive session refresh failed") from None
            token = getattr(credentials, "token", None)
            if not getattr(credentials, "valid", False) or not isinstance(token, str) or not token:
                raise DriveAuthError("Google Drive session refresh returned no valid access token")
            rotated = getattr(credentials, "refresh_token", None)
            if rotated and rotated != refresh_token:
                try:
                    store.save_refresh_token(rotated)
                except drive_session.SessionStoreError as exc:
                    raise DriveAuthError(str(exc)) from None
            return token

        if flow_class is None:
            try:
                from google_auth_oauthlib.flow import InstalledAppFlow
            except ImportError:
                raise DriveAuthError("Google OAuth dependencies are not installed") from None
            flow_class = InstalledAppFlow
        flow = flow_class.from_client_config(client_config, scopes=[SCOPE])
        credentials = flow.run_local_server(
            host="127.0.0.1", port=0, open_browser=True,
            authorization_prompt_message="Complete Google Drive read-only authorization in your system browser.",
            success_message="Authorization complete. You may close this browser tab.",
            access_type="offline", prompt="consent",
        )
        new_refresh_token = getattr(credentials, "refresh_token", None)
        if not isinstance(new_refresh_token, str) or not new_refresh_token:
            raise DriveAuthError("Google OAuth did not provide a persistent refresh token")
        if not getattr(credentials, "valid", False):
            credentials.refresh(request_class())
        token = getattr(credentials, "token", None)
        if not getattr(credentials, "valid", False) or not isinstance(token, str) or not token:
            raise DriveAuthError("OAuth did not provide a valid access token")
        store.save_refresh_token(new_refresh_token)
        return token
    except DriveAuthError:
        raise
    except drive_session.SessionStoreError as exc:
        raise DriveAuthError(str(exc)) from None
    except Exception:
        # Library exceptions can include authorization responses or credentials.
        raise DriveAuthError("Google Drive authorization failed or was cancelled") from None
    finally:
        oauth_logger.setLevel(previous_log_level)


def reset_auth_session(*, session_store: Any = None) -> bool:
    """Remove only this installed client/exact-scope local protected session."""
    client = _client_config()["installed"]
    try:
        store = session_store if session_store is not None else drive_session.DriveSessionStore(client["client_id"], SCOPE)
        return store.delete()
    except drive_session.SessionStoreError as exc:
        raise DriveAuthError(str(exc)) from None
