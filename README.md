# LLM Evaluation Lab

> This repository contains evaluation harnesses, benchmarks, provenance/evidence tooling, and reproducible experiments for LLM and agent behavior.

## Search Cup architecture note

`SEARCH-CUP-02` is currently under a **v2.2 benchmark-architecture reconciliation**. The original P0/P1/P2 engineering assets remain valid, but the measurement target has been refined so that search architecture, agent execution, result judgment, and retriever/search-stack quality are not conflated.

The current design is documented in:

- [`docs/search-cup-v2.2-architecture-reconciliation.md`](docs/search-cup-v2.2-architecture-reconciliation.md)

Key boundary:

- the main four-model Cup should compare general-purpose models under the same neutral/transparent retriever contract;
- dedicated intelligent search stacks (for example GLM Search/Search Agent) are evaluated separately as system-level challengers;
- Live Web and Frozen Corpus tracks are distinct;
- Judgment can be evaluated on a pooled, provenance-blinded candidate set;
- old SEARCH-CUP-02 evidence is preserved as historical end-to-end evidence rather than silently relabeled as pure execution performance.

No official SEARCH-CUP-02 paid/live match is authorized by this note, and implementation should stop before P3 until the v2.2 protocol gate is approved.

---

## Existing repository content

The repository also retains its previously merged evaluation and reproducibility assets. Existing code, tests, experiments, and documentation remain part of the project history unless explicitly superseded by a versioned decision or protocol document.
