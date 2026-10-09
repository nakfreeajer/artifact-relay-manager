# Windows Service Host

The Windows Service adapter delegates monitor cycles to the existing Project Supervisor. It has no workflow, dispatch, or acceptance authority.

## Install the Python modules without elevation

Use the same Python interpreter and Windows user identity that own the protected DPAPI Drive session:

```powershell
python -m pip install --user . -r requirements-windows-service.txt
```

The small `pyproject.toml` installs the existing Relay, Drive, registry, supervisor, CLI, and service modules as top-level modules in that interpreter's user site. When SCM starts PythonService under that same user, Python's user-site package path lets it import the service module from a system working directory; it does not depend on the shell's working directory or `PYTHONPATH`.

The adapter resolves `pythonservice.exe` beside the installed `win32service.pyd` and passes that exact path to pywin32. It never asks pywin32 to move the host into the interpreter or system directory. If the adjacent host is absent, the CLI fails before calling pywin32. SCM registration itself still requires the appropriate Windows permission.

## Service-local configuration

The service reads `%ProgramData%\ArtifactRelayManager\service.json`. It contains paths only, not OAuth client contents, tokens, or passwords:

```json
{
  "schemaVersion": 1,
  "registryPath": "C:\\absolute\\path\\to\\projects.json",
  "oauthClientFile": "C:\\absolute\\path\\to\\existing-desktop-oauth-client.json"
}
```

Both configured files must already exist at canonical absolute local paths. The registry is fully validated before session bootstrap. The OAuth client path is placed into `RELAY_GDRIVE_OAUTH_CLIENT_FILE` only in the service process, for the duration of service execution; the prior process value is restored on exit. The OAuth file itself is not copied, changed, or emitted in logs. `LOCALAPPDATA` is left untouched so the normal Drive session lookup continues to use the service user's profile and DPAPI identity.

The service configuration contains local paths and should be writable only by administrators while remaining readable by the service identity. The OAuth client file and project registry must also be readable by that identity. Service mode never starts browser OAuth; a missing, invalid, or inaccessible config or protected session fails before supervisor cycles.

## SCM account boundary

An unspecified Windows service account defaults to LocalSystem, which cannot use the interactive user's DPAPI-protected session. The ARM command currently rejects pywin32 `install` and `update` verbs until an explicit account-safe registration path is approved. Do not pass passwords on command lines, and do not start a LocalSystem instance. The service identity must be deliberately set to the Windows user that owns the protected session. Its `Log on as a service` right must be available; ARM does not grant or change that right.

No account-safe SCM registration procedure is currently provided, so SCM qualification remains blocked. Do not install or start a service until the owner and Architect approve a safe registration method and all prerequisites. The existing foreground `relay_supervisor.py` CLI remains operational.

## Local checks and limits

Deterministic tests stage the declared modules into an isolated temporary user site and import them from a fresh subprocess whose working directory is `%WINDIR%\System32`. A separate `pip install --user --no-deps .` smoke check was performed against an isolated `PYTHONUSERBASE`. Tests validate service config fail-closed behavior, explicit registry selection, process-local OAuth path wiring, pywin32 host path selection, and existing supervisor reuse/stop behavior. They do not install or start a Windows service and do not qualify SCM lifecycle.
