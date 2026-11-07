# ARM.M06.S2E — Drive project activation

**Project:** ARM
**Objective:** ARM-OBJ-001 v1.0
**Branch / baseline:** `arm-v2-amov5-agents-lock-1a` / `4fe0298bde34d213d2722749428a74b9a3294873`
**Classification:** offline CORE implementation candidate; Architect review pending.

## Fixed CORE objective

Allow the Human to safely enable or disable an existing Google Drive project through the Windows dashboard without compromising folder identity validation, durable notification state or project isolation.

## Candidate behavior

The Drive-mode **Enable Project** action now requires an existing selected project, a valid local registry/detector/notification/pause state, and a stopped UserHost. It serializes through the existing registry dashboard-write lock, acquires the UserHost start lock, confirms the worker lock is free, and uses the existing read-only `AuthenticatedDriveMetadataProvider` and `ProjectRegistry.validate_folder_projects()` path to revalidate the root and exact direct-child folder identities. The registry's existing atomic writer then changes only the selected project's `enabled` flag. The UserHost is not started. Failed validation leaves the registry unchanged. Drive-mode Edit and Remove remain restricted.

Drive-mode **Disable Project** uses the same stopped-host, dashboard-write, start/worker lock and local-state gates, but does not instantiate a Drive provider or require provider availability. It changes only the selected registry flag. Detector, notification ledger, ACK receipt and pause files are read and validated, not rewritten. The existing fixture-mode enable/disable path remains available and retains its prior behavior.

The action runs on the dashboard's existing serialized background executor. Feedback is sanitized; after completion the dashboard reloads local status. The controls are available only for the state-appropriate action while Drive mode is stopped.

## Offline qualification

Synthetic provider tests cover successful metadata revalidation and manual-start preservation; missing, ambiguous, moved, and mismatched child identities; active-host and competing start/worker locks; and fail-closed handling of malformed durable state. A state-preservation test creates deterministic M03 events and valid pending and signed-ACK ledger records, plus pause state, then disables and re-enables project A. It verifies byte-identical detector, ledger and pause files, unchanged project B configuration and event IDs, and fresh CLI/dashboard reload while the UserHost remains stopped. Disable is tested with a provider factory that fails if called.

Final focused dashboard Tk suite: `python -m unittest tests.test_arm_v2_dashboard -v` — **24/24 passed**.

Broader relevant offline modules: dashboard, registry, ForegroundMonitor, notification, pause-state and UserHost — **85/86 passed; one failure** in the existing M05 `test_real_windows_detached_worker_lifecycle_and_recovery_demo`. Its subprocess demo failed the pre-existing `failed_start` result/exit-code assertion at `tests/arm_v2_userhost_process_demo.py:330`; the assertion did not expose the actual values. This matches the historical intermittent M05 lifecycle exception recorded by prior milestones. No M05 repair or rerun was performed. The broader batch is not a clean pass.

An earlier full-discovery invocation ended without the command wrapper preserving its final summary or exit status, so it is not counted as a pass. The final focused Tk run passed; an earlier focused run also printed the known Tcl `_poll_future` teardown callback warning during a passing test. No Tk callback lifecycle change is included.

Python compilation and `git diff --check` are recorded with the final candidate evidence under `.agent-work/milestones/ARM.M06.S2E/evidence/`. No live Google Drive, OAuth session, receiver, Orchestrator, or CDB operation was performed. Folder identity validation on a future real Drive-mode enable action uses the existing protected read-only session; this milestone did not make that live request.

## Objective and governance status

This candidate implements the requested original-product dashboard capability; offline synthetic metadata verifies the activation gate and preservation behavior. It does not establish live folder identity or constitute full ARM acceptance. No project-Orchestrator workflow authority was introduced.

Historical support STOP remains `TRIGGERED`, exact support count `UNCERTAIN`, and the five-milestone CORE checkpoint `OVERDUE`. M02.1D remains `PARKED`; D27 remains `FROZEN`; production Orchestrator integration remains unauthorized. D03 accounting for this milestone: iteration 1/10; no repair attempts have been consumed. No Git staging, commit or push is included.
