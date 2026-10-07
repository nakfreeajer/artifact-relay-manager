# Artifact Relay Manager — Agent Governance

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
