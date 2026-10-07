# Tools

For every fresh Git worktree run:

```bash
python tools/bootstrap_agent_work.py
```

When the active milestone is already known, create its AMO working folders at the same time:

```bash
python tools/bootstrap_agent_work.py --milestone RELAY.CORE.VERTICAL.1A
```

That adds:

```text
.agent-work/milestones/RELAY.CORE.VERTICAL.1A/
├── scope/
├── evidence/
└── decisions/
```

The command is idempotent: existing directories are reported rather than recreated. Milestone IDs are restricted to letters, numbers, dot, underscore, and hyphen so the option cannot escape the milestone workspace.

The bootstrap creates ignored AMO local evidence folders only. It does not create project-Orchestrator runtime state.
