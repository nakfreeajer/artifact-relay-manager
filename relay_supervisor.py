"""Run the foreground sequential multi-project Relay supervisor."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import relay
import project_supervisor
from project_registry import ProjectRegistryError


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    run = commands.add_parser("run")
    run.add_argument("--interval-seconds", type=int, default=30)
    run.add_argument("--max-cycles", type=int)
    args = parser.parse_args(argv)
    try:
        return project_supervisor.run_cli(args.registry, args.interval_seconds, args.max_cycles)
    except (relay.RelayError, ProjectRegistryError) as exc:
        print(json.dumps({"error": str(exc)}, sort_keys=True, separators=(",", ":")))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
