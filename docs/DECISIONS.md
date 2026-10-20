# Decisions

## D-001 — Relay is transport-only
Artifact Relay Manager transports and monitors bounded artifacts/events. Workflow authority remains outside Relay.

## D-002 — Google Drive first
The first provider is Google Drive. Multi-provider expansion is deferred.

## D-003 — Project isolation fails closed
Every configured project binds project identity, repository identity, provider folder, local workspace and Watcher endpoint. Identity mismatch blocks delivery.

## D-004 — At-least-once transport
Relay delivery may repeat after restart/retry. Exactly-once workflow effects are owned by the project Watcher / Orchestrator.

## D-005 — No speculative database
MVP local state uses simple durable local files. Add SQLite or another database only after demonstrated runtime or measured scale need.

## D-006 — Raw evidence stays local
`.agent-work/` is ignored. Only bounded sanitized bridge/outbox artifacts may be published.


## D-007 — Human-approved permanent product charter and Release 1 scope

**Status:** Human decision recorded and four-file local documentation adoption applied under the one-time authorization on 2026-10-13.
**Date recorded:** 2026-10-13
**Authority:** Human-approved ARM Charter v1.0-RC1 instruction.

The permanent product objective is a secure, reliable, user-facing Artifact Relay Manager that transports and monitors project artifacts across Google Drive and the local Project Watcher boundary. Relay transports and monitors; Project Watcher / Orchestrator decides. CORE-07 raw artifact publishing to the correct configured Google Drive destination is mandatory minimum Release 1 scope and may not be deferred. Release 1 also requires reliable UI-independent bounded background monitoring and a desktop management UI, alongside exact-byte transport, strict isolation, durable state before side effects, acknowledgement, retry/deduplication/recovery, least privilege, and truthful lifecycle qualification as detailed in `docs/PROJECT_BRIEF.md`.

The human-approved Charter defines explicit non-goals, an objective lock, human-only amendments, CORE/BLOCKER/OPTIONAL/DRIFT classifications, a two-consecutive-BLOCKER stop rule, independent Executor alignment challenge, strict project isolation, and a five-milestone CORE progress review. These requirements do not supersede existing safety or authorization gates.

This entry records the human decision and bounded local documentation adoption. It does not claim a commit, push, or release; delivery history is recorded by Git and qualification evidence. Existing D-001 through D-006 remain unchanged.


## D-008 — ARM v2.0 Human decision register (D01–D28; approved planning direction)

**Authority:** Human decision interviews, final D07 reconciliation, M00 documentation-only authorization (2026-10-20).
**Planning source:** https://docs.google.com/document/d/1FVpU_vLLF43uFrU2O_KK1U6vO9_jwsR_aS-uDb9ry_4/edit
**Effect:** These decisions define the v2.0 charter candidate on the dedicated M00 branch. D-007 remains a factual record of the historical v1.0-RC1 instruction; its mandatory outbound-upload Release 1 rule is superseded only when v2.0 is authorized for adoption to the governing branch.

**D01** — Doorbell mission only: independent multi-project Windows Drive change notifier; no workflow authority.

**D02** — Preserve outbound-upload prototype as historical reference; outbound upload removed from v2 Release 1.

**D03** — Within separately approved milestone only: max 3 repairs/defect and 10 Executor iterations/milestone.

**D04** — No fixed number of projects; shared resource/API limits and strict isolation.

**D05** — Per-project existing named root with direct Architect_Prompts and Executor_Reports child folders.

**D06** — Human supplies existing root URL; ARM validates read-only and never creates/renames/moves/deletes Drive folders.

**D07** — FINAL RECONCILED: ALL prompt and report events to one configured Orchestrator endpoint/project; Orchestrator routes onward. Supersedes original split destinations.

**D08** — Windows 10 and Windows 11 Release 1; portable internals where practical.

**D09** — Dashboard for project/repository/folders/endpoint, status, last check, counts, errors and history.

**D10** — Global and per-project Start/Pause/Resume/Stop; preserve pending and config on pause.

**D11** — Notify only direct-child new files and content updates, not rename/delete/move; surface folder errors.

**D12** — Direct children only; no recursive monitoring.

**D13** — Adaptive nominal 10-second polling with bounded shared quotas/backoff; not a delivery guarantee.

**D14** — Metadata-only notifications (projectId, event type, fileId/version/URL, eventId, detection time). No envelope interpretation.

**D15** — Durable at-least-once delivery/Orchestrator ACK, dedupe, bounded retries and restart recovery; no silent pending loss.

**D16** — Remote-capable authenticated encrypted endpoints from Release 1; local also possible; live deployment needs further approval.

**D17** — Monitoring continues in background after UI closes; reattach without duplicate monitors.

**D18** — Manual launch only; no sign-in/pre-login/persistent scheduled automatic startup.

**D19** — Local config/logs/process permitted; services/Scheduler/firewall/registry startup modifications need separate Human approval.

**D20** — Isolated Drive test project and explicit Human consent before live provider qualification or OAuth/scope changes.

**D21** — Two-stage integration: simulated Orchestrator first, separately authorized real Orchestrator second; Desktop Bridge outside ARM acceptance.

**D22** — Reusable third-party developer app; no personal hardcoding or commercial licensing/account infrastructure obligation.

**D23** — Both installer and portable Windows distribution sharing one core, respecting manual startup/permissions.

**D24** — Update checks/notifications allowed; install only after explicit user confirmation.

**D25** — Strict ARM→Orchestrator ACK boundary; Orchestrator/Bridge own downstream routing and Desktop delivery.

**D26** — Milestone-bounded verified Git commits/pushes to approved dev branch only; protected/release/force/destructive operations separately approved.

**D27** — ACKed event metadata retained 90 days; unresolved pending retained; never log documents or credentials.

**D28** — Incremental development; early two-folder/simulated-Orchestrator slice before full Release 1 acceptance.

**Open implementation details (not extra Human decisions):** first-poll baseline/backfill, safe Pause-versus-Stop dispatch, Drive content-versus-metadata change discrimination, and durable storage exhaustion behavior must be qualified in their relevant future milestone. M00 did not implement or authorize any of them.

**STOP exception:** Human approved exactly one documentation-only M00 exception, restricted to AGENTS.md, docs/PROJECT_BRIEF.md, docs/DECISIONS.md and docs/HANDOVER.md on a dedicated development branch. Historical STOP stays TRIGGERED/UNCERTAIN and the exception expires after verified M00 documentation closure. M01 requires separate approval.
