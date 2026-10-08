# Artifact Relay Manager

Reusable deterministic artifact transport for multi-project Architect / Watcher / Executor workflows.

## Status

The deterministic Relay core, bounded one-shot Google Drive inbound adapter, live read-only qualification, and Windows protected Google Drive OAuth session are implemented on bounded feature branches. No project dispatch authority is implemented here.

Current accepted capabilities include:
- exact-byte SHA-256 and byte-length verification;
- deterministic normalized Relay event identity;
- durable pre-delivery state, acknowledgement recording, deduplication and restart-safe retry;
- fail-closed project/repository isolation;
- one-shot Google Drive v3 inbound polling for one explicitly configured folder;
- exact raw-file staging with provider-version revalidation before Watcher delivery;
- installed-app Google OAuth using the system browser, an ephemeral loopback callback, and exactly `drive.readonly`;
- Windows DPAPI-protected refresh-token session reuse across fresh processes, with local reset support;
- foreground single-project `monitor-drive` loop with bounded polling, in-memory access-token reuse, 401 recovery, degraded-cycle backoff, and pending transport retry;
- local schema-versioned project registry that references existing Drive config and Relay state files, with atomic JSON updates and collision validation;
- foreground `relay_supervisor.py` that reloads the project registry each cycle and sequentially runs one monitor cycle for every enabled project with one shared in-memory auth session;
- bounded real-Drive read-only qualification of one explicitly designated raw artifact without Watcher delivery or Relay state.

The registry is stored by default at `%LOCALAPPDATA%\ArtifactRelayManager\projects.json`. Manage it with `python relay_projects.py [--registry <path>] list|add|show|enable|disable|remove|validate`. It stores only project metadata and canonical config/state paths; it does not copy project configuration or credentials. Run the foreground multi-project supervisor with `python relay_supervisor.py [--registry <path>] run --interval-seconds 30 [--max-cycles N]`. It reloads the registry at each cycle boundary and runs enabled projects sequentially in projectId order. One noninteractive Drive auth session is shared across enabled projects and cycles. Windows Service/background hosting, desktop UI, and a management API are not implemented.

A real Google Drive read-only qualification passed on 2026-10-08 against one explicitly configured test folder and designated 26-byte text artifact. The observed Drive version was `3` and the exact-byte SHA-256 was `839ffb1cf48ad91270f4a395847100e412501c823a63270162a56306b1cc8ecf`.

The `RELAY.GDRIVE.AUTH.SESSION.1A` branch adds a current-user DPAPI encrypted local refresh-token file, bound to the installed client and exact scope. Fresh processes refresh silently; access tokens remain memory-only.

## Core rule

**Artifact Relay transports and monitors. Project Watcher decides.**

The Relay Manager must never decide whether a prompt is authorized, whether an Executor should run, whether a result is accepted, or whether rollover has priority.

## V1 transport

Google Drive is the first supported durable transport.

The current inbound adapter supports raw downloadable files only. Native Google Workspace documents are deliberately not exported into the machine transport path because export would not preserve authoritative stored bytes.

Future adapters may support other providers, but provider expansion is not part of the initial implementation.

## Product shape

One installation is intended to contain:

- a background Relay Service that continues monitoring when the UI is closed;
- a desktop UI for project/folder configuration, status, health, and event history;
- a Google Drive adapter;
- a local normalized event interface used by project Watchers;
- simple local durable state for configuration, provider cursors, deduplication, delivery attempts, and health; add a database only if demonstrated runtime or scale evidence requires it.

Persistent Google Drive OAuth sessions are implemented on Windows. First authorization uses the system browser; later fresh processes refresh from the DPAPI-protected refresh token without opening the browser. `monitor-drive` runs in the foreground only and requires an existing protected session. Windows Service installation/background startup and desktop UI are not implemented.

## Multi-project model

Each configured project maps:

`projectId ↔ Drive folder ↔ local relay workspace ↔ Watcher endpoint`

Project streams are isolated. A Drive folder must identify itself with the expected project identity before monitoring can be enabled.

## UI goals

The future UI must allow a user to:

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
