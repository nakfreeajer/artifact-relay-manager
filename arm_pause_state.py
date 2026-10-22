"""Config-bound durable pause controls for the ARM v2 fixture host."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import time
from datetime import datetime, timezone

from relay_userhost import SingleInstanceLock


MAX_STATE_BYTES = 32768
_STATE_KEYS = {"schemaVersion", "stateIdentity", "configDigest", "globalPaused",
               "pausedProjectIds", "pendingRequest", "lastAppliedRequest"}
_REQUEST_KEYS = {"requestId", "command", "projectId", "status", "requestedByWorkerInstanceId",
                 "requestedAt"}
_APPLIED_KEYS = {"requestId", "command", "projectId", "status", "requestedByWorkerInstanceId",
                 "requestedAt", "appliedByWorkerInstanceId", "appliedAt"}
_COMMANDS = {"PAUSE_GLOBAL", "RESUME_GLOBAL", "PAUSE_PROJECT", "RESUME_PROJECT"}


class PauseStateError(ValueError):
    """Sanitized durable pause-state or control validation failure."""


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _timestamp():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _empty(state_identity: str, config_digest: str):
    return {"schemaVersion": 1, "stateIdentity": state_identity, "configDigest": config_digest,
            "globalPaused": False, "pausedProjectIds": [], "pendingRequest": None,
            "lastAppliedRequest": None}


def _validate_request(value, allowed_project_ids, *, applied):
    if value is None:
        return
    expected = _APPLIED_KEYS if applied else _REQUEST_KEYS
    if (not isinstance(value, dict) or set(value) != expected
            or not isinstance(value.get("requestId"), str)
            or not re.fullmatch(r"[a-f0-9]{32}", value["requestId"])
            or not isinstance(value.get("command"), str) or value["command"] not in _COMMANDS
            or value.get("status") != ("APPLIED" if applied else "PENDING")
            or not isinstance(value.get("requestedAt"), str)
            or not isinstance(value.get("requestedByWorkerInstanceId"), str)
            or not re.fullmatch(r"[a-f0-9]{32}", value["requestedByWorkerInstanceId"])):
        raise PauseStateError("pause control state is invalid")
    command = value["command"]
    project_id = value.get("projectId")
    if command.endswith("_GLOBAL"):
        if project_id is not None:
            raise PauseStateError("pause control state is invalid")
    elif not isinstance(project_id, str) or project_id not in allowed_project_ids:
        raise PauseStateError("pause control state is invalid")
    if applied and (not isinstance(value.get("appliedAt"), str)
                    or not isinstance(value.get("appliedByWorkerInstanceId"), str)
                    or not re.fullmatch(r"[a-f0-9]{32}", value["appliedByWorkerInstanceId"])):
        raise PauseStateError("pause control state is invalid")


def _validate(value, state_identity, config_digest, project_ids):
    allowed = set(project_ids)
    paused = value.get("pausedProjectIds") if isinstance(value, dict) else None
    if (not isinstance(value, dict) or set(value) != _STATE_KEYS
            or type(value.get("schemaVersion")) is not int or value["schemaVersion"] != 1
            or value.get("stateIdentity") != state_identity
            or value.get("configDigest") != config_digest
            or type(value.get("globalPaused")) is not bool
            or not isinstance(paused, list) or len(paused) > 100
            or any(not isinstance(project_id, str) or project_id not in allowed for project_id in paused)
            or len(paused) != len(set(paused)) or paused != sorted(paused)):
        raise PauseStateError("pause control state does not match this configuration")
    _validate_request(value["pendingRequest"], allowed, applied=False)
    _validate_request(value["lastAppliedRequest"], allowed, applied=True)
    return value


class PauseStateStore:
    """Atomic read/update store serialized by a per-config OS-held lock."""

    def __init__(self, control_dir: Path, state_identity: str, config_digest: str):
        self.control_dir = Path(control_dir)
        self.state_identity = state_identity
        self.config_digest = config_digest
        self.path = self.control_dir / "pause-state.json"
        self.lock_path = self.control_dir / "pause-state.lock"

    def _with_lock(self, operation):
        self.control_dir.mkdir(parents=True, exist_ok=True)
        lock = SingleInstanceLock(self.lock_path)
        deadline = time.monotonic() + 2.0
        while not lock.acquire():
            if time.monotonic() >= deadline:
                raise PauseStateError("pause control state is busy")
            time.sleep(0.01)
        try:
            return operation()
        finally:
            lock.release()

    def _read_unlocked(self, project_ids):
        if not self.path.exists():
            return _empty(self.state_identity, self.config_digest)
        try:
            raw = self.path.read_bytes()
            if len(raw) > MAX_STATE_BYTES:
                raise ValueError("too large")
            value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            raise PauseStateError("pause control state is invalid") from None
        return _validate(value, self.state_identity, self.config_digest, project_ids)

    def _write_unlocked(self, state, project_ids):
        value = _validate(state, self.state_identity, self.config_digest, project_ids)
        data = (json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        if len(data) > MAX_STATE_BYTES:
            raise PauseStateError("pause control state exceeds its size limit")
        fd = None
        temporary = None
        try:
            fd, raw_path = tempfile.mkstemp(prefix=".pause-state-", suffix=".tmp", dir=self.control_dir)
            temporary = Path(raw_path)
            with os.fdopen(fd, "wb") as stream:
                fd = None
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        except OSError:
            raise PauseStateError("could not persist pause control state") from None
        finally:
            if fd is not None:
                os.close(fd)
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
        return value

    def load(self, project_ids):
        return self._with_lock(lambda: self._read_unlocked(project_ids))

    def initialize(self, project_ids):
        def operation():
            state = self._read_unlocked(project_ids)
            if not self.path.exists():
                return self._write_unlocked(state, project_ids)
            return state
        return self._with_lock(operation)

    def request(self, command, project_id, project_ids, worker_instance_id):
        if command not in _COMMANDS:
            raise PauseStateError("pause command is invalid")
        if command.endswith("_GLOBAL"):
            if project_id is not None:
                raise PauseStateError("pause command target is invalid")
        elif not isinstance(project_id, str) or project_id not in set(project_ids):
            raise PauseStateError("project does not exist")
        if not isinstance(worker_instance_id, str) or not re.fullmatch(r"[a-f0-9]{32}", worker_instance_id):
            raise PauseStateError("worker ownership is invalid")

        def operation():
            state = self._read_unlocked(project_ids)
            pending = state["pendingRequest"]
            if pending is not None:
                if pending["command"] == command and pending["projectId"] == project_id:
                    return pending["requestId"], state
                raise PauseStateError("another pause control request is pending")
            request = {"requestId": secrets.token_hex(16), "command": command,
                       "projectId": project_id, "status": "PENDING",
                       "requestedByWorkerInstanceId": worker_instance_id, "requestedAt": _timestamp()}
            state["pendingRequest"] = request
            self._write_unlocked(state, project_ids)
            return request["requestId"], state
        return self._with_lock(operation)

    def apply_pending(self, project_ids, worker_instance_id):
        if not isinstance(worker_instance_id, str) or not re.fullmatch(r"[a-f0-9]{32}", worker_instance_id):
            raise PauseStateError("worker ownership is invalid")

        def operation():
            state = self._read_unlocked(project_ids)
            request = state["pendingRequest"]
            if request is None:
                return state, False
            command, project_id = request["command"], request["projectId"]
            if command == "PAUSE_GLOBAL":
                state["globalPaused"] = True
            elif command == "RESUME_GLOBAL":
                state["globalPaused"] = False
            elif command == "PAUSE_PROJECT":
                state["pausedProjectIds"] = sorted(set(state["pausedProjectIds"]) | {project_id})
            elif command == "RESUME_PROJECT":
                state["pausedProjectIds"] = sorted(set(state["pausedProjectIds"]) - {project_id})
            applied = dict(request)
            applied.update({"status": "APPLIED", "appliedByWorkerInstanceId": worker_instance_id,
                            "appliedAt": _timestamp()})
            state["pendingRequest"] = None
            state["lastAppliedRequest"] = applied
            self._write_unlocked(state, project_ids)
            return state, True
        return self._with_lock(operation)


def public_pause_state(state):
    """Return a bounded metadata-only heartbeat/status projection."""
    pending = state["pendingRequest"]
    applied = state["lastAppliedRequest"]
    return {"globalPaused": state["globalPaused"],
            "pausedProjectIds": list(state["pausedProjectIds"]),
            "pendingRequestId": pending["requestId"] if pending else None,
            "lastAppliedRequestId": applied["requestId"] if applied else None,
            "lastAppliedCommand": applied["command"] if applied else None,
            "lastAppliedProjectId": applied["projectId"] if applied else None}
