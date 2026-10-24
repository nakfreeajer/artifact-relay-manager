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

## ARM.M03.R3 foreground Drive-to-mock-APO cycle ? offline candidate

Baseline: `arm-v2-m03r2-inbox-arrival-offline-1a` at `9a5990226ffb8d6c05d232bfb4d01e5fdbe3f484`; local branch `arm-v2-m03r3-foreground-cycle-1a`.

Implementation adds a bounded foreground runner around accepted M01 `folderProjects`, M03.R2 detector, and M04 sender. Enabled projects share each detector pass. The detector's selected-project scan option prevents polling disabled projects while preserving state for unselected projects. Existing scan persistence is atomic across the selected set: an incomplete listing marks the enabled set degraded, leaves detector state byte-identical, and does not masquerade as an empty listing. The runner still dispatches pre-existing durable intents after scan failure. The M04 sender accepts an optional per-project attempt cap; R3 uses one event/project/cycle. Default M04 behavior is unchanged. Ten seconds is the nominal injected/configured cycle delay, not an end-to-end delivery guarantee; provider failures back off exponentially to a configured maximum.

Validation commands/results:
- `python -m unittest tests.test_project_registry tests.test_project_folder_config tests.test_drive_change_detector tests.test_arm_notification tests.test_arm_foreground -v` ? 72 run, 72 passed, 0 failures/errors/skips.
- `python -m unittest discover -s tests -v` ? 162 run, 162 passed, 0 failures/errors/skips.
- `python -m py_compile arm_foreground.py drive_change_detector.py arm_notification.py tests/test_arm_foreground.py tests/test_drive_change_detector.py tests/test_arm_notification.py tests/drive_change_cli_demo.py tests/notification_cli_demo.py tests/foreground_cycle_cli_demo.py` ? passed.
- `python tests/drive_change_cli_demo.py` ? passed; nine fresh detector invocations and zero network/body reads.
- `python tests/notification_cli_demo.py` ? passed; two loopback APOs, matching ACKs, same-ID retry and dedupe.
- `python tests/foreground_cycle_cli_demo.py` ? passed; five recorded cycles across the foreground run and fresh monitor restart. Cycle 1: silent baseline and zero requests. Cycle 2: A `CONTENT_UPDATED`, event `m03-969d6872f34d03b1dc6b15f8b169745caf53bafbeacf7ebe6d006ec5ea16ee54`, ACKed. Cycle 3: A `ARRIVED/PROMPT_CHANGED`, `m03-ccdf09b56f60af21d3b10b621cbfe2980b8ac07cbe35731be1198bfc8987af9e`; B moved-in `ARRIVED/REPORT_CHANGED`, `m03-d20ab0b353254edc4e31ef3b960d152713bbca5f60d0d3aac0cb12f055f1f406`; A ACKed, B pending after receiver acceptance/timeout. Cycle 4 in a fresh monitor instance retried B with the same ID; receiver processed it once and ACK persisted. Cycle 5 incomplete B listing reported `DEGRADED_ATOMIC_SCAN`, left detector state byte-identical and caused no duplicate request. Final delivery status pending=0, ACKed=3.
- `git diff --check` ? passed.

Negative coverage includes malformed shared registry before provider/network access, disabled B not polled, incomplete B listing preserving atomic detector state while a preexisting A pending event retries, fair per-project dispatch cap, bounded backoff `[10,20,25,25]`, Ctrl+C persistence/restart, and all prior M01/M03.R2/M04 isolation, corruption, authentication, ACK, retry, and dedupe regressions. The full inherited offline suite includes mock OAuth/DPAPI regression cases using disposable test-only material; no stored session/credential was accessed.

Limits: this is deterministic synthetic integration through injected metadata-provider and secret-resolver seams, not live Drive, OAuth, actual APO, Windows background, or production secret-resolution qualification. An enabled-project listing error blocks the whole current enabled scan batch because accepted M03 persists that scan atomically; existing durable notifications continue. No partial scanning refactor was attempted. The implementation grants no Orchestrator workflow authority.

Publication: the updated M03.R3 instruction recorded Human D26 authorization. Commit `3a7605e99bf75093234fbbc074910ea6b958ecec` was pushed once, ordinarily and without force, to `arm-v2-m03r3-foreground-cycle-1a`; remote branch was verified at the same SHA. No merge or tag occurred.

## ARM.M05 Windows manual background host — offline candidate

Baseline `arm-v2-m03r3-foreground-cycle-1a` at `3a7605e99bf75093234fbbc074910ea6b958ecec`; local work branch `arm-v2-m05-userhost-lifecycle-offline-1a`. This is a Windows 10/11 manually launched, UI-independent process host for the accepted M01/M03/M04 pipeline. `arm_v2_userhost.py` runs the existing `ForegroundMonitor.cycle()` repeatedly in a detached per-user worker without retaining an unbounded cycle list. It imports the existing OS-released `relay_userhost.SingleInstanceLock` primitive; v1 source and behavior are unchanged. A registry/detector/ledger identity binds lock, heartbeat and stop request. Status and stop verify the current Windows user SID and process creation timestamp for the PID in the heartbeat. Stop requests name the active worker instance and stop succeeds only after its matching `STOPPED` heartbeat, lock release and process exit. Stale PID text or an unlocked stale lock file never authorizes process termination.

Offline/Windows qualification commands and results:
- `python -m unittest tests.test_project_registry tests.test_project_folder_config tests.test_drive_change_detector tests.test_arm_notification tests.test_arm_foreground tests.test_relay_userhost tests.test_arm_v2_userhost -v` — 88 run, 88 passed, 0 failed, 0 errors, 0 skipped.
- `python -m unittest tests.test_arm_v2_userhost -v` — 3 run, 3 passed, 0 failed, 0 errors, 0 skipped.
- `python -m unittest discover -s tests -v` — final rerun 165 run, 165 passed, 0 failed, 0 errors, 0 skipped. The first full-suite attempt recorded one failure at the later crash/restart assertion; a focused process test and subsequent full rerun passed without a behavior change. The transient failure did not recur, but its precise first-run start result was not captured.
- `python -m py_compile arm_v2_userhost.py arm_foreground.py drive_change_detector.py arm_notification.py relay_userhost.py tests/test_arm_v2_userhost.py tests/arm_v2_userhost_process_demo.py tests/test_arm_foreground.py tests/test_drive_change_detector.py tests/test_arm_notification.py tests/drive_change_cli_demo.py tests/notification_cli_demo.py tests/foreground_cycle_cli_demo.py` — passed.
- `python tests/drive_change_cli_demo.py` — passed; 9 fixture CLI processes, 4 stable event identities, no network calls or content reads.
- `python tests/notification_cli_demo.py` — passed; loopback-only receivers, signed ACK, accepted-timeout same-ID retry and duplicate dedupe.
- `python tests/foreground_cycle_cli_demo.py` — passed; 5 foreground cycles, 2 loopback receivers, 3 acknowledged events, 0 pending, same-ID retry and atomic incomplete-listing behavior.
- `python tests/arm_v2_userhost_process_demo.py` — passed on the current Windows host; worker stayed alive after START controller exit, simultaneous starts returned `ALREADY_RUNNING`, signed project-specific events completed, B remained pending with event ID `m03-d20ab0b353254edc4e31ef3b960d152713bbca5f60d0d3aac0cb12f055f1f406` after stop and was ACKed after fresh start with that same ID (attempt count 2; receiver processed it once). Final ACKed=3, pending=0. The demo also proved incomplete B scan state preservation, disabled B not polled, wrong-PID stop refusal with no stop request, failed-start cleanup, verified worker-only abrupt termination releasing the OS lock, stale lock-file restart recovery and zero leftover workers.
- `git diff --check` — passed.

The worker accepts only local current-user metadata fixtures, `test:` secret references, and `http` loopback simulated Orchestrator endpoints. It strips OAuth environment inputs and rejects public/LAN endpoints; socket access is guarded against non-loopback destinations. Test logs were scanned for event bodies, test keys, endpoint URLs and temporary private paths; none were found. No Google Drive request, OAuth/DPAPI credential/session access, real APO, external network, Windows service, Task Scheduler, sign-in startup, registry/firewall modification, elevation or desktop UI occurred.

Limits: production Drive provider and secret resolution are deliberately not wired; this worker is fixture-only and is not suitable for production credential or endpoint use. Status is process/heartbeat telemetry, not product acceptance. A hung in-flight loopback receiver can delay stop until its bounded transport timeout; stop remains bounded by the configured limit and reports timeout rather than killing a worker. Windows behavior is qualified only in this current per-user environment. Historical support STOP remains `TRIGGERED` with count `UNCERTAIN`; prior five-milestone support checkpoint remains `OVERDUE`. M05 is treated as the expressly selected CORE capability; neither governance record is reset. The Human subsequently authorized one commit and ordinary push to this named M05 branch after refreshed validation.

### D26 publication requalification — 2026-10-22

- Focused M01/M03.R2/M04/R3/v1 UserHost/M05 suite: 88 run, 88 passed. M05 suite: 3 run, 3 passed. Full unittest discovery: 165 run, 165 passed. The full run completed in 119 seconds.
- The Windows process demo was rerun directly with captured timestamps, stdout, stderr and exit status: exit 0. It again verified detached-worker survival after controller exit, two racing `ALREADY_RUNNING` responses, cooperative stop, exact ownership checks, pending same-event retry after restart, verified worker-only abrupt exit, stale-lock recovery and no leftover worker. Event `m03-d20ab0b353254edc4e31ef3b960d152713bbca5f60d0d3aac0cb12f055f1f406` remained identical across the pending/retry boundary; attempt count was 2 and the receiver processed one unique event.
- `python tests/drive_change_cli_demo.py`, `python tests/notification_cli_demo.py`, and `python tests/foreground_cycle_cli_demo.py` each exited 0. The changed-module `py_compile` command and `git diff --check` passed.
- Historical intermittent failure is preserved: the prior first full-suite attempt had 164 passed and 1 crash/restart assertion failure without its exact CLI return JSON; later prior focused/full runs passed without behavior change. Both captured focused runs in that prior D26 requalification completed with 88/88 passed. No test failure occurred in either focused invocation. The earlier crash/restart failure was not erased or represented as fixed.
- Reconciliation of the earlier capture: `d26-focused-regression-20261022-014431-969.json` records the first focused invocation completed with exit code 0 and 88/88 passed. Its output had been redirected to ignored evidence; a later explicit-poll rerun also passed 88/88. No test failure occurred in either focused invocation.
- Raw timestamped command outputs and status metadata are in ignored `.agent-work/milestones/ARM.M05.WINDOWS.USERHOST.LIFECYCLE.1A/evidence/`. Human D26 authorization permits one commit and ordinary push of the eight approved paths only. No main merge or tag.

## ARM.M05.R1 CLI exit-status correction — 2026-10-22

- `_emit()` preserves each JSON object and maps successful `STARTED`, `STOPPED`, `RUNNING` to exit 0; informative `STARTING` to 1; failure, degraded, invalid, timeout, or unknown outcomes to 2; and `ALREADY_RUNNING` to 3.
- Deterministic subprocess assertions cover successful start/status/stop and already-stopped status (0), STARTING (1), duplicate start (3), failed start, STOP_TIMEOUT, forged-owner degraded status, and malformed config (2). STOP_TIMEOUT is induced by holding the known startup OS lock, not by a timing race. The invalid synthetic test-key binding exercises START_FAILED.
- Windows process demonstration, including detached controller/worker lifecycle, same-event pending retry, abrupt worker exit and OS lock recovery, passed four complete standalone runs after one test-fixture setup failure. All captured CLI invocations include timestamp, JSON, sanitized stdout/stderr, exit code, and available PID/process-creation/user-identity observations. Same pending/retried event ID: `m03-d20ab0b353254edc4e31ef3b960d152713bbca5f60d0d3aac0cb12f055f1f406`.
- One first demo attempt failed before reaching its crash/restart segment because the new STARTING fixture tried to take a lock before its control directory existed. The test now creates the temporary directory first; this is test setup only. The failed attempt and output are retained. The prior M05 crash/restart assertion failure remains unexplained because its exact result was not captured; it did not recur in the three complete repeated runs. No root cause or runtime repair is claimed.
- M05.R1 focused suite: 4/4; focused inherited suite: 89/89; full discovery: 166/166. The three inherited CLI demos exited 0. Changed-module compilation and `git diff --check` passed. Evidence is under ignored `.agent-work/milestones/ARM.M05.R1.CLI.EXIT.STATUS.1A/evidence/`.
- No live Drive/OAuth/DPAPI/real APO, external network, Windows service/Scheduler, system configuration, Desktop Bridge, or Orchestrator workflow authority was used or added.

## ARM.M02.1A Windows dashboard — offline CORE candidate

Baseline `7f51720f9b81ba99a3fc494d050249d8d680d4a0`; branch `arm-v2-m02a-windows-dashboard-offline-1a`. `arm_v2_dashboard.py` is a native Tk/ttk dashboard that reads only v2 `folderProjects`, validated M03/M04 local metadata, and accepted M05 `start/status/stop`. A local v2 enabled-state writer preserves legacy `projects` and uses registry validation plus atomic replacement. Project creation is disabled by default and requires local direct-child FakeDriveProvider validation, a loopback-only simulated endpoint and a configured `test:` reference. Refresh does not start the worker or contact a network; subprocess work and periodic refresh are off the UI thread. Closing the dashboard leaves M05 running.

The visible Windows demo uses a temporary two-project registry, an unrelated legacy project, a local M01 folder fixture, the M05 local metadata fixture, and two deterministic loopback simulated APOs. The Tk tests and visible demo together qualify invalid root/child/endpoint/duplicate/corrupt fixture rejection without registry mutation; enable/disable persistence; no implicit worker start; UI close and fresh-process reattachment to the same worker (without retaining its PID in evidence), including Start returning existing-worker status; stable repeat-observation dedupe; A continuing after B is disabled; B's exact pending event retained and not dispatched again; clean UI stop and durable state; and visible fail-closed behavior for corrupt ledger data. Full sanitized results and failed-attempt history are in ignored `.agent-work/milestones/ARM.M02.1A.WINDOWS.DASHBOARD/evidence/`.

Final validation on Windows 10/11 environment (Python 3.14.4, Tk 8.6, `win32` window system):
- `python -m unittest tests.test_arm_v2_dashboard -v` — 5 run, 5 passed, 0 failed/errors/skipped.
- `python -m unittest discover -s tests -v` — 171 run, 171 passed, 0 failed/errors/skipped.
- `python -m py_compile arm_v2_dashboard.py project_registry.py tests/test_arm_v2_dashboard.py tests/arm_v2_dashboard_cli_demo.py` — passed.
- `python tests/project_config_cli_demo.py`, `python tests/drive_change_cli_demo.py`, `python tests/notification_cli_demo.py`, `python tests/foreground_cycle_cli_demo.py`, `python tests/arm_v2_userhost_process_demo.py`, and `python tests/arm_v2_dashboard_cli_demo.py` — all exited 0. The dashboard demo opened visible Tk windows in the current Windows session and used actual widget callbacks plus the accepted detached worker; it did not use a headless mock dashboard.
- `git diff --check` — passed.

Two initial dashboard-test attempts recorded fixture-only issues and were corrected. The first visible demo exposed the missing periodic UI refresh; after adding a one-second asynchronous, non-spawning refresh, the final visible demo passed. Details are preserved in the ignored evidence folder and append-only test ledger.

This qualifies the current Windows Tk implementation and M05 fixture process only. It does not qualify live Drive/OAuth/DPAPI, real Orchestrator, production secret resolution, installer, autostart, Windows service, pause/resume, removal, or full M02/Release 1. No D26 authorization to commit or push was included.

## ARM.M02.1B Global and Per-Project Pause/Resume (2026-10-22) — offline candidate

- Baseline `f9eef9d655eae98b4f1f2552cc269ac2e51c3bae`; isolated branch `arm-v2-m02b-runtime-pause-resume-offline-1a`.
- `arm_pause_state.py` persists config-bound, versioned pause controls atomically. The detached worker acknowledges each request only at a safe monitor boundary. Global pause keeps the worker/heartbeat alive without cycles, provider listings, or sends. Project pause filters scan and dispatch for that project while peers continue. Resume preserves detector baselines and notification IDs; Stop/restart preserves pause state. Project enablement remains independent.
- Dashboard adds Pause All/Resume All and Pause Selected/Resume Selected, separate Enabled and Paused presentation, truthful pending-vs-applied notices, and preserves selection/detail through refresh. The test exercises three real refresh cycles.
- Windows Tk/worker qualification uses local fixtures and two loopback mock receivers only. Focused pause/monitor/host/dashboard tests: 24/24. Full discovery: 179/179. All six inherited offline CLI demonstrations and the new pause/resume demonstration exited 0. The new demo proved peer progress during project pause, global scan/send freeze with heartbeat, paused restart, same event ID retry/ACK, disabled project remaining disabled on resume, fail-closed corruption/invalid controls, and cleanup. A focused real-Tk test verifies that refreshed worker status replaces the timeout-pending notice when the exact request is later acknowledged. See ignored evidence path below.
- Validation: `python -m py_compile arm_pause_state.py arm_foreground.py arm_notification.py arm_v2_userhost.py arm_v2_dashboard.py tests/mock_apo.py tests/test_arm_pause_state.py tests/test_arm_foreground.py tests/test_arm_v2_userhost.py tests/test_arm_v2_dashboard.py tests/arm_v2_pause_resume_cli_demo.py` passed; `git diff --check` passed.
- Initial timeout regression invocation exposed a missing `time` import in the test; the import was corrected, and the exact CLI timeout/same-request eventual-apply test then passed. An earlier visible demo had test-harness timing/control invocation issues; waits were bounded to the UI worker state and the repeated final visible demo passed. No implementation redesign was needed for those harness corrections.
- Evidence logs/report are in ignored `.agent-work/milestones/ARM.M02.1B.RUNTIME.PAUSE.RESUME/evidence/`.
- Human D26 authorized exactly one commit and one ordinary non-force push to this development branch. The implementation was published on the authorized branch after requalification; no merge, tag, or release occurred. No live Drive/OAuth/DPAPI/real APO, Scheduler/service/startup, public endpoint, or project-Orchestrator workflow authority was exercised or added. Historical support STOP remains TRIGGERED/count UNCERTAIN and checkpoint OVERDUE.


## ARM.M02.1C Windows project management ? offline candidate (2026-10-22)

- Focused: `python -m unittest tests.test_arm_v2_dashboard -v` ? 10 run, 10 passed, 0 failures/errors/skips.
- Full: `python -m unittest discover -s tests -v` ? 182 run, 182 passed, 0 failures/errors/skips.
- Visible qualification: `python tests/arm_v2_dashboard_cli_demo.py` ? exit 0, `PASS_VISIBLE_WINDOWS_DASHBOARD_OFFLINE`; actual Tk controls/dialogs and local fixture worker used. The result proved safe display-name edit, confirmed unused project removal, refusal while the shared worker was running, refusal with M03/M04 history after stop, unchanged project identities, preserved unrelated legacy project, peer progress and pending-event isolation, and unchanged Pause/Resume semantics.
- Seven inherited demonstrations: project configuration, Drive detection, notification/ACK, foreground cycle, detached UserHost process, dashboard, and pause/resume; all run outcomes are recorded in `.agent-work/milestones/ARM.M02.1C-WINDOWS-PROJECT-MANAGEMENT/evidence/demo-summary.json`.
- `python -m py_compile arm_v2_dashboard.py project_registry.py tests/test_arm_v2_dashboard.py tests/arm_v2_dashboard_cli_demo.py` and `git diff --check` passed.
- Validation was local/offline with loopback simulated APOs and test-only secret references. No live provider credentials/session, Google Drive, external endpoint, real APO, Scheduler/Service, or Orchestrator workflow execution.
- The updated instruction records Human D26 authorization for one ordinary commit and non-force push of the exact nine-path candidate after fresh requalification. This does not authorize a main merge, tag, release, or live operation.

## ARM.M06.S1 simulated end-to-end acceptance � offline candidate (2026-10-22)

The isolated branch `arm-v2-m06s1-simulated-e2e-offline-1a` starts at M02.1C baseline `da2286649d15a376df58200094936fb2d45fd687`. This candidate qualifies the existing Drive-fixture ? ARM ? simulated Orchestrator chain through the real Windows Tk dashboard and detached M05 worker. The only changed test/demo code extends `tests/arm_v2_dashboard_cli_demo.py` to observe prompt and report arrivals for both configured projects; no product runtime source changed.

The visible Windows demo verified four arrivals (A prompt/report, B prompt/report), per-project signed requests and matching signed ACKs, pending persistence after an accepted-timeout response, dashboard reattachment to the same worker PID, duplicate-start refusal, project disable isolation while the other project continued, corrupt-ledger fail-closed behavior, and clean worker shutdown. B's pending event ID was `m03-3d8fe0cfc7f434d9b069fa2209ba458c253350801a52b57979a3104bbf251dc8`. The inherited detached-worker and Pause/Resume demonstrations verified fresh-process retry of the same pending event ID and ACK on retry.

Validation: full suite `python -m unittest discover -s tests -v` � 182/182 passed; `python -m py_compile tests/arm_v2_dashboard_cli_demo.py` � passed; seven inherited/offline demonstrations exited 0 (project config, Drive change, notification/ACK, foreground cycle, detached UserHost, visible dashboard, visible Pause/Resume); `git diff --check` � passed. Outputs and sanitized failed-attempt records are in ignored `.agent-work/milestones/ARM.M06.S1-SIMULATED-E2E-OFFLINE/evidence/20261022/`.

No live Drive, OAuth/DPAPI credential session, real APO, public endpoint, Scheduler/Service/startup action, or Windows system modification occurred. At the original candidate checkpoint, no D26 publication authority had yet been established; the final recovery and publication disposition follow below. Stage 2 requires a separate instruction and Human authorization. Follow-up obligations before Release 1 include per-project failed-delivery counts, D27's 90-day ACK retention policy, adding a project after history exists, and disabled-looking Edit/Remove controls under invalid state. Historical support STOP remains TRIGGERED/count UNCERTAIN and the checkpoint remains OVERDUE. See `docs/ARM_M06_STAGE1.md` and `docs/VALIDATION.md`.

## ARM.M06.S1 RECOVERY3 final qualification � 2026-10-24

The final authorized recovery run used the unchanged visible-dashboard test contract. One focused real Windows Tk run passed, with 37 successful actual heartbeat reads from the prior failing line 782 (each present, 1,059 bytes, valid JSON and required schema keys); the existing 15-second wait returned after 3.308 seconds. This does not recover the removed heartbeat from RECOVERY2, so its generic line-782 error cause remains unknown.

The one full offline batch passed `python -m unittest discover -s tests -v` (182/182), all seven demos (including actual visible dashboard and Pause/Resume), and `python -m py_compile tests/arm_v2_dashboard_cli_demo.py`. The batch runner mistakenly attempted `python git diff --check`; the direct required `git diff --check` was executed once and passed. Six-path audit, credential isolation, loopback-only test scope and worker cleanup passed. No runtime or test source was modified during RECOVERY3. Detailed output is under ignored `.../evidence/20261024/recovery3-run01-20261024/`.
