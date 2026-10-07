# Validation

Accepted Relay core coverage now includes:
- valid project identity;
- project/repository identity mismatch fails closed;
- exact-byte SHA-256 and byte length;
- deterministic normalized event identity;
- persistence before delivery;
- Watcher acknowledgement recording;
- duplicate observation does not create uncontrolled repeated delivery;
- Watcher unavailable leaves retryable durable state;
- restart-safe retry of the same event identity;
- restart after acknowledged delivery does not create a new event;
- malformed JSON state fails closed;
- semantically malformed persisted normalized event fails closed;
- cross-project persisted pending event fails closed with zero delivery;
- dedupe/eventId inconsistency fails closed with zero delivery;
- metadata-only output does not leak artifact bodies.

For `RELAY.CORE.VERTICAL.1A`, final reported validation was:
- `python -m unittest discover -s tests -v` — 12 passed, 0 failed;
- `python -m py_compile relay.py tests/test_relay.py tests/cli_demo.py` — passed;
- `python tests/cli_demo.py` — passed;
- `git diff --check` — passed.

Live Google Drive validation remains a later provider milestone and must stay bounded to explicitly configured project folders.
