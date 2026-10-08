# Current State

Project: `artifact-relay-manager`

Status: `RELAY.GDRIVE.AUTH.LIVE.1A` is accepted on branch `gdrive-auth-live-1a` and awaiting merge to `main`.

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
- production API origin fixed to Google Drive v3; loopback override is test-only.

Accepted Google Drive authentication / qualification capabilities:
- installed desktop OAuth flow through the system browser;
- ephemeral `127.0.0.1` callback port;
- exact OAuth scope `https://www.googleapis.com/auth/drive.readonly`;
- OAuth client configuration supplied only from local `RELAY_GDRIVE_OAUTH_CLIENT_FILE`;
- access/refresh credentials remain in process memory only and are not serialized by Relay;
- `qualify-drive` validates one deliberately designated raw direct-child artifact;
- qualification reuses exact-byte, provider-version, parent/state and project-identity consistency checks;
- qualification creates no Watcher event, no Relay delivery state and performs no Drive mutation.

Accepted authentication implementation commit:
- `18d8d45c4ad505651f6ac4ef7f47165c0d068555` — ephemeral Drive OAuth and read-only qualification.

Deterministic validation:
- 39/39 unit tests passed;
- Python compile checks passed;
- fake-Drive CLI lifecycle demo passed;
- original core CLI demo passed;
- `git diff --check` passed.

Real live qualification:
- result: `QUALIFIED_READ_ONLY`;
- designated artifact MIME: `text/plain`;
- byte length: `26`;
- Drive `File.version`: `3`;
- SHA-256: `839ffb1cf48ad91270f4a395847100e412501c823a63270162a56306b1cc8ecf`;
- the configured folder and artifact relationship was independently rechecked through connected Drive metadata;
- no Drive content was created, modified, renamed or deleted by the qualification command;
- no Watcher event or Relay state was created by qualification.

Observed live prerequisite failure before PASS:
- browser OAuth authorization succeeded while the first Drive API request returned HTTP 403;
- enabling Google Drive API in the same Google Cloud project as the Desktop OAuth client resolved the provider access failure.

Current limitations:
- OAuth session is ephemeral and requires browser authorization per authenticated run;
- no secure persistent credential/session store;
- `poll-drive` still retains the existing manual `RELAY_GDRIVE_ACCESS_TOKEN` path;
- no background poll loop or scheduler;
- no Drive Changes cursor;
- no desktop UI;
- no outbound Drive publishing;
- no recursive/Drive-wide discovery;
- no native Workspace export;
- no multi-provider framework;
- no project-Orchestrator workflow authority.

Next engineering direction:
- add the smallest secure persistent Google OAuth session mechanism so repeated one-shot Drive reads do not require browser authorization every run;
- preserve `drive.readonly`, project isolation, exact-byte/version binding and the accepted one-shot adapter;
- do not start scheduler/UI/provider-framework complexity until secure session persistence is independently proven.
