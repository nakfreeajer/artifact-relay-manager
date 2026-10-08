"""Strict local registry for existing Relay project configurations."""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

import drive_adapter

SCHEMA_VERSION = 1
TOP_KEYS = {"schemaVersion", "projects"}
ENTRY_KEYS = {"projectId", "displayName", "configPath", "statePath", "enabled"}


class ProjectRegistryError(Exception):
    """Sanitized registry validation or persistence error."""


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def default_registry_path(environ=None) -> Path:
    env = os.environ if environ is None else environ
    local = env.get("LOCALAPPDATA")
    if not local:
        raise ProjectRegistryError("LOCALAPPDATA is unavailable; supply --registry")
    return Path(local) / "ArtifactRelayManager" / "projects.json"


def _canonical_path(value, *, must_exist=False, file=False) -> str:
    if not isinstance(value, str) or not value or len(value) > 32767 or any(ord(ch) < 32 for ch in value):
        raise ProjectRegistryError("invalid project path")
    # Reject remote paths; the registry only references local filesystem data.
    if value.startswith(("\\\\", "//")):
        raise ProjectRegistryError("project paths must be local")
    try:
        path = Path(value).resolve(strict=must_exist)
    except (OSError, RuntimeError, ValueError):
        raise ProjectRegistryError("invalid project path") from None
    if not path.is_absolute():
        raise ProjectRegistryError("project path must be absolute")
    if must_exist and (not path.exists() or (file and not path.is_file())):
        raise ProjectRegistryError("referenced project config is missing")
    return path.as_posix()


def _path_key(value: str) -> str:
    return os.path.normcase(os.path.normpath(value))


def _load_config(entry):
    config_path = Path(entry["configPath"])
    try:
        config = drive_adapter._load_drive_config(config_path)
    except Exception as exc:
        if isinstance(exc, ProjectRegistryError):
            raise
        raise ProjectRegistryError("referenced Drive project config is invalid") from None
    if config["projectId"] != entry["projectId"]:
        raise ProjectRegistryError("registry projectId does not match Drive project config")
    return config


def _validate_entry_shape(entry):
    if not isinstance(entry, dict) or set(entry) != ENTRY_KEYS:
        raise ProjectRegistryError("invalid registry project entry")
    if not isinstance(entry["projectId"], str) or not re.fullmatch(r"[A-Za-z0-9._-]+", entry["projectId"]):
        raise ProjectRegistryError("invalid registry projectId")
    name = entry["displayName"]
    if (not isinstance(name, str) or not name.strip() or len(name) > 200
            or any(ord(ch) < 32 for ch in name)):
        raise ProjectRegistryError("invalid project displayName")
    if type(entry["enabled"]) is not bool:
        raise ProjectRegistryError("invalid project enabled value")
    config_path = _canonical_path(entry["configPath"], must_exist=True, file=True)
    state_path = _canonical_path(entry["statePath"])
    if config_path != entry["configPath"] or state_path != entry["statePath"]:
        raise ProjectRegistryError("registry project paths are not canonical")
    return entry


def _validate_projects(projects):
    if not isinstance(projects, list):
        raise ProjectRegistryError("invalid registry projects value")
    identities = {key: set() for key in ("projectId", "configPath", "statePath", "workspace", "folderId")}
    normalized = []
    for entry in projects:
        _validate_entry_shape(entry)
        config = _load_config(entry)
        values = {
            "projectId": entry["projectId"],
            "configPath": _path_key(entry["configPath"]),
            "statePath": _path_key(entry["statePath"]),
            "workspace": _path_key(Path(config["_workspace"]).resolve().as_posix()),
            "folderId": config["folderId"],
        }
        for field, value in values.items():
            if value in identities[field]:
                raise ProjectRegistryError(f"duplicate project {field}")
            identities[field].add(value)
        normalized.append(dict(entry))
    return sorted(normalized, key=lambda item: item["projectId"])


def _validate_document(value):
    if (not isinstance(value, dict) or set(value) != TOP_KEYS
            or type(value.get("schemaVersion")) is not int or value["schemaVersion"] != SCHEMA_VERSION):
        raise ProjectRegistryError("invalid registry schema")
    projects = _validate_projects(value["projects"])
    return {"schemaVersion": SCHEMA_VERSION, "projects": projects}


class ProjectRegistry:
    def __init__(self, path):
        raw_path = str(path)
        if raw_path.startswith(("\\\\", "//")):
            raise ProjectRegistryError("registry path must be local")
        try:
            self.path = Path(raw_path).resolve()
        except (OSError, RuntimeError, ValueError):
            raise ProjectRegistryError("invalid registry path") from None

    def load(self):
        if not self.path.exists():
            return {"schemaVersion": SCHEMA_VERSION, "projects": []}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"), object_pairs_hook=_unique_pairs)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            raise ProjectRegistryError("cannot read valid project registry") from None
        return _validate_document(value)

    def _write(self, projects):
        document = _validate_document({"schemaVersion": SCHEMA_VERSION, "projects": projects})
        data = (json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(prefix="." + self.path.name + ".", dir=self.path.parent)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temp_name, self.path)
            except Exception:
                try:
                    os.unlink(temp_name)
                except OSError:
                    pass
                raise
        except OSError:
            raise ProjectRegistryError("could not persist project registry") from None
        return document

    def list(self):
        return self.load()["projects"]

    def show(self, project_id):
        for entry in self.load()["projects"]:
            if entry["projectId"] == project_id:
                return entry
        raise ProjectRegistryError("projectId is not registered")

    def add(self, project_id, display_name, config_path, state_path, enabled=True):
        current = self.load()["projects"]
        canonical_config = _canonical_path(str(config_path), must_exist=True, file=True)
        canonical_state = _canonical_path(str(state_path))
        entry = {"projectId": project_id, "displayName": display_name, "configPath": canonical_config,
                 "statePath": canonical_state, "enabled": enabled}
        return self._write(current + [entry])

    def set_enabled(self, project_id, enabled):
        current = self.load()["projects"]
        found = False
        updated = []
        for entry in current:
            item = dict(entry)
            if item["projectId"] == project_id:
                item["enabled"] = enabled
                found = True
            updated.append(item)
        if not found:
            raise ProjectRegistryError("projectId is not registered")
        return self._write(updated)

    def remove(self, project_id):
        current = self.load()["projects"]
        updated = [entry for entry in current if entry["projectId"] != project_id]
        if len(updated) == len(current):
            raise ProjectRegistryError("projectId is not registered")
        return self._write(updated)

    def validate(self, project_id=None):
        projects = self.load()["projects"]
        if project_id is not None and not any(e["projectId"] == project_id for e in projects):
            raise ProjectRegistryError("projectId is not registered")
        return projects if project_id is None else [e for e in projects if e["projectId"] == project_id]
