"""Strict local registry for existing Relay project configurations."""
from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path

import drive_adapter
import project_folder_config

SCHEMA_VERSION = 1
TOP_KEYS = {"schemaVersion", "projects"}
CURRENT_SCHEMA_VERSION = 2
CURRENT_TOP_KEYS = {"schemaVersion", "projects", "folderProjects"}
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
    if not isinstance(value, dict) or type(value.get("schemaVersion")) is not int:
        raise ProjectRegistryError("invalid registry schema")
    if value["schemaVersion"] == SCHEMA_VERSION and set(value) == TOP_KEYS:
        projects = _validate_projects(value["projects"])
        folder_projects = []
    elif value["schemaVersion"] == CURRENT_SCHEMA_VERSION and set(value) == CURRENT_TOP_KEYS:
        projects = _validate_projects(value["projects"])
        folder_projects = _validate_folder_projects(value["folderProjects"], projects)
    else:
        raise ProjectRegistryError("invalid registry schema")
    return {"schemaVersion": CURRENT_SCHEMA_VERSION, "projects": projects,
            "folderProjects": folder_projects}


def _validate_folder_projects(projects, legacy_projects):
    if not isinstance(projects, list):
        raise ProjectRegistryError("invalid two-folder projects value")
    identities = {entry["projectId"] for entry in legacy_projects}
    folder_ids = {_load_config(entry)["folderId"] for entry in legacy_projects}
    workspaces = {_path_key(str(_load_config(entry)["_workspace"])) for entry in legacy_projects}
    normalized = []
    for item in projects:
        try:
            item = project_folder_config.validate_project(item, _MetadataOnlyProvider(item))
        except Exception as exc:
            raise ProjectRegistryError("invalid two-folder project config") from None
        if item["projectId"] in identities:
            raise ProjectRegistryError("duplicate project projectId")
        identities.add(item["projectId"])
        ids = {item["driveRootId"], item["architectPromptsFolderId"], item["executorReportsFolderId"]}
        if len(ids) != 3 or ids & folder_ids:
            raise ProjectRegistryError("duplicate project Drive folder identity")
        if item["workspace"] is not None:
            workspace_key = _path_key(item["workspace"])
            if workspace_key in workspaces:
                raise ProjectRegistryError("duplicate project workspace")
            workspaces.add(workspace_key)
        folder_ids.update(ids)
        normalized.append(dict(item))
    return sorted(normalized, key=lambda item: item["projectId"])


class _MetadataOnlyProvider:
    """Validate persisted config shape without granting provider/network access."""
    def __init__(self, config):
        self.config = config

    def folder(self, item_id):
        if item_id == self.config.get("driveRootId"):
            return {"id": item_id, "mimeType": project_folder_config.FOLDER_MIME, "trashed": False}
        raise project_folder_config.FolderConfigError("folder not found")

    def children(self, root_id):
        if root_id != self.config.get("driveRootId"):
            return []
        return [
            {"id": self.config["architectPromptsFolderId"], "name": project_folder_config.PROMPTS_NAME,
             "mimeType": project_folder_config.FOLDER_MIME, "parents": [root_id], "trashed": False},
            {"id": self.config["executorReportsFolderId"], "name": project_folder_config.REPORTS_NAME,
             "mimeType": project_folder_config.FOLDER_MIME, "parents": [root_id], "trashed": False},
        ]


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
            return {"schemaVersion": CURRENT_SCHEMA_VERSION, "projects": [], "folderProjects": []}
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"), object_pairs_hook=_unique_pairs)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            raise ProjectRegistryError("cannot read valid project registry") from None
        return _validate_document(value)

    def _write(self, projects):
        current = self.load()
        document = _validate_document({"schemaVersion": CURRENT_SCHEMA_VERSION, "projects": projects,
                                      "folderProjects": current["folderProjects"]})
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

    def list_folder_projects(self):
        return self.load()["folderProjects"]

    def show_folder_project(self, project_id):
        for entry in self.list_folder_projects():
            if entry["projectId"] == project_id:
                return entry
        raise ProjectRegistryError("projectId is not registered")

    def configure_folder_project(self, *, project_id, display_name, root_url, prompts_id, reports_id,
                                 endpoint, provider, repository=None, workspace=None, secret_ref=None,
                                 enabled=False):
        current = self.load()
        if any(item["projectId"] == project_id for item in current["projects"] + current["folderProjects"]):
            raise ProjectRegistryError("duplicate project projectId")
        try:
            config = project_folder_config.build_project(project_id, display_name, root_url, prompts_id,
                reports_id, endpoint, provider, repository=repository, workspace=workspace,
                secret_ref=secret_ref, enabled=enabled)
        except project_folder_config.FolderConfigError as exc:
            raise ProjectRegistryError(str(exc)) from None
        _validate_document({"schemaVersion": CURRENT_SCHEMA_VERSION,
                            "projects": current["projects"],
                            "folderProjects": current["folderProjects"] + [config]})
        document = {"schemaVersion": CURRENT_SCHEMA_VERSION, "projects": current["projects"],
                    "folderProjects": sorted(current["folderProjects"] + [config], key=lambda item: item["projectId"])}
        self._write_document(document)
        return config

    def _write_document(self, document):
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

    def validate_folder_projects(self, provider, project_id=None):
        projects = self.list_folder_projects()
        selected = projects if project_id is None else [e for e in projects if e["projectId"] == project_id]
        if project_id is not None and not selected:
            raise ProjectRegistryError("projectId is not registered")
        try:
            return [project_folder_config.validate_project(item, provider) for item in selected]
        except project_folder_config.FolderConfigError as exc:
            raise ProjectRegistryError(str(exc)) from None
