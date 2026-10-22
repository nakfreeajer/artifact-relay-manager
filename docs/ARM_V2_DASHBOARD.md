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
- At the M02.1A revision, Add/identity configuration was blocked unless the worker was stopped and M03/M04 contained no event history; project Edit and Remove controls were not yet implemented. The later M02.1C candidate behavior is documented separately below.
- Refresh calls only the accepted M05 `status` CLI and local validators; it does not spawn a worker or contact Drive/APO. Status/history refresh runs off the Tk thread every second. Start, status and stop preserve the M05 CLI JSON and exit-code contract: success/healthy `0`, informational `STARTING` `1`, error/degraded `2`, and existing-worker `ALREADY_RUNNING` `3`.
- Closing the UI never calls stop. A later dashboard process reads the same host status and can invoke Start; the M05 host reports `ALREADY_RUNNING` without creating a second worker. Stop delegates to the existing cooperative M05 stop operation.
- The window prominently identifies itself as `FIXTURE / OFFLINE ONLY — NOT LIVE DRIVE / APO`.

## M02.1B pause/resume offline candidate

The dashboard exposes Pause All/Resume All and Pause Selected/Resume Selected. It shows `Enabled` and `Paused` independently; pausing never rewrites registry enablement. A selected-project refresh preserves selection and detail state as rows update across refreshes. Control results distinguish an acknowledged safe-boundary application from a still-pending timeout. Global pause keeps the detached worker alive with heartbeats and suppresses all scans/sends; per-project pause suppresses that project's scans and dispatch while peers continue. Stop/restart retains pause state. Pending notification IDs and detector state are not rebaselined; Resume permits normal observation and safe retry.

This is the offline Windows Tk and detached fixture-worker implementation published on `arm-v2-m02b-runtime-pause-resume-offline-1a`. It does not qualify live Drive/APO operation or complete M02/Release 1. Qualification details and limits are in `docs/VALIDATION.md`.

## M02.1C project management offline candidate

The M02.1C dashboard adds project-level management controls on the unpublished `arm-v2-m02c-project-management-offline-1a` candidate. The visible window remains marked `FIXTURE / OFFLINE ONLY — NOT LIVE DRIVE / APO`.

- **Edit Display Name** opens a modal editor for `displayName` only. Input is bounded and validated. `projectId`, Drive root and child identities, endpoint, repository/workspace, `secretRef`, enabled state, event IDs, legacy registry entries, pause state, and on-disk state are not editable. The save re-reads the registry under the shared dashboard write guard and refuses a stale display name rather than overwriting another dashboard's newer edit.
- **Start Project** and **Stop Project** control the existing validated v2 `folderProjects[].enabled` eligibility flag. Start validates the configured folder identities using the local folder fixture and enables future work; it does not launch the shared worker or unpause the project. Stop disables future project scans and sends after the next safe monitoring boundary. An in-flight send may still ACK or time out, and any pending notification remains durable. These controls are distinct from global **Start Monitor / Stop Monitor** and project/global **Pause / Resume**; changing eligibility never changes pause state.
- **Remove Selected** requires explicit confirmation. Under the same per-registry OS-held write guard used for dashboard mutations, it re-reads the registry and state and requires the shared worker to be verified `STOPPED`, the target project to be disabled, and no target M03 detector snapshot/candidate/event/ambiguity, M04 pending or ACKed ledger entry, paused-project membership, pending control reference, or last-applied project control reference. A competing dashboard write is serialized; invalid or changed state fails closed. Removal atomically removes only the v2 registry entry, preserving all other v2 and legacy projects. No referenced config, detector, notification, pause, fixture, or other file is deleted.
- If a project has transport history or a pause reference, removal is refused and the project remains configured. Use **Stop Project** to disable future work while retaining its durable history; Stop is not a purge operation. A running shared worker also blocks removal, even for an otherwise unused project.
- Selection-dependent controls update with the selected row. Existing one-second refresh continues to preserve selection and scroll; closing a dashboard cancels its refresh callback but does not stop the independent worker.

This candidate was qualified with local fixtures and loopback simulated APOs only. It does not qualify live Google Drive, OAuth/DPAPI, a real Orchestrator/APO, production secret resolution, or complete M02/Release 1. It has no project-Orchestrator workflow authority. M02.1C remains pending independent Architect source review. The updated instruction records D26 authorization for one ordinary commit and non-force push to this named branch after final requalification; publication does not imply Architect acceptance.

## Qualification boundary and limits

The M02.1A qualification above used a visible Windows Tk window, temporary two-project M01 registry and folder fixture, the accepted detached M05 fixture worker, and two deterministic loopback simulated APO receivers. It did not qualify pause/resume at that revision. M02.1B pause/resume is qualified separately below and in `docs/VALIDATION.md`. Neither slice qualifies live Google Drive, OAuth/DPAPI, real Orchestrator interoperability, production secret resolution, a Windows service/task, installer, startup, or complete M02/M07 behavior. Relay remains transport-only; no project-Orchestrator workflow authority is present.
