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
