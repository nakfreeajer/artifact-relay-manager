# Validation

Accepted Relay core coverage includes:
- valid project identity;
- project/repository identity mismatch fails closed;
- exact-byte SHA-256 and byte length;
- deterministic normalized event identity;
- persistence before delivery;
- Watcher acknowledgement recording;
- duplicate suppression;
- Watcher unavailable leaves retryable durable state;
- restart-safe retry of the same event identity;
- acknowledged restart does not create a new event;
- malformed/semantically corrupt persisted state fails closed;
- cross-project pending state fails closed with zero delivery;
- dedupe/eventId inconsistency fails closed;
- metadata-only output does not leak artifact bodies.

Accepted Google Drive inbound coverage includes:
- one configured Drive folder and direct children only;
- exactly one raw project identity file;
- project/repository mismatch hard stop;
- missing/duplicate/malformed/native Workspace identity hard stop;
- exact non-ASCII bytes and CRLF/LF distinction;
- same file/version deduplication;
- newer provider version creates a new event;
- native Workspace artifacts skipped without export;
- oversized artifact blocked before delivery;
- Drive auth/HTTP failure produces no invented success;
- outside-root/trashed artifacts are not delivered;
- token/artifact body absent from ordinary CLI output;
- Drive-originated pending event retries with the same eventId;
- same-size provider-version race fails closed before staging/delivery;
- post-download parent/trashed/native/not-downloadable races fail closed;
- identity change before delivery fails closed.

For `RELAY.GDRIVE.INBOUND.1A`, final reported validation was:
- `python -m unittest discover -s tests -v` — 29 passed, 0 failed;
- `python -m py_compile relay.py drive_adapter.py tests/test_relay.py tests/cli_demo.py tests/test_drive_adapter.py tests/gdrive_cli_demo.py` — passed;
- `python tests/gdrive_cli_demo.py` — passed;
- `python tests/cli_demo.py` — passed;
- `git diff --check` — passed.

Live provider qualification:
- `LIVE_VALIDATION_BLOCKED=credentials_not_supplied`;
- no live Drive request was made;
- deterministic milestone acceptance therefore remains distinct from live qualification.

Any future live Drive validation must remain bounded to an explicitly configured project folder and must not mutate Drive.
