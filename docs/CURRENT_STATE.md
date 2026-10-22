# Current State

Project: `artifact-relay-manager`

Status: `RELAY.PROJECT.SUPERVISOR.1A` is implemented on `main` (source/tests commit `fbee2f5bd97a7b5f252cccc6a81800c17ecbbd60`).

`RELAY.PROJECT.REGISTRY.1A` adds a local schemaVersion 1 JSON registry at `%LOCALAPPDATA%\ArtifactRelayManager\projects.json` by default. Entries reference existing per-project Drive config and Relay state paths rather than duplicating configuration. Writes use a same-directory temporary file, flush/fsync, and atomic replace. Validation rejects project ID, canonical config/state path, configured workspace, and Drive folder collisions. `relay_projects.py` provides list/add/show/enable/disable/remove/validate operations. Registry operations validate local configuration and have no Drive, Watcher, OAuth/browser, or protected-session side effects.

`RELAY.PROJECT.SUPERVISOR.1A` adds a foreground sequential supervisor. It reloads and validates the registry at each cycle boundary, runs enabled entries in deterministic projectId order, and executes one existing Drive monitor cycle for each. One lazily created noninteractive `DriveAuthSession` is shared across projects and cycles. Project-local provider/identity/Watcher/state failures do not stop later projects; a shared auth failure marks remaining projects auth-degraded for that cycle. Registry changes take effect on the next cycle. The CLI is `python relay_supervisor.py [--registry <path>] run --interval-seconds 30 [--max-cycles N]`.

Supervisor source/tests commit: `fbee2f5bd97a7b5f252cccc6a81800c17ecbbd60`. Final deterministic validation passed: 97/97 tests, changed Python compile checks, both existing CLI demos, the dedicated two-project supervisor qualification, and `git diff --check`. Live one-project supervisor qualification passed on 2026-10-08 with the existing protected session, no browser, and no Drive mutation. Two cycles returned OK: cycle 1 delivered the designated current file once; cycle 2 deduplicated it. The file was version `3`, 26 bytes, SHA-256 `839ffb1cf48ad91270f4a395847100e412501c823a63270162a56306b1cc8ecf`. One acknowledged state event and one mock Watcher receipt shared event ID `relay-02471a4ffcf9a90b6ee27824533420ebda3c7f3a93d13b1e88c6525438a76ae9`. The existing protected session remained usable after qualification. Sanitized evidence is in ignored `.agent-work/milestones/RELAY.PROJECT.SUPERVISOR.1A/evidence/live-supervisor-qualification.json`.

Registry source/tests commit: `6848633a69aba57b5b8f86596c5ccecce6d3c664`. Final deterministic validation passed: 82/82 tests; changed Python compile checks; both existing CLI demos; and `git diff --check`. The six-command local CLI qualification passed without Drive, Watcher, OAuth/browser, or protected-session access.

## ARM.M01 two-folder configuration branch

The dedicated `arm-v2-m01-two-folder-config-1a` branch extends the local registry with a schemaVersion 2 envelope that preserves legacy v1 operational entries in `projects` and stores v2 folder configuration records separately in `folderProjects`. This keeps the existing supervisor input limited to its legacy operational records; M01 does not add monitoring or delivery. Configuration stores project metadata, an existing canonical Drive root URL/ID, verified direct child IDs/URLs for `Architect_Prompts` and `Executor_Reports`, one Orchestrator endpoint, an optional secret-reference identifier, enablement metadata and revision. Provider validation is offline-only through a local deterministic fake. Legacy v1 registry files load without being rewritten and are upgraded only on a later explicit registry write. See the M01 record in `docs/VALIDATION.md` and ignored evidence under `.agent-work/milestones/ARM.M01.TWO_FOLDER_CONFIG.1A/evidence/`.

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
- no persistent Windows Service or Task Scheduler deployment is configured. The per-user UserHost launcher is Architect-accepted; its live manual Task Scheduler qualification proved task-context protected-session Drive reads, one local mock Watcher acknowledgement, and next-cycle deduplication. A separate disabled LogonTrigger definition qualification passed: the temporary task was never enabled or run and was removed. Actual sign-in trigger activation, sign-out behavior, and Scheduler crash/restart recovery remain unqualified;
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

`RELAY.WINDOWS.USERHOST.AUTOSTART.1A` definition qualification passed on 2026-10-10 (`PASS_DISABLED_LOGON_DEFINITION_QUALIFICATION`). One temporary current-user `InteractiveToken`/Limited LogonTrigger task was inspected through COM and `schtasks`, remained disabled and was never run, then was removed with absence confirmed through both interfaces. No persistent task remains. Actual sign-in trigger activation is explicitly **NOT QUALIFIED**; a human-approved lifecycle test plan is recorded in `docs/VALIDATION.md`.

## ARM.M03 Two-folder Drive change detection (offline candidate)

Branch `arm-v2-m03-dualfolder-detection-1a` is based on accepted M01 commit `158af8bcf42ce2e6edec2816de09259e438f9322`. The bounded detector reuses the schemaVersion 2 `folderProjects` bindings and reads only complete direct-child metadata for each project's `Architect_Prompts` and `Executor_Reports` folders. It establishes a first-scan baseline, records checksum-proven binary content changes, and accepts creation events only when the provider seam explicitly proves `CREATED_IN_FOLDER`. Folder listings without that proof classify a first-seen or moved-in item as ambiguous. Metadata-only version/rename changes, removal, nested items, and repeated observations do not create definite events. Detector state is local JSON written through a same-directory atomic replace and is validated against current project/folder identities on reload. Event records contain metadata only.

Historical M03.R1 outcome: the then-current list-only Drive adapter could not prove creation versus move-in, so it emitted no new-file event. The Human-authorized M03.R2 D11 amendment supersedes that detection policy: stable observation of a newly appearing direct child, including a moved-in file, now qualifies for an `ARRIVED` event. This is an offline metadata heuristic and does not claim provider-side creation provenance or content stability. The accepted adapter requests listing metadata only; the detector does not read media bodies. No live Drive or OAuth qualification occurred.

## ARM.M04 simulated Orchestrator notification and ACK (offline candidate)

Implementation is limited to `arm_notification.py`: it reuses the schemaVersion 2 `folderProjects` registry and validated, immutable M03 detector events. For each enabled project it persists metadata-only notification intent to an atomic local JSON ledger before sending to that project's single configured endpoint. Request and receipt authentication use an injected in-memory secret-reference resolver. A receipt is accepted only when its projectId/eventId match and its HMAC verifies; the persisted receipt is bound to the configured destination and revalidated after restart. Pending attempts are bounded per run and use capped exponential retry deadlines. ACKed metadata is retained indefinitely, exceeding the 90-day minimum and preserving source-event deduplication.

The offline demo uses two M01-configured projects and persisted M03 detector events: project A `PROMPT_CHANGED` and project B `REPORT_CHANGED`. Deterministic loopback simulated receivers durably dedupe eventId, including an accept-then-timeout case. Fresh sender processes prove ACK, same-ID restart retry, and repeat dedupe. No live Drive, real Orchestrator/APO, CDB, OAuth/DPAPI, or public network activity occurred. See the M04 record in `docs/VALIDATION.md` and `docs/TEST_EVIDENCE_LEDGER.md`, plus ignored `.agent-work/milestones/ARM.M04.SIMULATED_APO_ACK.1A/evidence/`.

This offline slice does not qualify live endpoint deployment, secret distribution/rotation, real APO behavior, transport scheduling, or the unresolved M03 live new-file creation proof. It adds no Orchestrator workflow or acceptance authority.

## ARM.M03.R2 — Human-approved D11 inbox arrival detection (offline candidate)

Human-approved D11 now treats a file newly arriving as a direct child after the silent first-scan baseline as eligible whether uploaded/created there or moved in. The detector requires two successive complete scans with an unchanged usable metadata fingerprint before persisting an `ARRIVED` event. Existing rename-only, metadata-only version changes and deletion do not notify; nested items are excluded. An observed departure cancels an unqualified candidate; confirmed departure followed by stable re-entry creates a new deterministic occurrence ID. Existing M03 `CREATED`/`CONTENT_UPDATED` event IDs and M04 notification payload/ACK behavior remain compatible through detector state migration. The historical M03.R1 finding remains accurate under the earlier strict-origin rule; the Human-approved D11 policy removes the need to infer historical creation origin.

Offline validation on `arm-v2-m03r2-inbox-arrival-offline-1a` from M04 baseline `5ba294d5fb93151f8a6a60b92088f5091df122c5`: focused M01/M03/M04 tests 64/64 passed; full discovery 154/154 passed; changed-file `py_compile` and `git diff --check` passed. `tests/drive_change_cli_demo.py` passed nine fresh detector CLI invocations across two projects, proving silent baseline, stable prompt/report arrivals, content update, repeat/restart dedupe and a distinct departure/re-entry event ID. `tests/notification_cli_demo.py` passed with two loopback simulated APOs; both `ARRIVED` events were acknowledged, one accepted-timeout retry reused the same event ID, and final duplicate dispatch made no additional requests. No live Drive, OAuth session, real APO, Desktop Bridge, or external network was used.

This is an offline metadata-readiness heuristic, not proof that a Drive upload is complete. Actual Drive arrival timing, provider listing behavior, and native Workspace content updates remain unqualified. Historical governance support STOP remains `TRIGGERED` with exact count `UNCERTAIN`; no later milestone is authorized by this entry.

## ARM.M03.R3 foreground monitoring integration (offline-qualified and published)

Baseline: `arm-v2-m03r2-inbox-arrival-offline-1a` at `9a5990226ffb8d6c05d232bfb4d01e5fdbe3f484`; published branch `arm-v2-m03r3-foreground-cycle-1a` at `3a7605e99bf75093234fbbc074910ea6b958ecec`. `arm_foreground.py` adds a bounded foreground cycle runner that composes M01 `folderProjects`, M03.R2 stable detector events and M04 durable notification/ACK handling through the existing provider and secret-resolver seams. It polls only enabled projects, waits 10 seconds by default, applies bounded exponential delay after provider failures, and limits a project to one delivery attempt per cycle for fairness. It supports injected clock/sleeper for deterministic operation and returns sanitized per-cycle project/event/delivery status.

`DriveChangeDetector.scan(project_ids=...)` is an opt-in enabled-project filter; legacy callers retain the original all-project behavior. Selected-project scans leave other project state unchanged. Existing M03 atomicity remains the failure boundary: if one enabled folder listing fails, the whole enabled scan batch is marked `DEGRADED_ATOMIC_SCAN` and detector state is unchanged; already persisted notification work may still be safely dispatched. Disabled projects are not queried or dispatched, and their pending entries remain durable for later enablement. The M04 sender has a compatible optional per-project dispatch cap; default behavior remains unchanged.

Offline integrated evidence: the bounded five-cycle demo produced a silent first baseline, one checksum-proven A content update, one stable A prompt arrival and one stable moved-in B report arrival; both project-specific mock endpoints received matching signed ACKs. B accepted its report and dropped the response; a fresh monitor instance retried the same event ID, and B processed it once. An incomplete B listing left detector bytes unchanged, marked the shared scan degraded, and generated no duplicate request. No live Drive/OAuth/APO/DPAPI, external endpoint, or Desktop Bridge activity occurred. Full regressions: 162/162 pass. See R3 records in `docs/VALIDATION.md`, `docs/TEST_EVIDENCE_LEDGER.md`, and ignored `.agent-work/milestones/ARM.M03.R3.FOREGROUND_CYCLE.1A/evidence/`.

This is offline synthetic integration only. The monitor accepts an injected read-only provider and secret resolver; this milestone does not wire or enable a live OAuth/Drive runner or production secret storage. Human D26 authorization was subsequently recorded in the updated M03.R3 instruction; the implementation was published on `arm-v2-m03r3-foreground-cycle-1a` at `3a7605e99bf75093234fbbc074910ea6b958ecec`.

## ARM.M05 Windows manual background host (offline candidate)

Baseline: published R3 `3a7605e99bf75093234fbbc074910ea6b958ecec`; work branch `arm-v2-m05-userhost-lifecycle-offline-1a`. `arm_v2_userhost.py` provides a manually invoked `start`, `status`, and `stop` controller for a detached per-user worker. The worker repeatedly calls the accepted `ForegroundMonitor.cycle()` and discards prior cycle records, uses the existing OS-released byte-lock primitive without changing v1 UserHost, and records sanitized bounded heartbeat/log data. Stop is config/state-bound, verifies the worker's current-user SID and process creation identity, requests a safe cycle/sleep-boundary exit, and confirms process exit. Stale lock files do not grant process ownership.

M05 qualification is Windows-only but fixture-only: it accepts current-user local metadata fixtures, `test:` secret references, and loopback simulated Orchestrator endpoints. It strips OAuth environment inputs and blocks non-loopback socket destinations. No service, scheduled startup, registry/firewall change, elevation, live Drive/OAuth, real APO, or production secret integration is included. Human D26 authorization now permits one commit and ordinary push to the M05 development branch after refreshed validation. See `docs/ARM_V2_USERHOST.md` and M05 qualification in `docs/VALIDATION.md`.

## ARM.M02.1A Windows dashboard — local offline candidate (2026-10-22)

Source baseline `7f51720f9b81ba99a3fc494d050249d8d680d4a0`; isolated branch `arm-v2-m02a-windows-dashboard-offline-1a`. This incremental CORE M02 slice adds a native Tk/ttk management window for v2 `folderProjects`, local FakeDriveProvider validation, validated atomic v2 enable/disable, metadata-only event/receipt history, M04 pending/ACK counts, and asynchronous Start/Status/Stop delegation to the accepted M05 fixture host. Closing the window leaves the worker alive; a fresh GUI process reattaches through the existing M05 state identity. The dashboard is prominently fixture/offline-only and has no Pause/Resume or removal control. See `docs/ARM_V2_DASHBOARD.md` for behavior and the reviewed pause proposal.

The visible Windows qualification used temporary projects A/B, one unrelated legacy M01 project, two loopback simulated APOs, and no Drive/OAuth/DPAPI/real Orchestrator. It proved same-PID reattachment without a duplicate worker, no repeat delivery for an ACKed observation, disabled B remains unpolled while its same pending event remains durable and A continues, graceful stop and durable ledgers, and fail-closed corrupt-ledger display. Sanitized output and test totals are in ignored `.agent-work/milestones/ARM.M02.1A.WINDOWS.DASHBOARD/evidence/`.

This is a local qualification candidate only. No D26 branch publication authorization was present; no commit/push, merge, tag, or release was performed. Full M02/Release 1, live provider/endpoint interoperability, and reviewed pause/resume remain incomplete. Historical support STOP remains TRIGGERED/count UNCERTAIN and the prior checkpoint remains OVERDUE.

## ARM.M02.1B Global and Per-Project Pause/Resume — offline candidate (2026-10-22)

Baseline `f9eef9d655eae98b4f1f2552cc269ac2e51c3bae`; isolated branch `arm-v2-m02b-runtime-pause-resume-offline-1a`. The candidate adds durable worker-acknowledged global/per-project pause controls and dashboard selection-refresh preservation, reusing the accepted M02.1A dashboard and M05 detached fixture host. It preserves notification/detector state, distinguishes pause from registry disablement, and fails closed on corrupt or mismatched pause state. Windows Tk, detached process, and loopback-only simulated APO qualification is recorded in `docs/VALIDATION.md`, `docs/TEST_EVIDENCE_LEDGER.md`, and ignored `.agent-work/milestones/ARM.M02.1B.RUNTIME.PAUSE.RESUME/evidence/`.

This offline implementation is qualified on its isolated branch and remains pending independent Architect acceptance. Human D26 authorizes exactly one commit and one ordinary non-force push to this named development branch; no main merge, tag, release, or later milestone is authorized. No live Drive/OAuth/DPAPI/APO, Scheduler, service, startup, or Orchestrator workflow authority was introduced. Historical support STOP remains TRIGGERED/count UNCERTAIN and the checkpoint remains OVERDUE.


## ARM.M02.1C Windows project management ? offline qualification candidate (2026-10-22)

Baseline `d1fe9b1a2629d8c63308a556441aec6130ea00b4`; isolated local branch `arm-v2-m02c-project-management-offline-1a`. The Windows dashboard now provides display-name-only editing, guarded v2 project removal, and truthful per-project Start/Stop eligibility controls distinct from the shared monitor and existing Pause/Resume controls. Dashboard registry mutations serialize through an OS-held per-registry lock; stale display-name edits fail closed. Removal requires a stopped shared worker and no project detector snapshots/candidates/events, notification entries, pause references, or pending control; it removes only the v2 registry row and never deletes referenced files. Historical v1 registry entries and transport identities/state remain preserved.

Qualification used real interactive Windows Tk widgets, local metadata fixtures, and loopback simulated APOs. Focused tests: 10/10; full discovery: 182/182. The visible M02.1C demo passed display-name edit with unchanged identity fields, confirmed unused-C removal, running-worker and history-bearing removal refusal, legacy-project preservation, worker reattachment, A/B isolation, and existing Pause/Resume behavior. Evidence is under ignored `.agent-work/milestones/ARM.M02.1C-WINDOWS-PROJECT-MANAGEMENT/evidence/`. Offline-only: no live Drive/OAuth/DPAPI/real APO or external endpoints. The updated instruction subsequently records D26 authorization for one ordinary commit and non-force push to this named branch after fresh requalification. No main merge, tag, or release is authorized; independent Architect review remains pending. Historical support STOP remains TRIGGERED/count UNCERTAIN and checkpoint remains OVERDUE.
