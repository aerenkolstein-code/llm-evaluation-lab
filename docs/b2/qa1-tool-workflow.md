# B2 QA1-B Tool-use / Agent Workflow QA

QA1-B is a deterministic, public-safe workflow profile using a fake connector/tool registry and a synthetic document state machine. It performs no external mutation and invokes no paid provider.

## Contracts

- `connector-schema-retry`: invalid request shape is a typed `ERROR`; rejection must not be recorded as commit, and retry requires exact-target readback.
- `capability-routing`: discovery and a matching action attempt precede an unavailability claim; capability and permission states stay separate.
- `destructive-write-recovery`: destructive writes require a live target, revision guard, pilot, neighbor readback, recovery evidence, and exactly one side effect.

Missing trace evidence returns `UNKNOWN`; it never satisfies a known-bad oracle. Duplicate side effects and unsafe destructive mutation are hard failures.

The frozen suite contains three known-bad cases and three matched controls. Its receipt is derived by code and fingerprints the complete gate payload.

## Boundary

The suite is synthetic and deterministic. It does not prove live connector reliability, production rollback, external-tool experience, or enterprise scale.
