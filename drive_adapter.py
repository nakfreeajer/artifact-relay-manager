"""Bounded one-shot Google Drive v3 inbound polling for the Relay core."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import relay

API_ORIGIN = "https://www.googleapis.com/drive/v3"
FOLDER_MIME = "application/vnd.google-apps.folder"
IDENTITY_NAME = ".relay-project.json"
MAX_IDENTITY_BYTES = 65536
MAX_CHILDREN = 1000


class DriveError(relay.RelayError):
    """Drive API or configured Drive observation failure."""


def _safe_json(data: bytes) -> dict:
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=_unique_pairs)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise DriveError("Drive returned malformed JSON") from exc
    if not isinstance(value, dict):
        raise DriveError("Drive returned a non-object JSON value")
    return value


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _write_atomic(path: Path, data: bytes) -> None:
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
        raise


class DriveClient:
    def __init__(self, token: str, base_url: str | None = None):
        if not isinstance(token, str) or not token or any(ord(char) < 33 or ord(char) > 126 for char in token):
            raise DriveError("invalid access token value")
        self.token = token
        self.base_url = API_ORIGIN
        if base_url is not None:
            parsed = urllib.parse.urlsplit(base_url)
            if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
                    or parsed.username or parsed.password or parsed.query or parsed.fragment):
                raise DriveError("test API base must be an HTTP loopback URL")
            try:
                if parsed.port is None or not 1 <= parsed.port <= 65535:
                    raise DriveError("test API base must specify a valid port")
            except ValueError as exc:
                raise DriveError("test API base must specify a valid port") from exc
            self.base_url = base_url.rstrip("/")

    def request(self, resource: str, params: dict[str, str], limit: int) -> bytes:
        url = self.base_url + "/" + resource.lstrip("/")
        if params:
            url += "?" + urllib.parse.urlencode(params)
        request = urllib.request.Request(url, headers={
            "Authorization": "Bearer " + self.token,
            "Accept": "application/json",
        })
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                data = response.read(limit + 1)
        except urllib.error.HTTPError as exc:
            code = exc.code
            exc.close()
            raise DriveError(f"Google Drive API returned HTTP {code}") from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise DriveError("Google Drive API request failed") from None
        if len(data) > limit:
            raise DriveError("Google Drive response exceeded its bounded size")
        return data

    def metadata(self, file_id: str) -> dict:
        encoded = urllib.parse.quote(file_id, safe="")
        return _safe_json(self.request("files/" + encoded, {
            "fields": "id,name,mimeType,parents,trashed,version,size,capabilities(canDownload)",
            "supportsAllDrives": "true",
        }, 65536))

    def list_children(self, folder_id: str, name: str | None = None) -> list[dict]:
        escaped = folder_id.replace("\\", "\\\\").replace("'", "\\'")
        query = f"'{escaped}' in parents and trashed = false"
        if name is not None:
            escaped_name = name.replace("\\", "\\\\").replace("'", "\\'")
            query += f" and name = '{escaped_name}'"
        files = []
        page_token = None
        while True:
            params = {
                "q": query,
                "pageSize": "1000",
                "fields": "nextPageToken,incompleteSearch,files(id,name,mimeType,parents,trashed,version,size,capabilities(canDownload))",
                "supportsAllDrives": "true",
                "includeItemsFromAllDrives": "true",
            }
            if page_token:
                params["pageToken"] = page_token
            page = _safe_json(self.request("files", params, 2_000_000))
            if page.get("incompleteSearch") is True:
                raise DriveError("Drive reported an incomplete folder listing")
            entries = page.get("files")
            if not isinstance(entries, list) or any(not isinstance(entry, dict) for entry in entries):
                raise DriveError("Drive returned an invalid folder listing")
            files.extend(entries)
            if len(files) > MAX_CHILDREN:
                raise DriveError("configured Drive folder exceeds the 1000 item poll limit")
            page_token = page.get("nextPageToken")
            if not page_token:
                return files

    def media(self, file_id: str, limit: int) -> bytes:
        encoded = urllib.parse.quote(file_id, safe="")
        return self.request("files/" + encoded, {"alt": "media", "supportsAllDrives": "true"}, limit)


def _load_drive_config(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DriveError("cannot read Drive project config") from exc
    required = {"schemaVersion", "projectId", "repository", "folderId", "relayWorkspace", "watcherEndpoint", "eventType"}
    if not isinstance(value, dict) or set(value) != required or value.get("schemaVersion") != 1:
        raise DriveError("invalid Drive project config")
    if not isinstance(value["projectId"], str) or not re.fullmatch(r"[A-Za-z0-9._-]+", value["projectId"]):
        raise DriveError("invalid configured projectId")
    if not isinstance(value["repository"], str) or not re.fullmatch(r"[^/\s]+/[^/\s]+", value["repository"]):
        raise DriveError("invalid configured repository")
    if not isinstance(value["folderId"], str) or not re.fullmatch(r"[A-Za-z0-9_-]+", value["folderId"]):
        raise DriveError("invalid Google Drive folder ID")
    if not isinstance(value["relayWorkspace"], str) or not value["relayWorkspace"]:
        raise DriveError("invalid local Relay workspace")
    if not isinstance(value["eventType"], str) or value["eventType"] not in relay.EVENTS:
        raise DriveError("invalid configured eventType")
    workspace = Path(value["relayWorkspace"]).resolve()
    value["_workspace"] = workspace
    # Validate the endpoint using the frozen core's existing policy.
    core_config = {
        "schemaVersion": 1, "projectId": value["projectId"], "repository": value["repository"],
        "fixtureRoot": str(workspace), "watcherEndpoint": value["watcherEndpoint"],
    }
    workspace.mkdir(parents=True, exist_ok=True)
    fd, check_name = tempfile.mkstemp(prefix=".relay-drive-config-check-", suffix=".json", dir=workspace)
    os.close(fd)
    relay_config_path = Path(check_name)
    try:
        relay_config_path.write_text(json.dumps(core_config), encoding="utf-8")
        relay.config(relay_config_path)
    except relay.RelayError as exc:
        raise DriveError("invalid Watcher endpoint or Relay config") from exc
    finally:
        try:
            relay_config_path.unlink()
        except OSError:
            pass
    value["_coreConfig"] = core_config
    return value


def _identity(client: DriveClient, config: dict) -> tuple:
    folder = client.metadata(config["folderId"])
    if folder.get("id") != config["folderId"] or folder.get("mimeType") != FOLDER_MIME or folder.get("trashed") is not False:
        raise DriveError("configured Drive root is missing, trashed, or not a folder")
    files = client.list_children(config["folderId"], IDENTITY_NAME)
    if len(files) != 1:
        raise DriveError("Drive root must contain exactly one project identity file")
    identity_file = files[0]
    parents = identity_file.get("parents")
    if (identity_file.get("name") != IDENTITY_NAME or identity_file.get("trashed") is True
            or not isinstance(parents, list) or config["folderId"] not in parents):
        raise DriveError("Drive identity file is outside the configured root")
    if str(identity_file.get("mimeType", "")).startswith("application/vnd.google-apps."):
        raise DriveError("Drive identity must be a raw file, not a Google Workspace document")
    if not isinstance(identity_file.get("id"), str) or not re.fullmatch(r"[A-Za-z0-9_-]+", identity_file["id"]):
        raise DriveError("Drive identity file has invalid ID metadata")
    if not isinstance(identity_file.get("capabilities"), dict) or identity_file["capabilities"].get("canDownload") is not True:
        raise DriveError("Drive identity file is not downloadable")
    version = identity_file.get("version")
    if not isinstance(version, str) or not re.fullmatch(r"[0-9]+", version):
        raise DriveError("Drive identity file has invalid version metadata")
    data = client.media(identity_file["id"], MAX_IDENTITY_BYTES)
    identity = _safe_json(data)
    if (set(identity) != {"schemaVersion", "projectId", "repository"}
            or type(identity.get("schemaVersion")) is not int or identity["schemaVersion"] != 1
            or identity.get("projectId") != config["projectId"]
            or identity.get("repository") != config["repository"]):
        raise DriveError("Drive project/repository identity mismatch")
    return (folder["id"], folder["mimeType"], folder["trashed"], identity_file["id"],
            identity_file["version"], identity_file["mimeType"], hashlib.sha256(data).hexdigest())


def _verify_artifact_snapshot(client: DriveClient, listed: dict, config: dict) -> None:
    current = client.metadata(listed["id"])
    parents = current.get("parents")
    caps = current.get("capabilities")
    if (current.get("id") != listed["id"] or current.get("version") != listed["version"]
            or current.get("size") != listed["size"] or current.get("mimeType") != listed["mimeType"]
            or current.get("trashed") is not False or not isinstance(parents, list)
            or config["folderId"] not in parents or current.get("mimeType") == FOLDER_MIME
            or current.get("mimeType", "").startswith("application/vnd.google-apps.")
            or not isinstance(caps, dict) or caps.get("canDownload") is not True):
        raise DriveError("Drive artifact changed during media download")


def qualify_drive(config_path: Path, qualification_file_id: str, token: str,
                  api_base_url: str | None = None) -> dict:
    """Read and qualify one explicitly designated raw artifact without staging or delivery."""
    config = _load_drive_config(config_path)
    if not isinstance(qualification_file_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", qualification_file_id):
        raise DriveError("invalid qualification file ID")
    client = DriveClient(token, api_base_url)
    identity_snapshot = _identity(client, config)
    matches = [item for item in client.list_children(config["folderId"])
               if item.get("id") == qualification_file_id]
    if len(matches) != 1:
        raise DriveError("qualification file must be a direct child of the configured Drive root")
    item = matches[0]
    parents = item.get("parents")
    if (item.get("trashed") is not False or not isinstance(parents, list)
            or config["folderId"] not in parents):
        raise DriveError("qualification file is not an active direct child of the configured root")
    mime = item.get("mimeType")
    if (not isinstance(mime, str) or mime == FOLDER_MIME
            or mime.startswith("application/vnd.google-apps.")):
        raise DriveError("qualification file must be a raw non-folder file")
    if not isinstance(item.get("capabilities"), dict) or item["capabilities"].get("canDownload") is not True:
        raise DriveError("qualification file is not downloadable")
    version = item.get("version")
    size = item.get("size")
    if not isinstance(version, str) or not re.fullmatch(r"[0-9]+", version):
        raise DriveError("qualification file has invalid version metadata")
    if not isinstance(size, str) or not size.isdigit():
        raise DriveError("qualification file has invalid size metadata")
    if int(size) > relay.MAX_BYTES:
        raise DriveError("qualification file exceeds the 1 MiB limit")
    data = client.media(qualification_file_id, relay.MAX_BYTES)
    if len(data) != int(size):
        raise DriveError("qualification media length does not match metadata")
    _verify_artifact_snapshot(client, item, config)
    if _identity(client, config) != identity_snapshot:
        raise DriveError("Drive project identity changed during qualification")
    return {
        "projectId": config["projectId"], "folderId": config["folderId"],
        "qualificationFileId": qualification_file_id, "version": version,
        "byteLength": len(data), "sha256": hashlib.sha256(data).hexdigest(),
        "mimeType": mime, "result": "QUALIFIED_READ_ONLY",
    }


def _stage_path(config: dict, file_id: str, version: str) -> Path:
    workspace = config["_workspace"]
    project_key = hashlib.sha256(config["projectId"].encode()).hexdigest()
    file_key = hashlib.sha256(file_id.encode()).hexdigest()
    return workspace / "staged" / project_key / file_key / (version + ".bin")


def poll_drive(config_path: Path, state_path: Path, token: str | None = None,
               api_base_url: str | None = None) -> list[dict]:
    config = _load_drive_config(config_path)
    token = token if token is not None else os.environ.get("RELAY_GDRIVE_ACCESS_TOKEN")
    if not token:
        raise DriveError("RELAY_GDRIVE_ACCESS_TOKEN is not set")
    client = DriveClient(token, api_base_url)
    identity_snapshot = _identity(client, config)
    children = client.list_children(config["folderId"])
    staged = []
    for item in children:
        if not isinstance(item.get("name"), str) or not isinstance(item.get("mimeType"), str) or not isinstance(item.get("trashed"), bool):
            raise DriveError("Drive artifact has invalid metadata")
        if item["trashed"] is True or item["name"] == IDENTITY_NAME:
            continue
        parents = item.get("parents")
        if not isinstance(parents, list):
            raise DriveError("Drive artifact has invalid parent metadata")
        if config["folderId"] not in parents:
            continue
        mime = item.get("mimeType")
        if mime == FOLDER_MIME:
            staged.append({"fileId": item.get("id"), "result": "skipped_folder"})
            continue
        if isinstance(mime, str) and mime.startswith("application/vnd.google-apps."):
            staged.append({"fileId": item.get("id"), "result": "skipped_workspace_file"})
            continue
        file_id, version = item.get("id"), item.get("version")
        if (not isinstance(file_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", file_id)
                or not isinstance(version, str) or not re.fullmatch(r"[0-9]+", version)):
            raise DriveError("Drive artifact is missing valid file ID/version metadata")
        caps = item.get("capabilities")
        if not isinstance(caps, dict) or caps.get("canDownload") is not True:
            staged.append({"fileId": file_id, "version": version, "result": "skipped_not_downloadable"})
            continue
        size = item.get("size")
        if not isinstance(size, str) or not size.isdigit():
            raise DriveError("Drive artifact has invalid size metadata")
        if int(size) > relay.MAX_BYTES:
            staged.append({"fileId": file_id, "version": version, "result": "blocked_oversized"})
            continue
        data = client.media(file_id, relay.MAX_BYTES)
        if len(data) != int(size):
            raise DriveError("Drive media length does not match metadata")
        _verify_artifact_snapshot(client, item, config)
        local_path = _stage_path(config, file_id, version)
        _write_atomic(local_path, data)
        staged.append({"fileId": file_id, "version": version, "path": local_path, "result": "staged"})

    # All Drive reads finish successfully before any Watcher delivery begins.
    if _identity(client, config) != identity_snapshot:
        raise DriveError("Drive project identity changed during poll")
    workspace = config["_workspace"]
    workspace.mkdir(parents=True, exist_ok=True)
    identity = {"schemaVersion": 1, "projectId": config["projectId"], "repository": config["repository"]}
    _write_atomic(workspace / ".relay-project.json", json.dumps(identity, sort_keys=True).encode("utf-8"))
    core_config_path = workspace / ".relay-core-config.json"
    _write_atomic(core_config_path, json.dumps(config["_coreConfig"], sort_keys=True).encode("utf-8"))
    results = []
    for item in staged:
        if item["result"] != "staged":
            results.append({key: value for key, value in item.items() if key != "path"})
            continue
        fixture = {
            "providerItemId": item["fileId"], "providerVersion": item["version"],
            "eventType": config["eventType"], "taskId": None,
            "artifactPath": str(item["path"].relative_to(workspace)),
        }
        key = json.dumps([config["projectId"], item["fileId"], item["version"], config["eventType"]], separators=(",", ":"))
        event_id = "relay-" + hashlib.sha256(key.encode()).hexdigest()
        observation_path = workspace / ".observations" / (event_id + ".json")
        _write_atomic(observation_path, json.dumps(fixture, sort_keys=True).encode("utf-8"))
        actual_id, disposition = relay.process(core_config_path, state_path, observation_path)
        results.append({"fileId": item["fileId"], "version": item["version"], "eventId": actual_id, "result": disposition})
    return results
