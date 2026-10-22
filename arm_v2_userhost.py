"""Manually launched, per-user ARM v2 fixture host.

This bounded M05 implementation intentionally supports only a local metadata
fixture and loopback simulated Orchestrators. It never constructs Drive OAuth.
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
from drive_change_detector import DetectionError
from project_registry import ProjectRegistry, ProjectRegistryError
from relay_userhost import SingleInstanceLock


class UserHostError(ValueError):
    """Sanitized ARM v2 user-host configuration or ownership failure."""


CONFIG_KEYS = {
    "schemaVersion", "registryPath", "detectorStatePath", "notificationLedgerPath",
    "providerFixturePath", "testSecrets", "intervalSeconds", "stopTimeoutSeconds",
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


class HostConfig:
    def __init__(self, path: Path, values: dict, raw_digest: str):
        self.path = path
        self.registry_path = _canonical_file(values["registryPath"], "project registry")
        self.detector_path = _canonical_output_file(values["detectorStatePath"], "detector state")
        self.ledger_path = _canonical_output_file(values["notificationLedgerPath"], "notification ledger")
        self.fixture_path = _canonical_file(values["providerFixturePath"], "provider fixture")
        self.test_secrets = {key: base64.b64decode(value, validate=True)
                             for key, value in values["testSecrets"].items()}
        self.interval_seconds = values["intervalSeconds"]
        self.stop_timeout_seconds = values["stopTimeoutSeconds"]
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
    if (not isinstance(values, dict) or set(values) != CONFIG_KEYS
            or type(values.get("schemaVersion")) is not int or values["schemaVersion"] != 1):
        raise UserHostError("host configuration schema is invalid")
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
    try:
        config = HostConfig(resolved, values, hashlib.sha256(raw).hexdigest())
    except (KeyError, TypeError, ValueError, OSError):
        raise UserHostError("host configuration is invalid") from None
    if any(len(key) < 16 for key in config.test_secrets.values()):
        raise UserHostError("offline test key is invalid")
    paths = [config.registry_path, config.detector_path, config.ledger_path, config.fixture_path,
             config.path]
    norm = [os.path.normcase(os.path.normpath(str(p))) for p in paths]
    if len(set(norm)) != len(norm):
        raise UserHostError("host files must have distinct paths")
    for p in (config.registry_path, config.fixture_path, config.path):
        if not _inside_local_app_data(p):
            raise UserHostError("host input files must remain under current-user local data")
    for p in (config.detector_path, config.ledger_path):
        if not _inside_local_app_data(p.parent):
            raise UserHostError("host state files must remain under current-user local data")
    _ensure_loopback_registry(config.registry_path)
    _read_json(config.fixture_path, 4 * 1024 * 1024)
    return config


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


def _worker(config_path: Path) -> int:
    config = load_config(config_path)
    if ("RELAY_GDRIVE_ACCESS_TOKEN" in os.environ
            or "RELAY_GDRIVE_OAUTH_CLIENT_FILE" in os.environ):
        raise UserHostError("M05 fixture worker refuses OAuth environment inputs")
    config.control_dir.mkdir(parents=True, exist_ok=True)
    worker_lock = SingleInstanceLock(config.worker_lock_path)
    if not worker_lock.acquire():
        return 3
    worker_id = secrets.token_hex(16)
    stop_network = socket.create_connection

    def loopback_connection(address, *args, **kwargs):
        host = address[0]
        try:
            allowed = ipaddress.ip_address(host).is_loopback
        except ValueError:
            allowed = isinstance(host, str) and host.casefold() == "localhost"
        if not allowed:
            raise OSError("M05 offline host blocked non-loopback network access")
        return stop_network(address, *args, **kwargs)

    socket.create_connection = loopback_connection
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
        provider = ReloadingFixtureProvider(config.fixture_path)
        monitor = ForegroundMonitor(
            config.registry_path, config.detector_path, config.ledger_path,
            provider=provider,
            secret_resolver=config.test_secrets.get,
            interval_seconds=config.interval_seconds, dispatch_limit=8,
        )
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
