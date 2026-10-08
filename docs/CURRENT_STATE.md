# Current State

Project: `artifact-relay-manager`

Status: `RELAY.GDRIVE.AUTH.SESSION.1A` is implemented on branch `gdrive-auth-session-1a`; it is not merged to `main`.

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
- `18d8d45c4ad505651f6ac4ef7f47165c0d068555` â€” ephemeral Drive OAuth and read-only qualification.
- `eb3339a452badc14e9fb05668a96f128efbb03a2` â€” script-mode Drive/Auth error identity correction, verified with subprocess tests.

`RELAY.GDRIVE.AUTH.SESSION.1A` adds a Windows current-user DPAPI protected refresh-token session. The deterministic suite and real read-only qualification verify fresh-process refresh reuse without reopening the browser. The protected file contains only the refresh token payload; client/scope identity is hashed into its filename and bound as DPAPI entropy. `reset-drive-auth` removes only that local session.
Implementation commit: `c479aa1488aacf470562a236090ae10d305d7ef8`.

Deterministic validation:
- 42/42 unit tests passed, including subprocess checks for HTTP 403, missing OAuth client configuration, and successful qualification;
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
- the script-mode correction was qualified locally with a deterministic fake Drive endpoint; the previously recorded real qualification result remains unchanged.

Current limitations:
- persistent OAuth session storage is Windows-only and tied to the current Windows user profile;
- reset removes the local token but does not revoke authorization at Google;
- refresh failure is sanitized and keeps the existing session; recovery requires explicit operator action such as reset and browser reauthorization;
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
- preserve the bounded Windows protected-session behavior while addressing future platform support only in a separately scoped milestone;
- keep scheduler, UI, outbound publishing and provider expansion out of scope until separately authorized.

