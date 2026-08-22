# SEARCH-CUP v2.3 Winner-vs-Search-Stack Fairness Framework

Status: CURRENT ARCHITECTURE / DOCS-ONLY / NO OFFICIAL MATCH AUTHORIZATION

Date: 2026-08-22

Applies to: SEARCH-CUP-02, the v2.2 architecture reconciliation, Draft PR #17, and any future GLM Search/Search Agent challenge.

## Why v2.3 exists

The v2.2 architecture correctly separates bare-agent execution, retriever/search-stack quality, judgment, and end-to-end system performance. v2.3 adds one further fairness rule: a future bare-model champion must not be compared with an integrated GLM Search/Search Agent stack using a single naive equality such as “the same number of calls.”

A GLM search-credit invocation may include query-level intent understanding, query decomposition/rewrite, retrieval/ranking, aggregation, and synthesis. It is therefore a declared integrated search-system resource unit, not automatically equivalent to one neutral/raw retriever call.

## Search Architecture split

- **A0 — Search Program Architecture:** overall objective, markets/languages/sources, layers, budget allocation, stop-on-signal rules, evidence requirements, and economic success criteria. Primarily Human+Model co-design; not a clean single-model leaderboard variable.
- **A1 — Query-Level Search Planning:** intent understanding, query decomposition/rewrite, and local search-direction selection inside a frozen task. A dedicated Search Agent may internalize part of this layer.

This distinction matters because a smart search stack can contribute A1 capability even when A0 has already been frozen upstream.

## Three distinct fairness questions

### F1 — Bare-Model Fairness

Question: **Which general-purpose LLM itself executes search best?**

Controls:
- same frozen Search Spec;
- same neutral/transparent retriever;
- same search budget and time window;
- same tool and output/evidence contracts;
- no GLM Search/Search Agent or other hidden intelligent planner as the common backend.

This is the main model-attribution leaderboard.

### F2 — System Fairness

Question: **Which complete search system performs the task better: the best general-purpose model search system or a dedicated GLM search stack?**

Controls:
- same A0 Search Program;
- same task goal, deadline, success criteria, and final output contract;
- each system may use its declared native search capabilities;
- system composition and resource boundaries must be disclosed.

This measures system effectiveness, not pure model ability.

### F3 — Economic Fairness

Question: **Given the same real-world resource budget, which system produces more value?**

Prefer comparable real resource alignment over mechanical call-count alignment, for example:
- same monetary budget;
- same wall-clock budget;
- or another pre-declared equivalent resource package.

Recommended metrics:
- Actionable Leads / Cost;
- Unique Valid Discovery / Cost;
- Qualified Replies / Cost;
- Paid Conversion / Cost;
- Revenue / Cost;
- Time-to-First-Actionable-Result.

Economic results belong to a real-world system/business track and must not be reported as pure model-quality scores.

## Capability-Matched Ablation

If the goal is to explain *why* a GLM Search Stack wins or loses, run separate mechanism experiments that explicitly isolate components such as:
- query planning/decomposition;
- retrieval;
- ranking/aggregation;
- synthesis.

Where feasible, hold all other components fixed and vary one component at a time. Never attribute an integrated-stack gain directly to one model capability without such isolation.

## Required reporting for Winner-vs-Stack

Any future playoff report must keep at least these outputs separate:

1. Bare Cup result;
2. System Playoff result;
3. Economic Playoff result;
4. Capability-Matched Ablation, if causal attribution is claimed.

No single total score may collapse F1, F2, and F3 into one “champion.”

## GLM search-credit policy

GLM search credits/coupons are primarily resources for:
- real-world Shot 0 commercial search;
- GLM Search Stack Challenge;
- retriever/integrated-stack comparison;
- economic search experiments.

They are **not** part of the Four-Model Bare Search Cup neutral budget pool.

## Compatibility

All P0/P1/P2 engineering assets remain reusable. This document changes measurement interpretation and future protocol design only. It does not invalidate prior adapter, trace, budget, hidden-isolation, freeze/hash, submission-validation, or secret-exclusion evidence.

## Hard stop

This v2.3 docs update does not authorize:
- P3 implementation;
- official prompt consumption;
- hidden judge/registry access by entrants;
- an official paid/live four-model match;
- GLM search-credit consumption for the bare-model main Cup.

The v2.3 protocol must explicitly select fairness mode(s) and resource accounting before any Winner-vs-Stack execution.
