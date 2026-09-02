# B2 QA0 Contracts

Status: bounded deterministic foundation for the user-approved B2-QA0 work order.

## Purpose

QA0 turns private failure lineage into **mechanism-preserving synthetic reconstructions** that can be validated and rerun without exposing private source bodies or locators. It is evidence infrastructure, not a live-model benchmark.

## Public contracts

- `ErrorMechanismSpec`: separates observed phenomenon from mechanism hypothesis and keeps the mechanism status explicit.
- `BugCase v1`: normalized defect evidence record for a concrete run.
- `MetricRegistry`: versioned definitions, scope, directionality, thresholds, hard/soft semantics, missing-data semantics, aggregation, and provenance.
- `B2 Public-Safe Seed`: a synthetic known-bad or matched control plus abstract provenance and expected deterministic verdict.

Terminal states are distinct: `PASS`, `FAIL`, `NOT_EVALUABLE`, `BLOCKED`, `ERROR`, `UNKNOWN`.

Infrastructure/schema failures must not be silently scored as model-quality `FAIL`. Missing evidence must not be turned into zero.

## Frozen QA0 families

1. Entity–attribute binding: claims must keep entity/scope/attribute identity aligned with evidence.
2. Connector schema: malformed request structures become typed infrastructure errors; rejected writes require no-mutation evidence and guarded retry semantics.
3. Integrity completeness: a global PASS requires full-set invariants, not sampled probes.
4. Evidence scope: current inventory claims require list/filter/account evidence; detail-page existence alone is insufficient.

Each family contains one `KNOWN_BAD` and one matched `CONTROL` fixture.

## Privacy boundary

Public fixtures contain synthetic entities and data only. Exact private Error IDs, user/assistant source text, RAW/L0 material, private file locators, credentials, platform-confidential assessment content, and personally identifying locators are forbidden.

The exact private-seed-to-public-family mapping remains outside this repository.

## QA0 scope limit

QA0 does not implement full Grounding/RAG, Agent Workflow, Safety, Fairness, LQE, dashboard, live-provider, or external-evaluator profiles. Those remain later work-order gates.
