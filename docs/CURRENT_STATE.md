# Current State

Project: `artifact-relay-manager`

Status: architecture/contracts plus AMO worktree scaffold exist. Runnable Relay implementation is not yet complete.

Current boundary:
- reusable Artifact Relay transport and monitoring;
- Google Drive first;
- project identity validation;
- bounded artifact hashing/transfer;
- normalized transport events;
- transport delivery/retry/acknowledgement;
- minimal configuration/health UI later.

Explicitly outside this repository:
- project-Orchestrator workflow engine;
- Executor launch authority;
- Architect rollover authority;
- product acceptance decisions;
- workflow retry authority.

Immediate engineering direction:
- implement the smallest runnable deterministic Relay transport vertical slice;
- use simple local durable files for MVP state;
- do not add SQLite without demonstrated need.
