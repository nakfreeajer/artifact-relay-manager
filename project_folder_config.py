"""Offline validation for v2 two-folder project configuration."""
from __future__ import annotations

import json
import re
import urllib.parse
from pathlib import Path

PROMPTS_NAME = "Architect_Prompts"
REPORTS_NAME = "Executor_Reports"
FOLDER_MIME = "application/vnd.google-apps.folder"
_ID = re.compile(r"[A-Za-z0-9_-]{1,256}\Z")


class FolderConfigError(ValueError):
    """Sanitized project folder configuration failure."""


class FakeDriveProvider:
    """Read-only deterministic metadata provider loaded from a local fixture."""

    def __init__(self, folders: dict):
        if not isinstance(folders, dict) or not isinstance(folders.get("items"), list):
            raise FolderConfigError("invalid offline Drive fixture")
        self.items = folders["items"]
        self.fail = folders.get("fail") is True

    @classmethod
    def from_path(cls, path):
        try:
            value = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            raise FolderConfigError("cannot read offline Drive fixture") from None
        return cls(value)

    def folder(self, item_id):
        if self.fail:
            raise FolderConfigError("offline Drive provider read failed")
        matches = [item for item in self.items if isinstance(item, dict) and item.get("id") == item_id]
        if len(matches) != 1:
            raise FolderConfigError("Drive folder is missing or ambiguous")
        return matches[0]

    def children(self, root_id):
        if self.fail:
            raise FolderConfigError("offline Drive provider read failed")
        return [item for item in self.items if isinstance(item, dict)
                and isinstance(item.get("parents"), list) and root_id in item["parents"]]


def canonical_folder_url(value: str) -> tuple[str, str]:
    if not isinstance(value, str) or len(value) > 2048:
        raise FolderConfigError("invalid Drive root URL")
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError:
        raise FolderConfigError("invalid Drive root URL") from None
    match = re.fullmatch(r"/drive/(?:u/[0-9]+/)?folders/([A-Za-z0-9_-]{1,256})", parsed.path)
    query = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    benign_query = (not parsed.query or set(query) == {"usp"} and len(query["usp"]) == 1
                    and query["usp"][0] in {"sharing", "drive_link", "drive_web", "drive_fs", "drivesdk"})
    if (parsed.scheme != "https" or parsed.hostname != "drive.google.com" or port is not None
            or parsed.username or parsed.password or parsed.fragment or not benign_query or not match):
        raise FolderConfigError("invalid Drive root URL")
    item_id = match.group(1)
    return item_id, f"https://drive.google.com/drive/folders/{item_id}"


def validate_endpoint(value: str) -> str:
    if not isinstance(value, str) or len(value) > 2048:
        raise FolderConfigError("invalid Orchestrator endpoint")
    try:
        parsed = urllib.parse.urlsplit(value)
        port = parsed.port
    except ValueError:
        raise FolderConfigError("invalid Orchestrator endpoint") from None
    host = (parsed.hostname or "").lower()
    loopback = host in {"localhost", "127.0.0.1", "::1"}
    if (parsed.scheme not in ({"https", "http"} if loopback else {"https"}) or not host
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or port is not None and not 1 <= port <= 65535):
        raise FolderConfigError("invalid Orchestrator endpoint")
    return value


def validate_project(config: dict, provider: FakeDriveProvider) -> dict:
    required = {"schemaVersion", "projectId", "displayName", "repository", "workspace",
                "driveRootUrl", "driveRootId", "architectPromptsFolderId", "architectPromptsFolderUrl",
                "executorReportsFolderId", "executorReportsFolderUrl", "orchestratorEndpoint",
                "orchestratorSecretRef", "enabled", "configRevision"}
    if not isinstance(config, dict) or set(config) != required:
        raise FolderConfigError("invalid two-folder project config")
    if type(config["schemaVersion"]) is not int or config["schemaVersion"] != 2:
        raise FolderConfigError("invalid two-folder project schema")
    if not isinstance(config["projectId"], str) or not re.fullmatch(r"[A-Za-z0-9._-]+", config["projectId"]):
        raise FolderConfigError("invalid projectId")
    if not isinstance(config["displayName"], str) or not config["displayName"].strip() or len(config["displayName"]) > 200:
        raise FolderConfigError("invalid displayName")
    if config["repository"] is not None and (not isinstance(config["repository"], str)
            or not re.fullmatch(r"[^/\s]+/[^/\s]+", config["repository"])):
        raise FolderConfigError("invalid repository")
    if config["workspace"] is not None:
        if (not isinstance(config["workspace"], str) or not Path(config["workspace"]).is_absolute()
                or config["workspace"].startswith(("\\\\", "//"))):
            raise FolderConfigError("invalid local workspace")
        config = dict(config)
        config["workspace"] = Path(config["workspace"]).resolve().as_posix()
    if type(config["enabled"]) is not bool or type(config["configRevision"]) is not int or config["configRevision"] < 1:
        raise FolderConfigError("invalid config revision or enabled value")
    if config["orchestratorSecretRef"] is not None and (not isinstance(config["orchestratorSecretRef"], str)
            or not re.fullmatch(r"[A-Za-z0-9._:-]{1,200}", config["orchestratorSecretRef"])):
        raise FolderConfigError("invalid Orchestrator secret reference")
    endpoint = validate_endpoint(config["orchestratorEndpoint"])
    root_id, root_url = canonical_folder_url(config["driveRootUrl"])
    ids = [root_id, config["architectPromptsFolderId"], config["executorReportsFolderId"]]
    if any(not isinstance(item, str) or not _ID.fullmatch(item) for item in ids) or len(set(ids)) != 3:
        raise FolderConfigError("Drive folder identities are invalid or duplicated")
    root = provider.folder(root_id)
    if root.get("id") != root_id or root.get("mimeType") != FOLDER_MIME or root.get("trashed") is not False:
        raise FolderConfigError("Drive root is inaccessible or not an active folder")
    if "projectId" in root and root["projectId"] != config["projectId"]:
        raise FolderConfigError("Drive root projectId mismatch")
    children = provider.children(root_id)
    selected = {}
    for name, key in ((PROMPTS_NAME, "architectPromptsFolderId"), (REPORTS_NAME, "executorReportsFolderId")):
        matches = [item for item in children if item.get("name") == name and item.get("trashed") is False]
        if len(matches) != 1:
            raise FolderConfigError("required Drive child is missing or ambiguous")
        child = matches[0]
        if child.get("mimeType") != FOLDER_MIME or child.get("id") != config[key]:
            raise FolderConfigError("Drive child identity or MIME type mismatch")
        if child.get("parents") != [root_id]:
            raise FolderConfigError("Drive child is not a direct child of configured root")
        selected[name] = child["id"]
    expected = {"driveRootId": root_id, "driveRootUrl": root_url,
                "architectPromptsFolderUrl": f"https://drive.google.com/drive/folders/{selected[PROMPTS_NAME]}",
                "executorReportsFolderUrl": f"https://drive.google.com/drive/folders/{selected[REPORTS_NAME]}",
                "orchestratorEndpoint": endpoint}
    for field, value in expected.items():
        if config[field] != value:
            raise FolderConfigError("configured folder identity or canonical URL mismatch")
    return dict(config)


def build_project(project_id, display_name, root_url, prompt_id, report_id, endpoint, provider,
                  *, repository=None, workspace=None, secret_ref=None, enabled=False):
    root_id, root_url = canonical_folder_url(root_url)
    children = provider.children(root_id)
    prompt_matches = [item for item in children if item.get("name") == PROMPTS_NAME and item.get("trashed") is False]
    report_matches = [item for item in children if item.get("name") == REPORTS_NAME and item.get("trashed") is False]
    if len(prompt_matches) != 1 or len(report_matches) != 1:
        raise FolderConfigError("required Drive child is missing or ambiguous")
    prompt_id = prompt_matches[0].get("id") if prompt_id is None else prompt_id
    report_id = report_matches[0].get("id") if report_id is None else report_id
    config = {"schemaVersion": 2, "projectId": project_id, "displayName": display_name,
              "repository": repository, "workspace": workspace, "driveRootUrl": root_url,
              "driveRootId": root_id, "architectPromptsFolderId": prompt_id,
              "architectPromptsFolderUrl": f"https://drive.google.com/drive/folders/{prompt_id}",
              "executorReportsFolderId": report_id,
              "executorReportsFolderUrl": f"https://drive.google.com/drive/folders/{report_id}",
              "orchestratorEndpoint": endpoint, "orchestratorSecretRef": secret_ref,
              "enabled": enabled, "configRevision": 1}
    return validate_project(config, provider)
