# SEARCH-CUP v2.3 Protocol Gate

Status: REQUIRED BEFORE P3 / NO OFFICIAL MATCH AUTHORIZATION

This gate supersedes v2.2 for future implementation while retaining v2.2 as history.

Before P3 begins, the Board/Plan Office must explicitly approve a protocol that freezes all of the following.

## SearchSpec

- task definition and success criteria;
- language/source/time-window boundaries;
- allowed query refinement behavior;
- UNKNOWN / exclusion semantics;
- evidence requirements;
- stop conditions.

## A0 / A1 boundary

- A0 Search Program Architecture is frozen and provenance-recorded before a comparable run;
- A1 Query-Level Search Planning allowances are explicitly declared;
- any search stack that performs A1 work such as intent understanding or query decomposition/rewrite is declared as an integrated system component.

## E1 Bare-Agent Execution

- neutral/transparent retriever acceptance criteria;
- common tool schema and normalized result contract;
- same search-call/turn budget;
- same retry policy;
- same time window;
- exact entrant model/config identity;
- no hidden intelligent search agent performing undeclared high-level decomposition for entrants.

## E2 Retriever / Search-Stack Benchmark

- fixed agent/model/config when measuring retriever effects;
- fixed task/SearchSpec/budget;
- declared retriever/backend/search-stack identity and version;
- metrics that attribute retrieval or stack gains to the backend/system, not to the model.

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

## Dedicated GLM Search-Stack Challenge

- GLM Search/Search Agent treated as a declared integrated system-level entrant;
- search-credit/coupon accounting isolated from the bare-model Cup;
- one GLM search credit is not presumed equivalent to one neutral/raw retriever call;
- system-stack resource budget and included capabilities declared before execution.

## Winner-vs-Stack fairness mode

A future playoff must declare which question it is answering:

- **F1 Bare-Model Fairness:** same neutral retriever and comparable model-level resource boundary;
- **F2 System Fairness:** same A0 Search Program, deadline, success criteria, and output contract; each system may use its declared native capabilities;
- **F3 Economic Fairness:** align comparable real-world resources such as money/time and report value per resource unit.

F1, F2, and F3 results must remain separate. No single total score may collapse them into one champion.

## Capability-Matched Ablation

If causal attribution is claimed for GLM Search Stack gains, the protocol must separately isolate, where feasible:

- query planning/decomposition;
- retrieval;
- ranking/aggregation;
- synthesis.

## Compatibility / migration

- existing P0/P1/P2 assets explicitly classified as REUSE / ADAPT / HISTORY-ONLY;
- old results labeled Strategy-heavy End-to-End Search Evidence;
- no silent conversion of old results into E1-only scores;
- Draft PR #17 disposition explicitly decided;
- v2.2 documents retained as history and v2.3 identified as Current architecture boundary.

## Hard stop

Until this gate is approved:

- no P3 runner/evidence implementation under the old measurement interpretation;
- no hidden judge/registry integration into entrant execution;
- no official competition prompt consumption;
- no official paid/live four-model match;
- no GLM search-credit consumption for the neutral main Cup;
- no Winner-vs-Stack execution without an explicit F1/F2/F3 fairness declaration.
