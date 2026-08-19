# Methodology

LLM Evaluation Lab treats evaluation as a failure-science and evidence discipline, not as a single score attached after implementation.

The long-term method is:

```text
Observed Failure / Friction
→ Phenomenon Classification
→ Mechanism Hypothesis / Cluster
→ Reproducible Case
→ Rubric / Oracle
→ Baseline
→ Mitigation Hypothesis
→ Independent Verification / Falsification
→ Regression
→ Cross-Method Comparison
→ Review
→ Best-Known Solution
```

The lab predeclares case inputs, expected behavior, oracle/rubric, relevant invariants and metrics before comparing baseline and treatment. A missing required observation is not a pass. `BLOCKED` and `NOT EVALUABLE` remain distinct from `PASS`.

## 1. Reproduce before repairing

A fluent explanation of a failure is not enough. Before accepting a mitigation, the lab tries to freeze a minimal case that reproduces the observable failure under controlled conditions.

The first artifact uses invariant transformations: child wording and order change while the required closure decision does not. A valid treatment must also preserve the sensitive all-terminal case, avoiding the trivial strategy “never close anything.”

The historical benchmark adds a second construction method:

1. review longitudinal correction chains in the private evidence layer;
2. group raw categories by shared failure mechanism and required gate;
3. rewrite each mechanism as a neutral synthetic scenario;
4. create one invalid `TRAP` and one matched valid `CONTROL`;
5. validate the pair with one uniform evidence-and-constraint policy;
6. scan the public fixture for private locators before release.

The 89 observations are therefore evidence for clustering, not 89 executable rules. The reference gate has no mechanism-specific branch and never reads the expected label. A new mechanism can use the same gate when it exposes evidence state and explicit constraint statuses.

## 2. Separate phenomenon from mechanism

A user-visible failure is not automatically its root cause.

Example phenomenon labels include:

```text
wrong answer
forgot constraint
persona drift
false shared history
missed correction
wrong source
premature closure
duplicate action
silent state loss
bad initiative
```

Candidate mechanism labels may instead include:

```text
insufficient evidence grounding
constraint omission
context eviction
retrieval miss
retrieval contamination
authority confusion
state projection error
identity binding failure
provider adapter failure
non-idempotent retry
premature terminalization
unsupported inference from UNKNOWN
```

One phenomenon may map to multiple candidate mechanisms. A mechanism is promoted only when evidence discriminates it from plausible alternatives.

This matters because the object under evaluation is broader than a foundation model. A failure may originate in:

```text
LLM reasoning or knowledge
instruction following
context assembly
retrieval / authority routing
tooling / provider adapters
durable state / journal semantics
persona / relationship continuity
model switching
crash / restart recovery
longitudinal workflow orchestration
```

The lab does not force every system failure into a “model quality” explanation.

## 3. Mitigation is a falsifiable hypothesis

A mitigation is not accepted merely because one output looks better. It should imply a measurable change in the frozen failure condition.

A high-value case should try to answer:

```text
What failed?
Under what conditions?
What evidence rules out alternative causes?
What is the minimum reproducible case?
What mechanism hypothesis explains it?
What intervention should change the outcome?
What result would falsify that hypothesis?
Does the mitigation preserve matched controls?
Does the old failure recur after unrelated changes?
```

A mitigation may be a prompt/instruction change, retrieval rule, schema/contract, state guard, context policy, runtime check, provider normalization, human-review gate, or another bounded intervention. “Mitigation” does not mean “prompt patch.”

The lab should compare benefit against complexity, latency, cost and side effects.

## 4. Falsification is as important as PASS

A good evaluation does not only seek confirming examples. It should actively look for results that would show the mechanism hypothesis or mitigation is wrong.

Useful falsification patterns include:

- matched controls that should remain unchanged;
- boundary cases that distinguish two candidate mechanisms;
- reintroduction of a known-bad policy;
- perturbations unrelated to the proposed causal mechanism;
- replay on a different implementation that preserves the same public contract;
- model/provider swaps where provider failure must not be mislabeled as behavioral quality.

If the required seam, evidence or observation is missing, the correct verdict is `BLOCKED` or `NOT EVALUABLE`, not a guessed PASS or FAIL.

## 5. Regression is part of the mitigation

A failure being fixed once does not close the evidence loop.

Accepted mitigations should, where practical, retain:

- the original reproduction;
- matched controls;
- a known-bad recurrence variant;
- version / commit identity;
- stable fixture and result fingerprints;
- a regression gate;
- links to later recurrences.

Longitudinal evidence makes a stronger question possible:

> Does the same mechanism recur weeks or months later, after model changes, runtime changes, retrieval changes, or unrelated refactors?

That produces a longitudinal regression corpus rather than a one-time benchmark snapshot.

## 6. Historical evidence: observation is not replay

Private historical Raw/L0 has two different evaluation uses and they must not be conflated.

### Historical Observed Baseline

Score what an older system actually did using a later frozen rubric.

This has strong naturalistic value, but the historical model build, hidden system behavior, platform memory, context truncation and tool environment may not be reconstructable exactly. It is therefore historical observation, not a strict rerunnable causal experiment.

### Frozen Replay Benchmark

Extract and sanitize the necessary user task, visible context, constraints, relevant corrections, source evidence and rubric/oracle into a replayable case pack. Later models, retrieval configurations or runtimes can then run against the same frozen case.

The distinction should be preserved in every evidence record:

```text
historical observed result ≠ replay result
```

A future Era Benchmark Pack may contain both, but must label them separately and preserve the known limitations of each.

## 7. RAW Harvest: archive completion is not evaluation completion

Recovered longitudinal material has two completion states:

```text
Archive Complete
= recovery + integrity/provenance checks + source/time boundary + archive

Eval Harvest Complete
= candidate selection
  → mechanism classification
  → anonymization / synthetic abstraction
  → rubric / oracle
  → baseline
  → mitigation
  → falsification
  → regression
  → longitudinal comparison
  → best-known solution
```

Not every conversation should become a case. Prefer material that is generalizable, reproducible, mechanism-bearing, contrastable, regression-worthy, and grounded by corrections, later outcomes or other source evidence.

Private Raw/L0 is the evidence mine, not the public dataset.

## 8. A1 conformance and A2 black-box evaluation

A1 / Companion-Mind builds the system and owns implementation authority. A2 measures observable behavior independently.

A1 owns, among other things:

- production/runtime implementation;
- internal storage mechanics;
- the canonical event contract authority;
- sanctioned fault hooks / test seams;
- implementation-specific conformance checks.

A2 owns:

- independent manifests;
- cases, rubrics and oracles;
- black-box observations;
- normalized evidence registries;
- comparative metrics;
- independent gate verdicts.

A2 must not copy A1 schema into a second authority or mutate Current, Persona or Relationship truth. A1 internal conformance and A2 external evidence are complementary; neither substitutes for the other.

## 9. Current product-linked gate: A019 / E1

The nearest product-linked evaluation target is the Durable Journal black-box gate.

The approved Wave 1 plan defines the observable dimensions:

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

Gate E1 is an all-of gate. Zero-tolerance failures are not averaged into a score. Execution requires the separately authorized A2 harness work plus an A1-D candidate and sanctioned public seam.

Later evaluation grows with the system under test:

```text
Journal / E1
→ Context Engine / Owned Home
→ Retrieval / Authority Routing
→ Model Gateway / model-switch continuity
→ W1 operational independence
→ Living Lab longitudinal reliability
→ W2 evidence readiness
```

The lab should not pre-build large empty benchmark structures for stages that do not yet expose a stable testable seam.

## 10. Experiment records

An experiment run is immutable evidence, not a mutable dashboard row. The SQLite store uses `run_id` as the primary key and rejects duplicate IDs. Every record keeps the case-suite identity, model or policy, prompt version, git commit, UTC timestamp, latency, token cost, baseline and treatment accuracy, regression status, and canonical result JSON. Listing returns indexed metadata without dumping the stored result payload.

For historical or era-derived studies, the evidence registry should additionally distinguish:

```text
source era
historical observation vs replay
anonymization transform
private-source access boundary
correction / intervention linkage
known limitations / UNKNOWNs
```

Structured lifecycle logs use one JSON object per line and remain separate from the report channel: `run_started`, `run_completed`, `run_persisted`, or `run_failed`. This preserves machine-readable observability without changing the deterministic report contract when tracking is not requested.

## 11. Read-only query boundary

The FastAPI surface is a projection over immutable SQLite evidence. It opens the database in URI `mode=ro`, enables SQLite `query_only`, and exposes only health, metadata-list, and single-run-detail GET routes. List responses omit the stored result payload; detail responses return the canonical result for one run. Tests hash the database before and after all three queries to prove the query path does not mutate the evidence file.

## 12. Container reproduction

The Docker image fixes the Companion-Mind runtime to an explicit commit, copies only the executable public-safe fixture and schema directories, installs the lab in editable mode so checked fixtures remain addressable, and drops privileges to UID 10001. CI treats the image as a black box: it verifies the version, executes the historical regression, writes one SQLite run through a mounted directory, then starts the API with that directory mounted read-only and queries it over HTTP.

The Python base tag and transitive package resolution are not locked by digest; this is repeatable functional packaging, not bit-for-bit image reproducibility.

## 13. Claims boundary

A benchmark result is evidence under a frozen protocol, not an automatic scientific conclusion.

The current repository does not claim:

- scientific benchmark validity;
- corpus representativeness;
- broad model generalization;
- live-model statistical significance;
- production or enterprise evaluation readiness;
- objective ground truth for personality, relationship, consciousness or subjective experience.

The methodology is deliberately stricter than the claim: preserve what is known, mark what is not evaluable, and make future reruns able to challenge today's best-known explanation.
