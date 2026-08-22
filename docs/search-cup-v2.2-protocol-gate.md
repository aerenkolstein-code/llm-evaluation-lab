# SEARCH-CUP v2.2 Protocol Gate

Status: REQUIRED BEFORE P3 / NO OFFICIAL MATCH AUTHORIZATION

This checklist turns the v2.2 architecture reconciliation into an implementation gate.

Before P3 begins, the Board/Plan Office must explicitly approve a protocol that freezes all of the following:

## SearchSpec

- task definition and success criteria;
- language/source/time-window boundaries;
- allowed query refinement behavior;
- UNKNOWN / exclusion semantics;
- evidence requirements;
- stop conditions.

## E1 Agent Execution

- neutral/transparent retriever acceptance criteria;
- common tool schema and normalized result contract;
- same search-call/turn budget;
- same retry policy;
- same time window;
- exact entrant model/config identity;
- no hidden intelligent search agent performing undeclared high-level decomposition for entrants.

## E2 Retriever Benchmark

- one fixed agent/model/config;
- one fixed task/SearchSpec/budget;
- declared retriever/backend identity and version;
- metrics that attribute retrieval gains to the backend, not to the model.

## Live / Frozen tracks

- Live Web timestamping and pooled adjudication rules;
- Frozen Corpus provenance, version, hash, and reference/adjudicated labels;
- separate leaderboards and result labels.

## Judgment Cup

- pooled/deduplicated candidate-set construction;
- entrant provenance blinding;
- common rubric;
- no extra search unless explicitly authorized as a verification subtrack;
- false-opportunity, false-reject, calibration, UNKNOWN, and Top-K metrics.

## Dedicated search-stack challenge

- GLM Search/Search Agent treated as a declared system-level entrant;
- search-credit/coupon accounting isolated from the bare-model Cup;
- system-stack resource budget declared;
- winner-vs-stack playoff rules declared before execution.

## Compatibility / migration

- existing P0/P1/P2 assets explicitly classified as REUSE / ADAPT / HISTORY-ONLY;
- old results labeled Strategy-heavy End-to-End Search Evidence;
- no silent conversion of old results into E1-only scores;
- Draft PR #17 disposition explicitly decided.

## Hard stop

Until this gate is approved:

- no P3 runner/evidence implementation under the old measurement interpretation;
- no hidden judge/registry integration into entrant execution;
- no official competition prompt consumption;
- no official paid/live four-model match;
- no GLM search-credit consumption for the neutral main Cup.
