"""Current-Windows-user DPAPI storage for per-project Orchestrator HMAC keys.

Provisioning accepts an operator-supplied existing key through hidden prompts.
It never generates, rotates, exports, or displays a key.
"""
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import ipaddress
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

from drive_session import PROTECTOR_FACTORY, Protector
from project_registry import ProjectRegistry
from arm_notification import _read_ledger, validate_notification_destination

MAGIC = b"ARMO1"
MAX_SECRET_FILE_BYTES = 16384
MIN_SECRET_BYTES = 32
MAX_SECRET_BYTES = 4096
_REF = re.compile(r"orchestrator:[A-Za-z0-9._-]{1,180}\Z")


class OrchestratorSecretError(ValueError):
    """Sanitized protected Orchestrator-key storage failure."""


def _canonical_json(value: dict) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _inside_local_app_data(path: Path, *, must_exist: bool) -> bool:
    root_value = os.environ.get("LOCALAPPDATA")
    if not root_value or str(path).startswith(("\\\\", "//")):
        return False
    try:
        root = Path(root_value).resolve(strict=True)
        resolved = path.resolve(strict=must_exist)
        return os.path.commonpath((os.path.normcase(str(root)), os.path.normcase(str(resolved)))) == os.path.normcase(str(root))
    except (OSError, RuntimeError, ValueError):
        return False


class OrchestratorSecretStore:
    """DPAPI-protected, create-only store bound to project, ref, and endpoint."""

    def __init__(self, *, protector: Protector | None = None,
                 local_app_data: str | Path | None = None):
        root_value = local_app_data if local_app_data is not None else os.environ.get("LOCALAPPDATA")
        if not root_value:
            raise OrchestratorSecretError("current-user local data directory is unavailable")
        self.root = Path(root_value) / "ArtifactRelayManager" / "OrchestratorSecrets"
        self._protector = protector

    @property
    def protector(self) -> Protector:
        if self._protector is None:
            self._protector = PROTECTOR_FACTORY()
        return self._protector

    @staticmethod
    def _identity(project_id: str, destination: str, secret_ref: str) -> tuple[str, bytes]:
        try:
            validate_notification_destination(destination, allow_remote_https=True)
            parsed = urlsplit(destination)
            host = parsed.hostname or ""
            try:
                loopback = ipaddress.ip_address(host).is_loopback
            except ValueError:
                loopback = host == "localhost"
            if parsed.scheme != "https" or loopback:
                raise ValueError("not a remote HTTPS destination")
        except Exception:
            raise OrchestratorSecretError("Orchestrator destination is invalid") from None
        if (not isinstance(project_id, str) or not re.fullmatch(r"[A-Za-z0-9._-]{1,200}", project_id)
                or not isinstance(secret_ref, str) or not _REF.fullmatch(secret_ref)):
            raise OrchestratorSecretError("Orchestrator secret identity is invalid")
        binding = (b"ArtifactRelayManager\0OrchestratorSecret\0" + project_id.encode("utf-8") +
                   b"\0" + secret_ref.encode("utf-8") + b"\0" + destination.encode("utf-8"))
        return hashlib.sha256(binding).hexdigest(), hashlib.sha256(binding).digest()

    def _path(self, project_id: str, destination: str, secret_ref: str) -> tuple[Path, bytes]:
        identity, entropy = self._identity(project_id, destination, secret_ref)
        return self.root / ("secret-" + identity + ".dpapi"), entropy

    def resolve(self, project_id: str, destination: str, secret_ref: str) -> bytes:
        path, entropy = self._path(project_id, destination, secret_ref)
        try:
            with path.open("rb") as stream:
                stored = stream.read(MAX_SECRET_FILE_BYTES + 1)
            if len(stored) > MAX_SECRET_FILE_BYTES or not stored.startswith(MAGIC) or len(stored) == len(MAGIC):
                raise OrchestratorSecretError("protected Orchestrator key is invalid")
            clear = self.protector.unprotect(stored[len(MAGIC):], entropy)
            value = json.loads(clear.decode("utf-8"))
            if (not isinstance(value, dict) or set(value) != {
                    "schemaVersion", "projectId", "destination", "secretRef", "secretBase64"}
                    or type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1
                    or value["projectId"] != project_id or value["destination"] != destination
                    or value["secretRef"] != secret_ref or not isinstance(value["secretBase64"], str)):
                raise OrchestratorSecretError("protected Orchestrator key identity is invalid")
            secret = base64.b64decode(value["secretBase64"], validate=True)
            if not MIN_SECRET_BYTES <= len(secret) <= MAX_SECRET_BYTES:
                raise OrchestratorSecretError("protected Orchestrator key is invalid")
            return secret
        except OrchestratorSecretError:
            raise
        except FileNotFoundError:
            raise OrchestratorSecretError("protected Orchestrator key is unavailable") from None
        except Exception:
            raise OrchestratorSecretError("protected Orchestrator key is invalid or inaccessible") from None

    def provision(self, project_id: str, destination: str, secret_ref: str, secret: bytes,
                  *, registry_path: str | Path, ledger_path: str | Path) -> Path:
        """Create one protected key only when the project has no transport history."""
        if not isinstance(secret, bytes) or not MIN_SECRET_BYTES <= len(secret) <= MAX_SECRET_BYTES:
            raise OrchestratorSecretError("operator-supplied Orchestrator key is invalid")
        try:
            registry_input = Path(registry_path)
            ledger_input = Path(ledger_path)
            if (not registry_input.is_absolute() or not _inside_local_app_data(registry_input, must_exist=True)
                    or not ledger_input.is_absolute() or not _inside_local_app_data(ledger_input, must_exist=False)):
                raise OrchestratorSecretError("registry and ledger must remain in current-user local data")
            registry = ProjectRegistry(registry_path).load()
            matches = [p for p in registry["folderProjects"] if p["projectId"] == project_id]
            if (len(matches) != 1 or matches[0]["orchestratorEndpoint"] != destination
                    or matches[0]["orchestratorSecretRef"] != secret_ref):
                raise OrchestratorSecretError("project transport binding does not match the registry")
            validate_notification_destination(destination, allow_remote_https=True)
            parsed = urlsplit(destination)
            host = parsed.hostname or ""
            try:
                loopback = ipaddress.ip_address(host).is_loopback
            except ValueError:
                loopback = host == "localhost"
            if parsed.scheme != "https" or loopback:
                raise OrchestratorSecretError("protected keys are for remote HTTPS projects only")
            if not secret_ref.startswith("orchestrator:"):
                raise OrchestratorSecretError("remote projects require a protected secret reference")
            ledger = _read_ledger(Path(ledger_path))
            if any(entry["projectId"] == project_id for entry in ledger["entries"].values()):
                raise OrchestratorSecretError("project transport history prevents key provisioning")
            path, entropy = self._path(project_id, destination, secret_ref)
            clear = _canonical_json({
                "schemaVersion": 1, "projectId": project_id, "destination": destination,
                "secretRef": secret_ref, "secretBase64": base64.b64encode(secret).decode("ascii"),
            })
            protected = MAGIC + self.protector.protect(clear, entropy)
            if len(protected) > MAX_SECRET_FILE_BYTES:
                raise OrchestratorSecretError("protected Orchestrator key exceeds its size limit")
            self.root.mkdir(parents=True, exist_ok=True)
            # Exclusive creation prevents silent replacement or rotation. A
            # partial file is intentionally fail-closed and never overwritten.
            with path.open("xb") as stream:
                stream.write(protected)
                stream.flush()
                os.fsync(stream.fileno())
            return path
        except OrchestratorSecretError:
            raise
        except FileExistsError:
            raise OrchestratorSecretError("protected Orchestrator key already exists") from None
        except Exception:
            raise OrchestratorSecretError("could not provision protected Orchestrator key") from None


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Provision an existing Orchestrator HMAC key for one ARM project.")
    parser.add_argument("--registry", required=True)
    parser.add_argument("--ledger", required=True)
    parser.add_argument("--project-id", required=True)
    args = parser.parse_args(argv)
    try:
        if not sys.stdin.isatty() or not sys.stdout.isatty():
            raise OrchestratorSecretError("secret provisioning requires an interactive console")
        registry = ProjectRegistry(args.registry).load()
        project = next(p for p in registry["folderProjects"] if p["projectId"] == args.project_id)
        first = getpass.getpass("Existing Orchestrator HMAC secret (input hidden): ").encode("utf-8")
        second = getpass.getpass("Confirm existing secret (input hidden): ").encode("utf-8")
        if first != second:
            raise OrchestratorSecretError("secret confirmation did not match")
        store = OrchestratorSecretStore()
        store.provision(args.project_id, project["orchestratorEndpoint"],
                        project["orchestratorSecretRef"], first,
                        registry_path=args.registry, ledger_path=args.ledger)
        print("Orchestrator secret provisioned for the selected project.")
        return 0
    except Exception as exc:
        message = str(exc) if isinstance(exc, OrchestratorSecretError) else "configuration is invalid"
        print("Orchestrator secret provisioning failed: " + message)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

