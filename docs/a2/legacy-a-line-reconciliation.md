# Legacy A-Line Evaluation Asset Reconciliation

**Work order:** [ENG-A2-RECON-01 / Eval Lab Issue #14](https://github.com/aerenkolstein-code/llm-evaluation-lab/issues/14)  
**Primary repository:** `aerenkolstein-code/llm-evaluation-lab` (A2 / measurement)  
**Read-only source:** `aerenkolstein-code/Companion-Mind` (A1 / runtime)  
**Evidence cut-off:** 2026-08-17  
**Status:** docs-only reconciliation; all code, test, workflow, data, and live-execution migration is deferred

## Scope and authority

This report reconciles the legacy A-line assets in Companion-Mind PRs [#4](https://github.com/aerenkolstein-code/Companion-Mind/pull/4), [#5](https://github.com/aerenkolstein-code/Companion-Mind/pull/5), [#7](https://github.com/aerenkolstein-code/Companion-Mind/pull/7), [#8](https://github.com/aerenkolstein-code/Companion-Mind/pull/8), and [Issue #6](https://github.com/aerenkolstein-code/Companion-Mind/issues/6). Companion-Mind was inspected as a read-only source. None of those branches is merged or modified by this work.

This report is an ownership and lineage map, not a new runtime specification. Companion-Mind [Issue #11](https://github.com/aerenkolstein-code/Companion-Mind/issues/11) is the current A1 Phase 0 hard gate for canonical event and runtime boundaries. Legacy v1/v2 names below identify historical experiment lanes only; they do not supersede or duplicate A1 truth.

Out of scope: code or test migration, merging legacy PRs, Companion-Mind Runtime changes, live or paid model calls, rerunning PR #8 / ENG-DIAG-03, Search Cup P2, A1 Phase 1+, and product implementation.

## Disposition legend

| Disposition | Meaning in this reconciliation |
|---|---|
| `A1-OWNED` | Product/runtime authority remains in Companion-Mind. A2 may consume a future published contract but must not copy or redefine the implementation. |
| `A2-INHERIT` | Provider-neutral evaluation or evidence contract is reusable without changing its semantics. Implementation still waits for a separately authorized migration. |
| `A2-REFACTOR` | Evaluation intent belongs in A2, but the legacy asset is coupled to Companion-Mind internals, provider calls, or old branch topology and must be redesigned before migration. |
| `EVAL-ONLY` | Frozen historical evidence. It can support lineage or a prior-result record but cannot be treated as current runtime truth or a release claim. |
| `RETIRE` | Do not carry forward. Keep only enough provenance to explain why the asset is no longer executable or authoritative. |

## Source ledger

| Source | Frozen role and observed status | Reconciliation consequence |
|---|---|---|
| CM PR #4 | Open draft, unmerged. Provider-independent Persona/State/Runtime skeleton; 32 implementation tests reported green. | Runtime implementation and its tests remain `A1-OWNED`; no branch merge or source copy. |
| CM PR #5 | Open draft, stacked on #4. Provider adapters, Prompt/Runtime v1, RAW attempt handling, native/runtime baselines and diagnostics. | Separate runtime code from evaluation contracts. Historical aggregates are not current benchmark claims. |
| CM Issue #6 | Open legacy work order for Runtime Contract v2. It specified product transitions plus offline gates, then required a separate live authorization. | Product schema/transition rules remain `A1-OWNED`; evaluation scenarios and gates require A2 decoupling. The later one-shot authority is spent. |
| CM PR #7 | Open draft, stacked on #5. Offline Runtime v2 implementation; 66 tests reported green; no live calls in the PR implementation phase. | Implementation and conformance tests remain `A1-OWNED`; the green count is historical conformance evidence only. |
| CM PR #8 | Open draft, stacked on #7. One-shot ENG-DIAG-03 harness and terminal execution record. | The experiment is terminal and must not be rerun. Reuse only its provider-neutral control envelope. |

## Inventory matrix

The path groups below cover the changed assets in all four required PRs plus the requirements and experiment contracts in Issue #6. A disposition applies to the complete path group named in its row.

| Source | Asset / path group | Kind | Disposition | Reason and future handling |
|---|---|---|---|---|
| PR #4 | `companion_mind/persona/{models,loader}.py`, `personas/lin_zhiyao.yaml` | Persona schema/config/loader | `A1-OWNED` | Product identity and persona loading are runtime authority. A2 must use synthetic/public-safe fixtures and a published adapter, not copy persona truth. |
| PR #4 | `companion_mind/state/{models,store}.py`, `companion_mind/runtime.py` | Runtime state and persistence | `A1-OWNED` | State shape, atomic persistence, session start, and event production are product responsibilities. Legacy classes are not an A2 schema. |
| PR #4 | `companion_mind/{__init__,persona/__init__,state/__init__}.py`, `pyproject.toml`, `.gitignore` | Package surface | `A1-OWNED` | Companion-Mind packaging and exports stay with A1. |
| PR #4 | `tests/test_persona_runtime.py`, `.github/workflows/test.yml` | Runtime conformance tests/CI | `A1-OWNED` | These verify A1 implementation invariants, not companion behavior. A2 should later test only an external versioned contract. |
| PR #4 | `README.md`, `README.zh-CN.md` | Runtime documentation | `A1-OWNED` | Retain as historical A1 context; do not transplant as A2 authority. |
| PR #5 | `companion_mind/providers/{base,deepseek,__init__}.py` | Provider adapter/runtime I/O | `A1-OWNED` | Provider invocation and response normalization are product/runtime concerns. A2 may own runner configuration, not the product adapter. |
| PR #5 | `companion_mind/{prompt,runtime}.py`, `companion_mind/state/models.py` | Prompt Contract v1 and history/state wiring | `A1-OWNED` | Prompt assembly and runtime state are implementation. The v1 lane may be named in historical comparisons only. |
| PR #5 | `companion_mind/raw/{writer,__init__}.py`, `companion_mind/__init__.py` | RAW attempt persistence/runtime exports | `A1-OWNED` | A1 owns canonical event production. A2 owns separate experiment receipts after ingestion, not source-of-truth conversation RAW. |
| PR #5 | `tests/test_persona_runtime.py` | Extended runtime conformance tests | `A1-OWNED` | These remain internal A1 implementation checks; their assertions are not an A2 behavioral rubric. |
| PR #5 | `scripts/cross_model_native_baseline.py`, `tests/test_cross_model_native_baseline.py` | Native baseline runner/tests | `A2-REFACTOR` | Benchmark intent belongs in A2, but the code is provider- and legacy-corpus-coupled. Rebuild behind a neutral runner and synthetic/public-safe corpus. |
| PR #5 | `scripts/deepseek_private_baseline.py`, `tests/test_deepseek_private_baseline.py`, `tests/test_deepseek_baseline.py` | Private/runtime baseline runner/tests | `A2-REFACTOR` | Preserve lane, rubric, and failure-code intent; do not copy private inputs, product imports, or branch-specific assumptions. |
| PR #5 | `scripts/glm_runtime_lift.py`, `tests/test_glm_runtime_lift.py` | Runtime-lift diagnostic | `A2-REFACTOR` | The comparison belongs in evaluation, but must wait for a frozen A1 adapter and a provider-neutral experiment contract. |
| PR #5 | `scripts/deepseek_live_smoke.py`, `tests/test_deepseek_live_smoke.py` | Legacy live-smoke executor | `RETIRE` | No present authorization to execute or migrate this paid/live path. Preserve only its failure-accounting principles. |
| PR #5 | `.github/workflows/{cross-model-native-baseline,deepseek-live-smoke,deepseek-private-baseline,glm-runtime-lift}.yml` | Legacy live/manual orchestration | `RETIRE` | Old workflows and triggers do not convey execution authority. Any future workflow requires a new A2 gate and new secrets review. |
| PR #5 | `.github/keys/lin_zhiyao_baseline_recipient.crt` | Legacy artifact recipient | `RETIRE` | Do not copy repository-specific cryptographic material. Retention/removal in Companion-Mind is an A1/governance decision. |
| PR #5 | `README.md`, `README.zh-CN.md` | Runtime/diagnostic documentation | `A1-OWNED` | Keep as historical source context; A2 records only approved provenance and avoids copying runtime claims. |
| PR #5 | Public experiment envelope: immutable model/corpus/commit identifiers, attempt ledger, aggregate-only public telemetry, private/public artifact split | Experiment contract | `A2-INHERIT` | These semantics are provider-neutral and compatible with A2's evidence role. No private content, secrets, or archive locators may cross repositories. |
| PR #5 | Reported aggregate results: DeepSeek Native 6/18, DeepSeek Runtime v1 12/18; GPT-4.1-mini Native 9/18; GLM-4.6 Native 13/18; GLM-4.7 Native 10/18; GLM-4.7 Runtime v1 3/18; other recorded GLM diagnostics | Historical results | `EVAL-ONLY` | Preserve as labeled prior observations with their original lane/commit context. They are not comparable as one current leaderboard and must not support a current release claim. |
| Issue #6 | Stable Core, Current State, UNKNOWN semantics, Observer, StateDelta, validator/reducer, replay, Prompt Contract v2, size caps | Product/runtime contract | `A1-OWNED` | These are legacy A1 requirements. Current canonicalization belongs to Issue #11; A2 must not adopt these definitions as authority. |
| Issue #6 | Offline scenarios A–H, lane isolation, fixed corpus/order/seed/model, hard-failure assertions, score gates | Evaluation scenarios/gates | `A2-REFACTOR` | Convert product-specific assertions into rubric/case contracts only after A1 publishes the canonical boundary. Keep scenario meaning; remove direct runtime internals. |
| Issue #6 | Authorization for the later 20 persona + 20 observer live diagnostic | Execution authority | `RETIRE` | The authorization was one-shot and culminated in PR #8. It cannot be reused for another run. |
| PR #7 | `companion_mind/{observer,prompt,runtime}.py`, `companion_mind/state/{models,transitions,delta_store,__init__}.py`, `companion_mind/persona/models.py`, `companion_mind/{__init__}.py`, `personas/lin_zhiyao.yaml` | Runtime v2 implementation | `A1-OWNED` | Product state transitions, observer integration, prompt generation, and journal persistence remain in A1 and are non-canonical legacy until reconciled under Issue #11. |
| PR #7 | `tests/test_runtime_contract_v2.py`, `tests/test_deepseek_baseline.py` | Runtime conformance/integration tests | `A1-OWNED` | These validate internal implementation. A2 may later derive black-box behavioral cases, not migrate the tests. |
| PR #7 | `README.md`, `README.zh-CN.md` | Runtime v2 documentation | `A1-OWNED` | Historical A1 documentation only. |
| PR #7 | Reported offline result: 66 tests green | Historical conformance result | `EVAL-ONLY` | Valid evidence that the legacy branch passed its stated offline suite; not evidence of live behavior improvement. |
| PR #8 | Manifest/fingerprint checks, exact call ceiling, no retry, fail-stop semantics, attempt-versus-success accounting, aggregate telemetry, private/public split, preserved-state replay check | Experiment control envelope | `A2-INHERIT` | Reuse these semantics without executing the old workflow or importing private artifacts. |
| PR #8 | `scripts/glm_runtime_v2_recovery.py`, `tests/test_glm_runtime_v2_recovery.py` | Runtime-coupled recovery harness/tests | `A2-REFACTOR` | Evaluation intent belongs in A2, but imports, prompts, corpus handling, and assertions are tied to the legacy Runtime v2 branch. No code/test migration in this work. |
| PR #8 | `.github/workflows/glm-runtime-v2-recovery.yml` and its one-shot/manual execution path | Legacy live orchestration | `RETIRE` | The experiment is terminal; workflow presence is not permission to rerun it. |
| PR #8 | Terminal ENG-DIAG-03 record: Persona attempted 1/succeeded 0; Observer attempted 0; `PERSONA_CALL_FAILED`; behavior not evaluable; no retry/second trajectory | Historical terminal result | `EVAL-ONLY` | Preserve exactly as an operational terminal outcome. Do not assign a behavior score, infer Runtime v2 quality, or rerun to fill the missing matrix cell. |

## Ownership map

### A1 owns system truth

A1 owns canonical events, runtime state and persistence, persona/relationship authority, prompt construction, provider adapters, observer/reducer behavior, and implementation/conformance tests. A2 must consume a versioned public boundary after A1 freezes it; it must not copy legacy runtime models into evaluation schemas.

### A2 owns measurement truth

A2 owns public-safe case contracts, experiment manifests, lane definitions, rubrics and scoring, regression gates, run/result identities, aggregate telemetry, reproducibility controls, and claims discipline. A2 behavioral tests answer whether externally observable behavior improves; they do not prove A1 internal correctness.

### Shared seam

The seam is a future versioned adapter/event contract: A1 publishes and tests production conformance; A2 validates that fixtures and runner inputs conform, then measures behavior through the public surface. Until Issue #11 freezes that seam, legacy v1/v2 imports remain prohibited.

## Reusable asset map

The following semantics may be inherited into future A2 design without rerunning any legacy experiment:

1. Immutable run identity containing source commit, corpus fingerprint, lane/model configuration, prompt/contract version, and UTC execution identity.
2. Explicit attempted/succeeded/failed call accounting with a hard call ceiling, no hidden retries, and a terminal failure reason.
3. Fixed lane/corpus/order/seed controls and a single-change comparison declaration.
4. Public aggregate telemetry separated from encrypted/private evidence; no prompts, responses, persona secrets, or archive locators in public artifacts.
5. Deterministic result serialization/fingerprinting, preserved-input or preserved-state replay checks, and fail-closed validation.
6. Hard-failure codes and release gates as rubric concepts, provided their definitions are re-grounded in a public-safe A2 case contract.

PR #8 is reusable only through items 1–5 and its frozen terminal receipt. Its workflow, model calls, corpus, and incomplete behavior lane are not reusable execution assets.

## Do-not-inherit list

- Companion-Mind Persona, State, Observer, Reducer, Prompt, provider, RAW writer, or persistence implementations.
- Legacy v1/v2 classes or schemas as current canonical contracts.
- Private prompts/responses, encrypted artifacts, keys/certificates, account identifiers, or private archive links.
- Old GitHub Actions triggers, repository secrets, paid-call paths, or prior one-shot authorizations.
- Historical aggregate scores as current benchmark, release, generalization, or model-ranking claims.
- Any implication that an offline implementation test is a behavioral evaluation.
- Search Cup assets or gates; repository co-location does not make Search Cup part of A2.

## v1/v2 coupling decision

Runtime v1 and v2 are inseparable from their original Companion-Mind branch topology, prompt serialization, state classes, provider adapters, and corpus handling. A2 may retain `runtime-v1` and `runtime-v2` as historical lane labels in provenance, but must not import either implementation. A future comparison must target the canonical interface that emerges from A1 Issue #11 and record any legacy adapter as an explicit compatibility layer.

## Legacy source disposition

| Legacy source | Recommendation |
|---|---|
| PR #4 | Do not merge for A2. Keep as read-only A1 lineage; reconcile any still-needed product ideas through the current A1 work order. |
| PR #5 | Do not merge. Preserve public aggregate lineage, then refactor only approved evaluation contracts in A2 under new tickets. Retire old live workflows. |
| Issue #6 | Keep as a historical requirements record while open/closure status is decided by A1. It grants no new A2 migration or live authority. |
| PR #7 | Do not merge for A2. Treat implementation and tests as legacy A1 material subject to Issue #11, not as an A2 dependency. |
| PR #8 | Do not merge or rerun. Preserve the terminal receipt and reusable control-envelope semantics; retire the executable path. |

## Deferred follow-up tickets

These are recommendations only; this reconciliation does not create or execute them.

1. **A1 canonical boundary export** — after Issue #11, publish the versioned event/adapter schema and black-box conformance contract A2 may consume.
2. **A2 legacy evidence registry** — decide whether approved public aggregates become immutable `legacy` result records or remain link-only provenance.
3. **A2 provider-neutral runner** — implement run identity, fingerprints, call accounting, fail-stop/no-retry controls, and content-free receipts without importing Companion-Mind internals.
4. **A2 continuity case/rubric pack** — translate approved Issue #6 scenarios and hard-failure concepts into synthetic public-safe cases and externally observable scoring.
5. **A2 adapter compatibility gate** — after the A1 boundary freezes, verify fixtures and runner integration at the published seam; keep product conformance tests in A1.
6. **Separately authorized live study** — only after the preceding offline gates and a new Board approval; no legacy workflow or authorization may be reused.

## Minimum future A2 migration sequence

1. Close the A1 Issue #11 Phase 0 contract decision and publish a versioned external seam.
2. Resolve the Board decisions below, especially evidence retention and the future observer lane.
3. Import only approved public-safe provenance and provider-neutral contracts; keep PR #8 as a terminal, non-scored prior result.
4. Build synthetic cases, rubric, manifest, and offline runner entirely in Eval Lab.
5. Add a black-box adapter compatibility gate against the A1-published interface.
6. Demonstrate deterministic offline replay and regression behavior before requesting any live/provider authorization.
7. If separately approved, create a new bounded live work order with fresh secrets, cost ceiling, stop conditions, and no hidden retries.

No step above is authorized by this report; migration remains deferred.

## Board decisions still required

| Decision | Closest current disposition | Why it is unresolved |
|---|---|---|
| Check in frozen public aggregate records from PR #5/#8 versus retain link-only provenance | `EVAL-ONLY` — `NEEDS-BOARD-DECISION` | Checked records improve reproducibility, but lineage, licensing/privacy review, and non-comparability labels must be approved first. |
| Preserve a legacy v1/v2 compatibility adapter after Issue #11 versus map only to the new canonical contract | `A2-REFACTOR` — `NEEDS-BOARD-DECISION` | A compatibility layer helps historical comparison but risks cementing superseded A1 semantics. |
| Include an independent observer lane in a future A2 live study, with its extra call/cost ceiling | `A2-REFACTOR` — `NEEDS-BOARD-DECISION` | PR #8 produced no observer attempt, so no behavior evidence resolves the design or budget choice. |
| Retain or remove the old encrypted private artifacts and recipient certificate in Companion-Mind | `RETIRE` — `NEEDS-BOARD-DECISION` | A2 must not migrate them; repository retention, privacy, and audit requirements belong to A1/governance. |

## Acceptance check

- [x] CM PRs #4/#5/#7/#8 and Issue #6 explicitly reconciled.
- [x] Every asset group assigned one of the five required dispositions.
- [x] A1 implementation truth is referenced, not duplicated or redefined.
- [x] Runtime conformance tests separated from A2 behavioral evaluation.
- [x] Legacy contracts/results and v1/v2 coupling identified.
- [x] PR #8 preserved as terminal and non-scored; no rerun performed.
- [x] Search Cup remains a separate workstream.
- [x] Private inputs, outputs, credentials, and archive locators excluded.
- [x] Code/test/workflow/data migration deferred.
- [x] This change is documentation only.
