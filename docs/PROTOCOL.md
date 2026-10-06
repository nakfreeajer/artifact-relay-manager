# Relay Protocol

## Principle

Transport events report provider facts. They do not grant workflow authority.

## Project identity file

Every monitored root contains an identity artifact equivalent to:

```json
{
  "schemaVersion": 1,
  "projectId": "affotech-agent-orchestrator",
  "repository": "nakfreeajer/affotech-agent-orchestrator"
}
```

Before enabling monitoring, the Relay must prove configured `projectId` matches the folder identity.

## Normalized incoming event

Minimum logical shape:

```json
{
  "schemaVersion": 1,
  "eventId": "<stable relay event id>",
  "projectId": "<project id>",
  "eventType": "PROMPT_READY",
  "taskId": "<task id or null>",
  "artifact": {
    "artifactId": "<provider-independent id>",
    "sha256": "<sha256>",
    "byteLength": 1234
  },
  "provider": {
    "kind": "google-drive",
    "version": "<opaque provider version>"
  },
  "observedAt": "<UTC timestamp>"
}
```

Supported initial event classes:
- PROMPT_READY
- RESULT_READY
- HANDOVER_READY
- SYSTEM_SNAPSHOT_READY
- ARTIFACT_CHANGED
- PROJECT_IDENTITY_CHANGED

## Local delivery acknowledgement

Watcher acknowledges transport receipt with a transport disposition such as:
- RECEIVED
- QUEUED
- REJECTED
- DUPLICATE

The Relay records the acknowledgement but does not reinterpret it.

## Outbound publication

Watcher places/publishes an outbound artifact with:
- projectId;
- artifact type;
- taskId when applicable;
- SHA-256;
- byte length;
- desired logical destination.

Relay verifies bytes before provider upload.

## Deduplication

Transport deduplication identity should include:
- projectId;
- provider item identity;
- provider version/change identity;
- normalized event type.

Repeated observation of the same provider version must not create an unbounded event stream.

Workflow exactly-once remains the Watcher's responsibility.

## Ordering

The Relay preserves observation order per project where the provider exposes a stable sequence/cursor.

The Relay does not reorder events based on workflow priority.

Watcher priority may intentionally process a later P1 rollover event before an earlier P2/P3 workflow event.

## Failure

Provider/network failure:
- retain local event/outbound state;
- mark health degraded;
- retry with bounded backoff;
- never invent successful delivery.

Watcher unavailable:
- queue normalized events durably;
- resume delivery when Watcher returns.

Project identity mismatch:
- stop delivery for that configured project;
- surface RED health;
- require human correction.

## Content logging

Logs should prefer identifiers, hashes, sizes, event types, provider versions, and status.

Prompt/result contents should not be copied into routine logs.
