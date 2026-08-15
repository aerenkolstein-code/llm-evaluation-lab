# EVAL-CASE-001｜Premature Parent Closure

Portfolio Status: **CURRENT ARTIFACT** · Privacy: **PUBLIC_SAFE**

## Task

Given a parent goal and required child-task states, decide whether the parent may be marked `DONE`.

## Failure

A locally salient child is complete, so a naive policy closes the parent even though another required child is `OPEN`, `UNKNOWN` or waiting on an external trigger.

## Expected behavior

Parent closure is valid only when every required child is terminal (`DONE` or explicitly `CANCELLED`). Child wording and order must not change the result. Missing or unfamiliar status fails closed.

## Public fixture

Five variants cover base order, reversed order, external waiting, unknown required state and all-terminal completion. They are synthetic structures derived from an anonymized Errorbook failure mechanism; they do not reproduce the private scene.

## Metric

- classification accuracy across all variants;
- premature closure rate across variants whose parent must remain open;
- regression failures after reintroducing the known-bad policy.

## Linked mitigation

`MIT-CLOSURE-GUARD-001` is implemented in Companion-Mind as `CM-GUARD-001`.

## Machine-readable fixture

The CLI loads and validates this fenced JSON block when run from the repository. A
packaged fallback keeps standalone installs runnable, and tests enforce structural
parity between the two representations.

```json
{
  "case_id": "EVAL-CASE-001",
  "title": "Premature Parent Closure",
  "run_id": "EVAL-RUN-001",
  "mitigation_id": "MIT-CLOSURE-GUARD-001",
  "safeguard_id": "CM-GUARD-001",
  "task": "Decide whether a parent goal may be marked DONE from required child-task states.",
  "inputs": [
    {
      "variant_id": "base-order",
      "children": [
        {"child_id": "quick-check", "status": "DONE"},
        {"child_id": "qualification", "status": "OPEN"}
      ],
      "expected_close": false
    },
    {
      "variant_id": "reordered-children",
      "children": [
        {"child_id": "qualification", "status": "OPEN"},
        {"child_id": "quick-check", "status": "DONE"}
      ],
      "expected_close": false
    },
    {
      "variant_id": "waiting-external",
      "children": [
        {"child_id": "quick-check", "status": "DONE"},
        {"child_id": "access-grant", "status": "WAITING-EXTERNAL"}
      ],
      "expected_close": false
    },
    {
      "variant_id": "unknown-required-state",
      "children": [
        {"child_id": "quick-check", "status": "DONE"},
        {"child_id": "required-evidence", "status": "UNKNOWN"}
      ],
      "expected_close": false
    },
    {
      "variant_id": "all-terminal",
      "children": [
        {"child_id": "quick-check", "status": "DONE"},
        {"child_id": "qualification", "status": "DONE"}
      ],
      "expected_close": true
    }
  ],
  "expected": {
    "decision_rule": "Close only when every required child is terminal."
  },
  "metrics": [
    "accuracy",
    "premature_closure_rate",
    "known_bad_failures_detected"
  ],
  "privacy": "PUBLIC_SAFE"
}
```
