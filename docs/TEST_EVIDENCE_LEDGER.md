# Test Evidence Ledger

Append-only milestone verification records. Detailed sanitized outputs remain in ignored `.agent-work/` evidence.

## ARM.M01 — Two-Folder Project Configuration — 2026-10-21

- Baseline: `6280c5b5e7c26393924f365a00bd95764b364722`; branch: `arm-v2-m01-two-folder-config-1a`.
- `python -m unittest tests.test_project_registry tests.test_project_folder_config -v` — 30 passed, 0 failed.
- `python -m unittest discover -s tests -v` — 120 passed, 0 failed.
- Changed-file `py_compile` command — passed.
- `python tests/project_config_cli_demo.py` — passed for two separate projects, canonical folders, one endpoint per project, provider validation, and fresh-process reload.
- `git diff --check` — passed.
- Provider and endpoint checks used only deterministic local fixtures. Google Drive, OAuth/DPAPI, remote endpoint, Watcher, Scheduler, Service and UserHost activity: none.
- Evidence: `.agent-work/milestones/ARM.M01.TWO_FOLDER_CONFIG.1A/evidence/` (ignored, sanitized).

## ARM.M03 — Two-folder Drive change detection (offline) — 2026-10-21

- Baseline: `arm-v2-m01-two-folder-config-1a` at `158af8bcf42ce2e6edec2816de09259e438f9322`; branch: `arm-v2-m03-dualfolder-detection-1a`.
- `python -m unittest tests.test_drive_change_detector tests.test_project_registry tests.test_project_folder_config -v` — 41 passed, 0 failed.
- `python -m unittest discover -s tests -v` — 131 passed, 0 failed.
- `python -m py_compile drive_change_detector.py drive_adapter.py tests/test_drive_change_detector.py tests/drive_change_cli_demo.py` — passed.
- `python tests/drive_change_cli_demo.py` — passed: two-project baseline, direct-child creation and checksum-proven content update, duplicate poll, metadata-only rename/version increment, move/delete with nested child excluded, and fresh-process reload. Three events persisted with stable IDs; repeat/restart emitted zero new events.
- `git diff --check` — passed.
- Negative coverage: provider failure, incomplete listing, unproven move-in, missing/native checksum, corrupted/cross-project state, failed state write/atomic replace, duplicate observation, and no-network fixture guard.
- The M03 detector/demo used local metadata fixtures and made no Google Drive/OAuth/protected-session, APO, or Watcher calls; network guard was enabled. The inherited suite did run deterministic loopback mock Watcher regressions and the Windows DPAPI primitive test with disposable text; no external endpoint, credential, or stored session was accessed. Scheduler, Service, UserHost, Desktop Bridge, and file-body access: none.
- Production list-only adapter limitation: new versus moved-in cannot be proven and stays ambiguous; native Workspace/missing-checksum content changes remain unqualified. No live qualification or M04 work.
- Evidence: `.agent-work/milestones/ARM.M03.TWO_FOLDER_DRIVE_CHANGE_DETECTION.1A/evidence/` (ignored, sanitized).

## ARM.M04 — Offline Orchestrator notification and ACK — 2026-10-21

- Source baseline: `arm-v2-m03-dualfolder-detection-1a` at `7e9fe693492b7ff71cd10bed81bba52045585bd6`; implementation branch: `arm-v2-m04-apo-ack-offline-1a`.
- Focused/affected/full validation commands, exact attempted/pass/fail/skip totals, compile result, demo output summary, and final commit SHA are recorded in the ignored `.agent-work/milestones/ARM.M04.SIMULATED_APO_ACK.1A/evidence/qualification.json`.
- The two-project local demo covers one `PROMPT_CHANGED` and one `REPORT_CHANGED`, matching authenticated receipts, durable pending state after receiver-accepted timeout, fresh-process retry with the identical M03 event ID, and dedupe after ACK. Receiver processing is unique per eventId; a repeated invocation sends no duplicate request.
- Negative tests cover project/destination binding, disabled projects, wrong/missing ACK, bad ACK authentication, unauthorized response, 503, redirect blocking, timeout ambiguity, corrupt/tampered state, initial and ACK atomic-write failures, bounded exponential backoff, and content/secret/path non-disclosure.
- Network activity is confined to two deterministic loopback receivers; no Google Drive/OAuth/DPAPI, public network, real Orchestrator/APO, CDB, Scheduler/Service/UserHost, or workflow authority was exercised.
- ACKed metadata is retained indefinitely in local JSON, exceeding the 90-day minimum and preserving dedupe against M03 source events. Real endpoint interoperability and production secret distribution remain unqualified.
- `python -m unittest tests.test_arm_notification -v` — 16 run, 16 passed, 0 failed, 0 skipped.
- `python -m unittest tests.test_project_registry tests.test_project_folder_config tests.test_drive_change_detector tests.test_arm_notification -v` — 57 run, 57 passed, 0 failed, 0 skipped.
- `python -m unittest discover -s tests -v` — 147 run, 147 passed, 0 failed, 0 skipped.
- `python -m py_compile arm_notification.py tests/test_arm_notification.py tests/mock_apo.py tests/notification_cli_demo.py` — passed; `git diff --check` — passed.
- `python tests/notification_cli_demo.py` — passed. Project A event `m03-4055e12a2291fefd6beae0020c7df6c7b90ba39d6cc859fe39743f6846002534` was `PROMPT_CHANGED`; project B event `m03-52ce89c1deb0a8a45aa26118f9dee3b9700e7d21cfbe863d44ec2341aa8c94ff` was `REPORT_CHANGED`. Invocation 1 delivered A and left B pending after receiver acceptance plus response timeout (`pending=1`, `acked=1`). Fresh invocation retried B with the identical event ID and got the receipt (`attemptCount=2`, receiver processed B once). Final invocation reported `pending=0`, `acked=2`, `deduplicated=2` and caused zero additional receiver requests.
- `arm_notification.py` request/receipt traffic was limited to these deterministic loopback receivers. No live Google Drive, external network, OAuth credential, stored DPAPI session, real APO/Orchestrator, CDB, Scheduler/Service/UserHost, or workflow decision was exercised. The inherited full suite's disposable DPAPI primitive and mocked auth tests are regression tests only.
- Final local commit SHA is included in the ignored qualification report; no merge, tag, or live deployment occurred.

## ARM.M03.R2 — Human-authorized D11 inbox arrival detection — 2026-10-21

- Baseline: `arm-v2-m04-apo-ack-offline-1a` at `5ba294d5fb93151f8a6a60b92088f5091df122c5`; candidate branch: `arm-v2-m03r2-inbox-arrival-offline-1a`.
- Human-approved D11 supersedes strict creation-origin detection: after silent first baseline, new direct-child membership qualifies whether created/uploaded there or moved in, after two successive complete scans with the same usable metadata fingerprint. No claim that the heuristic proves upload completion.
- Focused M01/M03/M04 command: 64 run, 64 passed, 0 failed, 0 errors, 0 skipped. Full offline discovery: 154 run, 154 passed, 0 failed, 0 errors, 0 skipped.
- Changed-file `py_compile` passed for detector, detector tests/demo, M04 integration test, and notification demo. `git diff --check` passed.
- `python tests/drive_change_cli_demo.py` passed in 9 fresh detector processes: silent two-project baseline; one eligible checksum-proven content update; candidate then stable `ARRIVED` events for A `PROMPT_CHANGED` and B `REPORT_CHANGED`; repeat/restart dedupe; metadata-only rename/version suppression; observed departure/re-entry with distinct event ID. The full event IDs and run trace are in ignored `.agent-work/milestones/ARM.M03.R2.D11_INBOX_ARRIVAL.1A/evidence/`.
- `python tests/notification_cli_demo.py` passed: two `ARRIVED` events reached project-specific loopback simulated APO receivers and received matching ACKs. One receiver accepted then timed out; fresh-process retry used the same event ID and was uniquely processed. Final duplicate dispatch made no requests.
- Added focused tests for moved-in classification, stability reset, binary missing checksum with size, native stable arrival, unusable fingerprint fail-closed, departure/re-entry occurrence identity, v1 state migration preserving legacy event IDs, project/folder identity overlap, atomic write failure, and M04 ARRIVED ACK compatibility.
- No live Google Drive/API request, OAuth change or stored session access, real APO, Desktop Bridge, public network, Scheduler/Service/UserHost, or Orchestrator decision authority. Local fixture providers and loopback simulated receivers only. Inherited full-suite auth mocks and DPAPI primitive test used disposable test material only.
- Limitations: live Drive listing behavior/timing, upload completion semantics, and native Workspace content updates are not qualified. Historical M03.R1 strict-origin evidence is preserved; the Human-approved D11 change removes origin as a requirement.
- Evidence: ignored `.agent-work/milestones/ARM.M03.R2.D11_INBOX_ARRIVAL.1A/evidence/`.

## ARM.M03.R3 ? Integrated foreground polling to simulated APO ? 2026-10-21

- Baseline: `arm-v2-m03r2-inbox-arrival-offline-1a` at `9a5990226ffb8d6c05d232bfb4d01e5fdbe3f484`; local proposed branch `arm-v2-m03r3-foreground-cycle-1a`.
- Focused M01/M03.R2/M04/R3 suite: 72 run, 72 passed, 0 failed, 0 errors, 0 skipped. Full discovery: 162 run, 162 passed, 0 failed, 0 errors, 0 skipped.
- Changed-source/test/demo `py_compile` passed. Existing M03 detector CLI and M04 notification CLI demos passed. New `python tests/foreground_cycle_cli_demo.py` passed with loopback-only network guard. `git diff --check` passed.
- Integrated cycles: baseline emitted 0 events and 0 requests; the A prompt checksum edit emitted `CONTENT_UPDATED` and was ACKed; after stable scans A prompt arrival emitted `ARRIVED/PROMPT_CHANGED` event `m03-ccdf09b56f60af21d3b10b621cbfe2980b8ac07cbe35731be1198bfc8987af9e`; B moved-in report emitted `ARRIVED/REPORT_CHANGED` event `m03-d20ab0b353254edc4e31ef3b960d152713bbca5f60d0d3aac0cb12f055f1f406`.
- B receiver durably accepted its event and dropped the response. A fresh monitor instance retried the identical event ID after bounded delay, received the matching signed ACK, and receiver unique processing stayed one. Final status: pending=0, ACKed=3; no extra duplicate requests.
- Incomplete B listing left detector-state bytes unchanged and marked the enabled scan batch degraded; already persisted A work safely retried. Separate tests prove disabled B is not polled, per-project delivery cap gives B progress behind multiple A events, backoff remains bounded, Ctrl+C preserves restart state, and malformed registry blocks before I/O.
- No live Google Drive/OAuth/DPAPI session, real APO, public network, Desktop Bridge, Windows background host, or workflow authority. Local fixture provider and test-only keys; two deterministic loopback APOs only.
- Atomicity limitation: existing detector scans all selected enabled projects in one transaction; one failed listing blocks new observations for the batch until a later successful scan, but does not clear state or suppress retries of already persisted events.
- No commit/push: explicit D26 publication authorization was not included; proposed branch publication gate remains. Sanitized evidence is in ignored `.agent-work/milestones/ARM.M03.R3.FOREGROUND_CYCLE.1A/evidence/`.

## ARM.M03.R3 D26 publication addendum — 2026-10-21

- The updated authoritative R3 instruction included explicit Human D26 publication authorization for the ten previously qualified files.
- Published exactly one commit: `3a7605e99bf75093234fbbc074910ea6b958ecec`; one ordinary non-force push verified remote `arm-v2-m03r3-foreground-cycle-1a` at the same SHA. Remote main remained `e722101f6f440593d90cf33b4a8103181f61828c`; no merge/tag.
- Final pre-publication validation: focused 72/72 and full 162/162; all three CLI demos, `py_compile`, staged/working `git diff --check`, exact ten-file staged list, and credential-pattern scan passed. Detailed evidence is in ignored `.agent-work/milestones/ARM.M03.R3.FOREGROUND_CYCLE.1A/evidence/`.

## ARM.M05 Windows manual background host — offline candidate — 2026-10-22

- Baseline: published R3 `3a7605e99bf75093234fbbc074910ea6b958ecec`; branch `arm-v2-m05-userhost-lifecycle-offline-1a`. The candidate remains uncommitted and unpushed because the M05 instruction labels D26 publication as not approved.
- Focused M01/M03.R2/M04/R3/v1 UserHost/M05 tests: 88 run, 88 passed. M05-specific tests: 3 run, 3 passed. Final full discovery: 165 run, 165 passed. An initial full attempt had one non-reproduced crash/restart start assertion; the next focused and full runs passed with no behavior change; exact initial return JSON was not captured.
- `py_compile` for M05, R3 and related tests/demos passed; `git diff --check` passed. Existing M03, M04 and R3 CLI demonstrations passed; the new M05 process demo passed on Windows.
- The M05 process demo showed STOPPED before start; one detached worker returned READY while its START controller exited; two racing starts returned `ALREADY_RUNNING`; A checksum update and A prompt/B moved-in report arrivals reached their own loopback simulated APOs with matching signed ACKs. B accepted then dropped an ACK response; after safe stop, the pending same ID `m03-d20ab0b353254edc4e31ef3b960d152713bbca5f60d0d3aac0cb12f055f1f406` remained durable, and a fresh worker retried and ACKed it (attemptCount=2; B receiver processed one unique event). Final ACKed=3/pending=0; repeat observation did not resend ACKed work.
- Additional process proof: incomplete B listing returned `DEGRADED_ATOMIC_SCAN` with byte-identical detector state; disabled B was not polled; wrong-PID metadata was rejected without writing a stop request; a bad test-key binding failed startup with no orphan; a worker-only abrupt termination was performed only after exact PID/SID/process-creation verification, released its OS lock, and a stale lock file did not prevent recovery; all test workers exited before fixture cleanup.
- Sanitized log scan found no body, test key, endpoint URL or temporary private path. The M05 process uses local fixtures, test-only HMAC keys and loopback receivers only. No live Drive/OAuth/DPAPI, real APO, public network, Windows service/Scheduler/startup, registry/firewall/elevation, or CDB activity occurred.
- Evidence: ignored `.agent-work/milestones/ARM.M05.WINDOWS.USERHOST.LIFECYCLE.1A/evidence/`; operator details: `docs/ARM_V2_USERHOST.md` and `docs/VALIDATION.md`.
- Limitations: provider and secret resolver are fixture/test-only; no production execution qualification. Historical support STOP remains `TRIGGERED`/`UNCERTAIN` and the support checkpoint remains `OVERDUE`; neither was cleared by this CORE milestone. No D26 authorization to commit or push M05 was present.

## ARM.M05 D26 publication requalification — 2026-10-22

- Human D26 authorization permits exactly one commit and ordinary non-force push to `arm-v2-m05-userhost-lifecycle-offline-1a`, limited to the eight approved paths. No merge, tag, or later milestone.
- Fresh preflight confirmed repository `nakfreeajer/artifact-relay-manager`, required baseline `3a7605e99bf75093234fbbc074910ea6b958ecec`, exact target branch, remote R3 at baseline, remote main `e722101f6f440593d90cf33b4a8103181f61828c`, and no existing remote M05 branch. The original main worktree retained its seven pre-existing unpublished paths; M01/M03.R2/R3/M04 worktrees retained their recorded HEADs and clean states.
- Refreshed focused suite: 88/88; M05-specific suite: 3/3; full discovery: 165/165. Windows process demo exit 0 with timestamped stdout/stderr and status metadata; same pending/retry event ID `m03-d20ab0b353254edc4e31ef3b960d152713bbca5f60d0d3aac0cb12f055f1f406`, attempt count 2, one receiver-side unique event, clean stop/restart and worker cleanup. All three prior CLI demos exited 0; `py_compile` and `git diff --check` passed.
- Historical failure remains disclosed: an earlier initial full run was 164/165 at the crash/restart assertion and its exact returned JSON was not captured; subsequent earlier runs passed without source change. The first requalification focused-suite shell wait yielded no completion metadata; the same command was rerun with session polling and passed 88/88. No test failure occurred in this refreshed requalification. Timestamped current captures are retained in ignored `.agent-work/milestones/ARM.M05.WINDOWS.USERHOST.LIFECYCLE.1A/evidence/`.
- No live Drive/OAuth/DPAPI/real APO/public network, service, Scheduler/startup, registry/firewall/elevation, Desktop Bridge, or workflow-authority activity occurred. Historical support STOP remains `TRIGGERED`/`UNCERTAIN`; the checkpoint remains `OVERDUE`.

## ARM.M05.R1 CLI exit-status correction — 2026-10-22

- Baseline `290460371d2f4329a4440aed8c714c1a68549075`; isolated branch `arm-v2-m05r1-cli-exit-status-offline-1a`. `_emit()` now maps success to 0, `STARTING` to 1, `ALREADY_RUNNING` to 3, and degraded/failure/invalid/timeout/unknown to 2 while preserving stdout JSON.
- Tests assert mapping directly and exact process exit codes for successful and failure CLI outcomes. The stop timeout uses a held test startup lock; invalid test-secret binding, forged heartbeat ownership, malformed configuration and duplicate start are deterministic cases.
- Four complete standalone Windows process-demo invocations passed and retained per-controller invocation JSON, sanitized stdout/stderr, timestamps, exit codes and available PID/process creation/user identity observations. Each demonstrated the same pending B event ID `m03-d20ab0b353254edc4e31ef3b960d152713bbca5f60d0d3aac0cb12f055f1f406` across restart retry, two attempts and one receiver-side unique event. All workers were cleaned up.
- First demo attempt failed in the new test fixture before crash/restart: the test acquired `SingleInstanceLock` before creating its parent control directory. The fixture now creates that directory. This was not the historical intermittent worker crash/restart failure. The earlier 164/165 failure remains unresolved because its exact CLI return JSON was not captured; three full repeat runs did not reproduce it, and no runtime cause/fix is claimed.
- Requalification: M05 suite 4/4; focused inherited suite 89/89; full suite 166/166; three inherited CLI demos exit 0; changed-module `py_compile` and `git diff --check` pass. The earlier focused capture `d26-focused-regression-20261022-014431-969.json` was verified to contain exit 0 / 88 passed; the previous sentence describing it as incomplete was a reporting mistake.
- Evidence: ignored `.agent-work/milestones/ARM.M05.R1.CLI.EXIT.STATUS.1A/evidence/`. No live Drive/OAuth/DPAPI/APO, public network, service/Scheduler/system setting, Desktop Bridge or Orchestrator workflow authority was used.

## ARM.M02.1A Windows dashboard — offline CORE candidate — 2026-10-22

- Baseline: `7f51720f9b81ba99a3fc494d050249d8d680d4a0`; isolated candidate branch: `arm-v2-m02a-windows-dashboard-offline-1a`.
- Native Tk/ttk dashboard reads the v2 folderProjects registry, validated M03 detector/M04 notification metadata and M05 host status; Start/Status/Stop use the accepted M05 CLI on background threads. `ProjectRegistry.set_folder_project_enabled` is a v2-only validated atomic writer and preserves the legacy projects array.
- Focused test history: first `python -m unittest tests.test_arm_v2_dashboard -v` attempt ran 5 with 3 passed/2 errors because the host config fixture omitted the existing registry input file. Second attempt ran 5 with 4 passed/1 failure because the assertion expected the empty registry file to be absent. Both were fixture/assertion corrections. Final focused run: 5 run, 5 passed.
- Final `python -m unittest discover -s tests -v` — 171 run, 171 passed, 0 failures/errors/skips. `python -m py_compile arm_v2_dashboard.py project_registry.py tests/test_arm_v2_dashboard.py tests/arm_v2_dashboard_cli_demo.py` passed. `git diff --check` passed.
- Final exit-0 demonstrations: `tests/project_config_cli_demo.py`, `tests/drive_change_cli_demo.py`, `tests/notification_cli_demo.py`, `tests/foreground_cycle_cli_demo.py`, `tests/arm_v2_userhost_process_demo.py`, and the visible `tests/arm_v2_dashboard_cli_demo.py`.
- First visible dashboard demo attempt failed to observe an A content event because the UI did not periodically refresh. That identified the implementation defect; a one-second non-spawning refresh was added on the Tk event loop and snapshot work remains in the background executor. The worker was gracefully stopped by demo cleanup. The corrected visible demo passed and its output is retained.
- The final visible Windows demonstration reported `PASS_VISIBLE_WINDOWS_DASHBOARD_OFFLINE`: two v2 projects plus one preserved legacy project; fresh GUI process reattached to the existing worker PID and Start returned the existing-worker status; A ACKed repeat observation did not add a request; B's event `m03-d20ab0b353254edc4e31ef3b960d152713bbca5f60d0d3aac0cb12f055f1f406` stayed pending after disabling B with zero subsequent B requests while A continued; corrupt-ledger UI was visibly fail-closed; worker stopped cleanly and state remained durable.
- All non-provider HTTP in the demonstration went only to two deterministic `127.0.0.1` simulated APO servers. The M05 worker's loopback network guard remained active. No live Drive, OAuth/DPAPI credential/session, real APO, external network, Scheduler/Service/startup/system setting, Desktop Bridge, or workflow authority was used.
- No D26 publication authorization was present. Local candidate only; no commit or push.
- Detailed sanitized outputs and summary: ignored `.agent-work/milestones/ARM.M02.1A.WINDOWS.DASHBOARD/evidence/`.

## ARM.M02.1B Global and Per-Project Pause/Resume — offline candidate — 2026-10-22

- Baseline `f9eef9d655eae98b4f1f2552cc269ac2e51c3bae`; isolated branch `arm-v2-m02b-runtime-pause-resume-offline-1a`.
- Change set: durable config-bound pause control state, worker safe-boundary acknowledgement, global and project scan/dispatch gating, state-preserving stop/restart, dashboard pause controls and selection refresh correction. No pause operation modifies project `enabled`.
- Focused command `python -m unittest tests.test_arm_pause_state tests.test_arm_foreground tests.test_arm_v2_userhost tests.test_arm_v2_dashboard -v`: 23 run, 23 passed, 0 failures/errors/skips. Full `python -m unittest discover -s tests -v`: 178 run, 178 passed, 0 failures/errors/skips.
- The real Windows CLI regression `test_pause_cli_reports_pending_timeout_then_worker_applies_same_request` proved JSON `PENDING/CONTROL_TIMEOUT` with process exit 2 while a loopback receiver delayed its response, then durable `APPLIED` for the exact same request ID once the in-flight cycle reached a boundary; clean Stop returned exit 0. Other CLI tests prove APPLIED/PAUSED success, invalid owner/project and degraded-state exit 2.
- Six inherited demonstrations exited 0: `project_config_cli_demo.py`, `drive_change_cli_demo.py`, `notification_cli_demo.py`, `foreground_cycle_cli_demo.py`, `arm_v2_userhost_process_demo.py`, and `arm_v2_dashboard_cli_demo.py`. New `arm_v2_pause_resume_cli_demo.py` exited 0 with `PASS_VISIBLE_WINDOWS_PAUSE_RESUME_OFFLINE`; selected project persisted across three refreshes; B had zero polls/sends while paused and A continued; global pause left cycle and provider/receiver state unchanged while heartbeats advanced; Stop/Start remained paused; Resume retried B's identical event ID `m03-d20ab0b353254edc4e31ef3b960d152713bbca5f60d0d3aac0cb12f055f1f406` and received ACK on attempt 2. Corrupt state, invalid owner/project, disabled-project resume, second-GUI attach, and cleanup passed.
- `python -m py_compile arm_pause_state.py arm_foreground.py arm_notification.py arm_v2_userhost.py arm_v2_dashboard.py tests/mock_apo.py tests/test_arm_pause_state.py tests/test_arm_foreground.py tests/test_arm_v2_userhost.py tests/test_arm_v2_dashboard.py tests/arm_v2_pause_resume_cli_demo.py` passed. `git diff --check` passed.
- Evidence files and sanitized report: ignored `.agent-work/milestones/ARM.M02.1B.RUNTIME.PAUSE.RESUME/evidence/`. Qualification environment was Windows with visible Tk 8.6, local metadata fixtures, test-only HMAC keys, and two loopback simulated APOs. No Google Drive/OAuth/DPAPI/real APO, public network, Scheduler/service/startup, credential changes, or Orchestrator workflow authority.
- Local candidate only: proposed branch lacks exact D26 publication authorization; do not commit or push. Historical support STOP remains TRIGGERED/count UNCERTAIN; checkpoint remains OVERDUE.

### ARM.M02.1B D26 publication requalification closure — 2026-10-22

- Updated authoritative instruction records explicit Human authorization for exactly one commit and one ordinary non-force push of the 17 listed M02.1B paths to `arm-v2-m02b-runtime-pause-resume-offline-1a`, directly parented on `f9eef9d655eae98b4f1f2552cc269ac2e51c3bae`.
- Source verification found a bounded UI reporting gap: after `PENDING/CONTROL_TIMEOUT`, the dashboard now tracks that durable request ID through refresh and updates the notice when the worker later confirms it. A new real-Tk regression covers pending then applied state. The CLI timeout test independently proves the exact persisted request ID is eventually applied after the in-flight operation.
- Requalification: focused suite 24/24; full discovery 179/179; all six inherited demos and the visible Windows pause/resume demo exited 0; py_compile and diff checks passed. Pending B event ID `m03-d20ab0b353254edc4e31ef3b960d152713bbca5f60d0d3aac0cb12f055f1f406` was retained across pause/retry and acknowledged on attempt 2.
- Exact local commit SHA, direct parent, remote branch SHA, and committed file list are recorded in the sanitized Executor publication report under ignored `.agent-work/milestones/ARM.M02.1B.RUNTIME.PAUSE.RESUME/evidence/`.
- No live Drive/OAuth/DPAPI/real APO, public network, Scheduler/service/startup/system changes, main merge, tag, or Orchestrator workflow authority. Historical support STOP remains TRIGGERED/count UNCERTAIN; checkpoint OVERDUE.
