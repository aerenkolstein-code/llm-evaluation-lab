# Method Lineage

This repository keeps evaluation-method changes versioned rather than silently rewriting historical evidence.

## SEARCH-CUP lineage

- **SEARCH-CUP-02 v0.1** — strategy-heavy end-to-end four-model web-search benchmark using a provider-independent `SearchProxy`, strict per-entrant search budget, frozen submissions, and a hidden-registry judge.
- **P0/P1/P2 engineering lineage** — fairness harness, unified real-search boundary, four provider adapters, normalized `SearchResult`, trace/budget accounting, and typed `NOT_EVALUABLE` semantics.
- **Search Cup Architecture v2.2** — measurement reconciliation that separates Search Architecture Co-Design, bare-model Search Execution, Result Judgment, and Retriever/Search-Stack quality; adds Live Web vs Frozen Corpus tracks; keeps dedicated intelligent search stacks such as GLM Search as separate system challengers.

Current reconciliation document:

- [`search-cup-v2.2-architecture-reconciliation.md`](search-cup-v2.2-architecture-reconciliation.md)

Historical v0.1 results remain valid as **Strategy-heavy End-to-End Search Evidence**. They are not silently relabeled as pure execution results.
