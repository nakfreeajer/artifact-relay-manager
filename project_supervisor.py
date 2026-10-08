"""Foreground sequential supervisor for registry-enabled Relay projects."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

import drive_adapter
import drive_auth
import drive_monitor
import relay
from project_registry import ProjectRegistry, default_registry_path

MIN_INTERVAL_SECONDS = 1
MAX_INTERVAL_SECONDS = 3600
MAX_CYCLES = 10000
BACKOFF_SECONDS = (1, 2, 4, 8, 16, 30)
_COUNT_FIELDS = ("observed", "delivered", "deduplicated", "pending", "skipped")


def _emit(record: dict) -> None:
    print(json.dumps(record, sort_keys=True, separators=(",", ":")))


def _project_cycle(entry: dict, session: Any) -> dict:
    config_path = Path(entry["configPath"])
    state_path = Path(entry["statePath"])
    # Re-read config at execution time. Registry validation is fresh per cycle,
    # but this also closes the gap if local config changes immediately after it.
    config = drive_adapter._load_drive_config(config_path)
    if config["projectId"] != entry["projectId"]:
        raise drive_adapter.DriveError("configured project identity changed")
    return drive_monitor.run_cycle(config_path, state_path, config, session)


def _counts(value: Any) -> dict:
    if not isinstance(value, dict):
        raise ValueError("invalid monitor cycle result")
    counts = {}
    for field in _COUNT_FIELDS:
        number = value.get(field, 0)
        if type(number) is not int or number < 0:
            raise ValueError("invalid monitor cycle result")
        counts[field] = number
    return counts


def _project_record(entry: dict, session: Any, cycle_runner: Callable) -> tuple[dict, bool]:
    try:
        counts = _counts(cycle_runner(entry, session))
        return {"projectId": entry["projectId"], "result": "OK", **counts}, False
    except drive_auth.DriveAuthError:
        return {"projectId": entry["projectId"], "result": "DEGRADED",
                "error": "AUTH_UNAVAILABLE", **dict.fromkeys(_COUNT_FIELDS, 0)}, True
    except (drive_adapter.DriveError, relay.RelayError):
        return {"projectId": entry["projectId"], "result": "DEGRADED",
                "error": "PROJECT_UNAVAILABLE", **dict.fromkeys(_COUNT_FIELDS, 0)}, False
    except Exception:
        # Provider libraries and OS errors may carry URLs or local file details.
        return {"projectId": entry["projectId"], "result": "DEGRADED",
                "error": "PROJECT_ERROR", **dict.fromkeys(_COUNT_FIELDS, 0)}, False


def run_supervisor(registry_path: Path, *, interval_seconds: int = 30,
                   max_cycles: int | None = None,
                   session_factory: Callable[[], Any] | None = None,
                   cycle_runner: Callable[[dict, Any], dict] | None = None,
                   registry_factory: Callable[[Path], Any] = ProjectRegistry,
                   sleeper: Callable[[float], None] = time.sleep,
                   emit: Callable[[dict], None] | None = None) -> int:
    """Run bounded or foreground-until-stopped fresh-registry supervisor cycles."""
    if type(interval_seconds) is not int or not MIN_INTERVAL_SECONDS <= interval_seconds <= MAX_INTERVAL_SECONDS:
        raise relay.RelayError("interval-seconds must be between 1 and 3600")
    if max_cycles is not None and (type(max_cycles) is not int or not 1 <= max_cycles <= MAX_CYCLES):
        raise relay.RelayError("max-cycles must be between 1 and 10000")
    if session_factory is None:
        session_factory = drive_auth.DriveAuthSession
    if cycle_runner is None:
        cycle_runner = _project_cycle
    if emit is None:
        emit = _emit

    shared_session = None
    cycle_number = 0
    registry_degraded_streak = 0
    try:
        while max_cycles is None or cycle_number < max_cycles:
            cycle_number += 1
            try:
                projects = registry_factory(registry_path).load()
                enabled = sorted((entry for entry in projects["projects"] if entry["enabled"]),
                                 key=lambda entry: entry["projectId"])
            except Exception:
                registry_degraded_streak += 1
                delay = BACKOFF_SECONDS[min(registry_degraded_streak - 1, len(BACKOFF_SECONDS) - 1)]
                emit({"cycle": cycle_number, "result": "DEGRADED", "enabledProjects": 0,
                      "projects": [], "error": "REGISTRY_INVALID", "retryDelaySeconds": delay})
                if max_cycles is not None and cycle_number >= max_cycles:
                    break
                sleeper(delay)
                continue

            registry_degraded_streak = 0
            if not enabled:
                emit({"cycle": cycle_number, "result": "IDLE", "enabledProjects": 0, "projects": []})
                delay = interval_seconds
            else:
                project_records = []
                auth_failed = False
                for entry in enabled:
                    if auth_failed:
                        project_records.append({
                            "projectId": entry["projectId"], "result": "DEGRADED",
                            "error": "AUTH_UNAVAILABLE", **dict.fromkeys(_COUNT_FIELDS, 0),
                        })
                        continue
                    try:
                        if shared_session is None:
                            shared_session = session_factory()
                    except Exception:
                        record = {"projectId": entry["projectId"], "result": "DEGRADED",
                                  "error": "AUTH_UNAVAILABLE", **dict.fromkeys(_COUNT_FIELDS, 0)}
                        project_records.append(record)
                        auth_failed = True
                        continue
                    record, failed_auth = _project_record(entry, shared_session, cycle_runner)
                    project_records.append(record)
                    auth_failed = auth_failed or failed_auth

                result = "DEGRADED" if any(p["result"] == "DEGRADED" for p in project_records) else "OK"
                emit({"cycle": cycle_number, "result": result, "enabledProjects": len(enabled),
                      "projects": project_records})
                delay = interval_seconds
            if max_cycles is not None and cycle_number >= max_cycles:
                break
            sleeper(delay)
    except KeyboardInterrupt:
        emit({"cycle": cycle_number, "result": "STOPPED"})
    return 0


def run_cli(registry_path: Path | None, interval_seconds: int, max_cycles: int | None) -> int:
    if interval_seconds < MIN_INTERVAL_SECONDS or interval_seconds > MAX_INTERVAL_SECONDS:
        raise relay.RelayError("interval-seconds must be between 1 and 3600")
    if max_cycles is not None and (max_cycles < 1 or max_cycles > MAX_CYCLES):
        raise relay.RelayError("max-cycles must be between 1 and 10000")
    path = registry_path if registry_path is not None else default_registry_path()
    return run_supervisor(path, interval_seconds=interval_seconds, max_cycles=max_cycles)
