# Current State

Project: `artifact-relay-manager`

Status: `RELAY.GDRIVE.INBOUND.1A` is accepted on branch `gdrive-inbound-1a`.

Accepted Relay core:
- exact-byte SHA-256 and byte length;
- deterministic normalized event identity;
- project/repository identity fail-closed checks;
- durable persistence before Watcher delivery;
- Watcher acknowledgement recording;
- duplicate suppression;
- pending retention and restart-safe retry;
- semantic persisted-state validation before retry.

Accepted Google Drive inbound capabilities:
- one-shot polling of direct children from one explicitly configured Drive folder;
- exactly one raw `.relay-project.json` identity file required;
- projectId/repository identity hard-stop enforcement;
- Drive file `id` as provider item identity;
- Drive `File.version` as provider version identity;
- exact raw-byte download and atomic local staging;
- 1 MiB artifact bound;
- native Google Workspace files skipped rather than exported/normalized;
- post-download metadata recheck binds downloaded bytes to the listed file version, size, parent, MIME/state and download capability;
- final Drive identity revalidation before Watcher delivery;
- token kept in `RELAY_GDRIVE_ACCESS_TOKEN`, not tracked config/state/output;
- production API origin fixed to Google Drive v3; loopback override is test-only.

Accepted Drive commits:
- `a1557e9c87c72e76243f5cebf1b59c9875ff472f` — Google Drive inbound adapter.
- `23fa8b9142f798fa22de50ae4cfe8e1624576794` — bind downloaded bytes to provider version and revalidate identity before delivery.

Final deterministic validation reported by Executor and independently source-reviewed by Architect:
- 29/29 unit tests passed;
- Python compile checks passed;
- fake-Drive CLI lifecycle demo passed;
- original core CLI demo passed;
- `git diff --check` passed.

Live qualification:
- `LIVE_VALIDATION_BLOCKED=credentials_not_supplied`;
- no live Drive request was made;
- this does not invalidate deterministic milestone acceptance because live access was explicitly optional and separately reported.

Current limitations:
- bearer access token must be supplied externally;
- no OAuth/login/refresh workflow;
- no background poll loop or scheduler;
- no Drive Changes cursor;
- no desktop UI;
- no outbound Drive publishing;
- no recursive/Drive-wide discovery;
- no native Workspace export;
- no multi-provider framework;
- no project-Orchestrator workflow authority.

Next engineering direction:
- add the smallest secure Google Drive authentication/session bootstrap and perform the first bounded live read-only qualification against one explicitly configured test folder;
- preserve the accepted one-shot adapter and core semantics;
- do not add scheduler/UI/provider-framework complexity until authentication and live read-only qualification are proven.
