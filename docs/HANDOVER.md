# Handover

## Repository
`nakfreeajer/artifact-relay-manager`

## Role
Reusable Artifact Relay transport infrastructure.

## Governing boundary
**Relay transports and monitors. Project Watcher / Orchestrator decides.**

This project deliberately omits project-Orchestrator internals.

## Accepted baseline
Milestone `RELAY.CORE.VERTICAL.1A` is accepted on branch `relay-core-vertical-1a`.

Accepted implementation commits:
- `e77b8105a8be26418165479ca4f92ea6be0c8a33`
- `9b73f05e0919796093a327f220d4d6ea093eb783`

The accepted core provides deterministic event identity, exact-byte hashing, project isolation, durable pre-delivery state, Watcher acknowledgement handling, duplicate suppression and restart-safe retry. Persisted events are semantically revalidated before retry.

## Fresh worktree bootstrap
From the repository root:

```bash
python tools/bootstrap_agent_work.py
```

For a known milestone:

```bash
python tools/bootstrap_agent_work.py --milestone <MILESTONE_ID>
```

## Next bounded implementation target
Add the real Google Drive inbound adapter around the accepted 1A core.

The next milestone should:
- observe one explicitly configured Drive project folder;
- validate the project identity artifact;
- surface exact provider item identity and provider version/change identity;
- download bounded artifact bytes exactly;
- feed those facts into the accepted normalized-event/durable-delivery core;
- preserve at-least-once Relay transport and fail-closed project isolation.

Do not redesign the accepted 1A transport core unless direct regression evidence proves a defect.

Still out of scope unless separately authorized:
- desktop UI;
- multi-provider framework;
- Codex launch/relaunch authority;
- Architect rollover;
- scheduler/workflow engine;
- product/workflow acceptance authority;
- SQLite or another database without demonstrated need.
