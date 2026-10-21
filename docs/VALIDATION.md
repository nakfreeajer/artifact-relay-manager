# Validation

## RELAY.PROJECT.SUPERVISOR.1A

Supervisor coverage proves zero-enabled `IDLE` without auth creation or state access; deterministic sequential execution with each registry entry's own config/state path; one auth object and one refresh reused across projects/cycles; project-local failure isolation; pending Watcher delivery remains in the same project's Relay state/event identity; shared-auth failure skips remaining project calls and retries on a later cycle; corrupt registry processes zero projects and recovers after repair; bounded registry backoff; next-cycle enable/disable/add/remove behavior; metadata-only output; and clean `STOPPED` handling.

The dedicated ignored local qualification uses two distinct project IDs, Drive configs, state paths, workspaces and folder IDs with a loopback mock Watcher and injected bounded provider observations. Three supervisor cycles executed A/B, then B while A was disabled, then A/B after re-enable. Each project retained one event under its own identity; the mock Watcher received exactly one event per project. The shared auth harness was instantiated once and refreshed once. No Drive API call or browser OAuth occurred. Results are in `.agent-work/milestones/RELAY.PROJECT.SUPERVISOR.1A/evidence/multi-project-qualification.json`.

The initial noninteractive prerequisite check was blocked because `RELAY_GDRIVE_OAUTH_CLIENT_FILE` was not configured. Live supervisor qualification subsequently passed on 2026-10-08 using the existing protected session: two cycles completed, cycle 1 delivered the designated file once, and cycle 2 deduplicated it. See the accepted live results below and in `docs/PROJECT_HISTORY.md`.

Final deterministic validation:
- `python -m unittest discover -s tests -v` — 97 passed, 0 failed;
- `python -m py_compile drive_monitor.py project_supervisor.py relay_supervisor.py tests/test_project_supervisor.py tests/supervisor_cli_demo.py` — passed;
- `python tests/gdrive_cli_demo.py` — passed;
- `python tests/cli_demo.py` — passed;
- `python tests/supervisor_cli_demo.py` — passed;
- `git diff --check` — passed.

Supervisor command: `python relay_supervisor.py [--registry <path>] run --interval-seconds 30 [--max-cycles N]`. It uses one process and sequential project execution. Windows Service/background startup, desktop UI, service management API, database, Drive Changes cursor, outbound publishing, multi-provider framework, scheduler/workflow engine, and project-Orchestrator authority are not implemented.

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

## RELAY.WINDOWS.USERHOST.1A

Implemented at `34ad80ed6110393500deabe19271f40a18d762d6` on `windows-userhost-1a` from `2b0e316ac347a769ce61b26fc6344528efeab168`; Architect accepted with explicit limitations. The per-user launcher starts the existing `project_supervisor.run_supervisor` implementation in a bounded child process, supplies an explicit local registry path and process-local OAuth client path, and leaves the foreground CLI unchanged. It validates absolute canonical paths, validates the project registry before launch, prevents log/control paths from aliasing runtime state, writes allowlisted metadata to capped rotating logs, holds parent and worker OS locks, checks that the parent process remains alive so a worker cannot remain orphaned after launcher failure, and supports an explicit cooperative stop request.

Deterministic validation:
- `python -m unittest tests.test_relay_userhost -v` — 13 passed, 0 failed;
- `python -m unittest discover -s tests -v` — 110 passed, 0 failed;
- `python -m py_compile relay_userhost.py tests/test_relay_userhost.py tests/userhost_cli_demo.py` — passed;
- `python tests/userhost_cli_demo.py` — passed; two bounded `IDLE` cycles, loopback mock Watcher health returned HTTP 200, zero Watcher POSTs;
- `git diff --check` — passed.

The ignored disabled-project CLI qualification used the approved `artifact-relay-manager` project identity in a disposable registry/config/state/workspace. It proved launcher startup, two supervisor cycles, metadata logging, and clean exit, without Drive, OAuth/DPAPI or Watcher activity. Separately, an enabled-project local injected-provider qualification exercised actual launcher and worker subprocesses with the existing supervisor, monitor and Relay paths. A simulated local observation produced two `OK` cycles, one acknowledged mock Watcher POST, and deduplication of the unchanged observation. A simulated Watcher 503 left the event pending; a fresh retry acknowledged the same event ID `relay-2bdb770d77c4f8103c7d03bc784789341273a22d2a80ace3d7ba0d27e4c65202`. The provider observation and in-memory token were simulated; there were no live Drive calls or OAuth/DPAPI accesses. Cooperative stop exited cleanly without force-kill, released both locks, and preserved state. Capped rotating logs omitted artifact body and non-ASCII fixture content. Evidence: ignored `.agent-work/milestones/RELAY.WINDOWS.USERHOST.1A/evidence/qualification/enabled-delivery-qualification.json`.

Initial Task Scheduler COM qualification used one temporary root task configured with the current user's `InteractiveToken`, Limited run level, no triggers, and `IgnoreNew`. It ran the disabled-project fixture for two `IDLE` cycles and exited with code 0; this initial run did not exercise Drive or DPAPI access. Its marker-verified task was deleted and absence verified through COM and `schtasks`. Historical evidence: ignored `.agent-work/milestones/RELAY.WINDOWS.USERHOST.1A/evidence/qualification/task-scheduler-com-qualification.json`.

Earlier PowerShell ScheduledTasks/CIM queries failed with `0x80070002` for existing unrelated tasks while COM and `schtasks` found them. Both prior disposable tasks were `START_NOT_CALLED`, then deleted and verified absent; do not describe those attempts as launcher failures.

### RELAY.WINDOWS.USERHOST.LIVE.1A qualification closure

Architect accepted the bounded live task-context qualification. One temporary, manually started, triggerless Task Scheduler task ran under the current user's `InteractiveToken` at Limited run level with `IgnoreNew`, for at most two cycles. A fresh UserHost invocation ran against the approved test project and read-only Drive folder using the existing current-user DPAPI session and a local loopback mock Watcher. Cycle 1 delivered one designated raw artifact and persisted its acknowledgement; cycle 2 deduplicated the same artifact. The mock Watcher received exactly one POST. The artifact was Drive version `3`, 26 bytes, SHA-256 `839ffb1cf48ad91270f4a395847100e412501c823a63270162a56306b1cc8ecf`; event ID was `relay-02471a4ffcf9a90b6ee27824533420ebda3c7f3a93d13b1e88c6525438a76ae9`. Drive operations were read-only; no production Watcher was used. The existing protected OAuth session and Drive artifact were preserved.

The exact ownership-marked task was deleted; COM and `schtasks` confirmed absence. The launcher exited with code 0, no worker remained, and both locks were free. Sanitized evidence: ignored `.agent-work/milestones/RELAY.WINDOWS.USERHOST.LIVE.1A/evidence/task-context-20261010-011100-bdcc22d8/qualification.json`.

Earlier PowerShell ScheduledTasks/CIM query-layer calls failed with `0x80070002` while enumerating unrelated existing tasks; this was separate from launcher execution. Native COM and `schtasks` successfully found and verified the relevant tasks.

Limitations and unqualified behavior:
- This was a manual no-trigger qualification, not deployment of a persistent task or automatic startup at sign-in.
- Automatic startup at Windows sign-in, operation before sign-in or after sign-out, clean sign-out behavior, and Task Scheduler crash/restart recovery remain unqualified. No claim of logged-out availability is made.
- Windows Service support remains unimplemented and unqualified. `windows-service-1a` is a separate branch.
- No OAuth browser flow, credential reset, Drive mutation, production Watcher delivery, SCM operation, or Windows account/policy change occurred.
- The offline launcher dry-run requires every configured registry project to be disabled and an explicit bounded cycle count.
- Relay remains transport/monitor only; no project-Orchestrator authority was added.

Sanitized evidence is in ignored `.agent-work/milestones/RELAY.WINDOWS.USERHOST.1A/evidence/qualification/qualification.json`.

### RELAY.WINDOWS.USERHOST.AUTOSTART.1A definition qualification and lifecycle plan

Architect accepted `PASS_DISABLED_LOGON_DEFINITION_QUALIFICATION` on 2026-10-10. The exact disposable task `\ArtifactRelayManager-UserHost-Logon-Definition-20261010-01` used the current user's `InteractiveToken` at Limited run level, one current-user LogonTrigger, `IgnoreNew`, a five-minute execution limit, and no restart policy. Native COM and `schtasks` agreed on the definition. It remained disabled, `run` was never called, no sign-in trigger fired, and ownership-verified removal and absence checks passed through both interfaces. No task, process, lock, credential, environment, or project state remains changed. Evidence: ignored `.agent-work/milestones/RELAY.WINDOWS.USERHOST.AUTOSTART.1A/evidence/qualification.json`.

**Actual sign-in trigger activation: NOT QUALIFIED.** The definition-only result does not prove that Task Scheduler fires the trigger or that the UserHost starts after sign-in. No sign-out/reboot or lifecycle test was performed.

Proposed first lifecycle test, requiring explicit human approval before task creation/enabling and before the planned sign-out/sign-in:
1. Protect ongoing user work; use the next human-selected safe sign-out/sign-in window. Do not force sign-out, reboot, or close work automatically. Confirm the existing UserHost launcher/worker locks are free, there is no matching process or stop request, and the exact task name below is absent in COM and `schtasks`.
2. Create only `\ArtifactRelayManager-UserHost-Logon-Lifecycle-Qualification-20261010-01`, owned by this qualification marker and scoped to the current user's `InteractiveToken`/Limited identity. Use one current-user LogonTrigger; action: the existing `relay_userhost.py --config <validated ignored fixture config> start --dry-run --max-cycles 2`; working directory: repository root. The fixture registry must validate and have zero enabled projects. Set `IgnoreNew`, a five-minute execution limit, no restart, no password/S4U, no battery start, no wake, and `StartWhenAvailable=false`. Verify the definition with COM and `schtasks` while it is disabled; do not use production config, Drive, Watcher, OAuth, or protected-session access.
3. Only after the human approves the planned sign-out/sign-in, enable this exact task. Verify it did not start merely upon registration/enabling; then observe the actual user's next sign-in and confirm that single trigger starts the existing launcher. Expect two bounded `IDLE` supervisor-cycle records in the fixture log, Task Scheduler result code 0, clean launcher/worker exit, and both locks free. Any unexpected process, state change, output, or nonzero result stops the qualification.
4. Disable and remove only this marker- and identity-verified task. Confirm absence through COM and `schtasks`, no matching process/lock remains, fixture state is unchanged, and no task persists. Record sanitized metadata only. If the trigger does not fire or cleanup cannot be proven, stop and report the exact outcome; do not add retries or broaden the test.

Keep sign-out cleanup behavior, crash/restart recovery, and battery/sleep/wake behavior as separate future qualifications. They remain unqualified after the proposed first logon-trigger test. Do not persist or enable any scheduled task without the explicit human approval described above.

## ARM.M01 two-folder project configuration

Baseline: `arm-v2-m00-charter-20261020` at `6280c5b5e7c26393924f365a00bd95764b364722`. The M01 development branch adds a schemaVersion 2 registry envelope with legacy operational `projects` preserved separately from configuration-only `folderProjects`. It accepts standard Google Drive folder paths (`/drive/folders/<id>` and `/drive/u/<n>/folders/<id>`) and benign Drive `usp` link parameters, then emits canonical folder URLs. A deterministic local fake provider validates active root metadata and exactly one direct folder child named `Architect_Prompts` and `Executor_Reports`; root/child IDs are unique across configured projects and existing legacy roots. Remote endpoint syntax allows HTTPS, plus HTTP loopback only; no endpoint request is made. Optional repository/workspace and secret-reference identifier, enabled flag, and config revision are persisted. No tokens or file bodies are stored.

Offline outcome qualification: two separate `relay_projects.py configure` invocations registered project A and B using one deterministic fake-provider fixture; `show` returned canonical root and child URLs/IDs; `validate --provider-fixture` checked both; fresh CLI `list` reloaded identical bindings. Both were stored with `enabled=false`. Negative tests cover missing/duplicate/wrong-MIME/trashed/mis-parented children, duplicate roots/overlap/workspaces, invalid Drive URLs and endpoint URLs, provider read failure, provider projectId mismatch, tampered IDs, corrupt legacy registry state, and non-destructive v1 load. The supervisor's existing `projects` input remains unchanged; no runtime monitoring was added.

Validation commands/results:
- `python -m unittest tests.test_project_registry tests.test_project_folder_config -v` — 30 passed, 0 failed;
- `python -m unittest discover -s tests -v` — 120 passed, 0 failed;
- `python -m py_compile project_registry.py relay_projects.py project_folder_config.py tests/test_project_registry.py tests/test_project_folder_config.py tests/project_config_cli_demo.py` — passed;
- `python tests/project_config_cli_demo.py` — passed; A/B config, show, validation and fresh-process reload; zero Google Drive, OAuth, endpoint request or Watcher activity;
- `git diff --check` — passed.

The offline fake validates configured metadata only; live Google Drive access, folder selection UI, monitoring, notifications, ACK/retry behavior, and Orchestrator integration are not qualified or implemented. See ignored `.agent-work/milestones/ARM.M01.TWO_FOLDER_CONFIG.1A/evidence/` for sanitized command evidence.

## ARM.M03 — Two-folder Drive change detection (offline candidate)

Baseline: M01 branch commit `158af8bcf42ce2e6edec2816de09259e438f9322`; implementation branch: `arm-v2-m03-dualfolder-detection-1a`.

- `python -m unittest tests.test_drive_change_detector tests.test_project_registry tests.test_project_folder_config -v` — 41 passed, 0 failed.
- `python -m unittest discover -s tests -v` — 131 passed, 0 failed.
- `python tests/drive_change_cli_demo.py` — passed six fresh CLI invocations over two configured projects: initial baseline, create plus checksum-proven content edit, identical repeat, metadata rename/version increment, move/delete with nested child excluded, and fresh-process reload. Three stable events were persisted (two `PROMPT_CHANGED` for project A and one `REPORT_CHANGED` for project B); repeat and restart emitted no new events. The unproven move-in was recorded as ambiguous.
- Changed-module `py_compile` — passed for `drive_change_detector.py`, `drive_adapter.py`, and both new test/demo modules.
- `git diff --check` — passed.
- Deterministic network guard passed; provider/server input was local JSON fixture only. The M03 detector and CLI made no Google Drive/OAuth/protected-session, APO, or Watcher calls; the CLI network guard was enabled. The inherited full regression suite did run deterministic loopback mock Watcher tests and its existing Windows DPAPI primitive round-trip with disposable test text; it contacted no external endpoint and accessed no credential or stored session. Scheduler, Service, UserHost, Desktop Bridge, file-body reads, and live monitoring: none.

Limitations: list-only Drive metadata does not prove whether an item first observed in a configured folder was created there or moved there; production adapter therefore records ambiguity rather than a definite create event. Native Workspace files and binary files lacking `md5Checksum` do not qualify for content-change events. Fixture-proven creation exercises deterministic event behavior only and is not live provider qualification. No periodic/adaptive polling, M04 notification queue, ACK/retry, UI, or Orchestrator behavior was added.

## ARM.M04 simulated Orchestrator notification and ACK (offline candidate)

Baseline: `arm-v2-m03-dualfolder-detection-1a` at `7e9fe693492b7ff71cd10bed81bba52045585bd6`; branch: `arm-v2-m04-apo-ack-offline-1a`.

Validation commands, exact attempted/pass/fail/skip totals, compile result, demo output, and commit SHA are in the appended M04 entry of `docs/TEST_EVIDENCE_LEDGER.md` and the sanitized ignored evidence report. Scope is offline only: two M01 folderProjects records, persisted M03 metadata events, and two deterministic loopback receiver instances. The demo launches a fresh sender Python process per dispatch and enforces a child-process loopback-only socket guard. No public network or Google Drive connection is used.

Latest local validation:
- `python -m unittest tests.test_arm_notification -v` — 16 run, 16 passed, 0 failed, 0 skipped.
- `python -m unittest tests.test_project_registry tests.test_project_folder_config tests.test_drive_change_detector tests.test_arm_notification -v` — 57 run, 57 passed, 0 failed, 0 skipped.
- `python -m unittest discover -s tests -v` — 147 run, 147 passed, 0 failed, 0 skipped.
- `python -m py_compile arm_notification.py tests/test_arm_notification.py tests/mock_apo.py tests/notification_cli_demo.py` — passed.
- `python tests/notification_cli_demo.py` — passed in three fresh sender processes; two events delivered/ACKed, one accept-then-timeout replayed with the same event ID, receiver unique processing remained one per event, and final duplicate invocation made zero requests.
- `git diff --check` — passed.

The full inherited offline suite includes deterministic auth/session coverage and a Windows DPAPI primitive test with disposable test material. No stored OAuth/DPAPI session or live credential was accessed. M04 receiver traffic was loopback-only and the sender child guard blocked non-loopback socket connections.

Claims are limited to simulated transport behavior. The M03 source-event identity, project/folder mapping, enabled status, endpoint binding, request authentication, matching signed receipt ACK, atomic pending/attempt persistence, retry deadlines, restart recovery, dedupe, and isolation are exercised offline. Real APO compatibility, production secret resolution/rotation, remote HTTPS deployment, live Drive monitoring, live new-file creation proof, and workflow effects remain unqualified.

## ARM.M03.R2 — Human-authorized D11 inbox arrival detection (offline)

Baseline: `arm-v2-m04-apo-ack-offline-1a` at `5ba294d5fb93151f8a6a60b92088f5091df122c5`; candidate branch: `arm-v2-m03r2-inbox-arrival-offline-1a`.

The updated detector takes a silent first-scan baseline. A direct-child file first seen after baseline is persisted as an arrival candidate; only two successive complete scans with an unchanged usable fingerprint create an `ARRIVED` event. The fingerprint uses available binary checksum/size/version metadata; native Workspace arrival requires stable version/modified-time metadata. A changed fingerprint restarts the stability window; missing usable metadata surfaces an ambiguity. Confirmed departure deactivates the item and cancels a candidate; stable re-entry increments the per-file arrival occurrence and yields a new deterministic ID. Rename-only and metadata-only version changes on active files remain silent. Nested descendants are absent from direct-child listings. State v1 migration validates and preserves old `CREATED`/`CONTENT_UPDATED` event IDs, and M04 continues to use the existing metadata payload and ACK contract.

Validation results:
- `python -m unittest tests.test_project_registry tests.test_project_folder_config tests.test_drive_change_detector tests.test_arm_notification -v` — 64 run, 64 passed, 0 failed, 0 errors, 0 skipped.
- `python -m unittest discover -s tests -v` — 154 run, 154 passed, 0 failed, 0 errors, 0 skipped.
- `python -m py_compile drive_change_detector.py tests/test_drive_change_detector.py tests/drive_change_cli_demo.py tests/test_arm_notification.py tests/notification_cli_demo.py` — passed.
- `python tests/drive_change_cli_demo.py` — passed, 9 fresh detector CLI invocations; first baseline emitted zero events, stable A prompt/B report arrivals emitted once, repeat/restart deduplicated, and observed departure/re-entry emitted a distinct event ID. Content edit remained eligible; rename/version-only update was silent. Event IDs: content `m03-1fa92664b478d6d019eaa8987d5b344502f80ae8b0b8e16b532db2d72ffa03d3`; prompt arrival `m03-ccdf09b56f60af21d3b10b621cbfe2980b8ac07cbe35731be1198bfc8987af9e`; report arrival `m03-26d3c314b93002d4ba15f2e01fe34f687b9127f5b16d884151bf4de6a1fa881e`; report re-entry `m03-2f46cdf9b3a8905ef4d0eabbd8fea0952981487a51141d186df72e80cbd1c8fc`.
- `python tests/notification_cli_demo.py` — passed; both `ARRIVED` events were sent to their own loopback simulated APO and ACKed. Project B accepted then timed out; a fresh sender process retried the same event ID, obtained the matching ACK, and the receiver processed it once. Final duplicate dispatch sent zero new requests. Arrival IDs: A `m03-f07837cc7e469a0da47b7e9fe99a376848a154e785ba27c13b8e31746f75b8a3`; B `m03-d20ab0b353254edc4e31ef3b960d152713bbca5f60d0d3aac0cb12f055f1f406`.
- `git diff --check` — passed.

All provider observations in these tests/demos are deterministic local fixtures. The only HTTP is loopback to simulated APO receivers with a non-loopback child-process network guard. No live Google Drive/API call, OAuth grant or stored session, real APO, Desktop Bridge, public network, or workflow authority was exercised. The full inherited suite includes mock auth tests and a DPAPI primitive round-trip with disposable test material; it did not access a stored credential/session. The stable metadata rule is an offline heuristic, not upload-completion proof. Actual Drive listing cadence/arrival behavior and native Workspace content updates remain unqualified.
