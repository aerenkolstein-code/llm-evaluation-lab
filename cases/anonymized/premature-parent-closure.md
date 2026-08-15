# EVAL-CASE-001｜Premature Parent Closure

Portfolio Status: **CURRENT ARTIFACT** · Privacy: **PUBLIC_SAFE_DERIVED**

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

