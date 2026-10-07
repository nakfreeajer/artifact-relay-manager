# Current State

Project: `artifact-relay-manager`

Status: `RELAY.CORE.VERTICAL.1A` is accepted on branch `relay-core-vertical-1a`.

Accepted Relay core capabilities:
- configured project identity and repository identity are enforced;
- bounded artifact bytes are hashed exactly with SHA-256 and byte length;
- normalized Relay events use deterministic event IDs derived from the transport dedupe tuple;
- event state is persisted before Watcher delivery;
- Watcher acknowledgements are recorded;
- duplicate observations are bounded;
- unavailable Watcher delivery remains pending and retryable;
- fresh-process retry preserves the same event identity;
- persisted state is semantically revalidated before retry so cross-project or identity-corrupt events fail closed;
- local durable files are used; no SQLite was introduced.

Accepted implementation commits:
- `e77b8105a8be26418165479ca4f92ea6be0c8a33` — deterministic core transport vertical slice.
- `9b73f05e0919796093a327f220d4d6ea093eb783` — persisted-event validation before retry.

Validation reported by Executor and independently source-reviewed by Architect:
- 12/12 unit tests passed;
- Python compile checks passed;
- CLI lifecycle demo passed;
- `git diff --check` passed.

Current limitations:
- fixture/local observation only;
- no real Google Drive API/change monitoring yet;
- no desktop UI;
- no scheduler or provider framework;
- no IPv6 Watcher endpoint support;
- no project-Orchestrator workflow authority.

Next engineering direction:
- implement the real Google Drive inbound adapter as the next bounded Relay milestone;
- feed provider facts into the accepted 1A transport core rather than redesigning it;
- preserve exact project isolation, at-least-once transport and transport-only authority.
