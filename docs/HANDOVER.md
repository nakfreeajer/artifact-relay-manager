# Handover

## Repository
`nakfreeajer/artifact-relay-manager`

## Role
Reusable Artifact Relay transport infrastructure.

## Governing boundary
**Relay transports and monitors. Project Watcher / Orchestrator decides.**

This project deliberately omits project-Orchestrator internals.

## Fresh worktree bootstrap
From the repository root:

```bash
python tools/bootstrap_agent_work.py
```

This creates the ignored local `.agent-work/` evidence folders used by Architect/Executor development.

## Next implementation target
Build one bounded runnable Relay vertical slice:

configured project -> observed bounded artifact -> identity validation -> exact-byte SHA-256/length -> normalized event -> durable local event state -> mock/local Watcher delivery -> acknowledgement -> duplicate suppression -> restart-safe retry.

Do not start with desktop UI, multi-provider support, Codex launch logic, Architect rollover, or a new database.
