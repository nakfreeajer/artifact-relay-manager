"""Machine-readable management CLI for the local Relay project registry."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from project_registry import ProjectRegistry, ProjectRegistryError, default_registry_path
from project_folder_config import FakeDriveProvider, FolderConfigError


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
    configure = commands.add_parser("configure")
    configure.add_argument("--project-id", required=True)
    configure.add_argument("--display-name", required=True)
    configure.add_argument("--root-url", required=True)
    configure.add_argument("--prompts-folder-id")
    configure.add_argument("--reports-folder-id")
    configure.add_argument("--orchestrator-endpoint", required=True)
    configure.add_argument("--provider-fixture", required=True, type=Path)
    configure.add_argument("--repository")
    configure.add_argument("--workspace")
    configure.add_argument("--secret-ref")
    configure.add_argument("--enabled", action="store_true")
    for name in ("show", "enable", "disable", "remove"):
        command = commands.add_parser(name)
        command.add_argument("projectId")
    validate = commands.add_parser("validate")
    validate.add_argument("projectId", nargs="?")
    validate.add_argument("--provider-fixture", type=Path)
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        registry = ProjectRegistry(args.registry or default_registry_path())
        if args.command == "list":
            document = registry.load()
            result = {"result": "VALID", "projects": document["projects"],
                      "folderProjects": document["folderProjects"]}
        elif args.command == "add":
            registry.add(args.project_id, args.display_name, args.config, args.state, not args.disabled)
            result = {"result": "ADDED", "project": registry.show(args.project_id)}
        elif args.command == "configure":
            provider = FakeDriveProvider.from_path(args.provider_fixture)
            project = registry.configure_folder_project(project_id=args.project_id,
                display_name=args.display_name, root_url=args.root_url,
                prompts_id=args.prompts_folder_id, reports_id=args.reports_folder_id,
                endpoint=args.orchestrator_endpoint, provider=provider,
                repository=args.repository, workspace=args.workspace,
                secret_ref=args.secret_ref, enabled=args.enabled)
            result = {"result": "CONFIGURED", "project": project}
        elif args.command == "show":
            try:
                project = registry.show(args.projectId)
            except ProjectRegistryError:
                project = registry.show_folder_project(args.projectId)
            result = {"result": "VALID", "project": project}
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
            if args.provider_fixture:
                provider = FakeDriveProvider.from_path(args.provider_fixture)
                projects = registry.validate_folder_projects(provider, args.projectId)
                result = {"result": "VALID", "folderProjects": projects}
            else:
                projects = registry.validate(args.projectId)
                result = {"result": "VALID", "projects": projects}
        print(json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        return 0
    except (ProjectRegistryError, FolderConfigError) as exc:
        print(json.dumps({"error": str(exc)}, sort_keys=True, separators=(",", ":")))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
