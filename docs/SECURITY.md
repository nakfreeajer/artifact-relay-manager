# Security and Safety Boundaries

## Credentials

Provider credentials/tokens are local Relay Service secrets.

They must not be:
- committed to Git;
- written into project artifacts;
- sent to project Watchers;
- included in ordinary logs.

Use the platform's secure credential storage where available.

### Current Google Drive authentication posture

The accepted live qualification uses an installed desktop OAuth client with exactly `https://www.googleapis.com/auth/drive.readonly`.

Current credential handling is deliberately ephemeral:
- the OAuth client JSON is supplied from local `RELAY_GDRIVE_OAUTH_CLIENT_FILE` outside Git;
- the authorization flow uses the system browser and an ephemeral `127.0.0.1` callback;
- access and refresh credentials remain in process memory only;
- Relay does not serialize a token cache yet.

A future persistent-session milestone must use protected local credential storage rather than a plaintext token file and must preserve the same no-log/no-artifact/no-Watcher-secret boundary.

## Folder scope

A project monitors only its explicitly configured Drive root.

Do not perform broad Drive-wide workflow discovery after configuration.

Folder selection may browse accessible folders in the UI, but runtime monitoring is scoped by stored folder identity.

## Project identity

Before monitoring is enabled, require the Drive root identity artifact to match configured projectId.

Identity mismatch is a hard stop for that project stream.

## Artifact integrity

For downloaded/uploaded workflow artifacts record and verify:
- SHA-256;
- byte length;
- provider version where available.

A hash/size mismatch must be surfaced as an integrity error; do not silently normalize or replace bytes.

## Logging

Default logs contain metadata, not prompt/result bodies.

Sensitive or private source content must not be included merely for diagnostics.

Diagnostic export should make the inclusion of content explicit and opt-in.

## Local interface

Watcher endpoint communication should default to loopback/local IPC unless a future explicit remote-control design is approved.

A project configuration must not be able to redirect another project's events.

## Authority boundary

Relay Manager does not:
- authorize Executor launch;
- accept/reject implementation;
- choose Architect generations;
- decide rollover priority;
- grant retry authority.

Compromise or malfunction of the Relay should therefore not be sufficient by itself to authorize source mutation; project Watcher validation remains mandatory.
