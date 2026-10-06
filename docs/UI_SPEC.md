# UI Specification

## Main dashboard

Show one row/card per configured project:

- project display name;
- projectId;
- monitoring enabled/disabled;
- Drive folder name;
- Watcher connectivity;
- health state;
- queued event count;
- last event summary and time.

Health colors:
- GREEN — normal;
- BLUE — synchronizing;
- YELLOW — Watcher unavailable / transport queued;
- RED — auth, folder identity, or configuration failure;
- GREY — disabled.

## Add/Edit Project wizard

Fields:

1. Display Name
2. Project ID
3. Google Drive Folder — Select Folder
4. Local Project Folder — Select Folder
5. Local Relay Workspace
6. Watcher Endpoint
7. Monitoring Enabled

Actions:
- Test Drive
- Validate Project Identity
- Test Local Path
- Test Watcher
- Save
- Cancel

Monitoring cannot be enabled until project identity validation passes.

## Project detail

Tabs:

### Overview
Current configuration, health, last provider cursor, Watcher status, last delivery.

### Live Monitor
Streaming transport activity:
- provider change detected;
- identity/hash verification;
- event normalized;
- delivery attempt;
- Watcher acknowledgement;
- outbound upload.

### Event History
Filter by:
- project;
- event type;
- task;
- status;
- time range.

### Queue
Pending inbound deliveries and outbound uploads.

Manual retry means **retry transport only**. UI wording must make clear that it does not authorize Executor rerun.

### Settings
Project-specific paths/endpoints and enable/disable controls.

## Global settings

- Google Drive account/connection;
- service startup behavior;
- polling/change-stream tuning;
- log retention;
- database location;
- diagnostics export.

## Safety UX

Never present a button named simply "Retry Task" in Relay Manager.

Allowed wording:
- Retry Delivery
- Retry Upload
- Reconnect Watcher
- Revalidate Folder

Workflow retry belongs to the project Watcher/human authority.

## Background behavior

Closing the UI leaves the Relay Service running.

The UI should clearly show whether:
- UI connected to service;
- service running;
- provider authenticated;
- each Watcher reachable.
