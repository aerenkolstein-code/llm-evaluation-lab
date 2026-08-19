# Current roadmap — failure science, independent gates, and longitudinal evidence

**Status:** public-safe evaluation orientation  
**Scope:** roadmap/narrative only; not an implementation authority or completion claim

LLM Evaluation Lab is the **A2 / Measure the system** repository. Its job is to turn AI-system failures, continuity claims and long-term observations into reproducible evidence that can challenge implementation claims rather than merely repeat them.

The current public evidence base already includes:

- First Closed Loop: Premature Parent Closure reproduction, mitigation and regression;
- Historical Failure Benchmark: 89 reviewed observations → 18 raw categories → 12 mechanism clusters → 24 public-safe synthetic cases;
- executable `MitigationSpec` integration with Companion-Mind;
- immutable SQLite experiment tracking;
- structured lifecycle logging;
- read-only FastAPI evidence querying;
- Docker CLI/API reproduction.

These are implemented artifacts. The roadmap below describes what comes next and what remains separately gated.

## Evaluation mission

```text
Observed failure / friction
→ phenomenon classification
→ mechanism hypothesis / cluster
→ reproducible case
→ rubric / oracle
→ baseline
→ mitigation hypothesis
→ independent verification / falsification
→ regression
→ cross-method comparison
→ review
→ best-known solution
```

The lab prefers reproducible mechanisms over one-off rules. It treats `BLOCKED` and `NOT EVALUABLE` as real outcomes. A mitigation is not complete without regression evidence when recurrence can be tested.

## Four connected lanes

### Lane A — Failure Mechanism Lab

Convert real or historical failures into reproducible mechanism experiments.

Typical assets:

```text
failure taxonomy
mechanism clusters
minimal pairs / TRAP-CONTROL
rubrics / oracles
baselines
mitigation specs
falsification results
regression suites
best-known-solution notes
```

The existing Historical Failure Benchmark is the first executable example of this lane.

### Lane B — A2 Independent System Gates

Measure whether A1 / Companion-Mind actually satisfies its public contracts and stage promises.

The immediate product-linked gate is:

> **A019 / Gate E1 — Durable Journal black-box evaluation.**

The approved A2 Wave 1 plan covers:

```text
Durability
Ordering
Dedupe
Crash Recovery
Restart Recovery
Correction
Secret Exclusion
UNKNOWN Semantics
```

Gate E1 is an all-of gate with zero-tolerance invariants. The planning document is published. Actual A2 implementation and Gate E1 execution remain separately gated and require an A1-D candidate plus a sanctioned black-box seam.

After E1, evaluation expands with the system under test:

```text
Journal / E1
→ Context Engine / Owned Home
→ Retrieval / Authority Routing
→ Model Gateway / model-switch continuity
→ W1 operational independence
→ Living Lab longitudinal reliability
→ W2 evidence readiness
```

A2 supplies evidence at W2; it does not decide whether a commercial product should exist.

### Lane C — RAW Harvest + Historical / Era Benchmarks

Private longitudinal evidence can be a failure mine, intervention history and historical benchmark source without becoming a public dataset.

The transformation is:

```text
Archive Complete
→ candidate selection
→ mechanism classification
→ anonymization / synthetic abstraction
→ rubric / oracle
→ baseline
→ mitigation / falsification
→ regression
→ longitudinal comparison
```

Historical evidence has two distinct forms:

- **Historical Observed Baseline** — score what the historical system actually did, while preserving uncertainty about unreconstructable model/platform internals.
- **Frozen Replay Benchmark** — sanitize and freeze the necessary task, context, constraints, evidence and oracle so later models or runtimes can be compared on the same replayable case.

Future **Era Benchmark Packs** may combine both forms with cross-model and model-vs-runtime comparisons. Era packs are a roadmap design target, not a claim that a public era benchmark suite is implemented today.

One especially useful historical category is a **Context-only Longitudinal Baseline**: naturally occurring long-context continuity before external archive/retrieval/runtime support existed. Such a baseline can become a regression floor for later runtime-assisted continuity, subject to the limitations of historical observation.

### Lane D — Longitudinal Cognitive / Persona Research

The lab retains the long-horizon questions that motivated the earlier AI Longitudinal Evaluation concept:

```text
Concept Growth
Reasoning Trajectory
World Model Evolution
Personality / Relationship Continuity
Prior Lock-in
Attractor Stability
Information Gain
Replay Selection Bias
Cost of Becoming
Consolidation Cost
Canonical Persona / Experimental Timeline
Cross-Raw Integration
```

These are research directions, not automatically implemented metrics. They become executable benchmark work only when the evidence, operational definition and protocol are mature enough.

## Historical continuity dimensions

Longitudinal continuity should not collapse into one “persona similarity” score. Candidate dimensions include:

```text
Identity Consistency
Biography Fidelity
Relationship-State Continuity
Shared-History Hallucination
Correction Retention
Topic Reactivation
Cross-Window Continuity
Model-Switch Identity Continuity
Authority Fidelity
Contradiction / Confabulation Rate
```

Future controlled studies may also measure fidelity decay with context depth, time-to-recurrence after corrections, A→B→A topic recovery, and whether retrieval/runtime support improves or suppresses bare-model capability.

## A1 / A2 authority boundary

```text
A1 / Companion-Mind
= build the system
= own implementation, internal storage mechanics and conformance

A2 / LLM Evaluation Lab
= measure the system
= own independent cases, manifests, evidence, comparison and verdicts
```

A1 cannot self-certify the independent A2 gate. A2 cannot copy A1 schemas into a second authority or mutate A1 Current / Persona / Relationship truth.

## Privacy boundary

Private Raw/L0 remains private evidence. Public assets may contain anonymized/synthetic cases, mechanisms, rubrics, protocols, aggregate metrics, mitigation specs, regression evidence and public-safe traces.

The repository must not publish private conversation bodies, reverse-lookup archive locators, credentials, account data, client material, private relationship/family records, medical/financial data or other non-public source material.

## Claims boundary

This roadmap does **not** claim:

- scientific benchmark validity;
- representative corpus coverage;
- broad model generalization;
- live-model statistical significance;
- a production evaluation platform;
- a completed public Era Benchmark Pack;
- objective ground truth for personality, relationship, consciousness or subjective experience;
- that private Raw is available for public training.

## Short form

> **A1 builds. A2 measures.**
>
> **The mine is longitudinal. The lab makes it reproducible.**
>
> **A benchmark should survive time, model changes, runtime changes, and our own interventions.**
