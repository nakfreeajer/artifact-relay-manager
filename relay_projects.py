"""Machine-readable management CLI for the local Relay project registry."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from project_registry import ProjectRegistry, ProjectRegistryError, default_registry_path


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    add = commands.add_parser("add")
    add.add_argument("--project-id", required=True)
    add.add_argument("--display-name", required=True)
    add.add_argument("--config", required=True, type=Path)
    add.add_argument("--state", required=True, type=Path)
    add.add_argument("--disabled", action="store_true")
    for name in ("show", "enable", "disable", "remove"):
        command = commands.add_parser(name)
        command.add_argument("projectId")
    validate = commands.add_parser("validate")
    validate.add_argument("projectId", nargs="?")
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        registry = ProjectRegistry(args.registry or default_registry_path())
        if args.command == "list":
            result = {"result": "VALID", "projects": registry.list()}
        elif args.command == "add":
            registry.add(args.project_id, args.display_name, args.config, args.state, not args.disabled)
            result = {"result": "ADDED", "project": registry.show(args.project_id)}
        elif args.command == "show":
            result = {"result": "VALID", "project": registry.show(args.projectId)}
        elif args.command == "enable":
            registry.set_enabled(args.projectId, True)
            result = {"result": "ENABLED", "project": registry.show(args.projectId)}
        elif args.command == "disable":
            registry.set_enabled(args.projectId, False)
            result = {"result": "DISABLED", "project": registry.show(args.projectId)}
        elif args.command == "remove":
            registry.remove(args.projectId)
            result = {"result": "REMOVED", "projectId": args.projectId}
        else:
            projects = registry.validate(args.projectId)
            result = {"result": "VALID", "projects": projects}
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 0
    except ProjectRegistryError as exc:
        print(json.dumps({"error": str(exc)}, sort_keys=True, separators=(",", ":")))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
