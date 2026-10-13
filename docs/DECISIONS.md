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
