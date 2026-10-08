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
Add the smallest secure Google Drive authentication/session bootstrap and perform the first real read-only qualification against one explicitly configured test folder.

Keep this bounded:
- obtain/use a Drive access token without committing credentials;
- support the existing one-shot adapter;
- qualify folder metadata, identity read, direct-child listing and one deliberately designated small raw test artifact;
- preserve exact-byte/version binding and zero Drive mutation.

Do not start the background poll loop, desktop UI, outbound publishing, multi-provider framework, Codex launch/relaunch, Architect rollover, scheduler/workflow engine, or a database in the same milestone.

Do not redesign accepted core/inbound behavior unless direct regression evidence proves a defect.
