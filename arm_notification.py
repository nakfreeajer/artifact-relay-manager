"""Offline-qualified metadata notification transport for ARM v2 projects.

This module sends validated M03 event metadata to each enabled project's one
configured Orchestrator endpoint. It does not interpret Orchestrator workflow.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from drive_change_detector import (
    DetectionError,
    _empty_state as _empty_detector_state,
    _json_load as _load_detector_json,
    _validate_state as _validate_detector_state,
)
from project_registry import ProjectRegistry, ProjectRegistryError

LEDGER_SCHEMA = 1
MAX_RETRY_SECONDS = 300
MAX_RESPONSE_BYTES = 8192
EVENT_TYPES = {"PROMPT_CHANGED", "REPORT_CHANGED"}
EVENT_PAYLOAD_KEYS = {
    "projectId", "eventType", "fileId", "providerVersion", "driveUrl", "eventId", "detectedAt"
}
ENTRY_KEYS = {
    "eventId", "projectId", "destination", "payload", "status", "attemptCount",
    "nextAttemptAt", "lastErrorClass", "firstSeenAt", "updatedAt", "receipt",
}
RECEIPT_KEYS = {"projectId", "eventId", "destination", "receivedAt", "signature"}


class NotificationError(ValueError):
    """Sanitized transport, identity, or persistence failure."""


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _atomic_write(path: Path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix="." + path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise NotificationError("could not atomically persist notification ledger") from None


def _canonical_json(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _utc_now(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat().replace("+00:00", "Z")


def _same_or_overlapping(path_a: Path, path_b: Path) -> bool:
    a = os.path.normcase(os.path.normpath(str(path_a)))
    b = os.path.normcase(os.path.normpath(str(path_b)))
    return a == b or a.startswith(b + os.sep) or b.startswith(a + os.sep)


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _read_ledger(path: Path):
    if not path.exists():
        return {"schemaVersion": LEDGER_SCHEMA, "entries": {}}
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_pairs)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        raise NotificationError("cannot read valid notification ledger") from None
    return _validate_ledger(value)


def _validate_ledger(value):
    if (not isinstance(value, dict) or set(value) != {"schemaVersion", "entries"}
            or type(value["schemaVersion"]) is not int or value["schemaVersion"] != LEDGER_SCHEMA
            or not isinstance(value["entries"], dict)):
        raise NotificationError("invalid notification ledger")
    for event_id, entry in value["entries"].items():
        if (not isinstance(event_id, str) or not isinstance(entry, dict) or set(entry) != ENTRY_KEYS
                or entry["eventId"] != event_id or not isinstance(entry["projectId"], str)
                or not isinstance(entry["destination"], str) or not isinstance(entry["payload"], dict)
                or set(entry["payload"]) != EVENT_PAYLOAD_KEYS or entry["payload"].get("eventId") != event_id
                or entry["payload"].get("projectId") != entry["projectId"]
                or type(entry["attemptCount"]) is not int or entry["attemptCount"] < 0
                or entry["status"] not in {"PENDING", "ACKED"}
                or not isinstance(entry["firstSeenAt"], (int, float))
                or not math.isfinite(entry["firstSeenAt"]) or not isinstance(entry["updatedAt"], (int, float))
                or not math.isfinite(entry["updatedAt"])):
            raise NotificationError("invalid notification ledger")
        retry_at = entry["nextAttemptAt"]
        if retry_at is not None and (not isinstance(retry_at, (int, float)) or not math.isfinite(retry_at)):
            raise NotificationError("invalid notification ledger")
        if entry["lastErrorClass"] is not None and not isinstance(entry["lastErrorClass"], str):
            raise NotificationError("invalid notification ledger")
        receipt = entry["receipt"]
        if entry["status"] == "PENDING":
            if receipt is not None:
                raise NotificationError("invalid notification ledger")
        elif (not isinstance(receipt, dict) or set(receipt) != RECEIPT_KEYS
              or receipt["projectId"] != entry["projectId"] or receipt["eventId"] != event_id
              or receipt["destination"] != entry["destination"]
              or not isinstance(receipt["receivedAt"], str)
              or not isinstance(receipt["signature"], str)
              or not re.fullmatch(r"[a-f0-9]{64}", receipt["signature"])):
            raise NotificationError("invalid notification ledger")
    return value


class NotificationSender:
    """Durable, at-least-once sender with an authenticated receipt boundary.

    `secret_resolver` must resolve a configured secret-reference identifier to
    in-memory bytes. It is deliberately injected; credentials are never read
    from or written to the project registry, M03 state, or notification ledger.
    """

    def __init__(self, registry_path, detector_state_path, ledger_path, *, secret_resolver,
                 clock=time.time, writer=_atomic_write, timeout_seconds=3.0,
                 retry_base_seconds=2, retry_max_seconds=MAX_RETRY_SECONDS):
        self.registry = ProjectRegistry(registry_path)
        self.detector_path = Path(detector_state_path).resolve()
        self.ledger_path = Path(ledger_path).resolve()
        self.clock = clock
        self.writer = writer
        self.timeout_seconds = timeout_seconds
        self.retry_base_seconds = retry_base_seconds
        self.retry_max_seconds = retry_max_seconds
        self.secret_resolver = secret_resolver
        paths = [self.registry.path.resolve(), self.detector_path, self.ledger_path]
        if any(_same_or_overlapping(paths[i], paths[j]) for i in range(len(paths)) for j in range(i + 1, len(paths))):
            raise NotificationError("registry, detector state, and notification ledger paths overlap")
        if (not callable(secret_resolver) or not isinstance(timeout_seconds, (int, float))
                or not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 30
                or type(retry_base_seconds) is not int or not 1 <= retry_base_seconds <= MAX_RETRY_SECONDS
                or type(retry_max_seconds) is not int
                or not retry_base_seconds <= retry_max_seconds <= MAX_RETRY_SECONDS):
            raise NotificationError("invalid notification transport settings")

    def _source(self, registry):
        try:
            state = _empty_detector_state() if not self.detector_path.exists() else _load_detector_json(self.detector_path)
            _validate_detector_state(state)
        except (DetectionError, OSError, ValueError):
            raise NotificationError("cannot validate M03 detector state") from None
        projects = {item["projectId"]: item for item in registry["folderProjects"]}
        source_events = {}
        folder_bindings = {}
        for project in registry["folderProjects"]:
            folder_bindings[(project["projectId"], project["architectPromptsFolderId"])] = ("PROMPT_CHANGED", project)
            folder_bindings[(project["projectId"], project["executorReportsFolderId"])] = ("REPORT_CHANGED", project)
        for event in state["events"]:
            project = projects.get(event["projectId"])
            binding = folder_bindings.get((event["projectId"], event["folderId"]))
            if (project is None or binding is None or binding[0] != event["eventType"]
                    or event["eventType"] not in EVENT_TYPES):
                raise NotificationError("M03 event does not match a configured project and folder")
            if event["eventId"] in source_events:
                raise NotificationError("duplicate M03 event identity")
            source_events[event["eventId"]] = (event, project)
        return source_events

    def _validate_bindings(self, ledger, source_events):
        for event_id, entry in ledger["entries"].items():
            source = source_events.get(event_id)
            if source is None:
                raise NotificationError("notification ledger references an unknown M03 event")
            event, project = source
            expected = _event_payload(event)
            if (entry["projectId"] != project["projectId"] or entry["destination"] != project["orchestratorEndpoint"]
                    or entry["payload"] != expected):
                raise NotificationError("notification ledger identity or destination binding changed")
            if entry["status"] == "ACKED":
                secret = self._resolve_secret(project)
                proof = {"projectId": entry["projectId"], "eventId": entry["eventId"]}
                expected_signature = hmac.new(secret, _canonical_json(proof), hashlib.sha256).hexdigest()
                if not hmac.compare_digest(entry["receipt"]["signature"], expected_signature):
                    raise NotificationError("persisted receipt authentication failed")

    def _resolve_secret(self, project):
        reference = project.get("orchestratorSecretRef")
        if not isinstance(reference, str) or not reference:
            raise NotificationError("project has no Orchestrator authentication reference")
        try:
            secret = self.secret_resolver(reference)
        except Exception:
            raise NotificationError("Orchestrator authentication reference could not be resolved") from None
        if not isinstance(secret, bytes) or len(secret) < 16:
            raise NotificationError("resolved Orchestrator authentication key is invalid")
        return secret

    def _persist(self, ledger):
        value = _validate_ledger(ledger)
        data = _canonical_json(value) + b"\n"
        try:
            self.writer(self.ledger_path, data)
        except Exception:
            raise NotificationError("could not persist notification ledger") from None

    @staticmethod
    def _counts(ledger, source_events):
        entries = ledger["entries"]
        enabled_unqueued = sum(1 for event_id, (_event, project) in source_events.items()
                               if project["enabled"] and event_id not in entries)
        pending = sum(entry["status"] == "PENDING" for entry in entries.values()) + enabled_unqueued
        acked = sum(entry["status"] == "ACKED" for entry in entries.values())
        return {"pending": pending, "acked": acked, "queued": len(entries),
                "total": len(entries) + enabled_unqueued}

    def _send(self, entry, secret):
        body = _canonical_json(entry["payload"])
        request = Request(entry["destination"], data=body, method="POST", headers={
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
            "X-ARM-Request-Signature": hmac.new(secret, body, hashlib.sha256).hexdigest(),
        })
        opener = build_opener(ProxyHandler({}), _NoRedirect())
        try:
            response = opener.open(request, timeout=self.timeout_seconds)
            try:
                status = response.status
                ack_body = response.read(MAX_RESPONSE_BYTES + 1)
                signature = response.headers.get("X-ARM-Ack-Signature")
            finally:
                response.close()
        except HTTPError as exc:
            status_code = exc.code
            exc.close()
            raise NotificationError(_http_error_class(status_code)) from None
        except (TimeoutError, URLError, OSError, ValueError, UnicodeError):
            raise NotificationError("TRANSPORT_UNCERTAIN") from None
        if status < 200 or status >= 300:
            raise NotificationError(_http_error_class(status))
        if len(ack_body) > MAX_RESPONSE_BYTES or not signature:
            raise NotificationError("INVALID_ACK")
        try:
            ack = json.loads(ack_body.decode("utf-8"), object_pairs_hook=_unique_pairs)
        except (UnicodeError, json.JSONDecodeError, ValueError):
            raise NotificationError("INVALID_ACK") from None
        if (not isinstance(ack, dict) or set(ack) != {"projectId", "eventId"}
                or ack["projectId"] != entry["projectId"] or ack["eventId"] != entry["eventId"]):
            raise NotificationError("INVALID_ACK")
        expected_signature = hmac.new(secret, _canonical_json(ack), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected_signature):
            raise NotificationError("INVALID_ACK_AUTHENTICATION")
        return ack, signature

    def dispatch(self, *, limit=100):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise NotificationError("dispatch limit must be between 1 and 100")
        registry = self.registry.load()
        source_events = self._source(registry)
        ledger = _read_ledger(self.ledger_path)
        self._validate_bindings(ledger, source_events)
        now = float(self.clock())
        if not math.isfinite(now) or now < 0:
            raise NotificationError("invalid clock value")

        # Persist every new intent in the selected batch before any network side effect.
        selected = []
        next_ledger = json.loads(json.dumps(ledger))
        attempted = acked = pending = deduplicated = deferred = 0
        for event_id in sorted(source_events):
            event, project = source_events[event_id]
            if not project["enabled"]:
                continue
            entry = next_ledger["entries"].get(event_id)
            if entry is None:
                payload = _event_payload(event)
                entry = {
                    "eventId": event_id, "projectId": project["projectId"],
                    "destination": project["orchestratorEndpoint"], "payload": payload,
                    "status": "PENDING", "attemptCount": 0, "nextAttemptAt": None,
                    "lastErrorClass": None, "firstSeenAt": now, "updatedAt": now, "receipt": None,
                }
                next_ledger["entries"][event_id] = entry
            if entry["status"] == "ACKED":
                deduplicated += 1
            elif entry["nextAttemptAt"] is not None and entry["nextAttemptAt"] > now:
                deferred += 1
            else:
                selected.append((event_id, project))
                if len(selected) >= limit:
                    break
        if next_ledger != ledger:
            self._persist(next_ledger)
            ledger = next_ledger
        for event_id, project in selected:
            entry = ledger["entries"][event_id]
            attempt = entry["attemptCount"] + 1
            delay = min(self.retry_base_seconds * (2 ** min(attempt - 1, 30)), self.retry_max_seconds)
            entry["attemptCount"] = attempt
            entry["nextAttemptAt"] = now + delay
            entry["lastErrorClass"] = None
            entry["updatedAt"] = now
            # Record attempt and next bounded retry time durably before sending.
            self._persist(ledger)
            attempted += 1
            try:
                secret = self._resolve_secret(project)
            except NotificationError as exc:
                entry["lastErrorClass"] = str(exc)
                entry["updatedAt"] = now
                self._persist(ledger)
                pending += 1
                continue
            try:
                _ack, signature = self._send(entry, secret)
            except NotificationError as exc:
                entry["lastErrorClass"] = str(exc)
                entry["updatedAt"] = float(self.clock())
                self._persist(ledger)
                pending += 1
                continue
            receipt_time = float(self.clock())
            receipt = {"projectId": entry["projectId"], "eventId": entry["eventId"],
                       "destination": entry["destination"], "receivedAt": _utc_now(receipt_time),
                       "signature": signature}
            entry["status"] = "ACKED"
            entry["nextAttemptAt"] = None
            entry["lastErrorClass"] = None
            entry["updatedAt"] = receipt_time
            entry["receipt"] = receipt
            # ACK is durable before this method reports it as delivered.
            self._persist(ledger)
            acked += 1

        counts = self._counts(ledger, source_events)
        return {"result": "DISPATCHED", "attempted": attempted, "ackedThisRun": acked,
                "pendingThisRun": pending, "deduplicated": deduplicated, "deferred": deferred,
                **counts}

    def status(self):
        registry = self.registry.load()
        source_events = self._source(registry)
        ledger = _read_ledger(self.ledger_path)
        self._validate_bindings(ledger, source_events)
        return {"result": "VALID", **self._counts(ledger, source_events)}


def _event_payload(event):
    return {"projectId": event["projectId"], "eventType": event["eventType"],
            "fileId": event["fileId"], "providerVersion": event["providerVersion"],
            "driveUrl": event["driveUrl"], "eventId": event["eventId"],
            "detectedAt": event["detectedAt"]}


def _http_error_class(status):
    if status == 401 or status == 403:
        return "UNAUTHORIZED"
    if 500 <= status <= 599:
        return "HTTP_5XX"
    if 300 <= status <= 399:
        return "REDIRECT_BLOCKED"
    return "HTTP_ERROR"
