# Project History

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
