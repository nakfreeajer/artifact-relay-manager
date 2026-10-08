# Bugs and Lessons

Record durable lessons backed by observed failures or demonstrated failure modes.

Do not promote speculative concerns into permanent complexity.

## Proven — OAuth success does not prove the Drive API is enabled
During the first real qualification, browser OAuth authorization completed successfully but the first Google Drive API request returned HTTP 403. Enabling Google Drive API in the same Google Cloud project as the Desktop OAuth client resolved the failure; the repeated read-only qualification then passed.

Permanent rule:
- treat OAuth authorization and provider API enablement as separate prerequisites;
- when browser auth succeeds but the first provider request is forbidden, verify the target API is enabled in the OAuth client's Cloud project before redesigning auth code;
- keep provider error reporting sanitized while preserving enough metadata to distinguish auth bootstrap from API-access failure.

## Proven — downloaded bytes must be rebound to provider version after download
The first passing Google Drive inbound adapter trusted `File.version` and size from `files.list`, then downloaded media later. A same-size file update between those requests could associate newer bytes with an older provider-version event identity.

Permanent rule:
- treat provider metadata and media retrieval as a snapshot that must be revalidated;
- after download, re-fetch metadata for the same file;
- require the same file ID, provider version, size, MIME type, configured parent, non-trashed state and download capability;
- fail closed before staging/delivery on mismatch;
- revalidate the project identity boundary again before Watcher delivery.

This protects the invariant that provider item identity + provider version identifies the exact bytes hashed and delivered.

## Proven — persisted transport state must be semantically revalidated before retry
A passing transport test suite initially allowed a structurally valid persisted event from another project to reach retry delivery because state validation was too shallow.

Permanent rule:
- before retry delivery, revalidate the normalized event structure;
- bind stored projectId to the active configured project;
- verify the stored dedupe tuple against projectId, provider item identity, provider version and event type;
- recompute and verify deterministic eventId;
- fail closed before any Watcher delivery on semantic mismatch.

This protects project isolation across restart/recovery, not only at first observation.

## Standing lessons
- reuse proven simple integrity/project-isolation patterns;
- do not reproduce legacy browser/recovery complexity inside Relay;
- passing happy-path tests are not enough for durable-state or provider-race paths;
- live provider access must be reported separately and never simulated or claimed when credentials are absent.
