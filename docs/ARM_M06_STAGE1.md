# ARM.M06.S1 simulated end-to-end qualification

## Scope and disposition

This is an offline qualification candidate on `arm-v2-m06s1-simulated-e2e-offline-1a`, based on M02.1C `da2286649d15a376df58200094936fb2d45fd687`. It exercises the existing Drive-fixture → ARM detector/notification pipeline → simulated Orchestrator through the actual Windows Tk dashboard and detached M05 worker. It does not qualify production Drive or Orchestrator interoperability. At initial candidate preparation, D26 publication authority had not yet been established; later recovery results and publication disposition are recorded below.

The only runtime-adjacent change is an extension to `tests/arm_v2_dashboard_cli_demo.py` so the visible existing integration demonstration exercises both configured folder types for both projects. No product runtime source was changed.

## Offline acceptance matrix

| Requirement | Qualification evidence |
| --- | --- |
| Two watched folders per project | Visible dashboard demo records `PROMPT_CHANGED` and `REPORT_CHANGED` for A and B, including a moved-in direct-child report. |
| Project isolation | Each project's configured loopback receiver verifies its signed requests and project identity. Disabling B prevents further B requests while A continues. |
| Signed ACK | Relay verifies matching signed ACKs. Receiver-side unique-event counts and ACKed ledger records are asserted. |
| Durable retry and restart | One simulated receiver accepts then drops a response. The pending event remains persisted and a fresh worker retries the same event ID; duplicate observations do not create a second unique receiver effect. |
| Detached worker and GUI reattachment | Visible Tk dashboard starts and reattaches to the same worker PID; duplicate start does not create another worker. |
| Pause/Resume | Existing visible Pause/Resume demonstration verifies project and global pause, state preservation, fresh GUI reattachment, and same-ID retry/ACK after resume. |
| Shutdown | Worker stops cleanly and evidence asserts no worker remains. The inherited process demo also covers controller exit, worker-only crash recovery, safe stop, and restart. |
| Invalid persisted state | Visible UI refresh with a corrupt notification ledger fails closed, starts no worker, and does not mutate the registry. Edit/Remove controls remain visually enabled in this state, but callbacks do not open an edit dialog or mutate state. This UI affordance is a follow-up. |
| Offline boundary | Deterministic local fixture provider and two loopback simulated APOs only. No live Drive, OAuth/DPAPI session, real APO, public endpoint, or Windows startup/system setting. |

The visible dashboard's four-event matrix has A `PROMPT_CHANGED` + `REPORT_CHANGED` and B `PROMPT_CHANGED` + `REPORT_CHANGED`. B's ambiguous accepted-timeout event remains pending under event ID `m03-3d8fe0cfc7f434d9b069fa2209ba458c253350801a52b57979a3104bbf251dc8`; the existing Pause/Resume and detached-worker restart demonstrations separately verify retry and ACK of stable pending IDs, including `m03-d20ab0b353254edc4e31ef3b960d152713bbca5f60d0d3aac0cb12f055f1f406`.

## Validation

- `python -m unittest discover -s tests -v`: 182 run, 182 passed, 0 failures, 0 errors, 0 skips.
- `python -m py_compile tests/arm_v2_dashboard_cli_demo.py`: passed.
- Seven offline CLI demonstrations exited 0: project configuration, Drive change detection, notification/ACK, foreground cycle, detached UserHost process, visible Windows dashboard, and visible Windows Pause/Resume.
- `git diff --check`: passed.
- Detailed sanitized outputs and failed-attempt records are retained under ignored `.agent-work/milestones/ARM.M06.S1-SIMULATED-E2E-OFFLINE/evidence/20261022/`.

The complete suite includes a deterministic Windows DPAPI primitive round-trip test with disposable test data. No protected OAuth credential/session was read, changed, or reset. No task, service, startup entry, firewall, registry setting, or other Windows system configuration was changed.

## Known closure obligations

These observed gaps are not repaired in this bounded acceptance milestone and must be resolved or explicitly accepted before Release 1:

1. Dashboard status does not provide a per-project failed-delivery counter.
2. ACK metadata is retained indefinitely by the current notification ledger, while D27 calls for 90-day ACK retention; pending items must remain retained. Existing indefinite retention is safe against loss but does not satisfy the bounded-retention policy.
3. Adding a new unused project after existing detector/notification history is present is blocked by the current configuration gate; the current product flow needs a bounded way to add a project without rewriting existing history.
4. In invalid ledger state, Edit/Remove controls appear enabled although their callbacks fail closed. The visible state should communicate unavailable controls.

These are follow-up product/retention obligations, not evidence of failure in the exercised two-project transport path. No workflow decision, acceptance authority, or Orchestrator runtime behavior is implemented in ARM.

## Stage 2 prerequisites

Any real-provider/real-Orchestrator stage requires a separate instruction and Human authorization. Before it starts, record the isolated Drive test root and exact child folder IDs, consumer-safe credential policy, fixture-to-provider mapping, signed HTTPS destination and Human-approved issuer/authentication model, secret storage and rotation, network allowlist, real ACK semantics, and failure rollback. This candidate contains no credential, secret, production endpoint, or test artifact content and performs no provisioning or live access.

Historical governance remains unchanged: support STOP `TRIGGERED`, exact count `UNCERTAIN`, and five-milestone checkpoint `OVERDUE`.


## Final bounded recovery qualification — 2026-10-24

RECOVERY3/3 ran the visible dashboard test with read-only heartbeat diagnostics and unchanged acceptance predicates. The test passed; 37 heartbeat reads at line 782 were present, 1,059 bytes, valid JSON with required keys. The earlier RECOVERY2 failure remains unexplained because no heartbeat bytes were retained before its temporary fixture cleanup. No runtime or test behavior was changed.

The single full offline qualification passed 182/182 tests, all seven demos, changed-demo compilation, and direct `git diff --check`. The qualification runner's malformed Git command and its corrected direct result are both recorded in ignored evidence. The six authorized paths remained the only candidate paths; no credential, live provider, public network, or Windows system action occurred. M06.S1 remains pending independent Architect review and is not live-provider or Release 1 qualification.
