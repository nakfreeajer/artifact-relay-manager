# Decisions

## D-001 — Relay is transport-only
Artifact Relay Manager transports and monitors bounded artifacts/events. Workflow authority remains outside Relay.

## D-002 — Google Drive first
The first provider is Google Drive. Multi-provider expansion is deferred.

## D-003 — Project isolation fails closed
Every configured project binds project identity, repository identity, provider folder, local workspace and Watcher endpoint. Identity mismatch blocks delivery.

## D-004 — At-least-once transport
Relay delivery may repeat after restart/retry. Exactly-once workflow effects are owned by the project Watcher / Orchestrator.

## D-005 — No speculative database
MVP local state uses simple durable local files. Add SQLite or another database only after demonstrated runtime or measured scale need.

## D-006 — Raw evidence stays local
`.agent-work/` is ignored. Only bounded sanitized bridge/outbox artifacts may be published.
