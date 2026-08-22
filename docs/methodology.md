# Methodology

The repository uses versioned, public-safe evaluation artifacts and keeps measurement claims narrower than the implementation surface.

## General principles

- Preserve exact experiment identity and configuration.
- Keep private source material outside public fixtures.
- Separate implementation evidence from claims of broad generalization.
- Treat UNKNOWN as distinct from supported fact or known-empty state.
- Keep failure, network, provider, and schema errors separate from model-quality judgments.
- Prefer reproducible contracts, immutable evidence, and explicit limitations.

## SEARCH-CUP methodology v2.2

SEARCH-CUP now separates four sources of search performance:

1. **Search Architecture / Strategy** — an upstream Human+Model co-design process. It defines the task, languages, sources, hard gates, budget allocation, and stop rules. It is recorded, but is not treated as a clean single-model leaderboard variable.
2. **Agent Search Execution** — the entrant model's query formulation, bounded refinement, and evidence-path following under a frozen Search Spec and common neutral/transparent retriever contract.
3. **Result Judgment** — the entrant's classification/ranking of a common candidate set, ideally with source-model provenance blinded.
4. **Retriever / Search-Stack quality** — capabilities supplied by the backend itself, including query rewrite/decomposition, retrieval/ranking, aggregation, or synthesis.

### Fair model comparison

The main bare-model Cup uses:

- byte/semantically identical task and Search Spec;
- the same allowed tool contract;
- the same transparent/neutral retriever;
- the same search-call/turn budget;
- the same time window;
- the same retry policy;
- exact model/version/config recording;
- hidden judge/registry isolation until frozen submission.

A dedicated smart search product is not used as an invisible common substrate if it performs its own high-level decomposition/planning. Instead, it is evaluated as a separate system-level challenger.

### E1 / E2 separation

- **E1 Agent Search Execution:** fixed retriever/backend, task, spec, and budget; vary the entrant model.
- **E2 Retriever Benchmark:** fixed entrant model/agent, task, spec, and budget; vary the retriever/backend.

This prevents retriever gains from being mislabeled as model gains, or vice versa.

### Live Web vs Frozen Corpus

- **Live Web** maximizes ecological validity but is time/index/ranking dependent. Prefer pooled adjudication, unique valid yield, evidence coverage, and cost-normalized metrics; do not claim exhaustive recall unless a defensible answer universe exists.
- **Frozen Corpus** maximizes reproducibility. Record corpus provenance/version/hash and use stable reference/adjudicated labels when available, enabling Recall@Budget, Precision@K, F1, and deterministic replay.

Results from Live and Frozen tracks remain separately labeled.

### Task design

Prefer **hard-to-find, easy-to-verify** tasks: discovery should require real search work, while a found answer should be confirmable from clear evidence with low judging ambiguity.

### Judgment-only track

Pool and deduplicate candidate results, blind entrant provenance, provide the same rubric, and prohibit extra search unless the protocol explicitly creates a verification subtrack. Useful metrics include false opportunity rate, false reject rate, calibration, UNKNOWN discipline, and Top-K actionable precision.

### Dedicated search-stack challenge

GLM Search/Search Agent or any future dedicated intelligent search stack is evaluated separately from the bare-model leaderboard. Recommended sequence:

1. four-model bare-agent Cup;
2. dedicated search-stack challenge;
3. winner-vs-stack playoff under an explicitly declared resource budget.

### Historical evidence

SEARCH-CUP-02 v0.1 evidence remains valid as **Strategy-heavy End-to-End Search Evidence**. Existing P0/P1/P2 implementation assets are retained. They are not retroactively relabeled as E1-only results unless their historical protocol satisfies the v2.2 isolation requirements.

See [`search-cup-v2.2-architecture-reconciliation.md`](search-cup-v2.2-architecture-reconciliation.md) for the v2.2 protocol boundary.

## SEARCH-CUP methodology v2.3 — Winner-vs-Search-Stack fairness

v2.3 adds a fairness distinction for comparing the bare-model champion with an integrated search stack such as GLM Search/Search Agent.

A search-credit invocation may itself contain query-level intent understanding, query decomposition/rewrite, retrieval/ranking, aggregation, and synthesis. Therefore one search credit is not assumed to be equivalent to one neutral/raw retriever call.

Search Architecture is further split into:

- **A0 Search Program Architecture:** task goal, markets/languages/sources, layers, budget allocation, stop rules, and economic success criteria. Primarily Human+Model co-design.
- **A1 Query-Level Search Planning:** intent understanding, query decomposition/rewrite, and local search-direction selection inside a frozen task. An integrated Search Agent may contribute part of A1.

Three fairness questions must remain separate:

1. **F1 Bare-Model Fairness** — same frozen Search Spec, neutral retriever, budget, time window, and output/evidence contract; compare general-purpose models only.
2. **F2 System Fairness** — same A0 Search Program, task goal, deadline, success criteria, and output contract; allow each declared system to use its native search capabilities; compare complete systems, not pure model ability.
3. **F3 Economic Fairness** — align comparable real-world resources such as money or time, then compare value produced per resource unit instead of mechanically equalizing call counts.

For economic tracks, useful metrics include Actionable Leads / Cost, Unique Valid Discovery / Cost, Qualified Replies / Cost, Paid Conversion / Cost, Revenue / Cost, and Time-to-First-Actionable-Result.

If causal attribution is required, use **Capability-Matched Ablation** to isolate query planning/decomposition, retrieval, ranking/aggregation, and synthesis while holding other components fixed where feasible.

Any future Winner-vs-Stack report must separately publish Bare Cup, System Playoff, and Economic Playoff results. A single total score must not collapse F1/F2/F3 into one champion.

GLM search credits belong to the dedicated search-stack/economic tracks and are not part of the Four-Model Bare Search Cup neutral budget pool.

See [`search-cup-v2.3-fairness-framework.md`](search-cup-v2.3-fairness-framework.md) for the current fairness framework.
