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

See [`search-cup-v2.2-architecture-reconciliation.md`](search-cup-v2.2-architecture-reconciliation.md) for the current protocol boundary.
