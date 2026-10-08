# Bugs and Lessons

Record durable lessons backed by observed failures or demonstrated failure modes.

Do not promote speculative concerns into permanent complexity.

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
