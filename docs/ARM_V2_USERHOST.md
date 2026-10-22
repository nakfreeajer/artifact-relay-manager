# ARM v2 manual host (M05 offline candidate)

`arm_v2_userhost.py` is a small Windows-only process host for the accepted M01/M03/M04 pipeline. Run it manually from a console or future UI controller:

```powershell
python arm_v2_userhost.py --config <absolute-current-user-config.json> start
python arm_v2_userhost.py --config <same-config.json> status
python arm_v2_userhost.py --config <same-config.json> stop
```

`start` waits for the worker's first completed monitor cycle and then exits; the detached per-user worker continues on its own. `status` reads local heartbeat/ownership state only. `stop` requests a cooperative cycle-boundary shutdown and returns success only after the same worker has recorded `STOPPED`, released the OS lock and exited. The controller does not terminate a PID. A second start reports `ALREADY_RUNNING` while the same registry/detector/ledger identity is owned.

CLI exit codes: `0` means the requested operation succeeded (including an already stopped worker) or status is healthy; `1` means status is informatively `STARTING`; `2` means start/stop failure, degraded status, invalid configuration/state, or an unknown outcome; `3` means `ALREADY_RUNNING`. The JSON result remains available on stdout and is not changed by this mapping. `_emit()` applies the same mapping to `result` or `status` outcomes and defaults unknown outcomes to failure code 2.

## M05 scope

This milestone deliberately supports an offline fixture provider only. The current host accepts a canonical JSON config under `%LOCALAPPDATA%` with schema version 1, absolute current-user paths for the M01 registry, detector state, M04 notification ledger, and changing metadata fixture, a mapping of `test:` secret references to base64 encoded test-only HMAC keys, a 1–3600 second interval and a 1–60 second stop timeout. All configured Orchestrator destinations must be local `http` loopback endpoints. The host strips OAuth environment variables and rejects live secret references or non-loopback destinations.

Worker lock, startup lock, heartbeat, stop request and bounded metadata log live under `%LOCALAPPDATA%\ArtifactRelayManager\ARMv2\UserHost\<state-identity-hash>`. The identity binds canonical registry, detector-state and notification-ledger paths. The process heartbeat binds the current Windows user SID, process creation time and active configuration digest. These files are local operational controls; they are not a user-editable PID authority.

No production Drive/OAuth adapter or secret resolver is wired by M05. Do not use this offline host with production credentials or endpoints. No sign-in startup, Windows service, Task Scheduler, registry/firewall modification or elevation is part of this milestone. See `docs/VALIDATION.md` for the process-boundary qualification and remaining limits.

## M02.1B pause/resume offline candidate

`pause` and `resume` accept an optional `--project-id`; without it they control the global pause. The control file is versioned, atomically replaced and bound to the existing host state identity/config digest. It records global and project pause state separately from the project registry's `enabled` flag. A control is accepted only for the currently verified worker owner. The controller returns `APPLIED` only after the worker acknowledges the exact request at a safe monitor boundary; a timeout is `PENDING/CONTROL_TIMEOUT` (exit 2), never a false success.

The worker checks Stop before applying controls. Global pause and the all-enabled-projects-paused case keep heartbeat/status alive without incrementing monitor cycles, listing provider folders, or dispatching notifications. A project pause filters both observation and dispatch for that project while peers continue. Resume reuses detector and notification state, so stable-arrival detection and pending ACK retry continue without rebaseline. Pausing does not alter `enabled`; resuming a disabled project does not enable it. Stop while paused exits normally and retains the durable pause state; a later explicit Start remains paused until Resume. Corrupt, incompatible, or project-mismatched pause state fails closed before provider or receiver side effects.

This remains limited to offline fixtures on the isolated M02.1B development branch. Its publication does not authorize live Drive/APO operation or Orchestrator workflow authority. See the M02.1B qualification and remaining limits in `docs/VALIDATION.md`.
