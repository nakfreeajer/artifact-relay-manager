# Test Evidence Ledger

Append-only milestone verification records. Detailed sanitized outputs remain in ignored `.agent-work/` evidence.

## ARM.M01 — Two-Folder Project Configuration — 2026-10-21

- Baseline: `6280c5b5e7c26393924f365a00bd95764b364722`; branch: `arm-v2-m01-two-folder-config-1a`.
- `python -m unittest tests.test_project_registry tests.test_project_folder_config -v` — 30 passed, 0 failed.
- `python -m unittest discover -s tests -v` — 120 passed, 0 failed.
- Changed-file `py_compile` command — passed.
- `python tests/project_config_cli_demo.py` — passed for two separate projects, canonical folders, one endpoint per project, provider validation, and fresh-process reload.
- `git diff --check` — passed.
- Provider and endpoint checks used only deterministic local fixtures. Google Drive, OAuth/DPAPI, remote endpoint, Watcher, Scheduler, Service and UserHost activity: none.
- Evidence: `.agent-work/milestones/ARM.M01.TWO_FOLDER_CONFIG.1A/evidence/` (ignored, sanitized).

## ARM.M03 — Two-folder Drive change detection (offline) — 2026-10-21

- Baseline: `arm-v2-m01-two-folder-config-1a` at `158af8bcf42ce2e6edec2816de09259e438f9322`; branch: `arm-v2-m03-dualfolder-detection-1a`.
- `python -m unittest tests.test_drive_change_detector tests.test_project_registry tests.test_project_folder_config -v` — 41 passed, 0 failed.
- `python -m unittest discover -s tests -v` — 131 passed, 0 failed.
- `python -m py_compile drive_change_detector.py drive_adapter.py tests/test_drive_change_detector.py tests/drive_change_cli_demo.py` — passed.
- `python tests/drive_change_cli_demo.py` — passed: two-project baseline, direct-child creation and checksum-proven content update, duplicate poll, metadata-only rename/version increment, move/delete with nested child excluded, and fresh-process reload. Three events persisted with stable IDs; repeat/restart emitted zero new events.
- `git diff --check` — passed.
- Negative coverage: provider failure, incomplete listing, unproven move-in, missing/native checksum, corrupted/cross-project state, failed state write/atomic replace, duplicate observation, and no-network fixture guard.
- The M03 detector/demo used local metadata fixtures and made no Google Drive/OAuth/protected-session, APO, or Watcher calls; network guard was enabled. The inherited suite did run deterministic loopback mock Watcher regressions and the Windows DPAPI primitive test with disposable text; no external endpoint, credential, or stored session was accessed. Scheduler, Service, UserHost, Desktop Bridge, and file-body access: none.
- Production list-only adapter limitation: new versus moved-in cannot be proven and stays ambiguous; native Workspace/missing-checksum content changes remain unqualified. No live qualification or M04 work.
- Evidence: `.agent-work/milestones/ARM.M03.TWO_FOLDER_DRIVE_CHANGE_DETECTION.1A/evidence/` (ignored, sanitized).
