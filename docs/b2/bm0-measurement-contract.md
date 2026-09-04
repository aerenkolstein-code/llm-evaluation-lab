# B2 BM0 Multi-Model Benchmark Measurement Contract

## Scope and authority

`WO-B2-BM0 v0.2` freezes an offline measurement contract at implementation
baseline `901ba05b99c413d45415c474c71b5969c155dea1`. It defines what a later
benchmark may measure and how it must be analyzed. It does not select a
provider or model, open a private holdout, run an API, spend money, emit a
benchmark result, rank models, or estimate a population failure rate.

The checked developer receipt may assert only that the offline contract is
internally valid and ready for exact-head CI plus distinct Independent QA.
It cannot assert `BM0_GREEN`.

## Target-under-test and applicability matrix

The frozen matrix has exactly 16 ordered targets:

| Class | Count | Current treatment | Model-failure denominator |
|---|---:|---|---|
| `MODEL_DIRECT` | 3 | default comparable | eligible now |
| `MODEL_CONTEXT_GROUNDED` | 5 | default comparable | eligible now |
| `AGENT_STANDARDIZED` | 4 | waits for sandbox-equivalence evidence | conditional only |
| `SYSTEM_EVAL_ONLY` | 4 | system-level evaluation | never eligible |

The default comparable set is exactly `MODEL_DIRECT` plus
`MODEL_CONTEXT_GROUNDED`. A later frozen manifest may add
`AGENT_STANDARDIZED` only when it binds all five frozen sandbox-equivalence
evidence types: image, tool surface, budget/retry, network/credential policy,
and an independent equivalence receipt.
`SYSTEM_EVAL_ONLY` can never enter a model-comparison denominator.

## Terminal and denominator semantics

| Terminal state | Meaning | In model-failure denominator | In numerator |
|---|---|---:|---:|
| `PASS` | model-scorable success | yes | no |
| `FAIL` | model-scorable failure | yes | yes |
| `NOT_EVALUABLE` | the attempt cannot be evaluated | no | no |
| `BLOCKED` | governance or authorization block | no | no |
| `ERROR` | infrastructure or execution error | no | no |
| `UNKNOWN` | evidence is insufficient | no | no |

For each model subject, the descriptive model-failure rate is
`FAIL / (PASS + FAIL)` over unique predeclared attempts in the complete
comparable `PRIVATE_HIDDEN_HOLDOUT` grid. Public development, control, and
mutation attempts remain available to the all-pool diagnostic but cannot enter
this primary estimate. Missing planned hidden observations fail closed as
`NOT_EVALUABLE/MISSING_PLANNED_OBSERVATIONS`. A zero model-scorable denominator
fails closed as `NOT_EVALUABLE/ZERO_MODEL_SCORABLE_DENOMINATOR`. Retries require
new predeclared attempt identities; a later row may not silently replace an
earlier attempt.

## Executable statistical analysis plan

The central contract binds these implementations and frozen parameters before
any hidden-corpus access:

| Method ID | Implementation | Frozen behavior |
|---|---|---|
| `BM0-SAP-01-FIXED-ATTEMPT-STOP-V1` | `fixed_attempt_stop_v1` | stop only after all predeclared attempt IDs are recorded; reject outcome-bearing stop inputs |
| `BM0-SAP-02-IDENTITY-GRID-V1` | `validate_observation_grid_v1` | reject duplicate, substituted, or unplanned observations; expose missing IDs |
| `BM0-SAP-03-TYPED-TERMINAL-PARTITION-V1` | `typed_terminal_partition_v1` | retain all six terminal states without coercion |
| `BM0-SAP-04-MODEL-FAILURE-DENOMINATOR-V1` | `model_failure_denominator_v1` | use only `FAIL / (PASS + FAIL)` and emit no ranking |
| `BM0-SAP-05-WILSON-INTERVAL-V1` | `wilson_interval_v1` | deterministic two-sided 95% Wilson interval; zero denominator is not evaluable |
| `BM0-SAP-06-PAIRED-COMPLETE-CASE-V1` | `paired_complete_case_v1` | pair on target, corpus alias, replicate, and derived retry ordinal; require matching target class, corpus commitment, prompt, harness, adapter version, seed, and environment; otherwise fail closed |
| `BM0-SAP-07-ADJUDICATION-RESOLUTION-V1` | `resolve_adjudication_v1` | two distinct blind primaries; exactly one distinct blind tiebreaker on disagreement |
| `BM0-SAP-08-SYSTEM-INVARIANT-FAILURE-RATE-V1` | `system_invariant_failure_rate_v1` | compute a system-only typed rate under `SYSTEM_SCOPE`; never attribute it to a model or emit a ranking |

The no-peeking stop function accepts only `attempt_id` and `recorded`. The
manifest binds both the frozen SAP and its executable implementation by
fingerprint.
`terminal_status`, `model_failure_value`, `score`, output content, and
adjudication decisions are rejected rather than ignored.

System-only attempts may be scheduled in the same frozen manifest, but they use
the reserved provider/model/snapshot identity `SYSTEM_SCOPE` and remain outside
`comparison_classes`. Their missing rows and denominators are evaluated by the
system-only method. Observation records keep `model_failure_value` and
`system_invariant_failure_value` mutually exclusive by target class, so a
system failure cannot contaminate a model-failure rate.

## Identity and manifest freeze

Every planned attempt binds the study, trial, attempt, optional parent attempt,
provider subject, model subject, immutable model snapshot, target, corpus alias
and commitment, corpus pool and any mutation-parent commitment, prompt, harness,
adapter, replicate, random seed, and
environment fingerprint. Moving snapshot aliases such as `latest`, duplicate
attempt IDs, class/target mismatches, orphan or forward parents, identity drift,
and branching retries are invalid. Multiple attempts may share a trial only as
one ordered, identity-stable root-to-child chain; each remains a distinct
predeclared denominator unit and never replaces its parent.

The checked manifest is deliberately a `DESIGN_ONLY` template:

- provider/model roster: `NOT_SELECTED`;
- corpus commitment: `NOT_COMMITTED`;
- adjudication mode: `NOT_SELECTED`;
- planned attempt count: `0`;
- sandbox equivalence: `NOT_ESTABLISHED`.

Execution requires a separate, fully populated `FROZEN` manifest created before
private-holdout access. `SEALED` requires a non-null aggregate corpus
commitment, not a status assertion alone. The aggregate is deterministically
rebuilt from the unique private-holdout aliases and per-item commitments; alias
drift and reuse of the same item commitment across pools are rejected. That
manifest must also fingerprint the adjudication
plan: mode, allowed metrics, two primary identities and types, one distinct
tiebreak identity and type, an immutable configuration fingerprint for every
human protocol or fixed judge, and the exact rubric version and fingerprint.
The template itself cannot be used to execute a study.

## Corpus separation

The public contract distinguishes development, control, mutation, and private
hidden-holdout pools. Public development, controls, and mutations cannot enter
the primary hidden estimate. The private holdout's exact content, exact case
IDs, private locator, and per-case commitments remain outside the public
repository.

Every mutation-pool identity must disclose its parent commitment. A mutation
whose parent commitment occurs in the private hidden pool is rejected, as is
reuse of one exact item commitment across corpus pools.

The required order is: freeze the manifest, seal an aggregate commitment,
authorize execution, open the private holdout, and log access. The contract
forbids treating the `B2-BLIND-01` / PR #30 corpus or outputs as BM0 material by
assumption.

## Adjudication and claim ceiling

PASS or FAIL adjudication requires complete evidence. Primaries and any
tiebreaker must use distinct adjudicator identities and remain blind to model,
provider, and peer decisions. Runtime records must match the adjudicator set,
mode composition, metric, attempt, item alias, and rubric frozen in the
manifest; an unplanned substitute is rejected. Missing adjudication remains
`UNKNOWN`; an adjudication-system failure remains `ERROR` and is never
converted to model failure.

BM0 permits only these developer claims:

- `BM0_OFFLINE_CONTRACT_VALIDATED`;
- `BM0_READY_FOR_EXACT_HEAD_CI_AND_INDEPENDENT_QA`.

Rankings, winners, live-provider performance, population rates, causal gains,
Fairness/LQE validation, production readiness, Independent QA PASS, and BM0
GREEN are outside the claim ceiling.

## Artifact map

| Artifact | Purpose |
|---|---|
| `cases/b2/public-safe/benchmark/bm0-measurement-contract.json` | central fingerprinted contract and artifact bindings |
| `cases/b2/public-safe/benchmark/bm0-target-applicability.json` | exact 16-target matrix |
| `cases/b2/public-safe/benchmark/bm0-metric-registry.json` | metric applicability, numerator, denominator, and uncertainty rules |
| `cases/b2/public-safe/benchmark/bm0-corpus-policy.json` | public/control/mutation/hidden split and access policy |
| `cases/b2/public-safe/benchmark/bm0-benchmark-manifest.template.json` | non-executable design template for a later frozen study |
| `schemas/bm0_*.schema.json` | strict JSON schemas for contract, manifest, identity, observation, and adjudication |
| `b2/bm0.py` | pure offline validators and executable SAP methods |
| `tests/test_b2_bm0.py` | deterministic and adversarial contract tests |
| `results/b2/bm0-contract-validation.json` | reproducible developer contract receipt |

Artifact fingerprints use the repository's canonical `sha256_json` encoding.
JSON artifacts are hashed as parsed canonical objects; the Python implementation
and its tests are hashed as canonical UTF-8 source strings.

## Acceptance boundary

The developer receipt remains `bm0_green: false`, with exact-head CI and
Independent QA both `NOT_RUN`. BM0 becomes green only after the exact candidate
head passes CI and a reviewer distinct from the implementation path records a
BM0-specific Independent QA PASS. Merge and release require separate
authorization.
