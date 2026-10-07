#!/usr/bin/env python3
"""Create the Git-ignored AMO working-evidence tree for this worktree."""

from __future__ import annotations

import argparse
from pathlib import Path

RELATIVE_DIRS = (
    ".agent-work/current",
    ".agent-work/discovery/sessions",
    ".agent-work/discovery/research",
    ".agent-work/discovery/decisions",
    ".agent-work/discovery/open-questions",
    ".agent-work/ideas/open",
    ".agent-work/ideas/accepted",
    ".agent-work/ideas/rejected",
    ".agent-work/ideas/implemented",
    ".agent-work/milestones",
    ".agent-work/transcripts/architect",
    ".agent-work/transcripts/executor",
    ".agent-work/reports/architect",
    ".agent-work/reports/executor",
    ".agent-work/artifacts",
    ".agent-work/bridge/outbox",
    ".agent-work/bridge/readback",
    ".agent-work/cache",
    ".agent-work/temp",
    ".agent-work/private",
)

def main() -> int:
    parser = argparse.ArgumentParser(description="Create Artifact Relay Manager AMO working folders.")
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository/worktree root (defaults to this script's repository).",
    )
    args = parser.parse_args()
    root = args.root.resolve()

    created = []
    existing = []
    for relative in RELATIVE_DIRS:
        path = root / relative
        if path.exists():
            existing.append(relative)
        else:
            path.mkdir(parents=True, exist_ok=True)
            created.append(relative)

    print(f"worktree_root={root}")
    print(f"created={len(created)}")
    for item in created:
        print(f"CREATE {item}")
    print(f"existing={len(existing)}")
    for item in existing:
        print(f"EXISTS {item}")
    print("orchestrator_runtime_dirs=0")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
