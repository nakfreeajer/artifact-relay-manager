"""Minimal Windows Service host for the existing Project Supervisor."""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any, Callable

import drive_auth
import project_registry
import project_supervisor


class WindowsServiceHostError(Exception):
    """Sanitized service startup failure."""


class WindowsServiceHost:
    """Own service lifecycle while delegating all monitoring to the supervisor."""

    def __init__(self, registry_path: Path | None = None, *, interval_seconds: int = 30,
                 session_factory: Callable[[], Any] = drive_auth.DriveAuthSession,
                 supervisor_runner: Callable[..., int] = project_supervisor.run_supervisor,
                 emit: Callable[[dict], None] | None = None):
        if type(interval_seconds) is not int or not project_supervisor.MIN_INTERVAL_SECONDS <= interval_seconds <= project_supervisor.MAX_INTERVAL_SECONDS:
            raise WindowsServiceHostError("service interval is invalid")
        self.registry_path = registry_path if registry_path is not None else project_registry.default_registry_path()
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
        """Preflight current-user DPAPI credentials without any browser fallback."""
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
            self.registry_path,
            interval_seconds=self.interval_seconds,
            max_cycles=None,
            stop_event=self.stop_event,
            session_factory=lambda: session,
            sleeper=self.stop_event.wait,
            emit=self.emit,
        )


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
    win32serviceutil.HandleCommandLine(RelayWindowsService)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
