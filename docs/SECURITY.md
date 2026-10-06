# Security and Safety Boundaries

## Credentials

Provider credentials/tokens are local Relay Service secrets.

They must not be:
- committed to Git;
- written into project artifacts;
- sent to project Watchers;
- included in ordinary logs.

Use the platform's secure credential storage where available.

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
