"""Bounded foreground loop joining Drive metadata detection to APO receipts."""
from __future__ import annotations

import json
import time

from arm_notification import NotificationError, NotificationSender
from drive_change_detector import DriveChangeDetector
from project_registry import ProjectRegistry, ProjectRegistryError


class ForegroundMonitor:
    """Run bounded foreground cycles over injected provider and secret seams.

    Production credential lookup and provider construction remain the caller's
    responsibility. The offline CLI demonstration supplies only fixtures,
    test-only keys, and loopback simulated APOs.
    """

    def __init__(self, registry_path, detector_state_path, notification_ledger_path, *,
                 provider, secret_resolver, clock=time.time, sleeper=time.sleep,
                 interval_seconds=10, max_backoff_seconds=300, dispatch_limit=100):
        if (type(interval_seconds) is not int or not 1 <= interval_seconds <= 3600
                or type(max_backoff_seconds) is not int
                or not interval_seconds <= max_backoff_seconds <= 3600
                or type(dispatch_limit) is not int or not 1 <= dispatch_limit <= 100
                or not callable(clock) or not callable(sleeper)):
            raise ValueError("invalid foreground monitor settings")
        self.registry = ProjectRegistry(registry_path)
        self.detector = DriveChangeDetector(registry_path, detector_state_path)
        self.sender = NotificationSender(registry_path, detector_state_path,
            notification_ledger_path, secret_resolver=secret_resolver, clock=clock)
        self.provider = provider
        self.clock = clock
        self.sleeper = sleeper
        self.interval_seconds = interval_seconds
        self.max_backoff_seconds = max_backoff_seconds
        self.dispatch_limit = dispatch_limit
        self._provider_failures = 0

    def cycle(self, cycle_number, *, paused_project_ids=None):
        if type(cycle_number) is not int or cycle_number < 1:
            raise ValueError("cycle number must be positive")

        # Validate the shared registry before any polling or notification side effect.
        registry = self.registry.load()
        projects = registry["folderProjects"]
        enabled = [project for project in projects if project["enabled"]]
        if paused_project_ids is None:
            paused_ids = set()
        else:
            if (not isinstance(paused_project_ids, (list, tuple, set, frozenset))
                    or any(not isinstance(project_id, str) for project_id in paused_project_ids)
                    or len(set(paused_project_ids)) != len(paused_project_ids)):
                raise ProjectRegistryError("invalid paused project set")
            configured_ids = {project["projectId"] for project in projects}
            if any(project_id not in configured_ids for project_id in paused_project_ids):
                raise ProjectRegistryError("paused project does not match registry")
            paused_ids = set(paused_project_ids)
        enabled_ids = [project["projectId"] for project in enabled if project["projectId"] not in paused_ids]
        detection = {"result": "SKIPPED_NO_ENABLED_PROJECTS", "newEvents": []}
        observation_error = None
        if enabled_ids:
            try:
                detection = self.detector.scan(self.provider, project_ids=enabled_ids)
            except Exception as exc:
                # M03 persists all selected listings as one transaction. On any
                # listing failure it writes none; label the whole enabled batch
                # degraded and never reinterpret a failed listing as empty.
                observation_error = type(exc).__name__
                detection["result"] = "DEGRADED_ATOMIC_SCAN"

        delivery = None
        delivery_error = None
        if enabled_ids:
            try:
                # Previously persisted work can still progress if an unpaused scan fails.
                # Paused projects are excluded from both new scans and every delivery attempt.
                delivery = self.sender.dispatch(limit=self.dispatch_limit, per_project_limit=1,
                                                project_ids=enabled_ids)
            except (NotificationError, ProjectRegistryError) as exc:
                delivery_error = type(exc).__name__

        if observation_error:
            self._provider_failures += 1
            delay = min(self.interval_seconds * (2 ** min(self._provider_failures - 1, 30)),
                        self.max_backoff_seconds)
        else:
            self._provider_failures = 0
            delay = self.interval_seconds

        statuses = []
        for project in projects:
            if not project["enabled"]:
                status = "DISABLED_NOT_POLLED"
            elif project["projectId"] in paused_ids:
                status = "PAUSED_NOT_POLLED"
            elif observation_error:
                status = "DEGRADED_ATOMIC_SCAN"
            else:
                status = "OBSERVED"
            statuses.append({"projectId": project["projectId"], "status": status})

        events = [{key: event[key] for key in (
            "projectId", "eventId", "eventType", "fileId", "providerVersion", "changeKind")}
            for event in detection.get("newEvents", [])]
        return {
            "cycle": cycle_number,
            "status": "DEGRADED" if observation_error or delivery_error else "OK",
            "projects": statuses,
            "observation": detection["result"],
            "observationErrorClass": observation_error,
            "events": events,
            "delivery": delivery,
            "deliveryErrorClass": delivery_error,
            "nextDelaySeconds": delay,
        }

    def run(self, *, max_cycles, start_cycle=1, emit=print):
        if (type(max_cycles) is not int or not 1 <= max_cycles <= 10000
                or type(start_cycle) is not int or start_cycle < 1):
            raise ValueError("max_cycles must be 1..10000 and start_cycle must be positive")
        records = []
        try:
            for index in range(max_cycles):
                record = self.cycle(start_cycle + index)
                record["sleepAfterSeconds"] = record["nextDelaySeconds"] if index + 1 < max_cycles else None
                records.append(record)
                if emit is not None:
                    emit(json.dumps(record, sort_keys=True, separators=(",", ":")))
                if record["sleepAfterSeconds"] is not None:
                    self.sleeper(record["sleepAfterSeconds"])
        except KeyboardInterrupt:
            stopped = {"status": "STOPPED", "completedCycles": len(records),
                       "persistedStatePreserved": True}
            if emit is not None:
                emit(json.dumps(stopped, sort_keys=True, separators=(",", ":")))
            return {"status": "STOPPED", "cycles": records}
        return {"status": "COMPLETED", "cycles": records}
