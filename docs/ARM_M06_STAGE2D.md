# ARM.M06.S2D — Drive-mode project onboarding

**Project:** ARM
**Objective:** ARM-OBJ-001 v1.0
**Branch/base:** `arm-v2-amov5-agents-lock-1a` / `e0753e3f04a29ef1db863ee3674f20574b8e840d`

## Fixed CORE objective

Enable safe initial registration of an existing Google Drive project through ARM's Windows dashboard without weakening folder validation, project isolation or metadata-only relay boundaries.

## Candidate behavior

In explicit Drive mode, the dashboard offers **Validate on Drive and Add Disabled Project** only while the UserHost is stopped and no detector event or notification-ledger transport history exists. The request runs on the dashboard's existing serialized worker thread. It uses the existing authenticated read-only `AuthenticatedDriveMetadataProvider` and canonical `project_folder_config` validation; it does not use the fixture provider as a fallback.

The transaction holds the registry dashboard-write lock and the UserHost start lock while it rechecks mode, stopped state, event history and project-ID uniqueness, validates the existing root and the exact direct-child `Architect_Prompts` and `Executor_Reports` identities, then uses the registry's atomic writer. A successful project is always registered with `enabled=false`. Validation or persistence failure leaves the registry unchanged. Drive-mode Enable, Disable, Edit and Remove remain unavailable. Fixture-mode onboarding continues using its existing local fixture path.

Offline tests inject synthetic folder metadata and block network access. They cover valid registration, disabled initial state, exact child mismatch, duplicate project identity, existing transport history, an active UserHost, concurrent UserHost start, and unchanged registry bytes on rejection. No OAuth session or Google endpoint is used by qualification.

## Qualification and limitations

Classification: **offline implementation candidate; Architect review pending**. Focused dashboard tests passed 17/17. The combined relevant dashboard, UserHost, ForegroundMonitor and project-registry suite passed 59/59. Python compilation and `git diff --check` passed. The captured suite output is `.agent-work/milestones/ARM.M06.S2D/evidence/relevant-offline-suite.txt`. No live Drive, OAuth, real Orchestrator or full-suite qualification was performed. Folder validation in actual use requires the existing protected read-only Drive session and makes read-only metadata requests after the operator submits the form. No new permission, credential path or remote destination was added.

Historical qualification exceptions remain unchanged: the prior full-suite result was 191/192 with a subsequent isolated M05 rerun PASS; S2C had no new full-suite run and was not live-qualified. Neither result is replaced or relabeled by this S2D offline batch. Two initial test-fixture setup failures were corrected within this candidate; final focused and combined runs passed.

## Governance assessment

This is a direct original-product CORE capability: registering an existing project safely through the dashboard. Historical support STOP remains `TRIGGERED`; its exact count remains `UNCERTAIN`; the five-milestone CORE checkpoint remains `OVERDUE`. This record does not reset or resolve those controls. The overdue checkpoint is acknowledged and remains for Architect/Human governance review. M02.1D remains `PARKED`; D27 remains `FROZEN`; production Orchestrator integration remains unauthorized. No Git publication is included.

## ARM.M06.S2D.UX.1A — single-root Drive folder selection

This bounded offline UX extension keeps the fixed CORE objective unchanged. Drive-mode onboarding accepts the existing project root URL as its only folder input. It passes `None` for both child IDs to the existing registry builder, which discovers and fully validates exactly one active `Architect_Prompts` and one active `Executor_Reports` direct child before the existing locked, history-checked, uniqueness-checked atomic registration as Disabled. Child IDs appear in read-only confirmation fields only after success; editing the root link clears them. Stale child-ID values cannot override provider discovery.

The user-initiated **Open Google Drive** button opens the Drive home page in the default browser so the operator can select an existing folder and copy its link. It is an external convenience link, not an embedded Drive picker. The dashboard does not open it automatically. Fixture-mode entry and validation behavior remains unchanged; Drive-mode Enable, Disable, Edit and Remove remain unavailable.

Offline qualification on the UX candidate: focused dashboard tests **19/19 passed**; dashboard, registry and ForegroundMonitor tests **48/48 passed**; Python compilation and `git diff --check` passed. Missing, duplicate and wrong-parent children and provider validation failure preserve exact registry bytes. The successful synthetic registration used discovered IDs despite stale child-ID values. No real Drive, OAuth, browser, receiver or Orchestrator activity occurred. Human synthetic UI validation PASS (session `ARM-M06S2D-UX1A-UAT-2093319f3ace`): the Human confirmed the root URL was the only folder input, both child IDs appeared automatically, one synthetic project was registered disabled, and UserHost stayed STOPPED with zero events. This was offline UAT only; no live Drive qualification is claimed.

An extended 61-test batch including UserHost tests had one failure in the unchanged detached-worker lifecycle demonstration: `tests/arm_v2_userhost_process_demo.py` asserted that the start controller process had exited. This unrelated failure is retained and is not represented as a passing full suite. The earlier full-suite result remains 191/192 with its isolated M05 rerun PASS; it is not replaced. The Tk tests also emitted an existing teardown warning for a scheduled `_poll_future` callback after a root window closed; affected tests passed. No repair of either issue is included in this UX candidate.

This extension is a direct CORE usability improvement to the already authorized S2D onboarding capability. Its local qualification does not clear historical support STOP `TRIGGERED`, exact count `UNCERTAIN`, or the overdue CORE checkpoint. M02.1D remains `PARKED`, D27 `FROZEN`, and production Orchestrator integration unauthorized. Human synthetic UAT passed. This offline candidate does not qualify live Drive or clear historical governance findings.
