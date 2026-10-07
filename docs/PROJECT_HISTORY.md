# Project History

## 2026-10-08 — RELAY.CORE.VERTICAL.1A accepted
Accepted the first runnable deterministic Artifact Relay transport core.

Implementation:
- exact-byte SHA-256 and byte-length capture;
- deterministic normalized event identity;
- project/repository identity fail-closed checks;
- durable event persistence before Watcher delivery;
- Watcher acknowledgement recording;
- duplicate suppression;
- pending delivery retention and restart-safe retry;
- semantic persisted-state validation before retry.

Independent Architect review found one cross-project retry gap after the first passing implementation. The same milestone was corrected so persisted event project identity, dedupe tuple, deterministic event ID and normalized event structure are all revalidated before delivery.

Accepted commits:
- `e77b8105a8be26418165479ca4f92ea6be0c8a33`
- `9b73f05e0919796093a327f220d4d6ea093eb783`

Final validation:
- 12 unit tests passed;
- compile checks passed;
- CLI lifecycle demonstration passed;
- `git diff --check` passed.

No SQLite, merge, tag, project-Orchestrator workflow authority, real Google Drive integration or UI was added.

## 2026-10-08 — AMO worktree scaffold
Established the reusable AMO working-folder scaffold for Artifact Relay Manager:
- tracked governance/memory documents;
- source-area placeholders matching the Relay package boundary;
- ignored `.agent-work/` bootstrap utility;
- no project-Orchestrator runtime internals.
