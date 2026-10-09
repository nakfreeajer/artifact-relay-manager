"""Minimal Windows Service host for the existing Project Supervisor."""
from __future__ import annotations

import json
import os
import sys
import threading
from pathlib import Path
from typing import Any, Callable

import drive_auth
import project_registry
import project_supervisor


class WindowsServiceHostError(Exception):
    """Sanitized service startup failure."""


SERVICE_CONFIG_NAME = "service.json"
SERVICE_CONFIG_KEYS = {"schemaVersion", "registryPath", "oauthClientFile"}
MAX_SERVICE_CONFIG_BYTES = 16384


def _unique_pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate service configuration key")
        result[key] = value
    return result


def default_service_config_path(environ=None) -> Path:
    """Return the machine-local config path without changing LOCALAPPDATA."""
    env = os.environ if environ is None else environ
    program_data = env.get("PROGRAMDATA")
    if not isinstance(program_data, str) or not program_data:
        raise WindowsServiceHostError("ProgramData is unavailable")
    root = Path(program_data)
    if not root.is_absolute() or str(program_data).startswith(("\\\\", "//")):
        raise WindowsServiceHostError("ProgramData path is invalid")
    return root / "ArtifactRelayManager" / SERVICE_CONFIG_NAME


def _canonical_local_file(value: Any, label: str) -> Path:
    if (not isinstance(value, str) or not value or len(value) > 32767
            or value.startswith(("\\\\", "//"))):
        raise WindowsServiceHostError(f"service {label} path is invalid")
    raw = Path(value)
    if not raw.is_absolute():
        raise WindowsServiceHostError(f"service {label} path must be absolute")
    try:
        resolved = raw.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        raise WindowsServiceHostError(f"service {label} file is unavailable") from None
    if (os.path.normcase(os.path.normpath(str(raw)))
            != os.path.normcase(os.path.normpath(str(resolved))) or not resolved.is_file()):
        raise WindowsServiceHostError(f"service {label} path is not a canonical local file")
    return resolved


def load_service_config(path: Path) -> tuple[Path, Path]:
    """Validate service-local paths before auth bootstrap or supervisor cycles."""
    try:
        config_path = Path(path)
        if not config_path.is_absolute() or not config_path.is_file():
            raise WindowsServiceHostError("service configuration is unavailable")
        resolved_config_path = config_path.resolve(strict=True)
        if (os.path.normcase(os.path.normpath(str(config_path)))
                != os.path.normcase(os.path.normpath(str(resolved_config_path)))):
            raise WindowsServiceHostError("service configuration path is not canonical")
        with resolved_config_path.open("rb") as stream:
            raw = stream.read(MAX_SERVICE_CONFIG_BYTES + 1)
        if len(raw) > MAX_SERVICE_CONFIG_BYTES:
            raise WindowsServiceHostError("service configuration exceeds its size limit")
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_pairs)
    except WindowsServiceHostError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
        raise WindowsServiceHostError("service configuration is invalid") from None
    if (not isinstance(value, dict) or set(value) != SERVICE_CONFIG_KEYS
            or type(value.get("schemaVersion")) is not int or value["schemaVersion"] != 1):
        raise WindowsServiceHostError("service configuration schema is invalid")
    registry_path = _canonical_local_file(value["registryPath"], "registry")
    oauth_client_file = _canonical_local_file(value["oauthClientFile"], "OAuth client")
    try:
        project_registry.ProjectRegistry(registry_path).load()
    except project_registry.ProjectRegistryError:
        raise WindowsServiceHostError("configured project registry is invalid") from None
    return registry_path, oauth_client_file


def resolve_service_host_path(win32service_module_file: str | Path) -> Path:
    """Use pywin32's installed service host in place; never relocate the binary."""
    module_file = Path(win32service_module_file).resolve()
    service_host = module_file.parent / "pythonservice.exe"
    if not service_host.is_file():
        raise WindowsServiceHostError("pywin32 service host is missing beside win32service")
    return service_host


def reject_implicit_service_registration(arguments) -> None:
    """Prevent pywin32's default LocalSystem account from being registered."""
    if any(str(arg).casefold() in {"install", "update"} for arg in arguments):
        raise SystemExit(
            "service registration is disabled until an explicit account-safe SCM setup is approved; "
            "pywin32 defaults an unspecified account to LocalSystem"
        )


class WindowsServiceHost:
    """Own service lifecycle while delegating all monitoring to the supervisor."""

    def __init__(self, service_config_path: Path | None = None, *, interval_seconds: int = 30,
                 session_factory: Callable[[], Any] = drive_auth.DriveAuthSession,
                 supervisor_runner: Callable[..., int] = project_supervisor.run_supervisor,
                 emit: Callable[[dict], None] | None = None):
        if type(interval_seconds) is not int or not project_supervisor.MIN_INTERVAL_SECONDS <= interval_seconds <= project_supervisor.MAX_INTERVAL_SECONDS:
            raise WindowsServiceHostError("service interval is invalid")
        self.service_config_path = service_config_path or default_service_config_path()
        self.interval_seconds = interval_seconds
        self.session_factory = session_factory
        self.supervisor_runner = supervisor_runner
        self.emit = emit if emit is not None else self._emit_json
        self.stop_event = threading.Event()

    @staticmethod
    def _emit_json(record: dict) -> None:
        print(json.dumps(record, sort_keys=True, separators=(",", ":")))

    def request_stop(self) -> None:
        self.stop_event.set()

    def run(self) -> int:
        """Load explicit service paths, then reuse the current-user session."""
        try:
            registry_path, oauth_client_file = load_service_config(self.service_config_path)
        except Exception:
            self.emit({"service": "relay", "result": "BLOCKED", "error": "INVALID_SERVICE_CONFIGURATION"})
            return 2

        env_key = "RELAY_GDRIVE_OAUTH_CLIENT_FILE"
        previous_client_file = os.environ.get(env_key)
        os.environ[env_key] = str(oauth_client_file)
        try:
            try:
                session = self.session_factory()
                token = session.access_token()
                if not isinstance(token, str) or not token:
                    raise WindowsServiceHostError("protected session returned no access token")
                del token
            except Exception:
                self.emit({"service": "relay", "result": "BLOCKED", "error": "PROTECTED_SESSION_UNAVAILABLE"})
                return 2

            if self.stop_event.is_set():
                self.emit({"service": "relay", "result": "STOPPED"})
                return 0

            return self.supervisor_runner(
                registry_path,
                interval_seconds=self.interval_seconds,
                max_cycles=None,
                stop_event=self.stop_event,
                session_factory=lambda: session,
                sleeper=self.stop_event.wait,
                emit=self.emit,
            )
        finally:
            if previous_client_file is None:
                os.environ.pop(env_key, None)
            else:
                os.environ[env_key] = previous_client_file


try:
    import servicemanager
    import win32service
    import win32serviceutil
except ImportError:
    servicemanager = None
    win32service = None
    win32serviceutil = None


if win32serviceutil is not None:
    class RelayWindowsService(win32serviceutil.ServiceFramework):
        _svc_name_ = "ArtifactRelayManager"
        _svc_display_name_ = "Artifact Relay Manager"
        _svc_description_ = "Monitors configured artifact projects and transports events to their Watchers."

        def __init__(self, args):
            super().__init__(args)
            self.host = WindowsServiceHost(emit=self._log_record)

        @staticmethod
        def _log_record(record):
            servicemanager.LogInfoMsg(
                "Artifact Relay Manager: " + json.dumps(record, sort_keys=True, separators=(",", ":"))
            )

        def SvcStop(self):
            self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
            self.host.request_stop()

        def SvcDoRun(self):
            servicemanager.LogInfoMsg("Artifact Relay Manager service starting")
            result = self.host.run()
            servicemanager.LogInfoMsg("Artifact Relay Manager service stopped (result %d)" % result)


def main() -> int:
    if os.name != "nt":
        raise SystemExit("Windows Service hosting requires Windows")
    if win32serviceutil is None:
        raise SystemExit("Windows Service hosting requires pywin32; install requirements-windows-service.txt")
    reject_implicit_service_registration(sys.argv[1:])
    try:
        RelayWindowsService._exe_name_ = str(resolve_service_host_path(win32service.__file__))
    except WindowsServiceHostError as exc:
        raise SystemExit(str(exc)) from None
    win32serviceutil.HandleCommandLine(RelayWindowsService)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
