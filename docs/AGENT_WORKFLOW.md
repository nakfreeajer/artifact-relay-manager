# Agent Workflow

## Roles
Human Owner: final authority.

Architect-Curator: architecture, bounded milestone design, independent review and official knowledge preservation.

Executor: bounded repository inspection, implementation, testing and evidence production.

Artifact Relay Manager: transport infrastructure only.

## Worktree startup
Run:

```bash
python tools/bootstrap_agent_work.py
```

Raw working evidence:
- `.agent-work/transcripts/architect/`
- `.agent-work/transcripts/executor/`
- `.agent-work/reports/architect/`
- `.agent-work/reports/executor/`
- `.agent-work/milestones/`
- `.agent-work/artifacts/`

Bounded publication:
- `.agent-work/bridge/outbox/`
- `.agent-work/bridge/readback/`

## Scope rule
One bounded milestone at a time. New ideas do not automatically expand active implementation scope.

## Evidence rule
Executor claims are not acceptance. Preserve exact hashes, byte lengths, repository identity and validation evidence.
