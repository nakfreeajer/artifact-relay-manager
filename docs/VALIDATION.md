# Validation

## RELAY.WINDOWS.SERVICE.1A

Deterministic lifecycle coverage:
- clean host start, reuse of the existing `project_supervisor.run_supervisor`, shared validated session, and stop-event wakeup between cycles;
- missing protected Drive session fails closed before the supervisor starts;
- simulated current-user DPAPI decryption failure under an incompatible service identity fails closed before monitoring;
- service startup uses `DriveAuthSession` only; it has no browser OAuth path.

Validation results:
- `python -m unittest discover -s tests -p test_relay_windows_service.py -v` — 3 passed, 0 failed;
- `python -m unittest discover -s tests -v` — 100 passed, 0 failed;
- `python -m py_compile project_supervisor.py relay_windows_service.py tests/test_relay_windows_service.py` — passed;
- `git diff --check` — passed.
- qualification-closure regressions after installing pywin32: service lifecycle 3/3, Project Supervisor 15/15, and Drive session 8/8; all 26 passed;
- qualification-closure compile checks for service, supervisor and DPAPI session modules/tests — passed; `git diff --check` — passed.

Actual Windows SCM qualification is `BLOCKED=scm_create_service_access_denied`. Environment checks on 2026-10-09:
- interpreter: `C:\Python314\python.exe`, Python `3.14.4`; pip `26.0.1`;
- `pywin32` `312` was installed with `python -m pip install --user "pywin32>=306"` into this interpreter's user site and imports successfully;
- current process identity is a standard, non-elevated Windows user; direct `OpenSCManager(..., SC_MANAGER_CREATE_SERVICE)` returned Access Denied (Win32 error `5`);
- pywin32's standard service installation leaves `lpServiceStartName` unset; Windows then assigns LocalSystem. That identity is incompatible with the current-user DPAPI session; qualification requires explicitly configuring the DPAPI-owning user SID;
- no `ArtifactRelayManager` service exists; no service creation was attempted;
- the previously approved local OAuth client file exists, but `RELAY_GDRIVE_OAUTH_CLIENT_FILE` is unset in the current process;
- `DriveAuthSession()` successfully decrypted the existing protected session under the current interactive user identity; this constructor-only check did not refresh an access token or make a network request;
- `%LOCALAPPDATA%` exists, but the default `%LOCALAPPDATA%\ArtifactRelayManager\projects.json` registry is absent.

No service account or project registry was created because SCM create permission is unavailable. The required service account is the same Windows user SID that owns the current-user DPAPI session; no SCM service account is currently configured. The noninteractive process must have `RELAY_GDRIVE_OAUTH_CLIENT_FILE` set to the existing Desktop client file, use that service identity's `%LOCALAPPDATA%\ArtifactRelayManager\projects.json`, and run with the interpreter containing pywin32. pywin32 registers its Python service host; SCM's working directory is not configured by this adapter and normally defaults to the system service directory. Project config and state paths are canonical absolute paths, but module import and runtime behavior from that SCM working directory remain unqualified. A different DPAPI identity or missing configuration fails closed before monitoring. The approved existing Artifact Relay Manager test project, Drive artifacts, and Relay state were not touched. No service was installed or started, no browser was launched, the protected OAuth session was not reset or refreshed, and Google Drive was not modified.

Limitations: actual SCM process startup, supervisor operation under SCM, graceful SCM stop, and on-disk state preservation remain unqualified because service creation is denied to this non-elevated process. Interactive browser authorization is intentionally unavailable in service mode. No desktop UI, service management API, scheduler, database, provider framework, or project-Orchestrator workflow authority was added.

## RELAY.PROJECT.SUPERVISOR.1A

Supervisor coverage proves zero-enabled `IDLE` without auth creation or state access; deterministic sequential execution with each registry entry's own config/state path; one auth object and one refresh reused across projects/cycles; project-local failure isolation; pending Watcher delivery remains in the same project's Relay state/event identity; shared-auth failure skips remaining project calls and retries on a later cycle; corrupt registry processes zero projects and recovers after repair; bounded registry backoff; next-cycle enable/disable/add/remove behavior; metadata-only output; and clean `STOPPED` handling.

The dedicated ignored local qualification uses two distinct project IDs, Drive configs, state paths, workspaces and folder IDs with a loopback mock Watcher and injected bounded provider observations. Three supervisor cycles executed A/B, then B while A was disabled, then A/B after re-enable. Each project retained one event under its own identity; the mock Watcher received exactly one event per project. The shared auth harness was instantiated once and refreshed once. No Drive API call or browser OAuth occurred. Results are in `.agent-work/milestones/RELAY.PROJECT.SUPERVISOR.1A/evidence/multi-project-qualification.json`.

Real one-project qualification was attempted only as a noninteractive prerequisite check. It is `LIVE_VALIDATION_BLOCKED=protected_session_unavailable`: `RELAY_GDRIVE_OAUTH_CLIENT_FILE` was not configured, so `DriveAuthSession` failed before protected-session access. No browser, Drive request, or Drive mutation occurred. No live supervisor cycles or event/deduplication result are claimed.

Final deterministic validation:
- `python -m unittest discover -s tests -v` — 97 passed, 0 failed;
- `python -m py_compile drive_monitor.py project_supervisor.py relay_supervisor.py tests/test_project_supervisor.py tests/supervisor_cli_demo.py` — passed;
- `python tests/gdrive_cli_demo.py` — passed;
- `python tests/cli_demo.py` — passed;
- `python tests/supervisor_cli_demo.py` — passed;
- `git diff --check` — passed.

Supervisor command: `python relay_supervisor.py [--registry <path>] run --interval-seconds 30 [--max-cycles N]`. It uses one process and sequential project execution. The Windows Service host is on `windows-service-1a`; actual SCM qualification remains blocked as documented above. Desktop UI, service management API, database, Drive Changes cursor, outbound publishing, multi-provider framework, scheduler/workflow engine, and project-Orchestrator authority are not implemented.

## RELAY.PROJECT.REGISTRY.1A

Registry-specific coverage proves absent-registry initialization, strict schema and duplicate-key rejection, metadata-only output, canonical paths, stable ordering, fresh-process persistence, enable/disable revalidation, safe remove semantics, project identity matching, and fail-closed collision handling for projectId/configPath/statePath/relayWorkspace/folderId. Atomic replacement failure preserves the prior valid registry. Side-effect tests block all `urllib.request.urlopen` calls and verify a protected-session sentinel remains unchanged.

Local qualification used an ignored fixture config and explicit registry under `.agent-work/milestones/RELAY.PROJECT.REGISTRY.1A/evidence/`. Separate invocations of `add`, `list`, `show`, `validate`, `disable`, and `enable` all exited zero. The final registry contained exactly one enabled project and canonical absolute config/state paths. The endpoint was loopback and was not contacted; OAuth/browser configuration was absent from the isolated process environment. The protected OAuth session was not read, reset, or modified. Sanitized command results are in the ignored `evidence/qualification.json` file.

Final deterministic validation:
- `python -m unittest discover -s tests -v` — 82 passed, 0 failed;
- `python -m py_compile project_registry.py relay_projects.py tests/test_project_registry.py` — passed;
- `python tests/gdrive_cli_demo.py` — passed;
- `python tests/cli_demo.py` — passed;
- `git diff --check` — passed.

Registry CLI shape: `python relay_projects.py [--registry <path>] list|add|show|enable|disable|remove|validate`. The default registry is `%LOCALAPPDATA%\ArtifactRelayManager\projects.json`. It stores schemaVersion 1 and project metadata plus canonical references to existing config/state files. The registry milestone itself added no consumer; the foreground multi-project consumer is recorded in the supervisor section below. Windows Service, UI, database, Drive Changes cursor, outbound publishing, provider framework, and Orchestrator authority were not added by the registry milestone.

Accepted Relay core coverage includes:
- valid project identity;
- project/repository identity mismatch fails closed;
- exact-byte SHA-256 and byte length;
- deterministic normalized event identity;
- persistence before delivery;
- Watcher acknowledgement recording;
- duplicate suppression;
- Watcher unavailable leaves retryable durable state;
- restart-safe retry of the same event identity;
- acknowledged restart does not create a new event;
- malformed/semantically corrupt persisted state fails closed;
- cross-project pending state fails closed with zero delivery;
- dedupe/eventId inconsistency fails closed;
- metadata-only output does not leak artifact bodies.

Accepted Google Drive inbound coverage includes:
- one configured Drive folder and direct children only;
- exactly one raw project identity file;
- project/repository mismatch hard stop;
- missing/duplicate/malformed/native Workspace identity hard stop;
- exact non-ASCII bytes and CRLF/LF distinction;
- same file/version deduplication;
- newer provider version creates a new event;
- native Workspace artifacts skipped without export;
- oversized artifact blocked before delivery;
- Drive auth/HTTP failure produces no invented success;
- outside-root/trashed artifacts are not delivered;
- token/artifact body absent from ordinary CLI output;
- Drive-originated pending event retries with the same eventId;
- same-size provider-version race fails closed before staging/delivery;
- post-download parent/trashed/native/not-downloadable races fail closed;
- identity change before delivery fails closed.

For `RELAY.GDRIVE.INBOUND.1A`, final reported validation was:
- `python -m unittest discover -s tests -v` — 29 passed, 0 failed;
- `python -m py_compile relay.py drive_adapter.py tests/test_relay.py tests/cli_demo.py tests/test_drive_adapter.py tests/gdrive_cli_demo.py` — passed;
- `python tests/gdrive_cli_demo.py` — passed;
- `python tests/cli_demo.py` — passed;
- `git diff --check` — passed.

Live provider qualification for `RELAY.GDRIVE.INBOUND.1A` was originally blocked because credentials were not supplied. That limitation was subsequently closed by `RELAY.GDRIVE.AUTH.LIVE.1A`.

Any future live Drive validation must remain bounded to an explicitly configured project folder and must not mutate Drive.

Accepted Google Drive OAuth / qualification coverage includes:
- exact OAuth scope is `drive.readonly` and no broader scope;
- installed-app loopback uses `127.0.0.1` with an ephemeral port;
- missing dependency/client file fails safely;
- web-client config and duplicate OAuth JSON keys fail closed;
- auth failure text is sanitized;
- access tokens and client secrets are not printed or persisted; the refresh token is stored only in current-user Windows DPAPI-protected storage;
- valid designated raw artifact returns exact metadata/hash only;
- outside-root/native/folder/trashed/not-downloadable/oversized designated items fail closed;
- provider-version and project-identity races fail closed;
- qualification creates zero Watcher events, zero Relay state and no staged artifact body.

For `RELAY.GDRIVE.AUTH.LIVE.1A`, final deterministic validation was:
- `python -m unittest discover -s tests -v` — 39 passed, 0 failed;
- Python compile checks — passed;
- `python tests/gdrive_cli_demo.py` — passed;
- `python tests/cli_demo.py` — passed;
- `git diff --check` — passed.

Real provider qualification:
- `QUALIFIED_READ_ONLY` — PASS;
- designated artifact MIME: `text/plain`;
- byte length: `26`;
- Drive `File.version`: `3`;
- SHA-256: `839ffb1cf48ad91270f4a395847100e412501c823a63270162a56306b1cc8ecf`;
- no Watcher delivery, Relay state mutation or Drive mutation occurred.

A first live attempt reached browser OAuth successfully but received HTTP 403 from Drive until Google Drive API was enabled in the OAuth client's Google Cloud project. The repeated live command then passed.

Architect Correction 1 then used subprocess tests to reproduce and correct the sanitized CLI error-path defect. The executing `relay.py` module is now registered as `relay` before provider imports, so the CLI catches the same `RelayError` class its providers raise.

Post-correction validation:
- `python -m unittest discover -s tests -v` — 42 passed, 0 failed;
- `python -m py_compile relay.py drive_adapter.py drive_auth.py tests/test_relay.py tests/cli_demo.py tests/test_drive_adapter.py tests/test_drive_auth.py tests/gdrive_cli_demo.py` — passed;
- `python tests/gdrive_cli_demo.py` — passed;
- `python tests/cli_demo.py` — passed;
- `git diff --check` — passed;
- subprocess `python relay.py ... qualify-drive` with fake Drive HTTP 403 — nonzero exit, sanitized `relay error: Google Drive API returned HTTP 403`, no traceback or credential/body leakage;
- subprocess `python relay.py ... qualify-drive` without OAuth client configuration — nonzero exit, sanitized Relay auth error, no traceback;
- subprocess fake/local successful `qualify-drive` — exit 0 and `QUALIFIED_READ_ONLY`.

## RELAY.GDRIVE.AUTH.SESSION.1A

Session-specific coverage includes protected refresh-token persistence and fresh-process reuse, client/scope isolation, real Windows DPAPI round-trip, corrupt-session fail-closed behavior, refresh failure retention, refresh-token rotation, idempotent local reset, and `poll-drive` reuse across fresh processes.

Final deterministic validation:
- `python -m unittest discover -s tests -v` - 51/51 passed, 0 failed;
- `python -m py_compile relay.py drive_adapter.py drive_auth.py drive_session.py tests/test_relay.py tests/cli_demo.py tests/test_drive_adapter.py tests/test_drive_auth.py tests/test_drive_session.py tests/gdrive_cli_demo.py` — passed;
- `python tests/gdrive_cli_demo.py` — passed: first delivery, duplicate deduplication, pending delivery while Watcher is unavailable, and fresh invocation retry with the same event ID;
- `python tests/cli_demo.py` — passed;
- `git diff --check` — passed.

Real read-only session qualification:
- first fresh invocation opened the system browser and returned `QUALIFIED_READ_ONLY`;
- subsequent fresh invocation used the stored protected refresh token without opening the browser and returned the same qualification metadata;
- an additional fresh invocation after implementation completion also passed without browser authorization;
- artifact metadata was MIME `text/plain`, byte length `26`, Drive version `3`, SHA-256 `839ffb1cf48ad91270f4a395847100e412501c823a63270162a56306b1cc8ecf`;
- no Watcher delivery or Drive mutation occurred.

The OAuth client JSON and protected session location/content are intentionally excluded from tracked evidence. The real protected session remains in the current Windows user's local application data.

## RELAY.PROJECT.SUPERVISOR.1A live qualification closure

Live supervisor qualification passed on 2026-10-08 using the existing protected Drive session and the real `relay_supervisor.py` CLI for two cycles with one enabled project and a local mock Watcher:
- both cycles returned `OK`; cycle 1 delivered one event and cycle 2 deduplicated the unchanged file/version;
- designated Drive file version `3`, MIME `text/plain`, byte length `26`, SHA-256 `839ffb1cf48ad91270f4a395847100e412501c823a63270162a56306b1cc8ecf`;
- exactly one acknowledged state event and one mock Watcher receipt, with stable event ID `relay-02471a4ffcf9a90b6ee27824533420ebda3c7f3a93d13b1e88c6525438a76ae9`;
- protected session remained usable after qualification; no browser opened and no Drive mutation occurred;
- sanitized metadata only is recorded in ignored `.agent-work/milestones/RELAY.PROJECT.SUPERVISOR.1A/evidence/live-supervisor-qualification.json`.

## RELAY.GDRIVE.MONITOR.LOOP.1A

Monitor coverage includes: missing protected session fails safely without browser flow; protected-session startup refreshes once; valid access token is reused across cycles; expiry refreshes once; rotated refresh token updates the DPAPI store; structured HTTP 401 invalidates/refreshes and retries one cycle exactly once; repeated 401/provider failures produce degraded results with bounded backoff and recovery resets backoff; project identity mismatch does not trigger local pending retries; pending events retry after the source disappears from Drive with the same event ID; unchanged versions remain deduplicated; and Ctrl+C preserves state/session while emitting `STOPPED`.

Final validation:
- `python -m unittest discover -s tests -v` — 62 passed, 0 failed (including all 51 previous tests);
- `python -m py_compile relay.py drive_adapter.py drive_auth.py drive_monitor.py tests/test_drive_monitor.py` — passed;
- `python tests/gdrive_cli_demo.py` — passed;
- `python tests/cli_demo.py` — passed;
- `git diff --check` — passed.

Live monitor qualification:
- command ran exactly 2 cycles with `--interval-seconds 1 --max-cycles 2`;
- both cycles returned `OK`; cycle 1 delivered one event and cycle 2 deduplicated it;
- the designated file remained version `3`, MIME `text/plain`, byte length `26`, SHA-256 `839ffb1cf48ad91270f4a395847100e412501c823a63270162a56306b1cc8ecf`;
- one stable event ID was present for the designated file/version and the local mock Watcher received it once;
- the monitor reused the existing protected session, emitted no authorization prompt, and did not open browser OAuth;
- Drive requests were read-only; no Drive content was created, modified, renamed, moved, or deleted.
