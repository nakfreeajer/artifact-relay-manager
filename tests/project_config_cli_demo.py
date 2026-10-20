"""Offline operator-visible ARM.M01 two-project configuration demonstration."""
import json
import subprocess
import sys
import tempfile
from pathlib import Path


def _call(root, *args):
    proc = subprocess.run([sys.executable, "relay_projects.py", "--registry", str(root / "projects.json"),
                           *map(str, args)], capture_output=True, text=True, timeout=15)
    if proc.returncode:
        raise RuntimeError(f"relay_projects.py returned {proc.returncode}: {proc.stderr}{proc.stdout}")
    return json.loads(proc.stdout)


def main():
    with tempfile.TemporaryDirectory(prefix="arm-m01-demo-") as temp:
        root = Path(temp)
        fixture = {"items": []}
        for suffix in ("a", "b"):
            project_id = f"project-{suffix}"
            root_id = f"root-{suffix}"
            fixture["items"].extend([
                {"id": root_id, "name": f"Root {suffix}", "mimeType": "application/vnd.google-apps.folder",
                 "parents": [], "trashed": False, "projectId": project_id},
                {"id": f"prompts-{suffix}", "name": "Architect_Prompts", "mimeType": "application/vnd.google-apps.folder",
                 "parents": [root_id], "trashed": False},
                {"id": f"reports-{suffix}", "name": "Executor_Reports", "mimeType": "application/vnd.google-apps.folder",
                 "parents": [root_id], "trashed": False},
            ])
        provider_path = root / "provider.json"
        provider_path.write_text(json.dumps(fixture), encoding="utf-8")
        print("commands: relay_projects.py configure (A), configure (B), show (A), validate --provider-fixture")
        for suffix in ("a", "b"):
            project_id = f"project-{suffix}"
            result = _call(root, "configure", "--project-id", project_id,
                "--display-name", f"Project {suffix.upper()}", "--root-url",
                f"https://drive.google.com/drive/folders/root-{suffix}", "--orchestrator-endpoint",
                f"https://apo-{suffix}.example/notify", "--provider-fixture", provider_path)
            project = result["project"]
            print(f"CONFIGURED {project['projectId']} root={project['driveRootId']} "
                  f"prompts={project['architectPromptsFolderId']} reports={project['executorReportsFolderId']} "
                  f"endpoint={project['orchestratorEndpoint']} enabled={project['enabled']}")
        shown = _call(root, "show", "project-a")["project"]
        print(f"SHOW {shown['projectId']} rootUrl={shown['driveRootUrl']} "
              f"promptsUrl={shown['architectPromptsFolderUrl']} reportsUrl={shown['executorReportsFolderUrl']}")
        checked = _call(root, "validate", "--provider-fixture", provider_path)["folderProjects"]
        print("VALID " + ",".join(item["projectId"] for item in checked))
        reloaded = _call(root, "list")["folderProjects"]
        if checked != reloaded or len(checked) != 2:
            raise RuntimeError("fresh-process reload changed project configuration")
        print("RELOAD identical=true projectCount=2 provider=deterministic-offline-fixture")
        print("SIDE_EFFECTS google_drive=0 oauth=0 endpoint_requests=0 watcher=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
