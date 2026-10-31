"""Manually launched, per-user ARM v2 monitoring host.

Legacy configurations remain fixture-only. An explicit drive provider mode
uses the protected read-only Drive session and local simulated Orchestrators.
"""
from __future__ import annotations

import argparse
import base64
import ctypes
from ctypes import wintypes
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from urllib.parse import urlsplit

from arm_foreground import ForegroundMonitor
from arm_pause_state import PauseStateError, PauseStateStore, public_pause_state
from drive_auth import DriveAuthError, DriveAuthSession
from drive_adapter import DriveClient, DriveHttpError
from drive_change_detector import DetectionError, DriveMetadataProvider
import project_folder_config
from project_registry import ProjectRegistry, ProjectRegistryError
from relay_userhost import SingleInstanceLock


class UserHostError(ValueError):
    """Sanitized ARM v2 user-host configuration or ownership failure."""


LEGACY_CONFIG_KEYS = {
    "schemaVersion", "registryPath", "detectorStatePath", "notificationLedgerPath",
    "providerFixturePath", "testSecrets", "intervalSeconds", "stopTimeoutSeconds",
}
COMMON_CONFIG_KEYS = {
    "schemaVersion", "registryPath", "detectorStatePath", "notificationLedgerPath",
    "testSecrets", "intervalSeconds", "stopTimeoutSeconds",
}
MAX_CONFIG_BYTES = 32768
MAX_HEARTBEAT_BYTES = 32768
MAX_STOP_SECONDS = 60
MAX_RECENT_PROJECTS = 100
_SAFE_CYCLE_STATUS = {"OK", "DEGRADED"}
_SAFE_OBSERVATION = {"SCANNED", "SKIPPED_NO_ENABLED_PROJECTS", "SKIPPED_PAUSED_PROJECTS",
                     "DEGRADED_ATOMIC_SCAN"}
_SAFE_PROJECT_STATUS = {"OBSERVED", "DISABLED_NOT_POLLED", "PAUSED_NOT_POLLED", "DEGRADED_ATOMIC_SCAN"}


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _canonical_file(value: object, label: str) -> Path:
    if not isinstance(value, str) or not value or len(value) > 32767 or any(ord(c) < 32 for c in value):
        raise UserHostError(f"{label} path is invalid")
    path = Path(value)
    if not path.is_absolute():
        raise UserHostError(f"{label} path must be absolute")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        raise UserHostError(f"{label} file is unavailable") from None
    if (os.path.normcase(os.path.normpath(str(path))) != os.path.normcase(os.path.normpath(str(resolved)))
            or not resolved.is_file()):
        raise UserHostError(f"{label} path is not a canonical local file")
    return resolved


def _canonical_output_file(value: object, label: str) -> Path:
    if not isinstance(value, str) or not value or len(value) > 32767 or any(ord(c) < 32 for c in value):
        raise UserHostError(f"{label} path is invalid")
    path = Path(value)
    if not path.is_absolute():
        raise UserHostError(f"{label} path must be absolute")
    try:
        parent = path.parent.resolve(strict=True)
        candidate = parent / path.name
        if path.exists():
            resolved = path.resolve(strict=True)
            if not resolved.is_file():
                raise UserHostError(f"{label} path is invalid")
        else:
            resolved = candidate
    except (OSError, RuntimeError, ValueError):
        raise UserHostError(f"{label} path is invalid") from None
    if os.path.normcase(os.path.normpath(str(path))) != os.path.normcase(os.path.normpath(str(resolved))):
        raise UserHostError(f"{label} path is not canonical")
    return resolved


def _inside_local_app_data(path: Path) -> bool:
    base_text = os.environ.get("LOCALAPPDATA")
    if not base_text:
        return False
    try:
        base = Path(base_text).resolve(strict=True)
        target = path.resolve(strict=True)
        return os.path.commonpath((os.path.normcase(str(base)), os.path.normcase(str(target)))) == os.path.normcase(str(base))
    except (OSError, RuntimeError, ValueError):
        return False


def _read_json(path: Path, maximum: int):
    try:
        raw = path.read_bytes()
        if len(raw) > maximum:
            raise ValueError("too large")
        return json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        raise UserHostError("local host data is invalid") from None


def _atomic_json(path: Path, value: dict, maximum: int = MAX_HEARTBEAT_BYTES) -> None:
    data = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    if len(data) > maximum:
        raise UserHostError("local host data exceeds its size limit")
    fd = None
    temporary = None
    try:
        fd, raw_path = tempfile.mkstemp(prefix=".arm-v2-host-", suffix=".tmp", dir=path.parent)
        temporary = Path(raw_path)
        with os.fdopen(fd, "wb") as stream:
            fd = None
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
    except OSError:
        raise UserHostError("could not persist local host state") from None
    finally:
        if fd is not None:
            os.close(fd)
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


def _sid_for_process(pid: int) -> str:
    if os.name != "nt":
        return f"uid:{os.getuid()}"
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.LocalFree.argtypes = (wintypes.HLOCAL,)
    kernel32.LocalFree.restype = wintypes.HLOCAL
    advapi32.OpenProcessToken.argtypes = (wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE))
    advapi32.OpenProcessToken.restype = wintypes.BOOL
    advapi32.GetTokenInformation.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                              wintypes.DWORD, ctypes.POINTER(wintypes.DWORD))
    advapi32.GetTokenInformation.restype = wintypes.BOOL
    advapi32.ConvertSidToStringSidW.argtypes = (ctypes.c_void_p, ctypes.POINTER(wintypes.LPWSTR))
    advapi32.ConvertSidToStringSidW.restype = wintypes.BOOL
    process = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not process:
        raise UserHostError("worker process identity is unavailable")
    token = wintypes.HANDLE()
    sid_text = wintypes.LPWSTR()
    try:
        if not advapi32.OpenProcessToken(process, 0x0008, ctypes.byref(token)):  # TOKEN_QUERY
            raise UserHostError("worker process identity is unavailable")
        required = wintypes.DWORD()
        advapi32.GetTokenInformation(token, 1, None, 0, ctypes.byref(required))  # TokenUser
        if not required.value:
            raise UserHostError("worker process identity is unavailable")
        buffer = ctypes.create_string_buffer(required.value)
        if not advapi32.GetTokenInformation(token, 1, buffer, required, ctypes.byref(required)):
            raise UserHostError("worker process identity is unavailable")

        class SID_AND_ATTRIBUTES(ctypes.Structure):
            _fields_ = [("Sid", ctypes.c_void_p), ("Attributes", wintypes.DWORD)]

        class TOKEN_USER(ctypes.Structure):
            _fields_ = [("User", SID_AND_ATTRIBUTES)]

        token_user = ctypes.cast(buffer, ctypes.POINTER(TOKEN_USER)).contents
        if not advapi32.ConvertSidToStringSidW(token_user.User.Sid, ctypes.byref(sid_text)):
            raise UserHostError("worker process identity is unavailable")
        return hashlib.sha256(sid_text.value.encode("ascii")).hexdigest()
    finally:
        if sid_text:
            kernel32.LocalFree(ctypes.cast(sid_text, ctypes.c_void_p))
        if token:
            kernel32.CloseHandle(token)
        kernel32.CloseHandle(process)


def _process_creation_time(pid: int) -> str:
    if os.name != "nt":
        return str(pid)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = (wintypes.HANDLE,)
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.GetProcessTimes.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.FILETIME),
                                         ctypes.POINTER(wintypes.FILETIME), ctypes.POINTER(wintypes.FILETIME),
                                         ctypes.POINTER(wintypes.FILETIME))
    kernel32.GetProcessTimes.restype = wintypes.BOOL
    process = kernel32.OpenProcess(0x1000, False, pid)
    if not process:
        raise UserHostError("worker process identity is unavailable")
    try:
        created = wintypes.FILETIME()
        exited = wintypes.FILETIME()
        kernel = wintypes.FILETIME()
        user = wintypes.FILETIME()
        if not kernel32.GetProcessTimes(process, ctypes.byref(created), ctypes.byref(exited),
                                        ctypes.byref(kernel), ctypes.byref(user)):
            raise UserHostError("worker process identity is unavailable")
        ticks = (created.dwHighDateTime << 32) | created.dwLowDateTime
        return str(ticks)
    finally:
        kernel32.CloseHandle(process)


def _process_is_alive(pid: int) -> bool:
    try:
        _process_creation_time(pid)
        return True
    except UserHostError:
        return False


def _drive_client_file() -> Path:
    value = os.environ.get("RELAY_GDRIVE_OAUTH_CLIENT_FILE")
    if (not isinstance(value, str) or not value or value.startswith(("\\\\", "//"))
            or not Path(value).is_absolute()):
        raise UserHostError("Drive provider requires the configured OAuth client file")
    candidate = Path(value)
    try:
        path = candidate.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        raise UserHostError("Drive OAuth client file is unavailable") from None
    if (not path.is_file()
            or os.path.normcase(os.path.normpath(str(candidate)))
            != os.path.normcase(os.path.normpath(str(path)))):
        raise UserHostError("Drive OAuth client file is unavailable")
    return path


class HostConfig:
    def __init__(self, path: Path, values: dict, raw_digest: str):
        self.path = path
        self.registry_path = _canonical_file(values["registryPath"], "project registry")
        self.detector_path = _canonical_output_file(values["detectorStatePath"], "detector state")
        self.ledger_path = _canonical_output_file(values["notificationLedgerPath"], "notification ledger")
        self.provider_mode = values.get("providerMode", "fixture")
        self.fixture_path = (_canonical_file(values["providerFixturePath"], "provider fixture")
                             if self.provider_mode == "fixture" else None)
        self.test_secrets = {key: base64.b64decode(value, validate=True)
                             for key, value in values["testSecrets"].items()}
        self.interval_seconds = values["intervalSeconds"]
        self.stop_timeout_seconds = values["stopTimeoutSeconds"]
        self.max_monitor_observations = values.get("maxMonitorObservations")
        self.config_digest = raw_digest
        identity_fields = [os.path.normcase(os.path.normpath(str(path)))
                           for path in (self.registry_path, self.detector_path, self.ledger_path)]
        identity = json.dumps(identity_fields, separators=(",", ":"), ensure_ascii=True)
        self.state_identity = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        self.user_root = Path(os.environ["LOCALAPPDATA"]).resolve(strict=True) / "ArtifactRelayManager" / "ARMv2" / "UserHost"
        self.control_dir = self.user_root / self.state_identity
        self.worker_lock_path = self.control_dir / "worker.lock"
        self.start_lock_path = self.control_dir / "start.lock"
        self.heartbeat_path = self.control_dir / "heartbeat.json"
        self.stop_path = self.control_dir / "stop.json"
        self.observation_budget_path = self.control_dir / "observation-budget.json"
        self.log_path = self.control_dir / "worker.jsonl"
        self.pause_store = PauseStateStore(self.control_dir, self.state_identity, self.config_digest)


def load_config(path: Path) -> HostConfig:
    try:
        config_path = Path(path)
        if not config_path.is_absolute() or not config_path.is_file():
            raise UserHostError("host configuration is unavailable")
        resolved = config_path.resolve(strict=True)
        if (os.path.normcase(str(config_path)) != os.path.normcase(str(resolved))
                or not _inside_local_app_data(resolved)):
            raise UserHostError("host configuration must be a canonical current-user local file")
        raw = resolved.read_bytes()
        if len(raw) > MAX_CONFIG_BYTES:
            raise UserHostError("host configuration exceeds its size limit")
        values = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs)
    except UserHostError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        raise UserHostError("host configuration is invalid") from None
    if not isinstance(values, dict):
        raise UserHostError("host configuration schema is invalid")
    keys = set(values)
    legacy_fixture = keys == LEGACY_CONFIG_KEYS
    explicit_fixture = (keys == COMMON_CONFIG_KEYS | {"providerMode", "providerFixturePath"}
                        and values.get("providerMode") == "fixture")
    explicit_drive = (keys == COMMON_CONFIG_KEYS | {"providerMode"}
                      and values.get("providerMode") == "drive")
    bounded_drive = (keys == COMMON_CONFIG_KEYS | {"providerMode", "maxMonitorObservations"}
                     and values.get("providerMode") == "drive")
    if not (legacy_fixture or explicit_fixture or explicit_drive or bounded_drive):
        raise UserHostError("host configuration schema is invalid")
    if type(values.get("schemaVersion")) is not int or values["schemaVersion"] != 1:
        raise UserHostError("host configuration schema is invalid")
    if bounded_drive and (type(values.get("maxMonitorObservations")) is not int
                          or not 1 <= values["maxMonitorObservations"] <= 6):
        raise UserHostError("Drive monitor observation limit must be between 1 and 6")
    if not bounded_drive and "maxMonitorObservations" in values:
        raise UserHostError("monitor observation limit is valid only in explicit Drive mode")
    provider_mode = "fixture" if legacy_fixture else values.get("providerMode")
    for name in ("registryPath", "detectorStatePath", "notificationLedgerPath"):
        if not isinstance(values[name], str) or not Path(values[name]).is_absolute():
            raise UserHostError("host runtime path is invalid")
    if type(values["intervalSeconds"]) is not int or not 1 <= values["intervalSeconds"] <= 3600:
        raise UserHostError("host interval is invalid")
    if type(values["stopTimeoutSeconds"]) is not int or not 1 <= values["stopTimeoutSeconds"] <= MAX_STOP_SECONDS:
        raise UserHostError("host stop timeout is invalid")
    secrets_value = values["testSecrets"]
    if (not isinstance(secrets_value, dict) or not secrets_value or len(secrets_value) > 100
            or any(not isinstance(k, str) or not k.startswith("test:") or len(k) > 256
                   or not isinstance(v, str) or len(v) > 2048 for k, v in secrets_value.items())):
        raise UserHostError("offline test key map is invalid")
    if provider_mode == "drive":
        _drive_client_file()
    try:
        config = HostConfig(resolved, values, hashlib.sha256(raw).hexdigest())
    except (KeyError, TypeError, ValueError, OSError):
        raise UserHostError("host configuration is invalid") from None
    if any(len(key) < 16 for key in config.test_secrets.values()):
        raise UserHostError("offline test key is invalid")
    paths = [config.registry_path, config.detector_path, config.ledger_path, config.path]
    if config.fixture_path is not None:
        paths.append(config.fixture_path)
    norm = [os.path.normcase(os.path.normpath(str(p))) for p in paths]
    if len(set(norm)) != len(norm):
        raise UserHostError("host files must have distinct paths")
    for p in (config.registry_path, config.path):
        if not _inside_local_app_data(p):
            raise UserHostError("host input files must remain under current-user local data")
    if config.fixture_path is not None and not _inside_local_app_data(config.fixture_path):
        raise UserHostError("host input files must remain under current-user local data")
    for p in (config.detector_path, config.ledger_path):
        if not _inside_local_app_data(p.parent):
            raise UserHostError("host state files must remain under current-user local data")
    _ensure_loopback_registry(config.registry_path)
    if config.fixture_path is not None:
        _read_json(config.fixture_path, 4 * 1024 * 1024)
    return config


class AuthenticatedDriveMetadataProvider:
    """Read-only Drive metadata adapter bound to registered project folders."""

    fatal_error_types = (DriveAuthError,)

    def __init__(self, registry_path: Path, *, session_factory=DriveAuthSession,
                 client_factory=DriveClient, request_class=None):
        self.registry = ProjectRegistry(registry_path)
        try:
            import drive_auth
            client_config = drive_auth._client_config()
            token_uri = urlsplit(client_config["installed"]["token_uri"])
            token_port = token_uri.port
        except Exception:
            raise UserHostError("Drive OAuth client configuration is invalid") from None
        if (token_uri.scheme != "https" or token_uri.hostname != "oauth2.googleapis.com"
                or token_port not in (None, 443) or token_uri.username or token_uri.password
                or token_uri.path != "/token" or token_uri.query or token_uri.fragment):
            raise UserHostError("Drive OAuth token endpoint is not approved")
        try:
            self.session = (session_factory(request_class=request_class) if request_class is not None
                            else session_factory())
        except DriveAuthError:
            raise
        except Exception:
            raise UserHostError("protected Drive session initialization failed") from None
        self.client_factory = client_factory
        self.client = None
        self.metadata = None
        self.calls_by_folder = {}

    def _client(self):
        try:
            token = self.session.access_token()
        except DriveAuthError:
            raise
        except Exception:
            raise UserHostError("protected Drive session token acquisition failed") from None
        if self.client is None:
            self.client = self.client_factory(token)
            self.metadata = DriveMetadataProvider(self.client)
        else:
            self.client.token = token
        return self.client

    def folder(self, folder_id):
        try:
            return self._client().metadata(folder_id)
        except DriveHttpError as exc:
            if exc.status_code == 401:
                self.session.invalidate()
                raise DriveAuthError("Google Drive session was rejected") from None
            raise

    def children(self, root_id):
        try:
            return self._client().list_children(root_id)
        except DriveHttpError as exc:
            if exc.status_code == 401:
                self.session.invalidate()
                raise DriveAuthError("Google Drive session was rejected") from None
            raise

    def list_folder(self, folder_id):
        registry = self.registry.load()
        project = next((item for item in registry["folderProjects"]
                       if folder_id in {item["architectPromptsFolderId"],
                                        item["executorReportsFolderId"]}), None)
        if project is None:
            raise UserHostError("Drive folder is not registered")
        try:
            project_folder_config.validate_project(project, self)
        except DriveAuthError:
            raise
        except Exception:
            raise UserHostError("registered Drive folder identity could not be verified") from None
        self.calls_by_folder[folder_id] = self.calls_by_folder.get(folder_id, 0) + 1
        try:
            return self.metadata.list_folder(folder_id)
        except DriveHttpError as exc:
            if exc.status_code == 401:
                self.session.invalidate()
                raise DriveAuthError("Google Drive session was rejected") from None
            raise


def _provider_network_destination_allowed(provider_mode: str, address) -> bool:
    if (not isinstance(address, tuple) or len(address) < 2
            or not isinstance(address[0], str) or type(address[1]) is not int):
        return False
    host, port = address[0], address[1]
    try:
        if ipaddress.ip_address(host).is_loopback:
            return True
    except ValueError:
        if host.casefold() == "localhost":
            return True
    return (provider_mode == "drive" and port == 443
            and host.casefold() in {"www.googleapis.com", "oauth2.googleapis.com"})


def _google_token_url_allowed(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except (TypeError, ValueError):
        return False
    return (parsed.scheme == "https" and parsed.hostname == "oauth2.googleapis.com"
            and port in (None, 443) and not parsed.username and not parsed.password
            and parsed.path == "/token" and not parsed.query and not parsed.fragment)


class _RestrictedGoogleTokenRequest:
    """Use the existing Google auth request only for the fixed token endpoint."""

    def __init__(self):
        try:
            from google.auth.transport.requests import Request
            import requests
        except ImportError:
            raise DriveAuthError("Google OAuth dependencies are not installed") from None

        class DirectSession(requests.Session):
            def request(self, method, url, *args, **kwargs):
                if not _google_token_url_allowed(url):
                    raise DriveAuthError("OAuth token request destination is not approved")
                kwargs["allow_redirects"] = False
                return super().request(method, url, *args, **kwargs)

        self.session = DirectSession()
        self.session.trust_env = False
        self.session.proxies.clear()
        self._request = Request(session=self.session)

    def __call__(self, url, *args, **kwargs):
        if not _google_token_url_allowed(url):
            raise DriveAuthError("OAuth token request destination is not approved")
        return self._request(url, *args, **kwargs)


def _ensure_loopback_registry(registry_path: Path) -> dict:
    try:
        registry = ProjectRegistry(registry_path).load()
    except Exception:
        raise UserHostError("configured project registry is invalid") from None
    for project in registry["folderProjects"]:
        parsed = urlsplit(project["orchestratorEndpoint"])
        try:
            host = parsed.hostname or ""
            is_loopback = host.casefold() == "localhost" or ipaddress.ip_address(host).is_loopback
        except ValueError:
            is_loopback = False
        if (parsed.scheme != "http" or not is_loopback or parsed.username or parsed.password
                or parsed.port is None or not parsed.path.startswith("/") or len(parsed.path) > 512
                or "\\" in parsed.path or ".." in parsed.path or parsed.query or parsed.fragment):
            raise UserHostError("M05 accepts only local simulated Orchestrator endpoints")
        reference = project.get("orchestratorSecretRef")
        if not isinstance(reference, str) or not reference.startswith("test:"):
            raise UserHostError("M05 accepts only offline test secret references")
    return registry


class ReloadingFixtureProvider:
    """Read a fresh complete local metadata fixture for each folder request."""

    def __init__(self, path: Path):
        self.path = path
        self.calls_by_folder = {}

    def list_folder(self, folder_id: str):
        self.calls_by_folder[folder_id] = self.calls_by_folder.get(folder_id, 0) + 1
        value = _read_json(self.path, 4 * 1024 * 1024)
        if (not isinstance(value, dict) or set(value) != {"folders", "fail"}
                or type(value["fail"]) is not bool or not isinstance(value["folders"], dict)
                or value["fail"]):
            raise DetectionError("provider fixture is unavailable")
        folder = value["folders"].get(folder_id)
        if (not isinstance(folder, dict) or set(folder) != {"complete", "items"}
                or folder["complete"] is not True or not isinstance(folder["items"], list)):
            raise DetectionError("provider listing is incomplete")
        return folder["items"]


def _safe_cycle(record: dict) -> dict:
    safe = {"cycle": record.get("cycle"), "status": record.get("status"),
            "observation": record.get("observation"), "projects": [], "events": [],
            "delivery": {}}
    if type(safe["cycle"]) is not int or safe["cycle"] < 0:
        safe["cycle"] = 0
    if safe["status"] not in _SAFE_CYCLE_STATUS:
        safe["status"] = "DEGRADED"
    if safe["observation"] not in _SAFE_OBSERVATION:
        safe["observation"] = "DEGRADED_ATOMIC_SCAN"
    delay = record.get("nextDelaySeconds")
    if type(delay) is int and 1 <= delay <= 3600:
        safe["nextDelaySeconds"] = delay
    for project in record.get("projects", [])[:MAX_RECENT_PROJECTS]:
        if (isinstance(project, dict) and isinstance(project.get("projectId"), str)
                and project.get("status") in _SAFE_PROJECT_STATUS):
            item = {"projectId": project["projectId"], "status": project["status"]}
            calls = project.get("providerCalls")
            if type(calls) is int and 0 <= calls <= 2**31 - 1:
                item["providerCalls"] = calls
            safe["projects"].append(item)
    for event in record.get("events", [])[:MAX_RECENT_PROJECTS]:
        if isinstance(event, dict):
            item = {key: event[key] for key in ("projectId", "eventId", "eventType", "fileId", "changeKind")
                    if isinstance(event.get(key), str)}
            if (len(item) == 5 and re.fullmatch(r"[A-Za-z0-9._-]{1,128}", item["projectId"])
                    and re.fullmatch(r"m03-[a-f0-9]{64}", item["eventId"])
                    and item["eventType"] in {"PROMPT_CHANGED", "REPORT_CHANGED"}
                    and re.fullmatch(r"[A-Za-z0-9_-]{1,256}", item["fileId"])
                    and item["changeKind"] in {"ARRIVED", "CONTENT_UPDATED"}):
                safe["events"].append(item)
    delivery = record.get("delivery")
    if isinstance(delivery, dict):
        for key in ("pending", "acked", "queued", "total", "attempted", "deduplicated"):
            number = delivery.get(key)
            if type(number) is int and 0 <= number <= 2**31 - 1:
                safe["delivery"][key] = number
    if isinstance(record.get("observationErrorClass"), str):
        safe["observationErrorClass"] = record["observationErrorClass"][:80]
    if isinstance(record.get("deliveryErrorClass"), str):
        safe["deliveryErrorClass"] = record["deliveryErrorClass"][:80]
    return safe


def _safe_prior_cycle(config: HostConfig) -> int:
    if not config.heartbeat_path.exists():
        return 0
    previous = _read_json(config.heartbeat_path, MAX_HEARTBEAT_BYTES)
    if (not isinstance(previous, dict) or previous.get("stateIdentity") != config.state_identity
            or previous.get("configDigest") != config.config_digest
            or type(previous.get("cycle")) is not int or previous["cycle"] < 0):
        raise UserHostError("previous worker state does not match this configuration")
    return previous["cycle"]


def _observation_budget(config: HostConfig) -> dict | None:
    limit = config.max_monitor_observations
    if limit is None:
        return None
    if not config.observation_budget_path.exists():
        return {"schemaVersion": 1, "stateIdentity": config.state_identity,
                "configDigest": config.config_digest, "limit": limit, "consumed": 0}
    value = _read_json(config.observation_budget_path, 4096)
    if (not isinstance(value, dict)
            or set(value) != {"schemaVersion", "stateIdentity", "configDigest", "limit", "consumed"}
            or type(value.get("schemaVersion")) is not int or value["schemaVersion"] != 1
            or value.get("stateIdentity") != config.state_identity
            or value.get("configDigest") != config.config_digest
            or type(value.get("limit")) is not int or value.get("limit") != limit
            or type(value.get("consumed")) is not int
            or not 0 <= value["consumed"] <= limit):
        raise UserHostError("Drive observation budget is invalid or belongs to another host state")
    return value


def _persist_observation_budget(config: HostConfig, budget: dict) -> None:
    config.control_dir.mkdir(parents=True, exist_ok=True)
    _atomic_json(config.observation_budget_path, budget, maximum=4096)


def _heartbeat(config: HostConfig, *, state: str, worker_id: str, cycle: int,
               recent: dict | None, pause_state: dict, error: str | None = None) -> dict:
    pid = os.getpid()
    result = {
        "schemaVersion": 1, "stateIdentity": config.state_identity,
        "configDigest": config.config_digest, "workerInstanceId": worker_id,
        "pid": pid, "userIdentity": _sid_for_process(pid),
        "processCreationTime": _process_creation_time(pid),
        "state": state, "cycle": cycle,
        "startedAt": getattr(_heartbeat, "started_at", datetime.now(timezone.utc).isoformat()),
        "heartbeatAt": datetime.now(timezone.utc).isoformat(),
        "recentCycle": recent,
        "pauseState": public_pause_state(pause_state),
    }
    if error:
        result["errorClass"] = error[:80]
    return result


def _effective_pause_state(registry: dict, pause_state: dict) -> bool:
    if pause_state["globalPaused"]:
        return True
    enabled = [project["projectId"] for project in registry["folderProjects"] if project["enabled"]]
    return bool(enabled) and all(project_id in set(pause_state["pausedProjectIds"]) for project_id in enabled)


def _pause_recent(cycle: int, registry: dict, pause_state: dict) -> dict:
    paused = set(pause_state["pausedProjectIds"])
    return {"cycle": cycle, "status": "OK", "observation": "SKIPPED_PAUSED_PROJECTS",
            "projects": [{"projectId": project["projectId"], "status":
                          ("DISABLED_NOT_POLLED" if not project["enabled"] else "PAUSED_NOT_POLLED"
                           if pause_state["globalPaused"] or project["projectId"] in paused
                           else "OBSERVED"), "providerCalls": 0}
                         for project in registry["folderProjects"]],
            "events": [], "delivery": None, "observationErrorClass": None,
            "deliveryErrorClass": None, "nextDelaySeconds": None}


def _heartbeat_state(registry: dict, pause_state: dict, recent: dict) -> str:
    if _effective_pause_state(registry, pause_state):
        return "PAUSED"
    return "DEGRADED" if recent.get("status") == "DEGRADED" else "RUNNING"


def _append_log(config: HostConfig, record: dict) -> None:
    safe = {"time": datetime.now(timezone.utc).isoformat(), "component": "arm-v2-worker"}
    cycle = record.get("recentCycle")
    if isinstance(cycle, dict):
        safe["cycle"] = cycle["cycle"]
        safe["status"] = cycle["status"]
        safe["observation"] = cycle["observation"]
        safe["delivery"] = cycle["delivery"]
    if "errorClass" in record:
        safe["errorClass"] = record["errorClass"]
    encoded = (json.dumps(safe, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    try:
        config.control_dir.mkdir(parents=True, exist_ok=True)
        current = config.log_path.stat().st_size if config.log_path.exists() else 0
        if current + len(encoded) > 1024 * 1024:
            backup = config.log_path.with_suffix(".jsonl.1")
            backup.unlink(missing_ok=True)
            if config.log_path.exists():
                config.log_path.replace(backup)
        with config.log_path.open("ab") as stream:
            stream.write(encoded)
            stream.flush()
    except OSError:
        # Heartbeat and monitor state remain authoritative; logs are secondary.
        pass


def _read_stop(config: HostConfig, worker_id: str) -> bool:
    if not config.stop_path.exists():
        return False
    request = _read_json(config.stop_path, 2048)
    return (isinstance(request, dict) and set(request) == {"schemaVersion", "stateIdentity", "workerInstanceId"}
            and request["schemaVersion"] == 1 and request["stateIdentity"] == config.state_identity
            and request["workerInstanceId"] == worker_id)


def _worker(config_path: Path, *, session_factory=DriveAuthSession,
            client_factory=DriveClient, fixture_provider_factory=ReloadingFixtureProvider) -> int:
    config = load_config(config_path)
    if "RELAY_GDRIVE_ACCESS_TOKEN" in os.environ:
        raise UserHostError("UserHost refuses access-token environment inputs")
    if config.provider_mode == "fixture" and "RELAY_GDRIVE_OAUTH_CLIENT_FILE" in os.environ:
        raise UserHostError("fixture worker refuses OAuth environment inputs")
    config.control_dir.mkdir(parents=True, exist_ok=True)
    worker_lock = SingleInstanceLock(config.worker_lock_path)
    if not worker_lock.acquire():
        return 3
    worker_id = secrets.token_hex(16)
    stop_network = socket.create_connection
    removed_proxy_environment = {}
    if config.provider_mode == "drive":
        for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
            if name in os.environ:
                removed_proxy_environment[name] = os.environ.pop(name)

    def guarded_connection(address, *args, **kwargs):
        if not _provider_network_destination_allowed(config.provider_mode, address):
            raise OSError("UserHost blocked a network destination outside its provider allowlist")
        return stop_network(address, *args, **kwargs)

    socket.create_connection = guarded_connection
    cycle = 0
    recent = None
    pause_state = {"globalPaused": False, "pausedProjectIds": [], "pendingRequest": None,
                   "lastAppliedRequest": None}
    try:
        cycle = _safe_prior_cycle(config)
        _heartbeat.started_at = datetime.now(timezone.utc).isoformat()
        registry = _ensure_loopback_registry(config.registry_path)
        project_ids = [project["projectId"] for project in registry["folderProjects"]]
        pause_state = config.pause_store.initialize(project_ids)
        ready = _heartbeat(config, state="STARTING", worker_id=worker_id, cycle=cycle,
                           recent=None, pause_state=pause_state)
        _atomic_json(config.heartbeat_path, ready)
        _append_log(config, {"recentCycle": None})
        secret_refs = {project.get("orchestratorSecretRef") for project in registry["folderProjects"]
                       if project["enabled"]}
        if any(reference not in config.test_secrets for reference in secret_refs):
            raise UserHostError("offline test key is missing for an enabled project")
        if config.provider_mode == "fixture":
            provider = fixture_provider_factory(config.fixture_path)
        else:
            if session_factory is DriveAuthSession:
                provider = AuthenticatedDriveMetadataProvider(
                    config.registry_path, session_factory=session_factory, client_factory=client_factory,
                    request_class=_RestrictedGoogleTokenRequest)
            else:
                provider = AuthenticatedDriveMetadataProvider(
                    config.registry_path, session_factory=session_factory, client_factory=client_factory)
        monitor = ForegroundMonitor(
            config.registry_path, config.detector_path, config.ledger_path,
            provider=provider,
            secret_resolver=config.test_secrets.get,
            interval_seconds=config.interval_seconds, dispatch_limit=8,
        )
        budget = _observation_budget(config)
        while True:
            if _read_stop(config, worker_id):
                stopped = _heartbeat(config, state="STOPPED", worker_id=worker_id,
                                     cycle=cycle, recent=recent, pause_state=pause_state)
                _atomic_json(config.heartbeat_path, stopped)
                _append_log(config, {"recentCycle": recent})
                return 0
            registry = _ensure_loopback_registry(config.registry_path)
            project_ids = [project["projectId"] for project in registry["folderProjects"]]
            pause_state = config.pause_store.load(project_ids)
            if pause_state["pendingRequest"] is not None:
                pause_state, _changed = config.pause_store.apply_pending(project_ids, worker_id)
            if _read_stop(config, worker_id):
                stopped = _heartbeat(config, state="STOPPED", worker_id=worker_id,
                                     cycle=cycle, recent=recent, pause_state=pause_state)
                _atomic_json(config.heartbeat_path, stopped)
                _append_log(config, {"recentCycle": recent})
                return 0
            secret_refs = {project.get("orchestratorSecretRef") for project in registry["folderProjects"]}
            if any(reference not in config.test_secrets for reference in secret_refs):
                raise UserHostError("offline test key is missing for a configured project")
            enabled_ids = [project["projectId"] for project in registry["folderProjects"]
                           if project["enabled"]]
            unpaused_ids = [project_id for project_id in enabled_ids
                            if project_id not in set(pause_state["pausedProjectIds"])]
            paused_idle = pause_state["globalPaused"] or bool(enabled_ids) and not unpaused_ids
            if paused_idle:
                recent = _safe_cycle(_pause_recent(cycle, registry, pause_state))
                state = "PAUSED"
                delay = min(config.interval_seconds, 5)
            else:
                if budget is not None:
                    if budget["consumed"] >= budget["limit"]:
                        stopped = _heartbeat(config, state="STOPPED", worker_id=worker_id,
                                             cycle=cycle, recent=recent, pause_state=pause_state)
                        _atomic_json(config.heartbeat_path, stopped)
                        _append_log(config, {"recentCycle": recent})
                        return 0
                    # Consume before polling so a crash cannot reset the live-run bound.
                    budget["consumed"] += 1
                    _persist_observation_budget(config, budget)
                cycle += 1
                call_counts_before = dict(provider.calls_by_folder)
                record = _safe_cycle(monitor.cycle(cycle, paused_project_ids=pause_state["pausedProjectIds"]))
                record = json.loads(json.dumps(record))
                for project_status in record["projects"]:
                    project = next(item for item in registry["folderProjects"]
                                   if item["projectId"] == project_status["projectId"])
                    project_status["providerCalls"] = sum(
                        provider.calls_by_folder.get(project[key], 0) - call_counts_before.get(project[key], 0)
                        for key in ("architectPromptsFolderId", "executorReportsFolderId"))
                record = _safe_cycle(record)
                recent = record
                # Apply controls only after the current monitor cycle has completed.
                if _read_stop(config, worker_id):
                    stopped = _heartbeat(config, state="STOPPED", worker_id=worker_id,
                                         cycle=cycle, recent=recent, pause_state=pause_state)
                    _atomic_json(config.heartbeat_path, stopped)
                    _append_log(config, {"recentCycle": recent})
                    return 0
                registry = _ensure_loopback_registry(config.registry_path)
                project_ids = [project["projectId"] for project in registry["folderProjects"]]
                pause_state = config.pause_store.load(project_ids)
                if pause_state["pendingRequest"] is not None:
                    pause_state, _changed = config.pause_store.apply_pending(project_ids, worker_id)
                if budget is not None and budget["consumed"] >= budget["limit"]:
                    stopped = _heartbeat(config, state="STOPPED", worker_id=worker_id,
                                         cycle=cycle, recent=recent, pause_state=pause_state)
                    _atomic_json(config.heartbeat_path, stopped)
                    _append_log(config, {"recentCycle": recent})
                    return 0
                state = _heartbeat_state(registry, pause_state, recent)
                delay = monitor.interval_seconds
                if record["status"] == "DEGRADED":
                    delay = min(record.get("nextDelaySeconds", delay), 3600)
            current = _heartbeat(config, state=state, worker_id=worker_id, cycle=cycle,
                                 recent=recent, pause_state=pause_state)
            _atomic_json(config.heartbeat_path, current)
            _append_log(config, {"recentCycle": recent})
            deadline = time.monotonic() + delay
            while time.monotonic() < deadline:
                if _read_stop(config, worker_id):
                    break
                registry = _ensure_loopback_registry(config.registry_path)
                project_ids = [project["projectId"] for project in registry["folderProjects"]]
                pending_state = config.pause_store.load(project_ids)
                if pending_state["pendingRequest"] is not None:
                    break
                time.sleep(min(0.2, max(0.0, deadline - time.monotonic())))
    except Exception as exc:
        try:
            failed = _heartbeat(config, state="DEGRADED", worker_id=worker_id,
                                cycle=cycle, recent=recent, pause_state=pause_state,
                                error=type(exc).__name__)
            _atomic_json(config.heartbeat_path, failed)
            _append_log(config, failed)
        except Exception:
            pass
        return 2
    finally:
        socket.create_connection = stop_network
        os.environ.update(removed_proxy_environment)
        worker_lock.release()


def _probe_lock(path: Path) -> bool:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        raise UserHostError("worker ownership state is unavailable") from None
    probe = SingleInstanceLock(path)
    if probe.acquire():
        probe.release()
        return False
    return True


def _verified_heartbeat(config: HostConfig, *, require_lock: bool) -> dict | None:
    if not require_lock:
        return None
    if not config.heartbeat_path.exists():
        return None
    value = _read_json(config.heartbeat_path, MAX_HEARTBEAT_BYTES)
    expected_keys = {"schemaVersion", "stateIdentity", "configDigest", "workerInstanceId", "pid",
                     "userIdentity", "processCreationTime", "state", "cycle", "startedAt",
                     "heartbeatAt", "recentCycle"}
    if (not isinstance(value, dict) or not expected_keys.issubset(value)
            or value.get("schemaVersion") != 1
            or value.get("stateIdentity") != config.state_identity
            or value.get("configDigest") != config.config_digest
            or not isinstance(value.get("workerInstanceId"), str)
            or not re.fullmatch(r"[a-f0-9]{32}", value["workerInstanceId"])
            or not isinstance(value.get("pid"), int) or value["pid"] <= 0
            or value.get("state") not in {"STARTING", "RUNNING", "PAUSED", "DEGRADED"}
            or type(value.get("cycle")) is not int or value["cycle"] < 0
            or not isinstance(value.get("heartbeatAt"), str) or len(value["heartbeatAt"]) > 64
            or value.get("recentCycle") is not None and not isinstance(value["recentCycle"], dict)
            or not isinstance(value.get("pauseState"), dict)
            or set(value["pauseState"]) != {"globalPaused", "pausedProjectIds", "pendingRequestId",
                                            "lastAppliedRequestId", "lastAppliedCommand", "lastAppliedProjectId"}
            or type(value["pauseState"].get("globalPaused")) is not bool
            or not isinstance(value["pauseState"].get("pausedProjectIds"), list)
            or any(not isinstance(project_id, str) for project_id in value["pauseState"]["pausedProjectIds"])
            or value["pauseState"].get("pendingRequestId") is not None
            and (not isinstance(value["pauseState"]["pendingRequestId"], str)
                 or not re.fullmatch(r"[a-f0-9]{32}", value["pauseState"]["pendingRequestId"]))
            or value["pauseState"].get("lastAppliedRequestId") is not None
            and (not isinstance(value["pauseState"]["lastAppliedRequestId"], str)
                 or not re.fullmatch(r"[a-f0-9]{32}", value["pauseState"]["lastAppliedRequestId"]))):
        raise UserHostError("worker ownership state does not match this configuration")
    if (_sid_for_process(value["pid"]) != value.get("userIdentity")
            or _sid_for_process(value["pid"]) != _sid_for_process(os.getpid())
            or _process_creation_time(value["pid"]) != value.get("processCreationTime")):
        raise UserHostError("worker process ownership could not be verified")
    return value


def status(config_path: Path) -> dict:
    config = load_config(config_path)
    registry = _ensure_loopback_registry(config.registry_path)
    project_ids = [project["projectId"] for project in registry["folderProjects"]]
    pause_state = config.pause_store.load(project_ids)
    pause_summary = public_pause_state(pause_state)
    control_status = ("PENDING" if pause_state["pendingRequest"] is not None else "IDLE")
    worker_busy = _probe_lock(config.worker_lock_path)
    start_busy = _probe_lock(config.start_lock_path)
    if not worker_busy and not start_busy:
        return {"status": "STOPPED", "platform": "windows" if os.name == "nt" else os.name,
                "globalPaused": pause_summary["globalPaused"],
                "pausedProjectIds": pause_summary["pausedProjectIds"],
                "pauseControlStatus": control_status,
                "lastAppliedControl": pause_state["lastAppliedRequest"]}
    if not worker_busy:
        return {"status": "STARTING", "platform": "windows" if os.name == "nt" else os.name}
    value = _verified_heartbeat(config, require_lock=True)
    if value is None:
        return {"status": "DEGRADED", "error": "HEARTBEAT_UNAVAILABLE",
                "platform": "windows" if os.name == "nt" else os.name}
    result = {"status": value["state"], "platform": "windows" if os.name == "nt" else os.name,
              "pid": value["pid"], "cycle": value["cycle"], "heartbeatAt": value["heartbeatAt"],
              "recentCycle": _safe_cycle(value["recentCycle"]) if value.get("recentCycle") else None,
              "globalPaused": pause_summary["globalPaused"],
              "pausedProjectIds": pause_summary["pausedProjectIds"],
              "pendingControl": pause_summary["pendingRequestId"],
              "lastAppliedControl": pause_state["lastAppliedRequest"],
              "pauseControlStatus": control_status}
    heartbeat_pause = value["pauseState"]
    if (heartbeat_pause["globalPaused"] != pause_summary["globalPaused"]
            or heartbeat_pause["pausedProjectIds"] != pause_summary["pausedProjectIds"]
            or heartbeat_pause["lastAppliedRequestId"] != pause_summary["lastAppliedRequestId"]):
        result["pauseControlStatus"] = "APPLYING"
    if result["pauseControlStatus"] == "PENDING":
        result["pendingControl"] = pause_summary["pendingRequestId"]
    try:
        heartbeat_time = datetime.fromisoformat(value["heartbeatAt"])
        if heartbeat_time.tzinfo is None:
            raise ValueError("timezone missing")
        age = (datetime.now(timezone.utc) - heartbeat_time.astimezone(timezone.utc)).total_seconds()
    except (TypeError, ValueError):
        result["status"] = "DEGRADED"
        result["heartbeatHealth"] = "INVALID"
    else:
        if age < -5 or age > max(60, config.interval_seconds * 3):
            result["status"] = "DEGRADED"
            result["heartbeatHealth"] = "STALE"
    return result


def _emit(value: dict) -> int:
    print(json.dumps(value, sort_keys=True, separators=(",", ":")), flush=True)
    outcome = value.get("result", value.get("status"))
    if not isinstance(outcome, str):
        return 2
    if outcome in {"STARTED", "STOPPED", "RUNNING", "PAUSED", "APPLIED"}:
        return 0
    if outcome == "PENDING":
        return 2 if value.get("error") == "CONTROL_TIMEOUT" else 1
    if outcome == "ALREADY_RUNNING":
        return 3
    if outcome == "STARTING":
        return 1
    # Unknown and degraded outcomes fail closed for shell callers.
    return 2


def _bounded_worker_completed(config: HostConfig, worker) -> dict | None:
    """Recognize only a verified UserHost exit after consuming its configured cap."""
    if (config.max_monitor_observations is None or worker.returncode != 0
            or _probe_lock(config.worker_lock_path)):
        return None
    try:
        heartbeat = _read_json(config.heartbeat_path, MAX_HEARTBEAT_BYTES)
        budget = _observation_budget(config)
    except UserHostError:
        return None
    if (not isinstance(heartbeat, dict) or heartbeat.get("state") != "STOPPED"
            or heartbeat.get("stateIdentity") != config.state_identity
            or heartbeat.get("configDigest") != config.config_digest
            or heartbeat.get("pid") != worker.pid
            or type(heartbeat.get("cycle")) is not int
            or not isinstance(heartbeat.get("recentCycle"), dict)
            or heartbeat["recentCycle"].get("cycle") != heartbeat["cycle"]
            or budget is None or budget["consumed"] != budget["limit"]):
        return None
    return {"result": "STOPPED", "reason": "OBSERVATION_LIMIT", "cycle": heartbeat["cycle"]}


def start(config_path: Path, *, ready_timeout_seconds: float = 15.0) -> int:
    config = load_config(config_path)
    registry = _ensure_loopback_registry(config.registry_path)
    config.pause_store.load([project["projectId"] for project in registry["folderProjects"]])
    config.control_dir.mkdir(parents=True, exist_ok=True)
    start_lock = SingleInstanceLock(config.start_lock_path)
    if not start_lock.acquire():
        return _emit({"result": "ALREADY_RUNNING"})
    worker = None
    try:
        if _probe_lock(config.worker_lock_path):
            _verified_heartbeat(config, require_lock=True)
            return _emit({"result": "ALREADY_RUNNING"})
        _safe_prior_cycle(config)
        try:
            config.stop_path.unlink(missing_ok=True)
        except OSError:
            raise UserHostError("could not clear stale stop request") from None
        command = [sys.executable, str(Path(__file__).resolve()), "--config", str(config.path), "_worker"]
        env = dict(os.environ)
        env.pop("RELAY_GDRIVE_ACCESS_TOKEN", None)
        if config.provider_mode == "fixture":
            env.pop("RELAY_GDRIVE_OAUTH_CLIENT_FILE", None)
        env["PYTHONUNBUFFERED"] = "1"
        flags = 0
        if os.name == "nt":
            flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        try:
            options = {"creationflags": flags} if os.name == "nt" else {"start_new_session": True}
            worker = subprocess.Popen(command, cwd=str(Path(__file__).resolve().parent), env=env,
                                      stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                      stderr=subprocess.DEVNULL, close_fds=True, **options)
        except OSError:
            return _emit({"result": "START_FAILED", "error": "SPAWN_FAILED"})
        deadline = time.monotonic() + ready_timeout_seconds
        while time.monotonic() < deadline:
            if worker.poll() is not None:
                bounded = _bounded_worker_completed(config, worker)
                if bounded is not None:
                    return _emit(bounded)
                return _emit({"result": "START_FAILED", "error": "WORKER_EXITED"})
            if _probe_lock(config.worker_lock_path):
                try:
                    heartbeat = _verified_heartbeat(config, require_lock=True)
                except UserHostError:
                    heartbeat = None
                if heartbeat and heartbeat.get("pid") == worker.pid and heartbeat.get("state") in {
                        "RUNNING", "PAUSED", "DEGRADED"}:
                    return _emit({"result": "STARTED", "ready": True, "pid": worker.pid,
                                  "controllerPid": os.getpid(), "cycle": heartbeat["cycle"],
                                  "status": heartbeat["state"]})
            time.sleep(0.05)
        if worker.poll() is not None:
            bounded = _bounded_worker_completed(config, worker)
            if bounded is not None:
                return _emit(bounded)
            return _emit({"result": "START_FAILED", "error": "WORKER_EXITED"})
        return _emit({"result": "DEGRADED", "error": "READY_TIMEOUT", "pid": worker.pid,
                      "controllerPid": os.getpid()})
    finally:
        start_lock.release()


def stop(config_path: Path) -> int:
    config = load_config(config_path)
    deadline = time.monotonic() + config.stop_timeout_seconds
    while True:
        worker_busy = _probe_lock(config.worker_lock_path)
        start_busy = _probe_lock(config.start_lock_path)
        if worker_busy:
            break
        if not start_busy:
            return _emit({"result": "STOPPED"})
        if time.monotonic() >= deadline:
            return _emit({"result": "STOP_TIMEOUT", "phase": "STARTING"})
        time.sleep(0.05)
    worker = _verified_heartbeat(config, require_lock=True)
    if worker is None:
        return _emit({"result": "STOP_FAILED", "error": "OWNERSHIP_UNAVAILABLE"})
    request = {"schemaVersion": 1, "stateIdentity": config.state_identity,
               "workerInstanceId": worker["workerInstanceId"]}
    _atomic_json(config.stop_path, request, maximum=2048)
    while time.monotonic() < deadline:
        time.sleep(0.1)
        if not _probe_lock(config.worker_lock_path):
            final = _read_json(config.heartbeat_path, MAX_HEARTBEAT_BYTES)
            if (isinstance(final, dict) and final.get("stateIdentity") == config.state_identity
                    and final.get("configDigest") == config.config_digest
                    and final.get("workerInstanceId") == worker["workerInstanceId"]
                    and final.get("state") == "STOPPED"):
                if not _process_is_alive(worker["pid"]):
                    return _emit({"result": "STOPPED", "cycle": final.get("cycle")})
                continue
            return _emit({"result": "STOP_FAILED", "error": "WORKER_EXIT_UNVERIFIED"})
    return _emit({"result": "STOP_TIMEOUT"})


def pause_control(config_path: Path, command: str, project_id: str | None = None) -> int:
    config = load_config(config_path)
    registry = _ensure_loopback_registry(config.registry_path)
    worker_busy = _probe_lock(config.worker_lock_path)
    if not worker_busy:
        return _emit({"result": "INVALID_OWNER", "error": "WORKER_NOT_RUNNING"})
    worker = _verified_heartbeat(config, require_lock=True)
    if worker is None or worker.get("state") not in {"RUNNING", "PAUSED", "DEGRADED"}:
        return _emit({"result": "INVALID_OWNER", "error": "WORKER_OWNERSHIP_UNAVAILABLE"})
    project_ids = [project["projectId"] for project in registry["folderProjects"]]
    try:
        request_id, _state = config.pause_store.request(
            command, project_id, project_ids, worker["workerInstanceId"])
    except PauseStateError as exc:
        if str(exc) == "another pause control request is pending":
            return _emit({"result": "PENDING", "error": "CONTROL_PENDING"})
        raise
    deadline = time.monotonic() + config.stop_timeout_seconds
    while time.monotonic() < deadline:
        if not _probe_lock(config.worker_lock_path):
            break
        worker = _verified_heartbeat(config, require_lock=True)
        if worker is None:
            break
        pause_view = worker.get("pauseState", {})
        if pause_view.get("lastAppliedRequestId") == request_id:
            return _emit({"result": "APPLIED", "requestId": request_id,
                          "command": command, "projectId": project_id,
                          "workerStatus": worker["state"]})
        if worker.get("state") == "DEGRADED":
            return _emit({"result": "DEGRADED", "requestId": request_id,
                          "error": "WORKER_DEGRADED"})
        time.sleep(0.05)
    return _emit({"result": "PENDING", "error": "CONTROL_TIMEOUT", "requestId": request_id})


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--project-id", help="v2 project target for pause/resume")
    parser.add_argument("command", choices=("start", "status", "stop", "pause", "resume", "_worker"))
    args = parser.parse_args(argv)
    try:
        if os.name != "nt":
            raise UserHostError("ARM M05 requires Windows")
        if args.command == "start":
            return start(args.config)
        if args.command == "status":
            return _emit(status(args.config))
        if args.command == "stop":
            return stop(args.config)
        if args.command in {"pause", "resume"}:
            command = ("PAUSE_PROJECT" if args.command == "pause" else "RESUME_PROJECT") if args.project_id else (
                "PAUSE_GLOBAL" if args.command == "pause" else "RESUME_GLOBAL")
            return pause_control(args.config, command, args.project_id)
        if args.project_id is not None:
            raise UserHostError("project target is valid only for pause or resume")
        return _worker(args.config)
    except (UserHostError, ProjectRegistryError, DetectionError, OSError, ValueError):
        print(json.dumps({"result": "DEGRADED", "error": "CONFIG_OR_STATE_INVALID"},
                         sort_keys=True, separators=(",", ":")), flush=True)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
