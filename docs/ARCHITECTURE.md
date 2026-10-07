# Artifact Relay Manager Architecture

## 1. Purpose

Artifact Relay Manager is reusable multi-project transport infrastructure.

It monitors configured durable artifact folders, normalizes provider changes into local events, delivers them to project Watchers, uploads outbound artifacts, and maintains delivery history.

It does **not** authorize workflow execution.

## 2. Boundary

```text
Google Drive
    ↕
Relay Service
    ↕
Normalized local event/artifact boundary
    ↕
Project Watcher
```

The project Watcher owns priority, task state, Architect rollover, Executor authorization, and acceptance decisions.

## 3. Processes

### Relay Service

Background process. Continues running when the UI is closed.

Responsibilities:
- provider authentication/session management;
- folder monitoring;
- provider cursor/change tracking;
- project identity validation;
- artifact download/upload;
- transport-level deduplication;
- local event delivery;
- outbound retry;
- health reporting.

### Desktop UI

Management surface only.

Responsibilities:
- add/edit/disable projects;
- choose Drive folders;
- configure local project path and Watcher endpoint;
- test Drive/local/Watcher connectivity;
- view project health;
- view event/delivery history;
- inspect queued/failed transport;
- manually retry transport delivery.

The UI does not authorize Executor work.

### Local durable state

The MVP uses simple local durable files. Add SQLite or another database only if demonstrated runtime failure or measured scale requires it.

Owns local Relay durability:
- project configuration;
- provider cursors;
- observed provider versions;
- normalized events;
- delivery attempts;
- outbound upload state;
- health history.

## 4. Project isolation

Each project is an independent stream:

```text
projectId
  ├── provider folder identity
  ├── local relay workspace
  ├── Watcher endpoint
  ├── provider cursor
  └── delivery ledger
```

One project's provider event must never be delivered under another project's identity.

## 5. Provider adapter

V1 supports Google Drive only.

The internal provider interface should expose concepts such as:
- validateFolder()
- readProjectIdentity()
- pollChanges(cursor)
- fetchArtifact(version)
- publishArtifact()
- acknowledgeCursor()

Provider-specific file IDs, versions, and change tokens stay inside the adapter/transport metadata.

## 6. Local Watcher boundary

The Relay delivers normalized events with artifact references.

The Watcher must acknowledge transport receipt separately from workflow acceptance.

Example outcomes:
- DELIVERED
- QUEUED_BY_WATCHER
- REJECTED_PROJECT_IDENTITY
- WATCHER_UNAVAILABLE

A DELIVERED transport event does not mean the associated prompt was authorized.

## 7. Delivery semantics

Relay transport is at-least-once.

Project Watcher execution must be exactly-once by its own task/prompt claim.

This separation is intentional:
- Relay can safely replay after crash;
- Watcher can safely deduplicate workflow effects.

## 8. Crash recovery

On Relay restart:
1. open local durable state;
2. restore project configs and provider cursors;
3. query changes since each stored cursor;
4. ignore already-recorded provider versions;
5. retry undelivered local events;
6. retry incomplete outbound uploads;
7. resume health monitoring.

No workflow decision is reconstructed by the Relay.

## 9. Background/UI lifecycle

Closing the desktop UI does not stop the Relay Service.

The UI reconnects to the service and reads current status/history.

## 10. Future providers

The architecture may later support OneDrive, Dropbox, local folders, or other artifact stores through adapters.

No future provider should change the normalized Watcher contract.
