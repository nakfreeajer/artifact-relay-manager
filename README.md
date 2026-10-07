# Artifact Relay Manager

Reusable deterministic artifact transport for multi-project Architect / Watcher / Executor workflows.

## Status

Architecture bootstrap only. No project dispatch authority is implemented here.

## Core rule

**Artifact Relay transports and monitors. Project Watcher decides.**

The Relay Manager must never decide whether a prompt is authorized, whether an Executor should run, whether a result is accepted, or whether rollover has priority.

## V1 transport

Google Drive is the first supported durable transport.

Future adapters may support other providers, but provider expansion is not part of the initial implementation.

## Product shape

One installation contains:

- a background Relay Service that continues monitoring when the UI is closed;
- a desktop UI for project/folder configuration, status, health, and event history;
- a Google Drive adapter;
- a local normalized event interface used by project Watchers;
- simple local durable state for configuration, provider cursors, deduplication, delivery attempts, and health; add a database only if demonstrated runtime or scale evidence requires it.

## Multi-project model

Each configured project maps:

`projectId ↔ Drive folder ↔ local relay workspace ↔ Watcher endpoint`

Project streams are isolated. A Drive folder must identify itself with the expected project identity before monitoring can be enabled.

## UI goals

The UI must allow a user to:

- add/edit/disable projects;
- select the Drive folder to monitor;
- select the local project/workspace;
- configure/test the Watcher endpoint;
- see live health;
- inspect event history;
- see queued/failed deliveries;
- retry transport delivery without authorizing workflow execution.

See:

- `docs/ARCHITECTURE.md`
- `docs/PROTOCOL.md`
- `docs/UI_SPEC.md`
- `docs/SECURITY.md`
