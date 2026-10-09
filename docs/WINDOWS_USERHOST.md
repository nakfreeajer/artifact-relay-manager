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

The launcher does not install or manage scheduled tasks. A separate bounded qualification registered exactly one temporary root task using the current user's `InteractiveToken`, Limited run level, no triggers, and `IgnoreNew`. COM and `schtasks` agreed on the task definition. One manual COM start ran the disabled-project dry-run for two `IDLE` cycles and exited cleanly; the marker-verified task was deleted, and absence was verified through both interfaces. No persistent task exists. Sanitized results are in ignored `.agent-work/milestones/RELAY.WINDOWS.USERHOST.1A/evidence/qualification/task-scheduler-com-qualification.json`.

This manual disabled-project run does not qualify an automatic logon trigger, enabled task-context delivery, task-context DPAPI access, Task Scheduler restart after failure, operation before user sign-in or after sign-out, or clean sign-out behavior. The UserHost requires the signed-in user's `InteractiveToken` and is not a machine service. Do not use S4U or store a Windows password. Keep any future restart policy finite and qualify stop/logoff behavior before relying on it. PowerShell ScheduledTasks/CIM task-instance queries failed with `0x80070002` for existing unrelated tasks during qualification; COM and `schtasks` succeeded. The two prior disposable attempts were not started and were removed.

No persistent Task Scheduler task, SCM service, Windows account policy, OAuth session, or Google Drive artifact remains changed by the milestone. Relay continues to transport and monitor; the Project Watcher / Orchestrator decides.
