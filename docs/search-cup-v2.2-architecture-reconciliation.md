# SEARCH-CUP Architecture Reconciliation v2.2

Status: CURRENT ARCHITECTURE / DOCS-ONLY RECONCILIATION / NO OFFICIAL MATCH AUTHORIZATION

Date: 2026-08-22

Applies to: `SEARCH-CUP-02` / Issue #8 and the stacked P0/P1/P2 work, including Draft PR #17.

## Why this reconciliation exists

The original SEARCH-CUP-02 v0.1 design intentionally put OpenAI, Gemini, DeepSeek, and GLM behind one provider-independent `SearchProxy -> search_pro -> public web` path. That was a strong fairness improvement over letting every provider use a different proprietary search index, and the existing P0/P1/P2 engineering work remains useful.

However, the measurement target has now been refined. A search benchmark can accidentally mix several distinct capabilities:

1. **Search Architecture / Strategy** — deciding what to search, how to decompose the task, which languages/sources to use, how to allocate budget, and when to stop.
2. **Search Execution** — under a frozen Search Spec, generating concrete queries, refining them within bounds, and following evidence paths efficiently.
3. **Result Judgment** — deciding which returned candidates are relevant, fresh, genuine, hidden/crowded, actionable, sufficiently evidenced, or UNKNOWN.
4. **Retriever / Search-stack quality** — capabilities supplied by the backend itself, including query rewriting/decomposition, retrieval, ranking, aggregation, and synthesis.

A smart search backend can therefore improve a weak entrant query. If such backend intelligence is not isolated, part of the measured score may belong to the search stack rather than to the entrant model.

## v2.2 governing interpretation

### A. Search Architecture is co-designed, not ranked as a pure model capability

Search Architecture is treated as an upstream Human+Model co-design process. The benchmark records its revisions and final frozen Search Spec, but the main leaderboard does not pretend that this interactive design process is a clean single-model variable.

### B. Main Cup = bare-agent execution under a neutral/transparent retriever contract

The primary model-comparison track should answer:

> Given the same frozen Search Spec, the same transparent retriever contract, the same budget, the same time window, and the same evidence rules, which general-purpose model executes search best?

"Bare" does **not** mean no web tool. It means the common search layer must not silently perform another intelligent agent's high-level decomposition/planning on behalf of an entrant.

The four general-purpose entrants remain provider-isolated and receive the same tool schema and normalized results.

### C. GLM Search / Search Agent is a separate system-level challenger

A dedicated search stack that performs intent recognition, query decomposition/rewrite, retrieval, routing/aggregation, or answer synthesis is evaluated as a **search system**, not used as the invisible common substrate for the bare-model leaderboard.

Recommended sequence:

1. Four-model Bare-Agent Cup.
2. Dedicated GLM Search Stack Challenge.
3. Winner-vs-Stack Playoff using the same task family and a clearly declared resource budget.

Search coupons/credits dedicated to the GLM search product belong to this system-level challenge (or real-world commercial search experiments), not to the neutral main Cup budget.

### D. Agent and Retriever are separately attributable

v2.2 defines two execution experiments:

- **E1 — Agent Search Execution:** fixed retriever/backend, fixed Search Spec, fixed budget; vary the entrant model.
- **E2 — Retriever Benchmark:** fixed model/agent, fixed task/Search Spec/budget; vary the retriever/search backend.

No score may attribute E2 gains to the model or E1 gains to the retriever.

### E. Judgment is blind and separable

Judgment-only evaluation uses the same pooled candidate set, with entrant provenance hidden, a common rubric, and no extra search unless the protocol explicitly creates a Judgment+Verification subtrack.

This enables independent measurement of false opportunity rate, false reject rate, UNKNOWN discipline, calibration, and Top-K actionable precision.

## Live Web and Frozen Corpus tracks

v2.2 supports two distinct environments.

### Live Web Track

Purpose: ecological validity and current-world usefulness.

Properties:
- real current web;
- vulnerable to index/ranking/page drift;
- results are timestamped;
- absolute recall is not claimed when an exhaustive answer set is unavailable;
- pooled adjudication, unique valid yield, evidence coverage, and cost-normalized metrics are preferred.

### Frozen Corpus Track

Purpose: reproducibility and strict cross-model comparison.

Properties:
- versioned corpus;
- corpus provenance/hash recorded;
- stable reference/adjudicated labels can exist;
- Recall@Budget, Precision@K, F1, and deterministic replay are appropriate.

Live and Frozen results must not be merged into one unlabeled leaderboard.

## Task-authoring principle

Prefer **hard-to-find, easy-to-verify** tasks:

- ordinary one-shot search should not trivially reveal the answer;
- once a candidate is found, correctness should be supportable by clear evidence;
- task difficulty should primarily come from discovery/search, not subjective judging.

## Standardized resource and output contracts

A formal track freezes at least:

- task and Search Spec;
- allowed source/retriever contract;
- maximum search calls/turns;
- per-call result limits where applicable;
- follow-link / verification allowance;
- automatic retry policy;
- time window;
- model identity and sampling config;
- output schema;
- evidence requirements;
- UNKNOWN semantics.

If token or monetary budget is used as a fairness variable, it must be explicitly declared rather than silently inferred across providers with incompatible accounting.

## Compatibility with existing P0/P1/P2 assets

The following assets remain valid and should be reused rather than rewritten:

- P0 fairness harness and hidden-registry isolation;
- provider-independent tool boundary;
- strict per-entrant search-budget enforcement;
- standardized `SearchResult`;
- auditable query/result/error/call trace;
- `automatic_retries = 0` boundary where already authorized;
- four provider adapters and exact requested/resolved model identity receipts;
- common `Submission` validation;
- freeze/hash concepts;
- secret exclusion and leak checks;
- typed `NOT_EVALUABLE` handling for provider/network/tool failures.

The existing P1 `search_pro` backend work is retained as prior engineering evidence and as a candidate retriever/search-stack integration. Its score interpretation must depend on whether the selected endpoint behaves as a neutral retriever or a smart search stack.

## Historical result labels

Old SEARCH-CUP-02 results/runs that allowed entrants to choose queries/refinements and also included final lead selection/judgment are labeled:

**Strategy-heavy End-to-End Search Evidence**

They are not retroactively relabeled as E1-only Search Execution results unless the old protocol demonstrably isolated the same variables required by v2.2.

## Updated experimental matrix

1. **E1-Live:** same neutral retriever + frozen Search Spec + same budget; compare general-purpose models on live web.
2. **E1-Frozen:** same frozen corpus/retriever + Search Spec + budget; compare general-purpose models reproducibly.
3. **E2-Retriever:** same model + same task/spec/budget; compare search backends.
4. **J-Judgment:** same pooled/blinded result set; compare result judgment.
5. **E+J End-to-End:** fixed architecture assumptions; compare combined execution + judgment, clearly labeled as composite.
6. **Search-Stack Challenge:** dedicated GLM search stack (and future specialized stacks) as system-level entrants.
7. **Winner-vs-Stack Playoff:** best bare general-purpose entrant vs dedicated search stack under declared budgets.
8. **Economic End-to-End:** real-world tasks such as hidden paid-information-demand mining; evaluate actionable opportunities, paid conversion, revenue/search-credit, and time-to-first-paid-result as system/business metrics, not pure model scores.

## Repository / phase impact

This reconciliation is intentionally docs-only.

- **Do not continue to P3 under the old v0.1 measurement interpretation.**
- **Do not merge Draft PR #17 solely on the assumption that the current search backend is the final neutral main-Cup backend.**
- Preserve P2 adapter code and smoke evidence while the v2.2 protocol decides the neutral retriever contract and GLM search-stack challenge boundary.
- No official competition prompt may be consumed.
- No hidden judge/registry access may be added to entrant execution.
- No new paid/live official match is authorized by this document.

## Next protocol gate

Before implementation continues, a v2.2 Protocol Stage Plan must freeze:

1. `SearchSpec` schema and allowed bounded refinement;
2. neutral retriever acceptance criteria;
3. GLM Search Stack challenge contract;
4. E1/E2 variable-control matrix;
5. Live/Frozen track contracts;
6. frozen corpus provenance/version/hash rules;
7. standardized search-turn/budget and output/evidence contracts;
8. Judgment pooled/blind pipeline and adjudication rubric;
9. v1 -> v2.2 result-label migration;
10. exact reuse plan for P0/P1/P2 code and Draft PR #17.

Until that gate is approved: **STOP before P3, official prompt execution, hidden judge integration, or official paid/live competition.**
