"""Foreground, single-project Google Drive monitor loop."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Callable

import drive_adapter
import drive_auth
import relay

MIN_INTERVAL_SECONDS = 1
MAX_INTERVAL_SECONDS = 3600
MAX_CYCLES = 10000
BACKOFF_SECONDS = (1, 2, 4, 8, 16, 30)


def _stats(results: list[dict], retries: list[tuple[str, str]]) -> dict:
    outcomes = [item.get("result") for item in results]
    outcomes.extend(result for _, result in retries)
    return {
        "observed": len(results),
        "delivered": outcomes.count("delivered"),
        "deduplicated": outcomes.count("deduplicated"),
        "pending": outcomes.count("pending"),
        "skipped": sum(
            1 for result in outcomes
            if isinstance(result, str) and (result.startswith("skipped") or result.startswith("blocked"))
        ),
    }


def _cycle(config_path: Path, state_path: Path, config: dict, session: Any,
           poller: Callable = drive_adapter.poll_drive,
           retryer: Callable = relay.retry_pending) -> dict:
    token = session.access_token()
    try:
        results = poller(config_path, state_path, token=token)
    except drive_adapter.DriveHttpError as exc:
        if exc.status_code != 401:
            raise
        session.invalidate()
        token = session.refresh()
        # A single explicit retry is the only 401 recovery attempt in this cycle.
        results = poller(config_path, state_path, token=token)

    attempted_ids = {
        item["eventId"] for item in results
        if isinstance(item, dict) and isinstance(item.get("eventId"), str)
    }
    core_config_path = config["_workspace"] / ".relay-core-config.json"
    pending_retries = retryer(core_config_path, state_path, exclude_event_ids=attempted_ids)
    return _stats(results, pending_retries)


def run_cycle(config_path: Path, state_path: Path, config: dict, session: Any, *,
              poller: Callable = drive_adapter.poll_drive,
              retryer: Callable = relay.retry_pending) -> dict:
    """Run exactly one configured project's existing Drive/Relay monitor cycle."""
    return _cycle(config_path, state_path, config, session, poller, retryer)


def run_monitor(config_path: Path, state_path: Path, config: dict, session: Any, *,
                interval_seconds: int = 30, max_cycles: int | None = None,
                poller: Callable = drive_adapter.poll_drive,
                retryer: Callable = relay.retry_pending,
                sleeper: Callable[[float], None] = time.sleep,
                emit: Callable[[dict], None] | None = None) -> int:
    if type(interval_seconds) is not int or not MIN_INTERVAL_SECONDS <= interval_seconds <= MAX_INTERVAL_SECONDS:
        raise relay.RelayError("interval-seconds must be between 1 and 3600")
    if max_cycles is not None and (type(max_cycles) is not int or not 1 <= max_cycles <= MAX_CYCLES):
        raise relay.RelayError("max-cycles must be between 1 and 10000")
    if emit is None:
        emit = lambda record: print(json.dumps(record, sort_keys=True, separators=(",", ":")))

    cycle_number = 0
    degraded_streak = 0
    try:
        while max_cycles is None or cycle_number < max_cycles:
            cycle_number += 1
            try:
                record = {
                    "cycle": cycle_number,
                    "projectId": config["projectId"],
                    "result": "OK",
                    **run_cycle(config_path, state_path, config, session, poller=poller, retryer=retryer),
                }
                degraded_streak = 0
                delay = interval_seconds
            except (drive_adapter.DriveError, drive_auth.DriveAuthError) as exc:
                degraded_streak += 1
                delay = BACKOFF_SECONDS[min(degraded_streak - 1, len(BACKOFF_SECONDS) - 1)]
                record = {
                    "cycle": cycle_number,
                    "projectId": config["projectId"],
                    "result": "DEGRADED",
                    "error": str(exc),
                    "retryDelaySeconds": delay,
                }
            emit(record)
            if max_cycles is not None and cycle_number >= max_cycles:
                break
            sleeper(delay)
    except KeyboardInterrupt:
        emit({"cycle": cycle_number, "projectId": config["projectId"], "result": "STOPPED"})
    return 0


def run_cli(config_path: Path, state_path: Path | None, interval_seconds: int,
            max_cycles: int | None) -> int:
    if state_path is None:
        raise relay.RelayError("--state is required for monitor-drive")
    if type(interval_seconds) is not int or not MIN_INTERVAL_SECONDS <= interval_seconds <= MAX_INTERVAL_SECONDS:
        raise relay.RelayError("interval-seconds must be between 1 and 3600")
    if max_cycles is not None and (type(max_cycles) is not int or not 1 <= max_cycles <= MAX_CYCLES):
        raise relay.RelayError("max-cycles must be between 1 and 10000")
    # Invalid local configuration fails before the long-running retry loop starts.
    config = drive_adapter._load_drive_config(config_path)
    session = drive_auth.DriveAuthSession()
    return run_monitor(
        config_path, state_path, config, session,
        interval_seconds=interval_seconds, max_cycles=max_cycles,
    )
