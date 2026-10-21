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
