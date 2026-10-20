# Artifact Relay Manager — Agent Governance

## ARM v2.0 M00 development-branch charter notice

Human authorized one bounded documentation-only M00 correction on 2026-10-20. On this M00 branch, docs/PROJECT_BRIEF.md records the ARM v2.0 charter candidate and docs/DECISIONS.md records D01–D28. GitHub main retains historical v1.0-RC1 until separately authorized adoption; do not assert global activation by development-branch publication. v2.0 ARM monitors existing project root/Architect_Prompts and Executor_Reports and sends BOTH types of metadata-only events to ONE Orchestrator endpoint/project. ARM does not directly invoke ChatGPT Desktop Bridge, author prompts, upload files for v2 Release 1, or implement Orchestrator workflow decisions. Manual startup only. Preserve historical code and qualifications.

The historical two-support-milestone STOP remains TRIGGERED and its count UNCERTAIN. Human's one-time M00 documentation exception expires upon verified documentation-only closure; it does not reset the STOP or authorize M01. Continue fresh preflight, independent alignment challenge and all protected-area controls. Sections below record pre-v2 governance history where applicable; specific v2 product objectives are determined by the versioned canonical charter on the current branch.

## Read first
1. README.md
2. docs/CURRENT_STATE.md
3. docs/HANDOVER.md
4. docs/ARCHITECTURE.md
5. docs/PROTOCOL.md
6. docs/SECURITY.md
7. docs/AGENT_WORKFLOW.md
8. docs/PROTECTED_AREAS.md
9. docs/VALIDATION.md

## Project boundary
This repository implements the reusable Artifact Relay Manager only.

**Relay transports and monitors. Project Watcher / Orchestrator decides.**

Do not implement project-Orchestrator internals here. Do not add workflow milestone selection, Executor launch authority, Architect rollover authority, product acceptance decisions, or workflow retry authority.

Google Drive is the first provider target. Additional providers require a later bounded milestone.

## Fresh worktree
Raw evidence belongs under Git-ignored `.agent-work/`.

Run:

```bash
python tools/bootstrap_agent_work.py
```

Do not commit the entire `.agent-work` tree. Only bounded sanitized evidence may cross `.agent-work/bridge/outbox/`.

## Infrastructure rule
Prefer GitHub, Google Drive, Google Sheets when needed, and local files before another database/service. Do not introduce SQLite or another database without demonstrated runtime failure or measured scale need.

## Mutation rule
One bounded milestone at a time. Preserve project isolation and fail closed on repository/project identity mismatch.


## Charter alignment record

## Active Architect pre-prompt gate (AMO v4.8 §37.2)

Before **each proposed Executor prompt**, including during an uninterrupted conversation and after handover, the Architect freshly retrieves and verifies from the exact repository: official `AGENTS.md`, the human-approved canonical charter, `docs/HANDOVER.md`, and pertinent accepted decisions/evidence. The Architect records and verifies repository/project identity, source revision, charter revision, CORE target and precise definition-of-done gap, measurable expected result and evidence, why action is necessary now rather than deferrable or isolatable, classification (`CORE`, `BLOCKER`, `OPTIONAL`, or `DRIFT`), continuous support-milestone streak and next five-milestone checkpoint, applicable Human permission, authorized mutations, and STOP conditions. A prior session's checklist or an unchecked `CHARTER_CHECK=VERIFIED` assertion is not source verification.

If a required source is inaccessible, stale, contradictory, or insufficient, HOLD/BLOCKED and issue **no executable Executor prompt**. The Executor independently rechecks the same authoritative sources and may return `BLOCKED_OBJECTIVE_DRIFT` or `PROJECT_ID_MISMATCH`. Every milestone records its CORE alignment and whether an independently verified original-product capability advanced. The human-owned charter and Release 1 commitments can be amended only by explicit Human approval. An independent Executor alignment challenge and strict repository/project isolation remain required.

Two consecutive support-focused milestones—including blocker work, diagnostics, infrastructure, or qualification—without independently verified CORE capability advancement require STOP and Human choice, regardless of whether either milestone result was PASS or BLOCKED. Do not reset the continuous streak because milestones are renamed or separated, or because synthetic tests pass. A further exception requires new evidence, explicit Human choice and approval, and one bounded stopping condition. Historical streak count remains UNCERTAIN and the threshold TRIGGERED until a trustworthy ledger resolves it. This rule does not veto the one-time bootstrap exception authorizing preparation and local documentation adoption of this reviewed four-file patch; that exception authorizes no additional support work.

Review and persist a five-milestone CORE progress checkpoint at least every five milestones; if overdue, STOP before further support work pending Human choice. Synthetic tests, qualification tooling, and documentation alone are not independently verified original-product capability advancement.

These alignment checks do not override or weaken existing safety, protected-area, authorization, validation, or evidence requirements. When evidence is incomplete or conflicting, preserve the uncertainty and stop at the applicable safety gate.
