# Windows Per-User Supervisor Host

`relay_userhost.py` is a small process host for the existing foreground Project Supervisor. It calls the existing `project_supervisor.run_supervisor` implementation from a child Python process; it does not contain project-monitoring or workflow decisions.

## User-owned configuration

Use a local configuration file readable and writable only by the Windows user who owns the protected DPAPI session. It contains paths and bounded runtime settings, never OAuth JSON, access tokens, refresh tokens, or passwords.

```json
{
  "schemaVersion": 1,
  "pythonExecutable": "C:\\Users\\<user>\\AppData\\Local\\Programs\\Python\\Python314\\python.exe",
  "supervisorScript": "C:\\Users\\<user>\\Projects\\artifact-relay-manager\\relay_supervisor.py",
  "workingDirectory": "C:\\Users\\<user>\\Projects\\artifact-relay-manager",
  "registryPath": "C:\\Users\\<user>\\AppData\\Local\\ArtifactRelayManager\\projects.json",
  "oauthClientFile": "C:\\Users\\<user>\\AppData\\Local\\ArtifactRelayManager\\oauth-client.json",
  "logPath": "C:\\Users\\<user>\\AppData\\Local\\ArtifactRelayManager\\logs\\userhost.jsonl",
  "lockPath": "C:\\Users\\<user>\\AppData\\Local\\ArtifactRelayManager\\userhost.lock",
  "workerLockPath": "C:\\Users\\<user>\\AppData\\Local\\ArtifactRelayManager\\userhost-worker.lock",
  "stopPath": "C:\\Users\\<user>\\AppData\\Local\\ArtifactRelayManager\\userhost.stop",
  "intervalSeconds": 30,
  "maxCycles": null,
  "stopTimeoutSeconds": 30,
  "logMaxBytes": 262144,
  "logBackups": 3
}
```

All paths must be absolute canonical local paths. The launcher validates the interpreter, existing supervisor script, working directory, registry and OAuth client path, then validates the registry before starting a child. The OAuth client file is not read by the launcher. `RELAY_GDRIVE_OAUTH_CLIENT_FILE` is set only in the child process environment; the parent and system/user environment are unchanged. The registry path is passed explicitly and `LOCALAPPDATA` is left unchanged for current-user DPAPI lookup.

The launcher writes metadata-only JSONL output with a byte cap and a fixed number of rotated backups. Child stdout is parsed through a field allowlist; unrecognized content is suppressed. Stderr contents are discarded and only a byte count is recorded. Routine logs do not contain OAuth paths, credentials, or artifact bodies.

## Start, stop, and bounded qualification

```powershell
python relay_userhost.py --config C:\absolute\path\userhost.json start
python relay_userhost.py --config C:\absolute\path\userhost.json stop
python relay_userhost.py --config C:\absolute\path\userhost.json start --dry-run --max-cycles 2
```

The `stop` command writes a local stop request and waits for both OS file locks to be released. The child polls for that request and interrupts the supervisor's existing cycle sleeper, so it exits at a cycle boundary. The worker holds a second one-instance lock and checks that its launcher process still exists; if that process crashes, the worker exits at a cycle boundary, preventing a duplicate supervisor. Only the launcher-owned child is terminated if the bounded stop deadline expires, and that path returns a failure status. Lock files themselves may remain after exit.

Dry-run requires an explicit `--max-cycles` and a registry with every project disabled. It runs the real supervisor loop to prove bounded process startup, cycle logging and exit without Drive or Watcher activity. It is not a delivery qualification. For a delivery qualification, use an approved disposable project and deterministic local provider/Watcher fixtures; do not use the live Drive endpoint absent a separately approved live qualification.

## Task Scheduler boundary

The launcher does not install or manage scheduled tasks. An initial bounded qualification registered one temporary root task using the current user's `InteractiveToken`, Limited run level, no triggers, and `IgnoreNew`. It manually ran a disabled-project dry-run for two `IDLE` cycles; the marker-verified task was deleted and absence verified through COM and `schtasks`. Historical evidence is in ignored `.agent-work/milestones/RELAY.WINDOWS.USERHOST.1A/evidence/qualification/task-scheduler-com-qualification.json.

Subsequent live qualification used one temporary manually started, triggerless task with the same `InteractiveToken`, Limited, and `IgnoreNew` settings. It ran at most two UserHost supervisor cycles with the approved test project and local loopback mock Watcher. The existing current-user DPAPI session supported read-only Drive observation; cycle 1 delivered and recorded one acknowledgement, and cycle 2 deduplicated the same artifact. The mock Watcher accepted exactly one POST. The task was ownership-checked, deleted, and confirmed absent through COM and `schtasks`; the launcher exited cleanly, processes and locks were cleared, and no persistent task exists. Sanitized evidence is in ignored `.agent-work/milestones/RELAY.WINDOWS.USERHOST.LIVE.1A/evidence/task-context-20261010-011100-bdcc22d8/qualification.json.

This qualification does not cover an automatic logon trigger, pre-login or after-sign-out operation, clean sign-out behavior, or Task Scheduler crash/restart recovery. The UserHost requires the signed-in user's `InteractiveToken` and is not a machine service. Do not use S4U or store a Windows password. Earlier PowerShell ScheduledTasks/CIM queries failed with `0x80070002` for unrelated existing tasks; native COM and `schtasks` succeeded. The earlier two disposable attempts were not started and were removed. Keep any future restart policy finite and qualify stop/logoff behavior before relying on it.

No persistent Task Scheduler task, SCM service, or Windows account policy was left changed. The protected OAuth session was not reset or removed and remained present and usable. Relay continues to transport and monitor; the Project Watcher / Orchestrator decides.

### Logon definition qualification status

On 2026-10-10, the exact temporary current-user `InteractiveToken`/Limited LogonTrigger definition was independently checked through native COM and `schtasks`. It remained disabled, was never run, and was removed with absence verified through both interfaces. Result: `PASS_DISABLED_LOGON_DEFINITION_QUALIFICATION`. This verifies only the task definition and cleanup. **Actual sign-in trigger activation remains NOT QUALIFIED.** A human-approved first sign-in test plan and its safeguards are recorded in `docs/VALIDATION.md`; no persistent task is configured.
