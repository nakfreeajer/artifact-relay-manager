# Google Drive Provider

Google Drive is the first Relay provider.

Milestone `RELAY.GDRIVE.INBOUND.1A` implements one-shot inbound polling only. The adapter reads direct children of the configured folder, validates one raw `.relay-project.json`, stages bounded exact bytes under the configured local Relay workspace, and submits provider observations through the accepted Relay core.

Create a local Drive project config (keep it out of Git):

```json
{
  "schemaVersion": 1,
  "projectId": "example-project",
  "repository": "owner/repository",
  "folderId": "GOOGLE_DRIVE_FOLDER_ID",
  "relayWorkspace": "C:/path/to/relay-workspace",
  "watcherEndpoint": "http://127.0.0.1:8765/events",
  "eventType": "ARTIFACT_CHANGED"
}
```

Set `RELAY_GDRIVE_ACCESS_TOKEN` in the process environment, then run:

```bash
python relay.py --config drive-project.json --state relay-state.json poll-drive
```

The optional `--api-base-url` accepts HTTP loopback only and exists for deterministic local API tests. Production requests use `https://www.googleapis.com/drive/v3`. Ordinary Drive files use the API `File.version` value for provider version identity. Workspace-native files are skipped; identity files must be raw downloadable files. Polling is capped at 1,000 direct children and 1 MiB per artifact. Logs/results include metadata only.

The relay workspace stores exact bytes under `staged/<project-hash>/<file-hash>/<version>.bin`, generated observation metadata under `.observations/`, and the derived core config/identity files needed by the existing transport path. No Drive-wide workflow discovery or recursive traversal is performed.

## Live read-only qualification

Install the optional authentication dependencies with `python -m pip install -r requirements-gdrive-auth.txt`. Set `RELAY_GDRIVE_OAUTH_CLIENT_FILE` to a local Google OAuth Desktop app client JSON file. The command opens the system browser, requests only `drive.readonly`, and listens on an ephemeral `127.0.0.1` port. The access token exists only in the current process; the command does not write credentials, download/stage a file, create Relay events, or contact the Watcher.

Use a deliberately designated raw artifact no larger than 1 MiB that is a direct child of the configured root:

```bash
python relay.py --config drive-project.json qualify-drive --qualification-file-id DRIVE_FILE_ID
```

Successful output contains the configured project and folder IDs, designated file ID, provider version, byte length, SHA-256, MIME type, and `QUALIFIED_READ_ONLY`. The optional `--api-base-url` is restricted to HTTP loopback for deterministic tests.
