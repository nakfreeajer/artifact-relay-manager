# ARM v2 Windows dashboard — M02.1A offline candidate

`arm_v2_dashboard.py` is a manually launched native Tk/ttk dashboard for the accepted M01 registry and M05 offline UserHost. This is the first CORE UI slice; it is not full M02 or Release 1 acceptance.

## Launch

```powershell
python arm_v2_dashboard.py --config <absolute-M05-host-config.json> `
  --folder-validation-fixture <local-M01-folder-fixture.json>
```

The M05 config and all host inputs must satisfy the existing current-user LocalAppData and fixture-only contract. The separate folder-validation fixture contains the existing root and its two direct child identities for `FakeDriveProvider`; it is read locally and is never sent to Drive. The M05 provider fixture supplies monitor metadata. Both provider inputs must be synthetic local fixtures for this candidate. No package beyond Python/Tkinter is required.

## Dashboard behavior

- The project list reads only v2 `folderProjects`; legacy M01 `projects` records remain unchanged and are not shown as v2 projects.
- The main view shows project/repository identity, enabled state, recent project status and sanitized issue class, root and child IDs/URLs, a masked loopback-endpoint indication, host status/heartbeat/cycle, the most recent 100 metadata events and M04 pending/ACK counts.
- Event history contains IDs, event type/change kind, observation time and receipt disposition. Artifact contents, event URLs, secret values, OAuth state, and local runtime paths are not displayed.
- Add validates the selected root and both direct children through the local `FakeDriveProvider`, accepts only an HTTP loopback simulated APO endpoint and a configured `test:` secret reference, then persists the project disabled. Failed validation leaves the registry bytes unchanged.
- Enable revalidates the project against the local folder fixture and uses `ProjectRegistry.set_folder_project_enabled`. The v2 writer validates and atomically replaces the registry while preserving the legacy `projects` array. Disable uses the same v2 writer; M03 stops scanning the disabled project and M04 stops dispatching new or pending work for it while its durable ledger entry remains.
- Add/identity configuration is blocked unless the worker is stopped and both M03/M04 contain no event history. This slice has no project edit or remove control; safe removal with retained event history is deferred.
- Refresh calls only the accepted M05 `status` CLI and local validators; it does not spawn a worker or contact Drive/APO. Status/history refresh runs off the Tk thread every second. Start, status and stop preserve the M05 CLI JSON and exit-code contract: success/healthy `0`, informational `STARTING` `1`, error/degraded `2`, and existing-worker `ALREADY_RUNNING` `3`.
- Closing the UI never calls stop. A later dashboard process reads the same host status and can invoke Start; the M05 host reports `ALREADY_RUNNING` without creating a second worker. Stop delegates to the existing cooperative M05 stop operation.
- The window prominently identifies itself as `FIXTURE / OFFLINE ONLY — NOT LIVE DRIVE / APO`.

## Pause semantics proposal for M02.1B review

Pause and Resume are intentionally absent from M02.1A. The proposed semantics, pending Architect review and a separate bounded CORE implementation, are:

- Global Pause keeps the worker and truthful host status alive, then freezes scans and dispatch at a safe cycle boundary; configuration and pending work remain durable.
- Global Resume continues from the same persisted detector/notification state without rebaselining.
- Per-project Pause suppresses scans and sends for that project while other projects continue; the project's config, event history and pending work remain durable.
- Stop exits the host cleanly. An in-flight transport follows M04 at-least-once semantics and is never shown as ACKed without a verified matching receipt.

No pause buttons or implied `enabled=false` semantics are presented in this slice.

## Qualification boundary and limits

Qualification uses a visible Windows Tk window, temporary two-project M01 registry and folder fixture, the accepted detached M05 fixture worker, and two deterministic loopback simulated APO receivers. It does not qualify live Google Drive, OAuth/DPAPI, real Orchestrator interoperability, production secret resolution, a Windows service/task, installer, startup, pause/resume, or complete M02/M07 behavior. Relay remains transport-only; no project-Orchestrator workflow authority is present.
