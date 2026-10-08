# Handover

## Repository
`nakfreeajer/artifact-relay-manager`

## Role
Reusable Artifact Relay transport infrastructure.

## Governing boundary
**Relay transports and monitors. Project Watcher / Orchestrator decides.**

This project deliberately omits project-Orchestrator internals.

## Accepted milestones

### RELAY.PROJECT.REGISTRY.1A
Implemented on branch `project-registry-1a`:
- schemaVersion 1 local JSON registry at `%LOCALAPPDATA%\ArtifactRelayManager\projects.json` by default;
- references existing Drive project config and Relay state paths, with canonical absolute paths and atomic replace;
- rejects project ID, config path, state path, workspace, and Drive folder collisions;
- `relay_projects.py` supports list/add/show/enable/disable/remove/validate;
- validates the current local Drive config without Drive HTTP, Watcher, OAuth/browser, or protected-session access;
- does not add a registry consumer; monitoring remains foreground and single-project.

Source/tests commit: `6848633a69aba57b5b8f86596c5ccecce6d3c664`.
Validation: 82/82 unit tests passed; changed Python files compiled; Drive and core CLI demos and `git diff --check` passed. Six-command local qualification passed in separate CLI processes. Evidence is in the ignored `.agent-work/milestones/RELAY.PROJECT.REGISTRY.1A/evidence/` directory.

### RELAY.CORE.VERTICAL.1A
Accepted deterministic transport core:
- exact-byte hashing;
- deterministic event identity;
- fail-closed project isolation;
- durable pre-delivery state;
- acknowledgement handling;
- duplicate suppression;
- restart-safe retry;
- semantic persisted-state validation.

Accepted commits:
- `e77b8105a8be26418165479ca4f92ea6be0c8a33`
- `9b73f05e0919796093a327f220d4d6ea093eb783`

### RELAY.GDRIVE.INBOUND.1A
Accepted bounded one-shot Google Drive inbound adapter:
- one configured folder only;
- raw identity file validation;
- Drive file ID + File.version provider identity;
- exact raw-byte staging;
- post-download provider metadata consistency check;
- final identity revalidation before Watcher delivery;
- no Workspace export;
- token only from environment.

Accepted commits:
- `a1557e9c87c72e76243f5cebf1b59c9875ff472f`
- `23fa8b9142f798fa22de50ae4cfe8e1624576794`

Deterministic validation: 29/29 tests passed.
Live status: `LIVE_VALIDATION_BLOCKED=credentials_not_supplied`.

### RELAY.GDRIVE.AUTH.LIVE.1A
Accepted ephemeral Google Drive OAuth bootstrap and live read-only qualification:
- installed desktop OAuth through the system browser;
- ephemeral `127.0.0.1` loopback callback;
- exact `drive.readonly` scope;
- OAuth client file stays local and outside Git;
- no Relay token/refresh-token persistence;
- one designated raw direct-child artifact qualified without Watcher delivery or Relay state;
- exact-byte/provider-version/project-identity safeguards preserved.

Accepted commit:
- `18d8d45c4ad505651f6ac4ef7f47165c0d068555`
- `eb3339a452badc14e9fb05668a96f128efbb03a2` - script-mode provider/auth failures now use the sanitized CLI error contract.

Deterministic validation after Architect Correction 1: 42/42 tests passed, including subprocess coverage for provider HTTP 403, missing OAuth client configuration, and a successful fake/local qualification.
Live qualification: `QUALIFIED_READ_ONLY`, 26 bytes, `text/plain`, Drive version `3`, SHA-256 `839ffb1cf48ad91270f4a395847100e412501c823a63270162a56306b1cc8ecf`.

### RELAY.GDRIVE.AUTH.SESSION.1A
Implemented Windows-only persistent Google OAuth session on branch `gdrive-auth-session-1a`:
- source/tests commit: `c479aa1488aacf470562a236090ae10d305d7ef8`;
- refresh token is protected with current-user DPAPI and bound to application, client ID and exact `drive.readonly` scope;
- refresh token is persisted atomically; access token and client secret remain in process memory;
- fresh processes refresh without opening a browser;
- corrupt state and refresh failures fail closed without exposing provider data or deleting the existing session;
- `reset-drive-auth` removes only the local client/scope session and is idempotent;
- real read-only qualification passed in separate fresh invocations, with browser authorization on first use and silent refresh in a later process;
- Windows-only; no credential revocation, non-Windows protected session backend, scheduler or UI.

Final deterministic validation: 51/51 tests passed; compile checks, both CLI demos, and `git diff --check` passed.

Deterministic validation and bounded evidence are recorded in `docs/VALIDATION.md` and `.agent-work/milestones/RELAY.GDRIVE.AUTH.SESSION.1A/evidence/`.

### RELAY.GDRIVE.MONITOR.LOOP.1A
Implemented on branch `gdrive-monitor-loop-1a`:
Source/tests commit: `d3d6ba38d02c03a609ca5a62cd9fd8eaac41c303`.
- `monitor-drive` is a foreground single-project loop; `--state` is required, `--interval-seconds` is bounded to 1-3600, and optional `--max-cycles` is bounded to 1-10000;
- monitor startup requires an existing current-user DPAPI session and never launches browser OAuth;
- the access token is reused in memory across cycles; credentials refresh only when invalid/expired or after one HTTP 401, with exactly one poll retry for a 401;
- each successfully completed Drive poll performs final project identity validation before local pending events are retried; events attempted in that same cycle are excluded from the local retry pass;
- degraded provider/auth cycles emit sanitized metadata and use bounded backoff; successful cycles reset the backoff;
- Ctrl+C emits `STOPPED` without deleting Relay state or the protected session;
- source-removal retry was proven against a deterministic local Drive server and delivered the same pending event ID;
- live two-cycle qualification reused the existing session with no browser prompt, delivered once, and deduplicated the unchanged file/version on cycle 2.

Final validation: 62/62 tests passed; compile checks, both existing CLI demos, monitor tests, and `git diff --check` passed.

Limitations: one project per process; full direct-child polling without a Drive Changes cursor; foreground process only; no Windows Service/background startup, UI, outbound publishing, multi-provider framework, database, or project-Orchestrator authority.

## Fresh worktree bootstrap
From the repository root:

```bash
python tools/bootstrap_agent_work.py
```

For a known milestone:

```bash
python tools/bootstrap_agent_work.py --milestone <MILESTONE_ID>
```

## Handover boundary

RELAY.GDRIVE.MONITOR.LOOP.1A completes foreground Windows Google Drive monitoring. No next implementation milestone is authorized by this handover. The Architect must choose the next bounded target before Executor work resumes.

Architectural guardrails:
- Relay transports and monitors; Watcher / Orchestrator decides.
- Do not add a scheduler, UI, outbound publishing, provider framework, or database unless explicitly selected in a future bounded milestone.
