"""Offline two-folder Drive metadata change detector (no APO or body access)."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

from project_registry import ProjectRegistry, ProjectRegistryError

STATE_SCHEMA = 2
LEGACY_STATE_SCHEMA = 1
FOLDER_EVENTS = {
    "architectPromptsFolderId": ("PROMPT_CHANGED", "Architect_Prompts"),
    "executorReportsFolderId": ("REPORT_CHANGED", "Executor_Reports"),
}
_ITEM_ID = re.compile(r"[A-Za-z0-9_-]{1,256}\Z")
_VERSION = re.compile(r"[0-9]+\Z")
_MD5 = re.compile(r"[a-fA-F0-9]{32}\Z")


class DetectionError(ValueError):
    """Sanitized provider, state, or observation failure."""


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def _json_load(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_pairs)
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        raise DetectionError("cannot read valid detector JSON") from None


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
        raise DetectionError("could not atomically persist detector state") from None


def _empty_state():
    return {"schemaVersion": STATE_SCHEMA, "folders": {}, "events": [], "eventIdentities": {}, "ambiguous": []}


def _validate_state_inner(state):
    if (not isinstance(state, dict) or set(state) != {"schemaVersion", "folders", "events", "eventIdentities", "ambiguous"}
            or type(state["schemaVersion"]) is not int or state["schemaVersion"] not in {LEGACY_STATE_SCHEMA, STATE_SCHEMA}
            or not isinstance(state["folders"], dict) or not isinstance(state["events"], list)
            or not isinstance(state["eventIdentities"], dict)
            or not isinstance(state["ambiguous"], list)):
        raise DetectionError("invalid detector state")
    schema = state["schemaVersion"]
    seen_event_ids = set()
    for folder_key, folder in state["folders"].items():
        if (not isinstance(folder_key, str) or not isinstance(folder, dict)
                or set(folder) != {"projectId", "folderId", "eventType", "baselineComplete", "files"}
                or not isinstance(folder["projectId"], str) or not isinstance(folder["folderId"], str)
                or folder_key != _folder_key(folder["projectId"], folder["folderId"])
                or folder["eventType"] not in {"PROMPT_CHANGED", "REPORT_CHANGED"}
                or type(folder["baselineComplete"]) is not bool or not isinstance(folder["files"], dict)):
            raise DetectionError("invalid detector state")
        for item_id, item in folder["files"].items():
            item_keys = {"checksum", "version", "active"} if schema == LEGACY_STATE_SCHEMA else {
                "checksum", "version", "active", "arrivalSerial", "arrivalEligible", "arrivalCandidate"}
            if (not isinstance(item_id, str) or not _ITEM_ID.fullmatch(item_id) or not isinstance(item, dict)
                    or set(item) != item_keys
                    or (item["checksum"] is not None and not _MD5.fullmatch(item["checksum"]))
                    or (item["version"] is not None and not _VERSION.fullmatch(item["version"]))
                    or type(item["active"]) is not bool):
                raise DetectionError("invalid detector state")
            if schema == STATE_SCHEMA:
                candidate = item["arrivalCandidate"]
                if (type(item["arrivalSerial"]) is not int or item["arrivalSerial"] < 0
                        or type(item["arrivalEligible"]) is not bool
                        or (candidate is not None and (not isinstance(candidate, dict)
                            or set(candidate) != {"fingerprint", "observations"}
                            or (candidate["fingerprint"] is not None
                                and (not isinstance(candidate["fingerprint"], str)
                                     or not re.fullmatch(r"[a-f0-9]{64}", candidate["fingerprint"])))
                            or type(candidate["observations"]) is not int
                            or candidate["observations"] not in {0, 1}
                            or (candidate["fingerprint"] is None) != (candidate["observations"] == 0)))
                        or (not item["arrivalEligible"] and candidate is not None)
                        or (not item["active"] and (item["arrivalEligible"] or candidate is not None))):
                    raise DetectionError("invalid detector state")
    for event in state["events"]:
        if (not isinstance(event, dict) or set(event) != {"projectId", "eventId", "eventType", "fileId", "folderId", "providerVersion", "driveUrl", "detectedAt", "changeKind"}
                or not isinstance(event["projectId"], str) or not isinstance(event["eventId"], str)
                or event["eventType"] not in {"PROMPT_CHANGED", "REPORT_CHANGED"}
                or not isinstance(event["fileId"], str) or not _ITEM_ID.fullmatch(event["fileId"])
                or not isinstance(event["folderId"], str) or not _ITEM_ID.fullmatch(event["folderId"])
                or not isinstance(event["providerVersion"], str) or not _VERSION.fullmatch(event["providerVersion"])
                or not isinstance(event["driveUrl"], str) or not isinstance(event["detectedAt"], str)
                or event["changeKind"] not in ({"CREATED", "CONTENT_UPDATED"} if schema == LEGACY_STATE_SCHEMA
                                                else {"CREATED", "CONTENT_UPDATED", "ARRIVED"})
                or event["eventId"] in seen_event_ids):
            raise DetectionError("invalid detector state")
        identity = state["eventIdentities"].get(event["eventId"])
        try:
            identity_values = json.loads(identity)
        except (TypeError, json.JSONDecodeError):
            raise DetectionError("invalid detector state") from None
        expected_fingerprint = None
        if event["changeKind"] == "CREATED":
            expected_fingerprint = "create:" + event["fileId"]
        elif event["changeKind"] == "ARRIVED":
            expected_fingerprint = "arrival:" + (identity_values[5].split(":", 1)[1]
                if isinstance(identity_values, list) and len(identity_values) == 6
                and isinstance(identity_values[5], str) and identity_values[5].startswith("arrival:") else "")
        if (not isinstance(identity_values, list) or len(identity_values) != 6
                or identity_values[:5] != [event["projectId"], event["folderId"], event["eventType"], event["fileId"], event["changeKind"]]
                or event["changeKind"] in {"CREATED", "ARRIVED"} and identity_values[5] != expected_fingerprint
                or event["changeKind"] == "ARRIVED" and not re.fullmatch(r"arrival:[1-9][0-9]*", identity_values[5])
                or event["changeKind"] == "CONTENT_UPDATED" and not re.fullmatch(r"md5:[a-f0-9]{32}:version:[0-9]+", identity_values[5])
                or event["eventId"] != "m03-" + hashlib.sha256(identity.encode("utf-8")).hexdigest()):
            raise DetectionError("invalid detector state")
        if event["changeKind"] == "ARRIVED":
            folder_key = _folder_key(event["projectId"], event["folderId"])
            item_state = state["folders"].get(folder_key, {}).get("files", {}).get(event["fileId"])
            occurrence = int(identity_values[5].split(":", 1)[1])
            if schema != STATE_SCHEMA or item_state is None or occurrence > item_state["arrivalSerial"]:
                raise DetectionError("invalid detector state")
        seen_event_ids.add(event["eventId"])
    if set(state["eventIdentities"]) != seen_event_ids:
        raise DetectionError("invalid detector state")
    for record in state["ambiguous"]:
        if (not isinstance(record, dict) or set(record) != {"projectId", "folderId", "fileId", "reason"}
                or not all(isinstance(record[key], str) for key in record)):
            raise DetectionError("invalid detector state")
    return state


def _validate_state(state):
    try:
        return _validate_state_inner(state)
    except DetectionError:
        raise
    except (TypeError, KeyError, AttributeError):
        raise DetectionError("invalid detector state") from None


def _folder_key(project_id, folder_id):
    return hashlib.sha256((project_id + "\0" + folder_id).encode("utf-8")).hexdigest()


def _canonical_url(item):
    url = item.get("webViewLink")
    try:
        parsed = urlsplit(url)
        port = parsed.port
    except (TypeError, ValueError):
        raise DetectionError("file has no valid retrievable Drive URL") from None
    if (not isinstance(url, str) or parsed.scheme != "https" or parsed.hostname not in {"drive.google.com", "docs.google.com"}
            or parsed.username or parsed.password or port is not None or parsed.fragment or len(url) > 2048
            or not re.search(r"/(?:file|document|spreadsheets|presentation|forms)/d/" + re.escape(item["id"]) + r"/", parsed.path)):
        raise DetectionError("file has no valid retrievable Drive URL")
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))


def _validate_items(project_id, folder_id, entries):
    if not isinstance(entries, list):
        raise DetectionError("provider returned an invalid folder listing")
    normalized = {}
    for item in entries:
        if not isinstance(item, dict):
            raise DetectionError("provider returned invalid file metadata")
        file_id = item.get("id")
        if (not isinstance(file_id, str) or not _ITEM_ID.fullmatch(file_id)
                or item.get("trashed") is not False or item.get("parents") != [folder_id]
                or not isinstance(item.get("name"), str) or not isinstance(item.get("mimeType"), str)
                or item["mimeType"] == "application/vnd.google-apps.folder"):
            raise DetectionError("provider returned invalid direct-child metadata")
        version, checksum = item.get("version"), item.get("md5Checksum")
        if not isinstance(version, str) or not _VERSION.fullmatch(version):
            raise DetectionError("provider returned invalid file version")
        if checksum is not None and (not isinstance(checksum, str) or not _MD5.fullmatch(checksum)):
            raise DetectionError("provider returned invalid content checksum")
        size = item.get("size")
        if size is not None and (not isinstance(size, str) or not _VERSION.fullmatch(size)):
            raise DetectionError("provider returned invalid file size metadata")
        modified_time = item.get("modifiedTime")
        if modified_time is not None:
            if not isinstance(modified_time, str):
                raise DetectionError("provider returned invalid modification time")
            try:
                parsed_time = datetime.fromisoformat(modified_time.replace("Z", "+00:00"))
            except ValueError:
                raise DetectionError("provider returned invalid modification time") from None
            if parsed_time.tzinfo is None:
                raise DetectionError("provider returned invalid modification time")
        if item["mimeType"].startswith("application/vnd.google-apps."):
            # Google Workspace editor metadata does not expose a binary content checksum.
            checksum = None
        if file_id in normalized:
            raise DetectionError("provider returned duplicate file identity")
        normalized[file_id] = {"version": version, "checksum": checksum.lower() if checksum else None,
                               "size": size, "modifiedTime": modified_time,
                               "url": _canonical_url(item), "name": item["name"], "mimeType": item["mimeType"]}
    return normalized


def _arrival_fingerprint(meta):
    is_workspace = meta["mimeType"].startswith("application/vnd.google-apps.")
    if is_workspace and meta["modifiedTime"] is None:
        return None
    if not is_workspace and meta["checksum"] is None and meta["size"] is None:
        return None
    stable = {key: meta[key] for key in ("checksum", "size", "version", "modifiedTime", "name", "mimeType")}
    encoded = json.dumps(stable, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _migrate_state(state):
    """Upgrade validated v1 observations without changing any persisted event IDs."""
    _validate_state(state)
    if state["schemaVersion"] == STATE_SCHEMA:
        return state
    upgraded = json.loads(json.dumps(state))
    upgraded["schemaVersion"] = STATE_SCHEMA
    legacy_pending = {(row["projectId"], row["folderId"], row["fileId"])
                      for row in upgraded["ambiguous"]
                      if row["reason"] == "NEW_OR_MOVED_IN_UNPROVEN"}
    for folder in upgraded["folders"].values():
        for file_id, item in folder["files"].items():
            pending = item["active"] and (folder["projectId"], folder["folderId"], file_id) in legacy_pending
            item.update({"arrivalSerial": 0, "arrivalEligible": pending,
                         "arrivalCandidate": {"fingerprint": None, "observations": 0} if pending else None})
    return _validate_state(upgraded)


class FixtureProvider:
    """Deterministic local metadata feed; never performs a network request."""

    def __init__(self, fixture):
        if not isinstance(fixture, dict) or set(fixture) != {"folders", "fail"}:
            raise DetectionError("invalid provider fixture")
        if type(fixture["fail"]) is not bool or not isinstance(fixture["folders"], dict):
            raise DetectionError("invalid provider fixture")
        self.fixture = fixture

    @classmethod
    def from_path(cls, path):
        return cls(_json_load(Path(path)))

    def list_folder(self, folder_id):
        if self.fixture["fail"]:
            raise DetectionError("provider listing failed")
        if folder_id not in self.fixture["folders"]:
            raise DetectionError("provider listing is incomplete")
        folder = self.fixture["folders"][folder_id]
        if (not isinstance(folder, dict) or set(folder) != {"complete", "items"}
                or folder["complete"] is not True or not isinstance(folder["items"], list)):
            raise DetectionError("provider listing is incomplete")
        return folder["items"]

class DriveMetadataProvider:
    """Adapter for the accepted read-only Drive listing client."""

    def __init__(self, client):
        self.client = client

    def list_folder(self, folder_id):
        return self.client.list_children(folder_id)


class DriveChangeDetector:
    def __init__(self, registry_path, state_path, *, writer=_atomic_write):
        self.registry = ProjectRegistry(registry_path)
        self.state_path = Path(state_path).resolve()
        if os.path.normcase(os.path.normpath(str(self.state_path))) == os.path.normcase(os.path.normpath(str(self.registry.path))):
            raise DetectionError("detector state path aliases project registry")
        self.writer = writer

    def scan(self, provider):
        registry = self.registry.load()
        projects = registry["folderProjects"]
        # Read and validate every configured listing before any state transition.
        snapshots = []
        observed_bindings = {}
        for project in projects:
            for config_key, (event_type, _name) in FOLDER_EVENTS.items():
                folder_id = project[config_key]
                entries = provider.list_folder(folder_id)
                items = _validate_items(project["projectId"], folder_id, entries)
                for file_id in items:
                    binding = (project["projectId"], folder_id)
                    if file_id in observed_bindings and observed_bindings[file_id] != binding:
                        raise DetectionError("provider returned overlapping file identity")
                    observed_bindings[file_id] = binding
                snapshots.append((project["projectId"], folder_id, event_type, items))
        state = _empty_state() if not self.state_path.exists() else _migrate_state(_json_load(self.state_path))
        # Verify persisted project/folder identity before deriving any output.
        configured = {(p["projectId"], p[k], event_type)
                      for p in projects for k, (event_type, _) in FOLDER_EVENTS.items()}
        if any((v["projectId"], v["folderId"], v["eventType"]) not in configured for v in state["folders"].values()):
            raise DetectionError("persisted folder state does not match configured projects")
        if any((e["projectId"], e["folderId"], e["eventType"]) not in configured for e in state["events"]):
            raise DetectionError("persisted event does not match configured projects")
        if any((r["projectId"], r["folderId"]) not in {(p, f) for p, f, _ in configured} for r in state["ambiguous"]):
            raise DetectionError("persisted ambiguity does not match configured projects")
        next_state = json.loads(json.dumps(state))
        existing_ids = {event["eventId"] for event in next_state["events"]}
        new_events = []
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        for project_id, folder_id, event_type, items in snapshots:
            folder_key = _folder_key(project_id, folder_id)
            folder_state = next_state["folders"].get(folder_key)
            if folder_state is None:
                folder_state = {"projectId": project_id, "folderId": folder_id, "eventType": event_type,
                                "baselineComplete": False, "files": {}}
                next_state["folders"][folder_key] = folder_state
            if not folder_state["baselineComplete"]:
                folder_state["files"] = {file_id: _file_state(meta, active=True, arrival_serial=0,
                                                               arrival_eligible=False, candidate=None)
                                          for file_id, meta in items.items()}
                folder_state["baselineComplete"] = True
                continue
            for file_id, meta in items.items():
                previous = folder_state["files"].get(file_id)
                if previous is None:
                    previous = _file_state(meta, active=True, arrival_serial=0,
                                           arrival_eligible=True, candidate=None)
                    folder_state["files"][file_id] = previous
                elif not previous["active"]:
                    previous.update({"active": True, "arrivalEligible": True, "arrivalCandidate": None})

                if previous["arrivalEligible"]:
                    fingerprint = _arrival_fingerprint(meta)
                    candidate = previous["arrivalCandidate"]
                    if fingerprint is None:
                        previous["arrivalCandidate"] = None
                        _add_ambiguous(next_state, project_id, folder_id, file_id,
                                       "ARRIVAL_STABILITY_METADATA_UNAVAILABLE")
                    elif candidate is None or candidate["fingerprint"] is None:
                        previous["arrivalCandidate"] = {"fingerprint": fingerprint, "observations": 1}
                        next_state["ambiguous"] = [r for r in next_state["ambiguous"]
                            if not (r["projectId"] == project_id and r["folderId"] == folder_id
                                    and r["fileId"] == file_id
                                    and r["reason"] == "ARRIVAL_STABILITY_METADATA_UNAVAILABLE")]
                    elif candidate["fingerprint"] != fingerprint:
                        previous["arrivalCandidate"] = {"fingerprint": fingerprint, "observations": 1}
                    else:
                        arrival_serial = previous["arrivalSerial"] + 1
                        change_kind = "ARRIVED"
                        fingerprint = "arrival:" + str(arrival_serial)
                        event_key = json.dumps([project_id, folder_id, event_type, file_id,
                                                change_kind, fingerprint], separators=(",", ":"))
                        event_id = "m03-" + hashlib.sha256(event_key.encode("utf-8")).hexdigest()
                        if event_id not in existing_ids:
                            event = {"projectId": project_id, "eventId": event_id, "eventType": event_type,
                                "fileId": file_id, "folderId": folder_id, "providerVersion": meta["version"],
                                "driveUrl": meta["url"], "detectedAt": now, "changeKind": change_kind}
                            next_state["events"].append(event)
                            next_state["eventIdentities"][event_id] = event_key
                            new_events.append(event)
                            existing_ids.add(event_id)
                        previous.update({"arrivalSerial": arrival_serial, "arrivalEligible": False,
                                         "arrivalCandidate": None})
                        next_state["ambiguous"] = [r for r in next_state["ambiguous"]
                            if not (r["projectId"] == project_id and r["folderId"] == folder_id
                                    and r["fileId"] == file_id)]
                elif (previous["checksum"] is not None and meta["checksum"] is not None
                      and previous["checksum"] != meta["checksum"]):
                    change_kind = "CONTENT_UPDATED"
                    content_fingerprint = "md5:" + meta["checksum"] + ":version:" + meta["version"]
                    event_key = json.dumps([project_id, folder_id, event_type, file_id,
                                            change_kind, content_fingerprint], separators=(",", ":"))
                    event_id = "m03-" + hashlib.sha256(event_key.encode("utf-8")).hexdigest()
                    if event_id not in existing_ids:
                        event = {"projectId": project_id, "eventId": event_id, "eventType": event_type,
                            "fileId": file_id, "folderId": folder_id, "providerVersion": meta["version"],
                            "driveUrl": meta["url"], "detectedAt": now, "changeKind": change_kind}
                        next_state["events"].append(event)
                        next_state["eventIdentities"][event_id] = event_key
                        new_events.append(event)
                        existing_ids.add(event_id)
                    next_state["ambiguous"] = [r for r in next_state["ambiguous"]
                        if not (r["projectId"] == project_id and r["folderId"] == folder_id
                                and r["fileId"] == file_id)]
                else:
                    if previous["checksum"] is None or meta["checksum"] is None:
                        if previous["version"] != meta["version"]:
                            _add_ambiguous(next_state, project_id, folder_id, file_id, "CONTENT_CHANGE_UNVERIFIED")
                previous.update({"checksum": meta["checksum"] or previous["checksum"],
                                 "version": meta["version"], "active": True})
            for file_id, previous in folder_state["files"].items():
                if file_id not in items:
                    previous.update({"active": False, "arrivalEligible": False, "arrivalCandidate": None})
        _validate_state(next_state)
        data = (json.dumps(next_state, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            self.writer(self.state_path, data)
        except Exception as exc:
            if isinstance(exc, DetectionError):
                raise
            raise DetectionError("could not atomically persist detector state") from None
        return {"result": "SCANNED", "newEvents": new_events,
                "totalEvents": len(next_state["events"]), "ambiguousCount": len(next_state["ambiguous"]),
                "candidateCount": sum(1 for folder in next_state["folders"].values()
                                      for item in folder["files"].values() if item["arrivalEligible"])}


def _file_state(meta, *, active, arrival_serial, arrival_eligible, candidate):
    return {"checksum": meta["checksum"], "version": meta["version"], "active": active,
            "arrivalSerial": arrival_serial, "arrivalEligible": arrival_eligible,
            "arrivalCandidate": candidate}


def _add_ambiguous(state, project_id, folder_id, file_id, reason):
    record = {"projectId": project_id, "folderId": folder_id, "fileId": file_id, "reason": reason}
    if record not in state["ambiguous"]:
        state["ambiguous"].append(record)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", required=True, type=Path)
    parser.add_argument("--state", required=True, type=Path)
    parser.add_argument("--provider-fixture", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = DriveChangeDetector(args.registry, args.state).scan(FixtureProvider.from_path(args.provider_fixture))
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0
    except (DetectionError, ProjectRegistryError) as exc:
        print(json.dumps({"error": str(exc)}, sort_keys=True, separators=(",", ":")))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
