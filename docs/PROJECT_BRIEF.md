# Artifact Relay Manager — Permanent Project Brief

**Charter:** ARM Charter v1.0-RC1 (human approved; local documentation adoption authorized 2026-10-13).
**Repository:** `nakfreeajer/artifact-relay-manager`
**Objective:** deliver a secure, reliable, user-facing Artifact Relay Manager that transports and monitors project artifacts across Google Drive and the local Project Watcher boundary.

> **Relay transports and monitors. Project Watcher / Orchestrator decides.**

## Product objective and authority

The permanent product objective is to provide a dependable, understandable desktop tool that observes configured project artifacts, preserves their exact bytes, transports them with durable and bounded delivery state, and reports truthful lifecycle status. Relay does not decide project workflow, acceptance, milestone selection, Executor launch, Architect rollover, or workflow retry. Those decisions belong to the appropriate external human or Project Watcher / Orchestrator authority.

The Charter is human-owned. Agents may identify conflicts, prepare evidence, and propose bounded changes; only a human may amend this objective or change its release commitments. The human-approved Charter v1.0-RC1 governs this objective; local documentation adoption was authorized on 2026-10-13.

## Core capability matrix

| ID | Required capability | Status at baseline `e5d7c288e87f500d9941b9728c7b88876d178a26` |
|---|---|---|
| CORE-01 | Preserve exact artifact bytes and deterministic transport identity; persist normalized transport state before delivery. | Accepted bounded transport implementation. |
| CORE-02 | Observe Google Drive artifacts and deliver validated raw inbound artifacts through Relay. | Accepted bounded Drive inbound path; preserve its tests and evidence. |
| CORE-03 | Enforce project and repository isolation and fail closed on identity mismatch. | Accepted safeguards exist; retain regression coverage. |
| CORE-04 | Provide at-least-once transport, acknowledgement, deduplication, durable pending state, and restart-safe recovery without deciding acceptance. | Accepted bounded transport behavior. |
| CORE-05 | Provide reliable, bounded, UI-independent background monitoring with start, stop, and restart behavior. | Partial: foreground supervisor and bounded UserHost task-context qualification are present in main. Natural sign-in activation, sign-out/recovery, persistent Scheduler behavior, and Windows Service operation are not qualified. |
| CORE-06 | Provide a desktop management UI for configuration, status, and safe user control. | Not implemented. |
| CORE-07 | Publish raw files outbound to the correct configured Google Drive destination, verify provider response and identity, and persist upload state for retry, deduplication, and recovery. | Not implemented or qualified. **Mandatory minimum scope for Release 1; do not defer.** Existing read-only OAuth scope does not authorize uploads. Do not acquire or change OAuth scopes as part of this documentation preparation. |
| CORE-08 | Apply least privilege, protected credentials, project isolation, bounded monitoring, and truthful lifecycle evidence. | Partial: security and isolation controls exist; unattended lifecycle remains unqualified. |

“Accepted” means supported by tracked implementation and retained qualification evidence; it does not imply every deployment mode is qualified. “Not qualified” must not be reported as success or failure without evidence.

## Release 1 minimum-scope definition of done

Release 1 is complete only when all of the following are implemented and qualified together:

1. Exact-byte inbound and outbound transport, including SHA-256 and byte length, without content normalization.
2. Strict project/repository/destination isolation and fail-closed identity checks.
3. Durable event or upload intent persisted before an external side effect; provider acknowledgement/identity recorded; bounded retry, deduplication, and restart recovery.
4. Reliable UI-independent bounded background monitoring with understandable start, stop, and restart behavior.
5. Desktop management UI for project configuration and truthful operational status.
6. Outbound Google Drive authorization and least-privilege behavior explicitly designed, reviewed, and qualified; read-only scope is insufficient.
7. Deterministic unit/regression tests and bounded integration/security qualification covering success, mismatch, duplicates, unavailable provider/Watcher, restart, and protected credentials.
8. User-facing documentation and evidence that distinguish implemented, qualified, blocked, and unqualified behavior.

No individual component or synthetic test suite alone satisfies Release 1.

## Explicit non-goals

- Project Orchestrator internals, workflow meaning, acceptance authority, workflow retries, milestone selection, Executor launch, or Architect rollover.
- Additional provider frameworks or generalized multi-provider architecture before a separately approved milestone.
- SQLite or another database without demonstrated runtime failure or measured scale need.
- Broad OAuth scope expansion, credential reset, or live account changes during offline/documentation work.
- Treating synthetic qualification, a foreground process, or a task-context test as proof of natural-sign-in or unattended production operation.
- Deferring desktop management UI, reliable background monitoring, or CORE-07 outbound publishing from Release 1.

## Objective lock and change classification

Every proposed milestone must record its alignment to CORE-01 through CORE-08 and state which original-product capability it advances. Classify work as `CORE` (direct accepted-product capability), `BLOCKER` (evidence-backed impediment to a CORE capability), `OPTIONAL` (supporting work with no current CORE advancement), or `DRIFT` (outside the charter or displacing mandatory scope). Use `BLOCKED_OBJECTIVE_DRIFT` when proposed work is materially drifting from the locked objective and `PROJECT_ID_MISMATCH` when configured project identity does not match the target. A rename, session boundary, separation between sessions, or synthetic infrastructure test does not reset the continuous support-milestone streak or objective progress.

Two consecutive support-focused milestones—including `BLOCKER`, diagnostics, infrastructure, and qualification—without independently verified CORE capability advancement require STOP and Human choice, regardless of whether an individual milestone result is PASS or BLOCKED. Passing synthetic tests does not count as CORE advancement. Do not reset the streak by renaming or separating milestones. Historical count remains UNCERTAIN and the threshold TRIGGERED until a trustworthy ledger resolves it. Any further exception requires new evidence, explicit Human choice and approval, and one bounded stopping condition. The one-time bootstrap exception authorized preparation and local documentation adoption of this reviewed four-file patch only; it does not veto the stop rule or authorize additional support work.

Review and persist a five-milestone CORE progress checkpoint at least every five milestones; if overdue, STOP before further support work pending Human choice. Meaningful progress is an independently verified, accepted original-product capability, not only synthetic tests, tooling, documentation, or qualification infrastructure. Independent Executor alignment challenge and strict repository/project isolation remain required. These safeguards supplement and do not weaken the repository’s existing security, authorization, evidence, and protected-area rules.

## Current status and evidence limits

At the stated baseline, bounded real Google Drive → Relay → local mock Watcher transport has been qualified and must not be described as wholly absent. The desktop UI and outbound raw-file publishing remain unimplemented. Persistent Scheduler activation, natural sign-in, sign-out/recovery, Windows Service operation, and a complete unattended Architect↔Executor production loop are not qualified. The AUTOSTART 1B F47 attempt stopped at preflight (`BLOCKED_PREFLIGHT`) before task registration or fresh authorization consumption. F48 read-only authorization-history reconciliation is pending; do not claim it completed.

This brief records the human-approved Charter v1.0-RC1, with local documentation adoption authorized on 2026-10-13. It does not itself authorize runtime, Scheduler, OAuth, Drive, Watcher, source, or release actions.
