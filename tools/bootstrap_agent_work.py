#!/usr/bin/env python3
"""Create the Git-ignored AMO working-evidence tree for this worktree."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

BASE_DIRS = (
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

MILESTONE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def milestone_dirs(milestone_id: str) -> tuple[str, ...]:
    if not MILESTONE_ID_RE.fullmatch(milestone_id):
        raise ValueError(
            "invalid milestone id; use only letters, numbers, dot, underscore, and hyphen"
        )

    base = f".agent-work/milestones/{milestone_id}"
    return (
        base,
        f"{base}/scope",
        f"{base}/evidence",
        f"{base}/decisions",
    )


def ensure_dirs(root: Path, relative_dirs: tuple[str, ...]) -> tuple[list[str], list[str]]:
    created: list[str] = []
    existing: list[str] = []

    for relative in relative_dirs:
        path = root / relative
        if path.exists():
            if not path.is_dir():
                raise RuntimeError(f"expected directory but found non-directory: {path}")
            existing.append(relative)
            continue

        path.mkdir(parents=True, exist_ok=False)
        created.append(relative)

    return created, existing


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create Artifact Relay Manager AMO working folders."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="Repository/worktree root (defaults to this script's repository).",
    )
    parser.add_argument(
        "--milestone",
        metavar="MILESTONE_ID",
        help=(
            "Also create .agent-work/milestones/<id>/{scope,evidence,decisions}. "
            "Example: --milestone RELAY.CORE.VERTICAL.1A"
        ),
    )
    args = parser.parse_args()

    root = args.root.resolve()

    relative_dirs = list(BASE_DIRS)
    if args.milestone:
        try:
            relative_dirs.extend(milestone_dirs(args.milestone))
        except ValueError as exc:
            parser.error(str(exc))

    created, existing = ensure_dirs(root, tuple(relative_dirs))

    print(f"worktree_root={root}")
    if args.milestone:
        print(f"milestone={args.milestone}")
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
