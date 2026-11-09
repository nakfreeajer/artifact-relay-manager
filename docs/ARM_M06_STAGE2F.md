# ARM.M06.S2F — Remote-Capable Notification Transport

**Status:** Offline CORE candidate; awaiting Architect review. No Git publication or live remote integration has occurred.

The Human Owner authorized the separate current-Windows-user DPAPI-protected Orchestrator key store for this offline implementation. This permission does not authorize production credentials, live endpoints, deployment, or real network qualification.

**Fixed objective:** Extend the existing ARM Windows UserHost notification transport to support authenticated metadata-only notifications to a separately hosted HTTPS Orchestrator while preserving project isolation, durable pending state, authenticated ACK, retries and restart recovery.

## Scope and alignment

S2F advances ARM's original metadata-only notification capability through the existing M04 `NotificationSender` and the accepted M05/M06.S2B detached UserHost. It does not interpret event contents or own workflow decisions. Orchestrator interpretation, project workflow and downstream actions remain outside ARM.

## Transport selection and compatibility

The UserHost configuration may explicitly include `"notificationTransportMode":"https-remote"` only with `"providerMode":"drive"`. If the field is absent, transport remains `loopback`. Existing fixture and Drive-mode loopback configurations retain their HTTP loopback receiver and `test:` reference contract. Fixture mode cannot enable remote transport. A non-loopback destination fails closed unless the explicit mode is present and the destination is HTTPS on port 443 with a DNS hostname.

The remote option uses the same canonical event payload, HMAC request signature, matching signed ACK, durable ledger and bounded retries as loopback delivery. It adds the non-secret `secretRef` to newly persisted ledger entries so endpoint and key-reference changes fail closed for pending and acknowledged events. Existing loopback ledger entries without that field remain readable; old entries cannot be silently rebound to a remote key reference.

## Protected per-project HMAC keys

`arm_orchestrator_secrets.py` keeps Orchestrator key material separate from Google Drive OAuth sessions. It reuses the current-user `WindowsDpapi` primitive from `drive_session.py`, with domain-separated entropy bound to the exact project ID, secret reference and configured endpoint. Each create-only protected file is stored under `%LOCALAPPDATA%\ArtifactRelayManager\OrchestratorSecrets\`; the project registry, host configuration, notification ledger, logs and evidence contain only the non-secret reference and event metadata.

An operator can provision an existing key using a foreground console command:

```powershell
python arm_orchestrator_secrets.py --registry <absolute-local-registry.json> --ledger <absolute-local-ledger.json> --project-id <project-id>
```

The command prompts for the existing HMAC key twice with hidden input. It does not generate or share a key. It accepts only an `orchestrator:` reference bound to that project's HTTPS endpoint, requires the registry and ledger to be under current-user local data, refuses provisioning if that project has any pending or acknowledged ledger history, and creates the protected record without replacement. A missing, corrupt, mismatched or inaccessible DPAPI record fails closed. No key rotation, delete or reset operation is provided.

Offline tests inject a synthetic protector; they do not exercise production DPAPI or create a real protected credential.

## Remote destination controls

Remote destinations require explicit mode, HTTPS, a public DNS-style hostname, and port 443. IP literals, local/private naming suffixes, user information, query strings, fragments, malformed paths and non-HTTPS schemes are rejected. The worker's connection guard permits only configured remote hostname/443 pairs plus the existing provider allowlist and loopback. For configured remote hosts, DNS results are checked and every returned address must be globally routable before the original address list is used. This prevents private/loopback resolution and avoids a second unvalidated DNS lookup.

The HTTP opener uses an empty `ProxyHandler`, blocks redirects, and leaves Python's default certificate-chain and hostname verification enabled. Any redirect, transport uncertainty or invalid ACK remains durably pending. Destination and secret-reference changes that do not match stored notification bindings fail before delivery.

## Offline qualification and limitations

The synthetic qualification verifies signed metadata-only requests, matching ACK persistence, invalid ACK retention, same-event retry/restart, project-scoped key resolution, endpoint and reference binding, create-only provisioning, missing/corrupt key failure, HTTPS/TLS policy, DNS address rejection, proxy/redirect restrictions, explicit UserHost mode selection and fixture compatibility.

The final stable relevant batch passed 48/48 tests while explicitly excluding two Windows timing-sensitive M05 lifecycle tests. In the immediately preceding combined batch, one of those tests timed out at worker startup and the other completed; each then passed on one isolated run without source changes. Those failed combined results remain qualification exceptions and are not erased by the isolated passes. Full unittest discovery was not run for S2F. Python compilation and `git diff --check` results are recorded in `docs/VALIDATION.md` and the ignored S2F evidence bundle.

No external DNS lookup or HTTP(S) connection, real Orchestrator, production key, OAuth session, Drive request, deployment or CDB operation was used. Existing loopback tests used only their deterministic local simulated receivers. Current-user Windows DPAPI behavior, real TLS interoperability, operator key-sharing/contract ownership, production endpoint approval and D21 live integration remain unqualified and separately gated. D20/D21 authorization remains unchanged.

Historical governance remains: support STOP `TRIGGERED`, count `UNCERTAIN`, five-milestone CORE checkpoint `OVERDUE`, M02.1D `PARKED`, and D27 `FROZEN`.

