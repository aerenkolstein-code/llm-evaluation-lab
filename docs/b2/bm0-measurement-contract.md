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
That expansion permits the separately registered
`sandboxed_agent_failure_rate`; it does not mix agent observations into
`model_failure_rate`, whose target classes remain direct plus
context-grounded.
`SYSTEM_EVAL_ONLY` can never enter a model-comparison denominator.

The 16 targets are not newly invented generic capabilities. Each row binds one
formal entry and its existing public-safe fixture/validation lineage:

| Entry | Source family | Class |
|---|---|---|
| E01 | `QA0/entity-attribute-binding` | `MODEL_CONTEXT_GROUNDED` |
| E02 | `QA0/connector-schema` | `AGENT_STANDARDIZED` |
| E03 | `QA0/integrity-completeness` | `SYSTEM_EVAL_ONLY` |
| E04 | `QA0/evidence-scope` | `MODEL_CONTEXT_GROUNDED` |
| E05 | `QA1-G/entity-attribute-binding` | `MODEL_CONTEXT_GROUNDED` |
| E06 | `QA1-G/inventory-evidence-scope` | `MODEL_CONTEXT_GROUNDED` |
| E07 | `QA1-G/source-modality` | `MODEL_CONTEXT_GROUNDED` |
| E08 | `QA1-T/connector-schema-retry` | `AGENT_STANDARDIZED` |
| E09 | `QA1-T/capability-routing` | `AGENT_STANDARDIZED` |
| E10 | `QA1-T/destructive-write-recovery` | `AGENT_STANDARDIZED` |
| E11 | `QA2/constraint-action-persistence` | `MODEL_DIRECT` |
| E12 | `QA2/live-assessment-rule-persistence` | `MODEL_DIRECT` |
| E13 | `QA2/live-production-no-ai-persistence` | `MODEL_DIRECT` |
| E14 | `QA3/full-set-projection-completeness` | `SYSTEM_EVAL_ONLY` |
| E15 | `QA3/metric-attribution-provenance-separation` | `SYSTEM_EVAL_ONLY` |
| E16 | `QA3/dashboard-field-semantics-scope-lock` | `SYSTEM_EVAL_ONLY` |

Every row records the exact source fixture, PASS receipt, and matched
`KNOWN_BAD`/`CONTROL` case IDs. Contract validation recomputes all 32 case
fingerprints against those five source fixture/receipt pairs; a renamed family,
substitute target, missing case, changed variant, or cross-wired receipt fails.

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
comparable `PRIVATE_HIDDEN_HOLDOUT` grid. `PUBLIC_REGRESSION`, `CONTROL`, and
`MECHANISM_PRESERVING_MUTATION` attempts remain available to all-pool
diagnostics but cannot enter
this primary estimate. Missing planned hidden observations fail closed as
`NOT_EVALUABLE/MISSING_PLANNED_OBSERVATIONS` and suppress the numerator,
denominator, rate, excluded-state aggregates, and interval rather than exposing
a partial estimate. A zero model-scorable denominator
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
| `BM0-SAP-03-TYPED-TERMINAL-PARTITION-V1` | `typed_terminal_partition_v1` | bind rows to the frozen manifest, reject duplicate/unplanned rows, retain all six states, and suppress the diagnostic rate for a partial grid |
| `BM0-SAP-04-MODEL-FAILURE-DENOMINATOR-V1` | `model_failure_denominator_v1` | use only `FAIL / (PASS + FAIL)` on one registered metric's target classes, suppress incomplete-grid aggregates, and emit no ranking |
| `BM0-SAP-05-WILSON-INTERVAL-V1` | `wilson_interval_v1` | deterministic two-sided 95% Wilson interval; zero denominator is not evaluable |
| `BM0-SAP-06-PAIRED-COMPLETE-CASE-V1` | `paired_complete_case_v1` | pair on formal entry/family/case/variant, replicate, and retry ordinal; require matching case/configuration, wrappers, prompt/context/tool/sandbox/state, scorer/oracle, seed, adapter, and environment; otherwise fail closed |
| `BM0-SAP-07-ADJUDICATION-RESOLUTION-V1` | `resolve_adjudication_v1` | two distinct blind primaries; one distinct blind tiebreaker only for PASS-versus-FAIL disagreement; UNKNOWN is terminal |
| `BM0-SAP-08-SYSTEM-INVARIANT-FAILURE-RATE-V1` | `system_invariant_failure_rate_v1` | compute a complete-grid system-only typed rate under `SYSTEM_SCOPE`; suppress partial aggregates and never attribute it to a model or emit a ranking |
| `BM0-SAP-09-CASE-FAILURE-PROBABILITY-V1` | `case_failure_probability_v1` | compute CFP for one exact model/version and one case; repeated trials remain nested in that case |
| `BM0-SAP-10-FAMILY-CONDITIONAL-FAILURE-RATE-V1` | `family_conditional_failure_rate_v1` | compute FCFR as the unweighted macro mean of distinct-case CFP values in one formal family entry |
| `BM0-SAP-11-FCFR-CASE-CLUSTER-BOOTSTRAP-V1` | `fcfr_case_cluster_bootstrap_v1` | deterministic 10,000-resample percentile bootstrap over distinct `case_id` clusters, seed `20260904`, 95% interval |
| `BM0-SAP-12-CONTROL-FALSE-POSITIVE-RATE-V1` | `control_false_positive_rate_v1` | report matched `CONTROL` failures separately with a Wilson interval |
| `BM0-SAP-13-WITHIN-CASE-INSTABILITY-V1` | `within_case_instability_v1` | count repeat-eligible cases containing both PASS and FAIL; repeats never become distinct cases |
| `BM0-SAP-14-INFRASTRUCTURE-ERROR-RATE-V1` | `infrastructure_error_rate_v1` | report ERROR/planned attempts separately and forbid model-failure attribution |

The sample-size rule is explicitly
`BOUNDED-PILOT-FIXED-SUITE-V1`: 2–8 distinct cases per formal family entry and
2–5 repeated trials per case. Its claim is bounded-pilot,
mechanism-conditioned frequency evidence, not target-precision,
significance, superiority, ranking, or population evidence. Extending the
sample from observed outcomes is forbidden and requires a new frozen manifest
plus separate approval.

The metric registry separately freezes:

- CFP = `FAIL / (PASS + FAIL)` for one model/version × one case;
- FCFR = equal-weight mean across distinct case CFPs in one family entry;
- CFPR = failed matched `CONTROL` trials / scorable `CONTROL` trials;
- within-case instability = switching cases / repeat-eligible cases;
- infrastructure error rate = `ERROR / planned attempts`;
- the complete typed terminal distribution.

Wilson uncertainty applies to binary trial-level CFP/CFPR estimates. FCFR uses
case-cluster bootstrap uncertainty; repeated trials are never resampled or
weighted as independent case variants.

The no-peeking stop function accepts only `attempt_id` and `recorded`. The
manifest binds the central measurement-contract core, target matrix, metric
registry, corpus policy, frozen SAP, and executable implementation by
fingerprint. A `FROZEN` manifest is accepted only when the validator receives
the expected fingerprint map from an independent caller; a self-consistent
manifest alone is insufficient.
`terminal_status`, `model_failure_value`, `score`, output content, and
adjudication decisions are rejected rather than ignored.

System-only attempts may be scheduled in the same frozen manifest, but they use
the reserved provider/model/snapshot identity `SYSTEM_SCOPE` and remain outside
`comparison_classes`. Their missing rows and denominators are evaluated by the
system-only method. Observation records keep `model_failure_value` and
`system_invariant_failure_value` mutually exclusive by target class, so a
system failure cannot contaminate a model-failure rate.

## Identity and manifest freeze

Every planned attempt binds `benchmark_id`, contract version, study, trial,
attempt, optional parent attempt, provider, requested model, expected resolved
model/version and identity-certainty/alias limitation, endpoint/capability,
system/developer wrappers, full sampling and reasoning controls, formal entry,
family, target, stable case and variant, corpus lane, mechanism lineage, case
fingerprint, generator/mutation version, contamination/exposure status, corpus
alias and commitment, optional mutation-parent commitment, prompt/context/tool
schema/sandbox/state-machine fingerprints, harness, adapter, scorer, oracle,
replicate, random seed, and environment fingerprint. Moving snapshot aliases
such as `latest`, duplicate
attempt IDs, class/target mismatches, orphan or forward parents, identity drift,
and branching retries are invalid. Multiple attempts may share a trial only as
one ordered, identity-stable root-to-child chain; each remains a distinct
predeclared denominator unit and never replaces its parent.

Each observation separately records the actual resolved model/version,
identity certainty, provider request ID and terminal/HTTP status, timestamps,
raw-response and evidence-receipt fingerprints, scorer/oracle identity,
terminal and model/system failure tri-state, plus attributable usage, latency,
and observed cost. A scorable model observation requires a successful provider
receipt. Usage, latency, and cost are populated only when independently
attributable; otherwise their status is explicitly `UNAVAILABLE` with no value.
`NOT_APPLICABLE` is reserved for system-only observations. A provider/runtime
failure remains `ERROR`; it cannot be translated into model-quality `FAIL`. The grid rejects a
validly re-fingerprinted row if any planned case, wrapper, configuration,
scorer/oracle, or resolved-model identity drifted.

The checked manifest is deliberately a `DESIGN_ONLY` template:

- provider/model roster: `NOT_SELECTED`;
- corpus commitment: `NOT_COMMITTED`;
- adjudication mode: `NOT_SELECTED`;
- planned attempt count: `0`;
- sandbox equivalence: `NOT_ESTABLISHED`.

Execution requires a separate, fully populated `FROZEN` manifest created before
runtime access to the private holdout and containing at least one predeclared
private-hidden attempt. `SEALED` requires a non-null aggregate corpus
commitment, not a status assertion alone. The aggregate is deterministically
rebuilt from the unique private-holdout aliases and per-item commitments. A
corpus alias has exactly one pool/commitment binding, and an item commitment has
exactly one pool/alias binding; cross-pool alias drift, alias splitting, and
self-parenting mutations are rejected. That
manifest must also fingerprint the adjudication
plan: mode, allowed metrics, two primary identities and types, one distinct
tiebreak identity and type, an immutable configuration fingerprint for every
human protocol or fixed judge, and the exact rubric version and fingerprint.
The template itself cannot be used to execute a study.

## Corpus separation

The public contract uses the four mandatory lanes: `PUBLIC_REGRESSION`,
`PRIVATE_HIDDEN_HOLDOUT`, `MECHANISM_PRESERVING_MUTATION`, and `CONTROL`.
Public regression cases, controls, and mutations cannot enter the primary
hidden estimate. The private holdout's exact content, exact case
IDs, private locator, and per-case commitments remain outside the public
repository.

Every mutation-pool identity must disclose its parent commitment. A mutation
whose parent commitment occurs in the private hidden pool is rejected, as is
reuse of one exact item commitment across corpus pools.

An independent curator first selects the private holdout and creates its
aggregate commitment outside the public repository. The execution manifest
then freezes that commitment and the opaque planned identities; only afterward
may execution be authorized, the holdout be opened to the execution path, and
access be logged. Thus exact content remains hidden from developers and models
before freeze while the manifest can truthfully bind a pre-existing seal. The contract
forbids treating the `B2-BLIND-01` / PR #30 corpus or outputs as BM0 material by
assumption.

The public manifest contains a machine-validated
`NOT_IN_PUBLIC_REPO_DECLARATION` binding. Its fixed non-secret ID and safe
fingerprint state that exact prompts, inputs, labels, oracle-bearing content,
and private locators are absent. A later execution manifest may instead bind a
non-secret private File ID or archive identifier, but cannot embed a secret or
confidential locator.

## Adjudication and claim ceiling

PASS or FAIL adjudication requires complete evidence. Primaries and any
tiebreaker must use distinct adjudicator identities and remain blind to model,
provider, and peer decisions. Runtime records must match the adjudicator set,
mode composition, metric, attempt, item alias, and rubric frozen in the
manifest; an unplanned substitute is rejected. Missing or insufficient
adjudication remains `UNKNOWN` and cannot be converted to PASS or FAIL by a
tiebreaker. A tiebreaker is legal only when two complete primaries disagree
PASS versus FAIL. An adjudication-system failure remains `ERROR` and is never
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
| QA0/QA1-G/QA1-T/QA2/QA3 source fixtures and PASS receipts | canonical E01–E16 lineage and 32 matched source-case bindings |

Artifact fingerprints use the repository's canonical `sha256_json` encoding.
JSON artifacts are hashed as parsed canonical objects; the Python implementation
and its tests are hashed as canonical UTF-8 source strings. The manifest's
`measurement_contract_core` commitment hashes the central contract with only
`artifact_bindings` and `contract_fingerprint` removed, which binds semantics
without creating a contract↔manifest fingerprint cycle.

## Acceptance boundary

The developer receipt remains `bm0_green: false`, with exact-head CI and
Independent QA both `NOT_RUN`. BM0 becomes green only after the exact candidate
head passes CI and a reviewer distinct from the implementation path records a
BM0-specific Independent QA PASS. Merge and release require separate
authorization.
