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
- registry milestone provided the data store; `RELAY.PROJECT.SUPERVISOR.1A` adds the foreground consumer below.

Source/tests commit: `6848633a69aba57b5b8f86596c5ccecce6d3c664`.
Validation: 82/82 unit tests passed; changed Python files compiled; Drive and core CLI demos and `git diff --check` passed. Six-command local qualification passed in separate CLI processes. Evidence is in the ignored `.agent-work/milestones/RELAY.PROJECT.REGISTRY.1A/evidence/` directory.

### RELAY.PROJECT.SUPERVISOR.1A
Implemented on branch `project-supervisor-1a`:
- `relay_supervisor.py [--registry <path>] run --interval-seconds 30 [--max-cycles N]` runs a foreground sequential supervisor;
- registry is loaded and strictly validated fresh at each cycle boundary; enabled projects execute in deterministic projectId order;
- one shared in-memory noninteractive DriveAuthSession is reused across enabled projects and cycles;
- project-local failures are isolated; shared auth failure degrades the current and remaining projects for that cycle;
- enable/disable/add/remove changes take effect on the next cycle;
- local two-project qualification passed with separate configs, state paths, workspaces and Drive folder identities; shared auth refreshed once and the mock Watcher received one stable event per project;
- live one-project supervisor qualification passed on 2026-10-08 using the existing protected session. Two cycles returned OK: cycle 1 delivered the current designated file once and cycle 2 deduplicated it. The file was version `3`, 26 bytes, SHA-256 `839ffb1cf48ad91270f4a395847100e412501c823a63270162a56306b1cc8ecf`; one acknowledged state event and one local mock Watcher receipt shared event ID `relay-02471a4ffcf9a90b6ee27824533420ebda3c7f3a93d13b1e88c6525438a76ae9`. The protected session remained usable afterward; no browser opened and no Drive mutation occurred. Sanitized evidence is in ignored `.agent-work/milestones/RELAY.PROJECT.SUPERVISOR.1A/evidence/live-supervisor-qualification.json`.

Source/tests commit: `fbee2f5bd97a7b5f252cccc6a81800c17ecbbd60`.
Validation: 97/97 tests passed; changed Python files compiled; both existing CLI demos, the dedicated supervisor qualification, and `git diff --check` passed. Evidence is in the ignored `.agent-work/milestones/RELAY.PROJECT.SUPERVISOR.1A/evidence/` directory.

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

Limitations of `monitor-drive`: one configured project per process. The separate foreground supervisor executes enabled projects sequentially. The per-user UserHost process host reuses that supervisor. A manual triggerless Task Scheduler qualification later proved task-context protected-session Drive reads, one acknowledged local mock Watcher delivery, and deduplication on the next cycle. It does not configure a persistent task. Automatic sign-in startup, sign-out behavior, and Scheduler crash/restart recovery remain unqualified. No Windows Service is qualified. UI, outbound publishing, multi-provider framework, database, and project-Orchestrator authority remain outside this branch.

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

`RELAY.PROJECT.SUPERVISOR.1A` is implemented on `main` at source/tests commit `fbee2f5bd97a7b5f252cccc6a81800c17ecbbd60`. `RELAY.WINDOWS.USERHOST.1A` was implemented from baseline `2b0e316ac347a769ce61b26fc6344528efeab168` at `34ad80ed6110393500deabe19271f40a18d762d6`; its implementation and initial documentation closure were Architect-accepted. A later live qualification passed using one temporary triggerless task: two task-context supervisor cycles read the approved Drive artifact using the current-user protected session, delivered once to a local mock Watcher, and deduplicated on cycle 2. The exact task was ownership-verified, removed, and confirmed absent by COM and `schtasks`; no persistent task exists. Automatic sign-in startup, sign-out behavior, Scheduler crash/restart recovery, and Windows Service operation remain unqualified. See `docs/VALIDATION.md` and `docs/WINDOWS_USERHOST.md` for evidence and limits.

Architectural guardrails:
- Relay transports and monitors; Watcher / Orchestrator decides.
- Do not add a scheduler/workflow engine, UI, service management API, outbound publishing, provider framework, database, Windows Service, or persistent/automatic Task Scheduler deployment unless explicitly selected in a bounded milestone. The per-user launcher is a process host only; its one-shot manual Scheduler qualification did not add a persistent task. Relay still transports and monitors while the Watcher decides.


## ARM Charter v1.0-RC1 adoption preparation (2026-10-13)

This section records the human-approved ARM Charter v1.0-RC1 and its local documentation adoption authorized on 2026-10-13. CORE-07 raw outbound artifact publishing is mandatory Release 1 scope. The four-file candidate was prepared in ignored `.agent-work/milestones/ARM.CHARTER.1.0-RC1.DOCUMENTATION.PREPARATION/evidence/20261013/`, reviewed, and applied locally under the one-time authorization. Preparation itself made no tracked changes; this adoption is documentation-only and makes no claim of commit, push, or release.

### Baseline and capability status

Preparation was performed against `main` at `e5d7c288e87f500d9941b9728c7b88876d178a26`, also the locally recorded `origin/main` ref at inspection. The worktree was clean. The accepted bounded Google Drive → Relay → local mock Watcher qualification is present in main. CORE-01 through CORE-04 have accepted bounded implementations; CORE-05 is partial and unattended natural-sign-in/Scheduler/Service lifecycle is unqualified; CORE-06 desktop UI and CORE-07 outbound raw publishing are not implemented; CORE-08 has partial security/isolation controls but incomplete unattended lifecycle qualification. See `docs/PROJECT_BRIEF.md` for the Release 1 definition of done.

The local `windows-userhost-1a` tip `7d4e806c8647f8c75d9f25b1404e220c28898049` is an ancestor of main, despite stale README language calling that work unmerged. The `windows-service-1a` tip `0b0b070ef3fdbc0bcda205a4f9c962618d3e4a20` is not an ancestor of main (merge base `2b0e316ac347a769ce61b26fc6344528efeab168`); do not describe Windows Service as deployed. The stale README statement is identified for a later bounded documentation correction; README is outside this four-file proposal.

### AUTOSTART 1B authorization evidence and support-streak reconciliation

The F47 report records `BLOCKED_PREFLIGHT` on 2026-10-13 and states that task registration and fresh authorization consumption did not occur. Inspection of retained ignored evidence found the F37 consumed marker at `evidence/AUTOSTART1B-20261011-LOGON-5F914FBB/registration-attempt-consumed.json`, SHA-256 `79df105818316e813b7ba5d71547705ff70562ba3458a1f7a1b5980fb38df7d1`, matching the recorded F39 reference. The F39 marker remains present with SHA-256 `4b39e3088519203941da310cfd37b5a1517884bb7e4adaa7a97ee9cf53c8a82e`. Some later F45/F46/F47 narrative described the F37 marker as absent; this conflicts with the inspected retained artifact. Neither marker was changed, reconstructed, reset, or consumed during this preparation. F48 read-only reconciliation remains pending.

The Charter instruction says the two-consecutive-`BLOCKER` stop threshold has already triggered. Retained records include a F39 `BLOCKED_DEFINITION` result (23/25 definition checks) and F47 `BLOCKED_PREFLIGHT`. F40–F46 include offline, synthetic, and partial qualification work; current retained evidence does not establish that F39 and F47 were consecutive qualifying `BLOCKER` outcomes under one consistent ledger. Therefore the exact contiguous streak is **unresolved**. Preserve the conservative stop condition; do not reset the streak, declare it cleared, or invent a definitive count. F47 did not register or remove a Scheduler task in its attempt. No Scheduler action was performed for this documentation preparation.

The recent F43–F47 work is qualification and planning, not accepted CORE capability progress. At least five milestones have elapsed without evidence of a newly accepted CORE capability; conduct the Charter’s five-milestone review before authorizing further supporting work.

### Next-session guardrails

- Local application of the reviewed four-file patch is complete under the bounded authorization. Commit or push requires separate Architect review; no such action is authorized here.
- Keep CORE-07 in Release 1 minimum scope; read-only OAuth scope does not authorize upload. No scope change or credential operation is authorized here.
- Preserve both consumed authorization records and the unresolved F37 narrative conflict. F48 remains pending.
- No Scheduler registration, mutation, or execution; no UserHost runtime; no OAuth/DPAPI/Drive/Watcher operations or live monitoring were performed for this preparation.
- Do not infer workflow meaning from artifact content or introduce Project-Orchestrator runtime authority into Relay.


### Persistent five-milestone checkpoint record

- **Most recent stage/result:** `ARM.CHARTER.1.0-RC1.DOCUMENTATION.ADOPTION`; the four documentation files were applied locally. No source change or product capability advancement.
- **Independently verified CORE advancement since the prior checkpoint:** none established by this documentation-preparation stage.
- **Continuous support-milestone streak:** threshold `TRIGGERED`; exact count/consecutiveness `UNCERTAIN`. Evidence source: the human-approved charter instruction says the two-or-more threshold is triggered; retained F39 `BLOCKED_DEFINITION` and F47 `BLOCKED_PREFLIGHT` records are separated by F40–F46 offline/synthetic/partial work without a consistent chronological ledger. Do not infer an exact streak or reset it.
- **Five-milestone review:** `OVERDUE / DUE BEFORE ANY FURTHER SUPPORT WORK`. Last/next canonical milestone IDs are not reliably available in the retained ledger; do not fabricate them. Resolve against a source-backed milestone chronology at the checkpoint.
- **Outstanding Human-approved exception:** the one-time bootstrap exception authorized preparation and local application of this reviewed four-file patch only; it is exhausted. It does not authorize commit, push, or further support work. No additional exception is recorded.
- **AUTOSTART state:** F47 remains `BLOCKED_PREFLIGHT`; no task registration or fresh authorization consumption occurred. F48 remains pending read-only authorization-history reconciliation. F37/F39 consumed markers remain unchanged; no marker was reconstructed or reset.
- **Stage boundary:** patch preparation and local documentation adoption only. This record asserts no Scheduler qualification, deployment completion, source merge, or CORE advancement.
