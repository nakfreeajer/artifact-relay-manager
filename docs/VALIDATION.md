# Validation

Initial Relay transport coverage should include:
- valid project identity;
- project/repository identity mismatch fails closed;
- exact-byte SHA-256 and byte length;
- deterministic normalized event identity;
- persistence before delivery;
- Watcher acknowledgement recording;
- duplicate observation does not create uncontrolled repeated delivery;
- Watcher unavailable leaves retryable durable state;
- restart-safe retry;
- restart after acknowledged delivery does not create a new event;
- metadata-only logging does not leak artifact bodies.

Live Google Drive validation is a later provider milestone and must remain bounded to configured folders.
