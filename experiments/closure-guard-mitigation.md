# MIT-CLOSURE-GUARD-001｜Closure Guard

**Target failure:** premature parent closure.

## Control

Close the parent when any child is `DONE`.

## Treatment

Read every required child status. Reject closure while any child is open, unknown, waiting, blocked or pending. Hold when child-state evidence is absent. Accept only when all required children are terminal.

## Decision rule

Adopt the mitigation for this failure class only if it lowers premature closure without blocking the valid all-terminal case.

## Executed result

On five deterministic public-safe variants, accuracy moved from `0.20` to `1.00`; premature closure rate moved from `1.00` to `0.00`. The known-bad regression probe failed four variants; the guard failed zero.

## Executable contract

`llm-eval` validates this block, emits it as canonical JSON, and passes it to
Companion-Mind. The runtime accepts only the supported schema, failure target,
guard type, decision mapping, and non-overlapping status sets.

```json
{
  "schema_version": "mitigation-spec/v1",
  "mitigation_id": "MIT-CLOSURE-GUARD-001",
  "target_failure": "premature_parent_closure",
  "intervention": "Require every required child to be terminal before closure.",
  "control": "naive_any_done",
  "treatment": "companion_mind.runtime.ClosureGuard",
  "metrics": [
    "accuracy",
    "premature_closure_rate",
    "known_bad_failures_detected"
  ],
  "decision_rule": "Adopt only when premature closure falls to zero, the all-terminal case remains accepted, and the known-bad regression probe still fails.",
  "regression_cases": ["EVAL-CASE-001"],
  "runtime": {
    "guard_type": "closure_guard",
    "safeguard_id": "CM-GUARD-001",
    "terminal_statuses": ["CANCELLED", "DONE"],
    "blocking_statuses": [
      "BLOCKED",
      "OPEN",
      "PENDING",
      "UNKNOWN",
      "WAITING",
      "WAITING-EXTERNAL",
      "WAITING-ON-TRIGGER"
    ],
    "empty_evidence_decision": "HOLD",
    "non_terminal_decision": "REJECT",
    "all_terminal_decision": "ACCEPT"
  }
}
```

## Boundary

This supports the structural guard on the checked fixture only. It does not establish live-LLM or production effectiveness.
