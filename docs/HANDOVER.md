# Handover

## Repository
`nakfreeajer/artifact-relay-manager`

## Role
Reusable Artifact Relay transport infrastructure.

## Governing boundary
**Relay transports and monitors. Project Watcher / Orchestrator decides.**

This project deliberately omits project-Orchestrator internals.

## Accepted milestones

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
- `eb3339a452badc14e9fb05668a96f128efbb03a2` â€” script-mode provider/auth failures now use the sanitized CLI error contract.

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

Deterministic validation and bounded evidence are recorded in `docs/VALIDATION.md` and `.agent-work/milestones/RELAY.GDRIVE.AUTH.SESSION.1A/evidence/`.

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
Add the smallest secure persistent Google OAuth session mechanism so repeated one-shot Drive reads do not require browser authorization on every run.

Keep this bounded:
- retain exact `drive.readonly`;
- store no credential material in Git, project artifacts, Watcher payloads or ordinary logs;
- use platform-appropriate protected local credential storage rather than a plaintext token file;
- support the accepted one-shot adapter and qualification path;
- prove restart/reuse/refresh behavior deterministically before any background scheduler is added.

Do not start the background poll loop, desktop UI, outbound publishing, multi-provider framework, Codex launch/relaunch, Architect rollover, scheduler/workflow engine, or a database in the same milestone.

Do not redesign accepted core/inbound/auth behavior unless direct regression evidence proves a defect.

