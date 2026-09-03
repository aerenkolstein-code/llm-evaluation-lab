# B2 QA1-B Tool-use / Agent Workflow QA

QA1-B is a deterministic, public-safe workflow profile using a fake connector/tool registry and a synthetic document state machine. It performs no external mutation and invokes no paid provider.

## Contracts

- `connector-schema-retry`: invalid request shape is a typed `ERROR`; rejection must not be recorded as commit, and retry requires exact-target readback.
- `capability-routing`: discovery and a matching action attempt precede an unavailability claim; the user-facing availability claim must equal the capability state independently of permission state.
- `destructive-write-recovery`: destructive writes require a live target, revision guard, pilot, neighbor readback, recovery evidence, and exactly one side effect.

Required trace fields are frozen per family. Partial missing trace evidence returns `UNKNOWN` with `evidence_complete=false`; it never satisfies a known-bad oracle. Deterministic contract tests cover retry after readback, retry before readback, and duplicate side effects. Provider/schema `ERROR` remains separate from model/workflow `FAIL`.

The frozen suite contains three known-bad cases and three matched controls. Its receipt derives and fingerprints the exact three-family set, one known-bad/control pair per family, unique case IDs, and family-specific deterministic public seed digests.

## Boundary

The suite is synthetic and deterministic. It does not prove live connector reliability, production rollback, external-tool experience, or enterprise scale.
