# Project History

## 2026-10-08 — RELAY.PROJECT.SUPERVISOR.1A implementation

Added a foreground sequential supervisor that reloads and validates the local project registry on every cycle, then runs one accepted monitor cycle for each enabled project in projectId order. It shares one lazy noninteractive DriveAuthSession across projects/cycles, isolates project-local failures, suppresses further project work after a shared auth failure, observes registry changes at cycle boundaries, and emits metadata-only cycle records. Ctrl+C emits `STOPPED`. No background service or workflow authority was added.

Source/tests commit: `fbee2f5bd97a7b5f252cccc6a81800c17ecbbd60`.
Validation: 97/97 tests passed; Python compile checks and both existing CLI demos passed; deterministic two-project qualification passed with per-project state/event isolation and one shared auth refresh. Live two-cycle supervisor qualification passed on 2026-10-08 using the existing protected session. Cycle 1 delivered the designated file once; cycle 2 deduplicated it. The current file was version `3`, 26 bytes, SHA-256 `839ffb1cf48ad91270f4a395847100e412501c823a63270162a56306b1cc8ecf`; one acknowledged event and one local mock Watcher receipt shared event ID `relay-02471a4ffcf9a90b6ee27824533420ebda3c7f3a93d13b1e88c6525438a76ae9`. No browser opened and no Drive mutation occurred. Sanitized evidence is in ignored `.agent-work/milestones/RELAY.PROJECT.SUPERVISOR.1A/evidence/live-supervisor-qualification.json`.

## 2026-10-08 — RELAY.PROJECT.REGISTRY.1A implementation

Added a local durable project registry that references existing per-project Drive config and Relay state files. The schemaVersion 1 JSON registry uses canonical paths, deterministic projectId ordering, strict duplicate-key/schema checks, project/config identity checks, and collision checks for project IDs, config/state paths, Relay workspaces, and Drive folders. Writes use a same-directory temporary file followed by flush/fsync and atomic replacement. The `relay_projects.py` CLI supports list/add/show/enable/disable/remove/validate and returns metadata-only JSON. Registry operations do not call Drive, Watcher, browser OAuth, or protected-session APIs. No supervisor consumes the registry yet.

Source/tests commit: `6848633a69aba57b5b8f86596c5ccecce6d3c664`.
Validation: 82/82 unit tests passed; Python compile checks, both existing CLI demos, and `git diff --check` passed. Six CLI operations passed in fresh processes during ignored local qualification.

## 2026-10-08 — RELAY.GDRIVE.MONITOR.LOOP.1A implementation

Added the foreground single-project Google Drive monitor loop:
- protected-session-only noninteractive startup; in-memory access-token reuse and refresh-token rotation through current-user DPAPI storage;
- structured HTTP errors and one bounded 401 refresh/retry per poll cycle;
- successful-cycle local retry for pending Relay deliveries after final Drive identity validation, excluding events attempted in that cycle;
- metadata-only cycle reporting, bounded degraded-cycle backoff, and graceful Ctrl+C stop;
- no Windows Service/background startup, UI, database, Changes cursor, outbound publishing, multi-project manager, provider framework or Orchestrator authority.

Validation: 62/62 tests passed; Python compile checks, both existing CLI demos, and `git diff --check` passed. The live two-cycle monitor used the existing session without browser OAuth, delivered one event, then deduplicated the unchanged file/version. A local Drive test also confirmed a pending event retries with the same identity after its source disappears.

## 2026-10-08 — RELAY.GDRIVE.AUTH.SESSION.1A implementation

Added the bounded Windows protected Google Drive OAuth session:
- refresh-token-only payload protected by current-user DPAPI and bound to the installed client and exact read-only scope;
- atomic replacement, fail-closed corruption behavior, refresh-token rotation, refresh failure retention, fresh-process reuse, and local idempotent reset;
- system browser remains the first-use authorization path; later fresh processes refresh without the browser;
- deterministic test coverage includes actual Windows DPAPI round trip and CLI integration;
- real read-only qualification succeeded in multiple fresh processes.

Validation: 51/51 unit tests passed; Python compile checks, fake Drive lifecycle CLI demonstration, core CLI demonstration, and `git diff --check` passed. Sanitized evidence is recorded under the ignored milestone workspace. No Orchestrator workflow authority, scheduler, UI, database, merge, or tag was introduced.

## 2026-10-08 — RELAY.GDRIVE.AUTH.LIVE.1A accepted
Accepted the smallest secure Google Drive authentication bootstrap and first real bounded read-only qualification.

Implementation:
- Google installed desktop OAuth through the system browser;
- ephemeral `127.0.0.1` loopback callback;
- exact `drive.readonly` scope only;
- OAuth client config supplied from a local file outside Git;
- access/refresh credentials kept in process memory only;
- no token cache or credential persistence;
- `qualify-drive` validates one explicitly designated raw direct-child artifact;
- qualification performs exact-byte SHA-256, byte-length, provider-version, MIME/parent/state and project-identity revalidation;
- qualification creates no Watcher event, no Relay state and no Drive mutation.

Accepted implementation commit:
- `18d8d45c4ad505651f6ac4ef7f47165c0d068555`

Deterministic validation:
- 39 unit tests passed;
- compile checks passed;
- fake-Drive CLI lifecycle demonstration passed;
- original core CLI lifecycle demonstration passed;
- `git diff --check` passed.

Real live qualification passed:
- result `QUALIFIED_READ_ONLY`;
- MIME `text/plain`;
- byte length `26`;
- Drive `File.version` `3`;
- SHA-256 `839ffb1cf48ad91270f4a395847100e412501c823a63270162a56306b1cc8ecf`;
- zero Drive mutation by the qualification command.

One live prerequisite failure was observed and resolved: browser OAuth authorization succeeded but Drive API returned HTTP 403 until Google Drive API was enabled in the same Google Cloud project as the Desktop OAuth client.

Architect Correction 1 verified a separate CLI defect: `python relay.py` defined `RelayError` as `__main__.RelayError`, while lazy provider imports raised errors inheriting from a second `relay.RelayError`. The entry point now aliases the executing module as `relay` before calling `main()`. Actual subprocess tests confirm sanitized handling of HTTP 403 and missing-client failures, and preserve successful qualification behavior.

Correction commit:
- `eb3339a452badc14e9fb05668a96f128efbb03a2` — `fix(relay): sanitize script-mode Drive failures`.

Post-correction deterministic validation: 42 unit tests passed, including the three subprocess cases.

No background scheduler, desktop UI, outbound publishing, database, multi-provider framework or project-Orchestrator workflow authority was introduced.

## 2026-10-08 — RELAY.GDRIVE.INBOUND.1A accepted
Accepted the first real Google Drive inbound adapter around the deterministic Relay core.

Implementation:
- one-shot Drive v3 polling of direct children from one configured folder;
- raw `.relay-project.json` project/repository identity validation;
- Drive file `id` + `File.version` provider identity;
- exact raw-byte staging under the local Relay workspace;
- 1 MiB artifact bound;
- native Workspace files skipped instead of exported;
- environment-only bearer token;
- fake-Drive test endpoint constrained to loopback;
- Drive observations fed through the already accepted Relay transport core.

Independent Architect review found a provider-version race after the first passing implementation: listed metadata could identify version N while the media download returned bytes from a later same-size version. The same milestone was corrected with a post-download metadata recheck and final identity revalidation before any Watcher delivery.

Accepted commits:
- `a1557e9c87c72e76243f5cebf1b59c9875ff472f`
- `23fa8b9142f798fa22de50ae4cfe8e1624576794`

Final deterministic validation:
- 29 unit tests passed;
- compile checks passed;
- fake-Drive CLI lifecycle demonstration passed;
- original core CLI lifecycle demonstration passed;
- `git diff --check` passed.

Live validation was not fabricated:
- `LIVE_VALIDATION_BLOCKED=credentials_not_supplied`;
- no live Drive request was made.

No OAuth UI, background scheduler, recursive discovery, Workspace export, outbound publishing, SQLite, multi-provider framework, or project-Orchestrator workflow authority was introduced.

## 2026-10-08 — RELAY.CORE.VERTICAL.1A accepted
Accepted the first runnable deterministic Artifact Relay transport core.

Implementation:
- exact-byte SHA-256 and byte-length capture;
- deterministic normalized event identity;
- project/repository identity fail-closed checks;
- durable event persistence before Watcher delivery;
- Watcher acknowledgement recording;
- duplicate suppression;
- pending delivery retention and restart-safe retry;
- semantic persisted-state validation before retry.

Independent Architect review found one cross-project retry gap after the first passing implementation. The same milestone was corrected so persisted event project identity, dedupe tuple, deterministic event ID and normalized event structure are all revalidated before delivery.

Accepted commits:
- `e77b8105a8be26418165479ca4f92ea6be0c8a33`
- `9b73f05e0919796093a327f220d4d6ea093eb783`

Final validation:
- 12 unit tests passed;
- compile checks passed;
- CLI lifecycle demonstration passed;
- `git diff --check` passed.

No SQLite, merge, tag, project-Orchestrator workflow authority, real Google Drive integration or UI was added.

## 2026-10-08 — AMO worktree scaffold
Established the reusable AMO working-folder scaffold for Artifact Relay Manager:
- tracked governance/memory documents;
- source-area placeholders matching the Relay package boundary;
- ignored `.agent-work/` bootstrap utility;
- no project-Orchestrator runtime internals.
