# Method lineage

LLM Evaluation Lab separates private longitudinal evidence, public-safe evaluation assets, and implementation authority.

The core lineage is:

```text
Raw / L0: what happened
→ L1: what changed the trajectory
→ L2: what reusable rule appeared
→ Errorbook: what failed, why, risk, mitigation
→ Case Library: how to reproduce it
→ Stress Test: how to expose it deliberately
→ Mitigation Experiment: whether an intervention works
→ Regression Test: whether the failure returns
→ Best-Known Solution: what current evidence supports
```

For `HISTORICAL-FAILURE-BENCHMARK-v1`, the public boundary is crossed only after the private evidence layer has been reviewed: 89 correction observations and 18 raw categories are compressed into 12 mechanism clusters, then reconstructed as 24 synthetic public-safe minimal-pair cases. The repository contains the reconstructed cases, not the underlying evidence corpus.

## Archive Complete is not Eval Harvest Complete

Recovering an old conversation or evidence package is only the first layer of completion.

```text
Archive Complete
= recover source
  → verify integrity / continuity / provenance
  → confirm time and source boundary
  → archive
```

A useful evaluation harvest requires a second transformation:

```text
Eval Harvest Complete
= Raw candidate
  → failure / intervention / continuity candidate
  → phenomenon + mechanism classification
  → anonymization / synthetic abstraction
  → rubric / oracle
  → baseline
  → mitigation hypothesis
  → verification / falsification
  → regression
  → longitudinal comparison
```

Not every archived turn deserves evaluation treatment. The useful subset is the one that can support a reproducible question, a discriminating mechanism hypothesis, a matched comparison, a later regression, or a grounded historical baseline.

## Historical observation and frozen replay are different assets

Historical Raw can support two distinct products:

### Historical Observed Baseline

A later evaluator scores what the historical system actually produced.

This preserves naturalistic behavior and the original correction chain, but the exact historical model build, hidden system behavior, memory layer, context truncation and tool environment may not be fully reconstructable. It is therefore historical evidence, not a strict rerunnable causal experiment.

### Frozen Replay Benchmark

The evaluator extracts and sanitizes the necessary task, visible context, constraints, prior corrections, source evidence and oracle into a replayable pack. Modern models, retrieval policies or runtimes can then be compared against the same frozen case.

These results must remain labeled separately:

```text
historical observed score ≠ replay score
```

## Era Benchmark lineage

A high-value historical era may eventually produce an Era Benchmark Pack:

```text
private era source
→ integrity / provenance receipt
→ historical observed cases
→ public-safe replay cases
→ rubric / oracle version
→ historical score
→ later bare-model reruns
→ retrieval/runtime reruns
→ mechanism labels
→ intervention / correction history
→ regression status
```

The purpose is not one global “smartness” ranking. The purpose is to ask which continuity or reliability dimensions improve, which failures recur across generations, and which gains come from the foundation model versus retrieval, context assembly or runtime support.

## Public boundary

The repository does not publish private L0/L1/L2 material. It publishes public-safe method cards and reproducible assets derived from reviewed sources.

Public-safe outputs may include:

```text
anonymized / synthetic cases
failure mechanisms
rubrics / oracles
protocols / schemas
aggregate metrics
mitigation specs
regression evidence
public-safe traces
reproducible runners
```

Private source bodies, reverse-lookup archive locators, relationship/family records, medical/financial data, credentials, client material and other non-public evidence remain outside the repository.

## Build / measure boundary

The lineage also stops at the A1/A2 authority boundary:

```text
A1 / Companion-Mind
= owns implementation and internal conformance

A2 / LLM Evaluation Lab
= owns independent cases, evidence, comparisons and gate verdicts
```

A2 may prove that an observable protection works or fails. It does not become a second owner of A1 runtime state, schemas, Persona, Relationship or Current truth.
