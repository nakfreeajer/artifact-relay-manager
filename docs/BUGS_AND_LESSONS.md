# Bugs and Lessons

Record durable lessons backed by observed failures or demonstrated failure modes.

Do not promote speculative concerns into permanent complexity.

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
- passing happy-path tests are not enough for durable-state recovery paths; include semantic-corruption regressions where project isolation depends on persisted state.
