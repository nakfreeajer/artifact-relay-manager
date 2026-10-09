# Current State

Project: `artifact-relay-manager`

Status: `RELAY.PROJECT.SUPERVISOR.1A` is implemented on `main` (source/tests commit `fbee2f5bd97a7b5f252cccc6a81800c17ecbbd60`).

`RELAY.PROJECT.REGISTRY.1A` adds a local schemaVersion 1 JSON registry at `%LOCALAPPDATA%\ArtifactRelayManager\projects.json` by default. Entries reference existing per-project Drive config and Relay state paths rather than duplicating configuration. Writes use a same-directory temporary file, flush/fsync, and atomic replace. Validation rejects project ID, canonical config/state path, configured workspace, and Drive folder collisions. `relay_projects.py` provides list/add/show/enable/disable/remove/validate operations. Registry operations validate local configuration and have no Drive, Watcher, OAuth/browser, or protected-session side effects.

`RELAY.PROJECT.SUPERVISOR.1A` adds a foreground sequential supervisor. It reloads and validates the registry at each cycle boundary, runs enabled entries in deterministic projectId order, and executes one existing Drive monitor cycle for each. One lazily created noninteractive `DriveAuthSession` is shared across projects and cycles. Project-local provider/identity/Watcher/state failures do not stop later projects; a shared auth failure marks remaining projects auth-degraded for that cycle. Registry changes take effect on the next cycle. The CLI is `python relay_supervisor.py [--registry <path>] run --interval-seconds 30 [--max-cycles N]`.

Supervisor source/tests commit: `fbee2f5bd97a7b5f252cccc6a81800c17ecbbd60`. Final deterministic validation passed: 97/97 tests, changed Python compile checks, both existing CLI demos, the dedicated two-project supervisor qualification, and `git diff --check`. Live one-project supervisor qualification passed on 2026-10-08 with the existing protected session, no browser, and no Drive mutation. Two cycles returned OK: cycle 1 delivered the designated current file once; cycle 2 deduplicated it. The file was version `3`, 26 bytes, SHA-256 `839ffb1cf48ad91270f4a395847100e412501c823a63270162a56306b1cc8ecf`. One acknowledged state event and one mock Watcher receipt shared event ID `relay-02471a4ffcf9a90b6ee27824533420ebda3c7f3a93d13b1e88c6525438a76ae9`. The existing protected session remained usable after qualification. Sanitized evidence is in ignored `.agent-work/milestones/RELAY.PROJECT.SUPERVISOR.1A/evidence/live-supervisor-qualification.json`.

Registry source/tests commit: `6848633a69aba57b5b8f86596c5ccecce6d3c664`. Final deterministic validation passed: 82/82 tests; changed Python compile checks; both existing CLI demos; and `git diff --check`. The six-command local CLI qualification passed without Drive, Watcher, OAuth/browser, or protected-session access.

Accepted Relay core:
- exact-byte SHA-256 and byte length;
- deterministic normalized event identity;
- project/repository identity fail-closed checks;
- durable persistence before Watcher delivery;
- Watcher acknowledgement recording;
- duplicate suppression;
- pending retention and restart-safe retry;
- semantic persisted-state validation before retry.

Accepted Google Drive inbound capabilities:
- one-shot polling of direct children from one explicitly configured Drive folder;
- exactly one raw `.relay-project.json` identity file required;
- projectId/repository identity hard-stop enforcement;
- Drive file `id` as provider item identity;
- Drive `File.version` as provider version identity;
- exact raw-byte download and atomic local staging;
- 1 MiB artifact bound;
- native Google Workspace files skipped rather than exported/normalized;
- post-download metadata recheck binds downloaded bytes to the listed file version, size, parent, MIME/state and download capability;
- final Drive identity revalidation before Watcher delivery;
- production API origin fixed to Google Drive v3; loopback override is test-only.

Accepted Google Drive authentication / qualification capabilities:
- installed desktop OAuth flow through the system browser;
- ephemeral `127.0.0.1` callback port;
- exact OAuth scope `https://www.googleapis.com/auth/drive.readonly`;
- OAuth client configuration supplied only from local `RELAY_GDRIVE_OAUTH_CLIENT_FILE`;
- access tokens remain memory-only; refresh tokens are persisted only in current-user Windows DPAPI-protected storage;
- OAuth client JSON remains local through `RELAY_GDRIVE_OAUTH_CLIENT_FILE` and outside Git;
- `qualify-drive` validates one deliberately designated raw direct-child artifact;
- qualification reuses exact-byte, provider-version, parent/state and project-identity consistency checks;
- qualification creates no Watcher event, no Relay delivery state and performs no Drive mutation.

Accepted authentication implementation commit:
- `18d8d45c4ad505651f6ac4ef7f47165c0d068555` - ephemeral Drive OAuth and read-only qualification.
- `eb3339a452badc14e9fb05668a96f128efbb03a2` - script-mode Drive/Auth error identity correction, verified with subprocess tests.

`RELAY.GDRIVE.AUTH.SESSION.1A` adds a Windows current-user DPAPI protected refresh-token session. The deterministic suite and real read-only qualification verify fresh-process refresh reuse without reopening the browser. The protected file contains only the refresh token payload; client/scope identity is hashed into its filename and bound as DPAPI entropy. `reset-drive-auth` removes only that local session.
Implementation commit: `c479aa1488aacf470562a236090ae10d305d7ef8`.

`RELAY.GDRIVE.MONITOR.LOOP.1A` adds the foreground `monitor-drive` command for one configured project. It reuses the protected refresh token without browser launch, keeps the access token in memory across cycles, retries one cycle once after structured HTTP 401, and retries previously pending local transport events only after a successful Drive poll and identity validation. A bounded deterministic backoff handles degraded cycles. Ctrl+C returns a clean `STOPPED` record.

Source/tests commit: `d3d6ba38d02c03a609ca5a62cd9fd8eaac41c303`.

Final deterministic validation:
- 62/62 unit tests passed, including all previous 51 regressions;
- Python compile checks passed;
- fake Drive and core CLI lifecycle demos passed;
- monitor tests cover noninteractive startup, access-token reuse/expiry, one-time 401 recovery, backoff, source-removal retry with the same event ID, identity-mismatch isolation, deduplication, and graceful stop;
- `git diff --check` passed.

Bounded live monitor qualification completed two cycles using the existing protected session and a local mock Watcher. The designated raw file was version `3`, 26 bytes, SHA-256 `839ffb1cf48ad91270f4a395847100e412501c823a63270162a56306b1cc8ecf`. Cycle 1 delivered one event; cycle 2 deduplicated it. The state retained one stable event identity and the mock Watcher received that event once. No browser authorization prompt appeared, and the monitor made no Drive mutation.

Final `RELAY.GDRIVE.AUTH.SESSION.1A` deterministic validation:
- 51/51 unit tests passed;
- Python compile checks passed;
- fake Drive lifecycle CLI demo and core CLI demo passed;
- `git diff --check` passed.

Historical `RELAY.GDRIVE.AUTH.LIVE.1A` deterministic validation (before session persistence):
- 42/42 unit tests passed, including subprocess checks for HTTP 403, missing OAuth client configuration, and successful qualification;
- Python compile checks passed;
- fake-Drive CLI lifecycle demo passed;
- original core CLI demo passed;
- `git diff --check` passed.

Real live qualification:
- result: `QUALIFIED_READ_ONLY`;
- designated artifact MIME: `text/plain`;
- byte length: `26`;
- Drive `File.version`: `3`;
- SHA-256: `839ffb1cf48ad91270f4a395847100e412501c823a63270162a56306b1cc8ecf`;
- the configured folder and artifact relationship was independently rechecked through connected Drive metadata;
- no Drive content was created, modified, renamed or deleted by the qualification command;
- no Watcher event or Relay state was created by qualification.

Observed live prerequisite failure before PASS:
- browser OAuth authorization succeeded while the first Drive API request returned HTTP 403;
- enabling Google Drive API in the same Google Cloud project as the Desktop OAuth client resolved the provider access failure.
- the script-mode correction was qualified locally with a deterministic fake Drive endpoint; the previously recorded real qualification result remains unchanged.

Current limitations:
- foreground supervisor is available and executes projects sequentially in one process;
- no persistent Windows Service or Task Scheduler deployment is configured. The per-user UserHost launcher is Architect-accepted; its live manual Task Scheduler qualification proved task-context protected-session Drive reads, one local mock Watcher acknowledgement, and next-cycle deduplication. Automatic sign-in startup, sign-out behavior, and Scheduler crash/restart recovery remain unqualified;
- desktop UI and supervisor management API are not implemented;
- persistent OAuth session storage is Windows-only and tied to the current Windows user profile;
- reset removes the local token but does not revoke authorization at Google;
- refresh failure is sanitized and keeps the existing session; recovery requires explicit operator action such as reset and browser reauthorization;
- `poll-drive` still retains the existing manual `RELAY_GDRIVE_ACCESS_TOKEN` path;
- `monitor-drive` remains available as a foreground single-project command;
- no scheduler or Drive Changes cursor;
- no desktop UI;
- no outbound Drive publishing;
- no recursive/Drive-wide discovery;
- no native Workspace export;
- no multi-provider framework;
- no concurrent project execution;
- no database;
- no project-Orchestrator workflow authority.

`RELAY.WINDOWS.USERHOST.1A` was implemented at `34ad80ed6110393500deabe19271f40a18d762d6` from baseline `2b0e316ac347a769ce61b26fc6344528efeab168`; implementation and initial documentation closure were Architect-accepted. Subsequent live qualification used one temporary manually started triggerless task under the current user's `InteractiveToken`/Limited context. The existing protected session completed read-only Drive observation, one designated artifact was acknowledged by a local mock Watcher, and a second cycle deduplicated it. The ownership-verified task was removed and absence confirmed by COM and `schtasks`; no persistent task exists. Automatic sign-in startup, sign-out behavior, and Scheduler crash/restart recovery remain unqualified. Windows Service support and Orchestrator authority are out of scope. See `docs/WINDOWS_USERHOST.md` and `docs/VALIDATION.md`.
