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

## Boundary

This supports the structural guard on the checked fixture only. It does not establish live-LLM or production effectiveness.

