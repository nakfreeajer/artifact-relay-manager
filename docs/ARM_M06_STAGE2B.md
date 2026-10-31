# ARM.M06.S2B — Real Google Drive integration into Windows UserHost

**Project:** ARM
**Objective Lock:** ARM-OBJ-001 v1.0
**Authorization:** Human-approved, 2026-10-31
**Branch/base:** `arm-v2-amov5-agents-lock-1a` / `4b1fb78ccb4f0f8090991b2e4caa78037e3e88fc`

## Fixed milestone objective

> Enable ARM's existing Windows background host to monitor authorized real Google Drive folders using the qualified read-only provider, while preserving authenticated metadata-only delivery, durable ACK, project isolation, and manual startup.

## Scope and implementation

This CORE milestone closes the gap between the independently qualified S2A foreground runner and the M05 detached UserHost. The host has explicit `fixture` and `drive` provider modes. A legacy M05 schema-1 config without `providerMode` remains fixture mode; fixture mode still requires its local fixture and rejects OAuth environment inputs. Drive mode must be explicit and omits `providerFixturePath`.

Drive mode reuses `DriveAuthSession`, its existing current-Windows-user protected `drive.readonly` refresh-token session, `DriveClient`, `DriveMetadataProvider`, `project_folder_config.validate_project`, `ForegroundMonitor`, and the existing notification ledger/ACK contract. The OAuth client path comes only from `RELAY_GDRIVE_OAUTH_CLIENT_FILE`; the access token stays in memory. The mode has no browser or alternate-account fallback. Failed protected-session/token authentication terminates the worker fail-closed without provider fallback or notification dispatch.

Every real folder listing is bound to a project in the current registry and revalidates the root and exact configured direct-child folder IDs/names/parents through metadata calls. The host only permits the fixed Google Drive API host and Google OAuth token host over HTTPS/443 plus loopback HTTP for the simulated Orchestrator. Drive mode bypasses ambient proxy settings so OAuth and Drive traffic cannot be rerouted through an unapproved proxy. All Orchestrator entries still require loopback endpoints and `test:` HMAC references; no production resolver or remote destination is introduced.

An optional `maxMonitorObservations` setting is accepted only in explicit Drive mode and is limited to 1–6. Its state is durably bound to the host state identity and config digest and consumed before each poll, so process restart cannot reset the qualification bound. A crash after reservation consumes a cycle conservatively. Normal unbounded manual host operation omits this field. UserHost remains manually launched, detached, single-instance, heartbeat/ownership checked, pause aware and cooperatively stopped.

## Qualification status

**Executor qualification: PASS, pending independent Architect review.** Offline validation passed 189/189 tests, compilation, `git diff --check`, and four existing offline demonstrations. One qualification-controller import preflight aborted before receiver startup, UserHost launch, authentication or Drive requests; the failure is preserved as `preflight-abort-01.json`. The runner's ignored import root was corrected, then its import/syntax checks passed before the one actual live run.

The actual detached UserHost run passed on 2026-10-31. It established a silent cycle-1 baseline with zero events and receiver requests, paused the project, and resumed after the independent writer created one plain-text file under the approved `Architect_Prompts` folder. The worker verified the approved Drive root and direct-child identities through metadata, detected the new file as `PROMPT_CHANGED`/`ARRIVED`, delivered the metadata-only event to the loopback simulated receiver, persisted a matching authenticated ACK as `ACKED`, then stopped and restarted on the same state. The restart retained the same event identity and caused no second receiver request/effect. Four complete monitor observations were consumed against the durable six-observation cap. The exact disposable file was deleted by the independent Drive connector and a subsequent exact-ID metadata read returned `404 NOT_FOUND`. Both worker stops were cooperative, its OS lock was free, the receiver shut down, isolated local state was removed, and the local test source was removed.

Sanitized live evidence is `.agent-work/milestones/ARM.M06.S2B/evidence/live-userhost-qualification.json`, `simulated-receiver-receipts.json`, and `preflight-abort-01.json`. No OAuth client/session contents, token, test key, or document body is retained. The initial ignored controller source containing only a synthetic test key was removed after the run.

The live run qualifies the actual detached UserHost on the approved isolated prompt-folder path to a local simulated receiver. It does not qualify real/production Orchestrator interoperability, report-folder live event coverage, long-duration unattended OAuth, D27 retention, or full Release 1. This is an Executor candidate awaiting independent Architect acceptance; it is not published.

## Governance and boundary

- This advances the original product CORE capability; it does not change ARM-OBJ-001 v1.0 or make ARM a workflow controller.
- Historical support STOP: `TRIGGERED`; support count: `UNCERTAIN`; five-milestone CORE checkpoint: `OVERDUE`.
- M02.1D: `PARKED`; D27: `FROZEN`; real/production Orchestrator D21: `NOT AUTHORIZED`.
- No commit/push is authorized by this record. No merge, tag, release, service, scheduler, startup change, OAuth scope change, credential reset, production Orchestrator or Desktop Bridge activity is included.


## M06.S2B authentication propagation repair 1A (2026-10-31)

The bounded offline repair preserves `DriveAuthError` across the Drive folder-validation boundary in `arm_v2_userhost.py`; unrelated validation/provider exceptions remain sanitized as `UserHostError`. The existing ForegroundMonitor fatal-authentication path is unchanged. A regression injects a refresh failure after session construction and verifies terminal worker exit, sanitized status, safe lock release, no delivery, and preservation of the pre-existing pending notification. Ordinary provider errors retain bounded degraded-scan behavior.

Validation: focused regressions 4/4; UserHost and ForegroundMonitor modules 22/22; full unittest discovery 190/190; Python compilation and `git diff --check` passed. No live operation or Git publication occurred. This repair does not resolve the historical limitations in the live qualification record: a durable live ledger snapshot is unavailable, and overwritten M05 demonstration evidence is not reconstructed.
