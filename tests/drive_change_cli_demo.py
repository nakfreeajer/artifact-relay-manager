"""Deterministic two-project, fresh-process CLI demonstration for M03."""
import os
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from project_folder_config import FakeDriveProvider
from project_registry import ProjectRegistry


def item(file_id, folder_id, version, checksum, name=None):
    return {"id": file_id, "name": name or file_id + ".bin", "mimeType": "application/octet-stream",
            "parents": [folder_id], "trashed": False, "version": str(version), "md5Checksum": checksum,
            "webViewLink": f"https://drive.google.com/file/d/{file_id}/view"}


def main():
    with tempfile.TemporaryDirectory(prefix="arm-m03-demo-") as temporary:
        root = Path(temporary)
        registry_path = root / "registry.json"
        registry = ProjectRegistry(registry_path)
        drive_items = []
        for project, suffix in (("project-a", "a"), ("project-b", "b")):
            root_id = f"root-{suffix}"
            drive_items.extend([
                {"id": root_id, "name": project, "mimeType": "application/vnd.google-apps.folder", "parents": [], "trashed": False, "projectId": project},
                {"id": f"prompts-{suffix}", "name": "Architect_Prompts", "mimeType": "application/vnd.google-apps.folder", "parents": [root_id], "trashed": False},
                {"id": f"reports-{suffix}", "name": "Executor_Reports", "mimeType": "application/vnd.google-apps.folder", "parents": [root_id], "trashed": False},
            ])
        provider = FakeDriveProvider({"items": drive_items})
        for project, suffix in (("project-a", "a"), ("project-b", "b")):
            registry.configure_folder_project(project_id=project, display_name=project,
                root_url=f"https://drive.google.com/drive/folders/root-{suffix}", prompts_id=None,
                reports_id=None, endpoint="https://apo.example/notify", provider=provider,
                repository=f"owner/{project}", enabled=False)
        folders = ("prompts-a", "reports-a", "prompts-b", "reports-b")
        base_items = {
            "prompts-a": [item("old-a", "prompts-a", 1, "a" * 32)],
            "reports-a": [item("report-a", "reports-a", 1, "b" * 32)],
            "prompts-b": [item("old-b", "prompts-b", 1, "c" * 32)],
            "reports-b": [item("report-b", "reports-b", 1, "d" * 32)],
        }
        state = root / "state.json"
        fixture_path = root / "provider.json"
        guard = root / "network-guard"
        guard.mkdir()
        (guard / "sitecustomize.py").write_text(
            "import socket, urllib.request\n"
            "def blocked(*args, **kwargs): raise RuntimeError('network disabled by M03 demo guard')\n"
            "urllib.request.urlopen = blocked\n"
            "socket.create_connection = blocked\n"
            "socket.socket.connect = blocked\n", encoding="utf-8")

        def run(label, items):
            fixture = {"folders": {folder: {"complete": True, "items": items.get(folder, [])} for folder in folders},
                       "fail": False}
            fixture_path.write_text(json.dumps(fixture, sort_keys=True), encoding="utf-8")
            environment = os.environ.copy()
            environment["PYTHONPATH"] = str(guard) + os.pathsep + environment.get("PYTHONPATH", "")
            proc = subprocess.run([sys.executable, "drive_change_detector.py", "--registry", str(registry_path),
                "--state", str(state), "--provider-fixture", str(fixture_path)], capture_output=True,
                text=True, timeout=15, env=environment)
            if proc.returncode != 0:
                raise RuntimeError(proc.stderr or proc.stdout)
            result = json.loads(proc.stdout)
            print(json.dumps({"step": label, "result": result["result"],
                              "newEventIds": [e["eventId"] for e in result["newEvents"]],
                              "newEventTypes": [e["eventType"] for e in result["newEvents"]],
                              "changeKinds": [e["changeKind"] for e in result["newEvents"]],
                              "totalEvents": result["totalEvents"], "ambiguousCount": result["ambiguousCount"]},
                             sort_keys=True, separators=(",", ":")))
            return result

        first = run("two-project-baseline", base_items)
        if first["newEvents"] or first["totalEvents"] != 0:
            raise AssertionError("baseline emitted an event")

        updated = json.loads(json.dumps(base_items))
        updated["prompts-a"][0] = item("old-a", "prompts-a", 2, "1" * 32)
        updated["prompts-a"].append(item("new-prompt-a", "prompts-a", 1, "e" * 32))
        updated["reports-b"].append(item("new-report-b", "reports-b", 1, "f" * 32))
        first = run("new-file-candidate-and-content-edit", updated)
        if [(e["projectId"], e["eventType"], e["changeKind"]) for e in first["newEvents"]] != [
                ("project-a", "PROMPT_CHANGED", "CONTENT_UPDATED")]:
            raise AssertionError("content update changed or candidate notified before stability")
        if first["candidateCount"] != 2:
            raise AssertionError("new and moved-in files were not held as candidates")

        arrived = run("stable-new-and-moved-in-arrivals", updated)
        expected = [("project-a", "PROMPT_CHANGED", "ARRIVED"),
                    ("project-b", "REPORT_CHANGED", "ARRIVED")]
        if [(e["projectId"], e["eventType"], e["changeKind"]) for e in arrived["newEvents"]] != expected:
            raise AssertionError("arrival classification or two-project isolation mismatch")
        first_arrival_ids = {e["fileId"]: e["eventId"] for e in arrived["newEvents"]}

        repeated = run("repeat-identical-observation", updated)
        if repeated["newEvents"] or repeated["totalEvents"] != 3:
            raise AssertionError("repeat was not deduplicated")

        renamed = json.loads(json.dumps(updated))
        renamed["prompts-a"][0] = item("old-a", "prompts-a", 8, "1" * 32, "renamed.bin")
        metadata = run("metadata-rename-version-only", renamed)
        if metadata["newEvents"]:
            raise AssertionError("metadata-only change emitted an event")

        moved_out = json.loads(json.dumps(updated))
        moved_out["reports-b"] = [x for x in moved_out["reports-b"] if x["id"] != "new-report-b"]
        departure = run("observed-departure", moved_out)
        if departure["newEvents"]:
            raise AssertionError("departure emitted an event")

        reentry = json.loads(json.dumps(updated))
        reentry_first = run("reentry-candidate", reentry)
        if reentry_first["newEvents"]:
            raise AssertionError("re-entry notified before stability")
        reentered = run("stable-reentry", reentry)
        b_arrival = next(e for e in reentered["newEvents"] if e["fileId"] == "new-report-b")
        if b_arrival["changeKind"] != "ARRIVED" or b_arrival["eventId"] == first_arrival_ids["new-report-b"]:
            raise AssertionError("re-entry did not get a distinct stable arrival identity")

        restarted = run("fresh-process-restart", reentry)
        if restarted["newEvents"] or restarted["totalEvents"] != 4:
            raise AssertionError("restart re-emitted events or lost persistent observations")
        persisted = json.loads(state.read_text(encoding="utf-8"))
        ids = [e["eventId"] for e in persisted["events"]]
        if len(ids) != len(set(ids)) or first_arrival_ids["new-report-b"] not in ids or b_arrival["eventId"] not in ids:
            raise AssertionError("arrival identities were not durably distinct")
        print(json.dumps({"demonstration": "PASS", "eventCount": 4, "freshProcessInvocations": 9,
                          "provider": "local-fixture", "networkCalls": 0, "networkGuard": "ENABLED", "bodyReads": 0,
                          "eventIdentitiesStableAfterRestart": True,
                          "movedInArrival": "new-report-b", "reentryIdDistinct": True},
                         sort_keys=True, separators=(",", ":")))


if __name__ == "__main__":
    main()
