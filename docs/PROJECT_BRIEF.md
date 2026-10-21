# Artifact Relay Manager — ARM Charter v2.0 (M00 development-branch candidate)

**Repository:** nakfreeajer/artifact-relay-manager
**Human decision basis:** D01–D28 in the ARM v2.0 master planning document, including final D07 reconciliation.
**M00 authority:** Human-approved documentation-only amendment and one-time bounded historical STOP exception, 2026-10-20.
**Adoption status:** Candidate published on the dedicated M00 development branch. The published main branch retains ARM Charter v1.0-RC1 until separately authorized integration; do not claim v2.0 already governs main.

> ARM detects Google Drive changes and notifies the Orchestrator. The Orchestrator alone decides what happens next.

## 1. Permanent product objective and strict boundary

Build a small, reusable Windows 10/11 desktop application acting as a Google Drive change doorbell for multiple independent projects. ARM monitors two designated folders for each project and reliably sends metadata-only events to that project's **single configured Orchestrator endpoint**. The external Orchestrator validates authority, acknowledges receipt, interprets any prompt envelope, chooses destinations and routes to Architect or Executor; the separately managed ChatGPT Desktop Bridge, if used, controls Desktop interaction. ARM does not directly call the Desktop Bridge or the Executor.

ARM never selects milestones, reads prompts for meaning, dispatches execution, decides workflow priority, approves implementation, resumes Architect chats or retries workflow actions. The project remains independent and reusable, with no personal project, path, account or endpoint hardcoding (D01, D07, D22, D25).

## 2. Project and Google Drive contract

- Each project has a distinct immutable project ID, display name, optional repository/workspace identity and configuration, and one existing project-named Drive root folder selected by URL. Directly beneath it must be exactly the two separately designated child folders named Architect_Prompts and Executor_Reports (D05–D06).
- ARM verifies canonical root/child identities, direct parent-child relationships, access and uniqueness; overlapping identities across projects fail closed. ARM never creates, renames, moves or deletes Drive folders, and does not monitor nested descendants (D04–D06, D12).
- After a silent first-scan baseline, a file newly arriving as a direct child of either configured watched folder qualifies for a metadata-only notification whether created/uploaded there or moved there, after bounded stable observation. Existing in-folder rename, metadata-only version change, deletion, and nested membership alone do not qualify; verified file-content updates remain eligible. Repeat scans/restarts do not duplicate an arrival occurrence. Incomplete, unstable, inaccessible, inconsistent or ambiguous provider results fail closed and surface an issue. This is a metadata-readiness heuristic, not proof an upload is complete (Human-approved D11 amendment, 2026-10-21).
- Nominal polling target is 10 seconds, adaptive across projects with fair shared API/CPU budgets and bounded backoff. This is not an end-to-end latency guarantee (D13).
- Maintain read-only Drive access with protected credentials. Existing accepted Drive code, identity checks and evidence remain useful reference; do not require raw-byte download for the v2 metadata-only doorbell (D02, D20).

## 3. Notifications and receipt contract

For each detected event, emit at least projectId, eventType (PROMPT_CHANGED or REPORT_CHANGED), Drive fileId, fileVersion, retrievable Drive fileUrl, deterministic eventId and detectedAt. The recipient fetches and interprets files outside ARM; TaskId or workflow approval is not inferred by ARM (D14).

**Both event types go only to the configured Orchestrator endpoint for that project.** There is no second destination for Architect or any direct ARM-to-Bridge handoff (final D07; D25). Support authenticated encrypted notification delivery to separately hosted Orchestrators over the internet, and authenticated local integration. Live credentials and public endpoint exposure require separate approval (D16).

Persist notification intent before delivery, require a matching receiver ACK, and provide at-least-once transport with deterministic IDs, durable pending/restart recovery, bounded exponential retries and failure alerts. Only Orchestrator receipt is acknowledged; downstream execution/delivery is outside ARM, so never claim exactly-once workflow results (D15, D25). Keep ACKed event metadata 90 days; preserve unresolved pending until receipt or explicit Human resolution, including across restarts. Logs/state must exclude document content and credentials. Disk-exhaustion/corruption must surface a fail-closed health state, never silently drop pending (D27).

## 4. Desktop application and lifecycle

- Reusable Windows 10/11 project dashboard with project identity, repository, existing Drive root and both child URLs, **one** Orchestrator endpoint, health, last check, event history, errors, pending/delivered/failed counters; add/edit/enable/disable/remove projects and validate before enabling (D08–D09).
- Global and per-project Start/Pause/Resume/Stop. Pause preserves config and pending events. Exact safe paused-versus-stopped dispatch semantics must be specified in M02 and tested, not guessed (D10).
- The monitor starts **manually only**, stays alive when the UI closes after launch, and permits UI reattachment without duplicate monitor instances. Do not install Windows sign-in autostart, services, persistent scheduled startup, firewall/registry changes or elevated privileges without separate explicit Human authorization (D17–D19).
- Release 1 includes both a portable Windows application and installer using the same core, an explicit-consent update mechanism (check/notify but never silently install), user onboarding and truthful troubleshooting. Commercial licensing and subscription infrastructure are not required (D22–D24).

## 5. Release plan and acceptance

M00 — Adopt this corrected charter and decisions on a dedicated development branch, preserve historical evidence; documentation only.

M01 — Multi-project configuration and read-only validation of the two direct child folders.

M02 — Usable Windows management UI; may stage UI refinement incrementally but must satisfy full dashboard by Release 1.

M03 — Two-folder direct-child new/content-change monitoring and adaptive shared polling, offline-qualified before any live authorization.

M04 — Single-Orchestrator metadata notifications, durable queue, verified ACK, retry/dedupe, retention and authenticated local/remote transport.

**Early usable checkpoint (D28):** M01 + M03 + M04 integrated with a simulated Orchestrator for both folders, before full Release 1. The checkpoint is not a production-release qualification and does not waive UI/background or security requirements.

M05 — Manually launched UI-independent background monitor, lifecycle controls and restart/reattachment behavior.

M06 — Stage 1 simulated Orchestrator end-to-end evidence; Stage 2 dedicated isolated Drive folders and actual Orchestrator integration **only after separate Human approval**. Desktop Bridge conversation delivery is never an ARM acceptance test (D20–D21).

M07 — Windows 10/11 portable + installer packaging, update consent, usability and evidence-backed complete Release 1 acceptance.

Every milestone requires explicit bounded Human authorization and objective-based DoD. No milestone designation alone licenses implementation, live Drive testing or credential changes.

## 6. Authority, autonomy and fail-closed governance

Architect may direct routine implementation repairs and offline verification **only within a separately approved milestone**: at most three repair attempts per defect and ten Executor iterations per milestone (D03). Verified commits/pushes may target only a specifically approved development branch within authorized scope. No protected-branch modification, release, force push, deletion, new privilege or destructive Git operation without separate approval (D26). Maintain independent Executor alignment challenge, project identity checks, honest evidence, and CORE/BLOCKER/OPTIONAL/DRIFT classification.

The historical v1.0 governance STOP threshold remains **TRIGGERED; exact support streak UNCERTAIN**, and five-milestone progress checkpoint status must be reconciled. Human granted a **single M00 documentation-only exception** for these four files and a dedicated development-branch commit/push. This permission expires after verified M00 documentation closure, does not reset the historical count and **does not authorize M01 or any other support or runtime milestone**. Before M01, independently record baseline, current charter publication status and an explicit Human-authorized next milestone scope. Continue STOP on mismatches, missing approvals, privilege expansion or source conflict.

## 7. Historical v1.0 preservation and charter change

The previously Human-approved Charter v1.0-RC1 on main required CORE-07 raw outbound Google Drive upload as mandatory Release 1 scope. **This is superseded for v2.0 upon authorized charter adoption:** outbound uploading is not a v2.0 Release 1 requirement (D02). Preserve existing uncommitted/offline prototype, code, tests, accepted exact-byte transport and historical qualification evidence untouched as legacy reference, not a new v2.0 obligation. No code/credentials/Drive folders/Windows settings were authorized for change by M00. Earlier architecture/protocol/UI specification references to upload, two destinations or automatic startup describe legacy design and must not override this v2.0 charter; reconcile them only under a separately approved bounded documentation milestone.

**Planning source:** https://docs.google.com/document/d/1FVpU_vLLF43uFrU2O_KK1U6vO9_jwsR_aS-uDb9ry_4/edit

**M00 completion:** source-backed docs only, on development branch; no v2 runtime or release-qualification claim.
