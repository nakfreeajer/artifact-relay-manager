# Project History

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
