# LLM Evaluation Lab

**Reproducible LLM evaluation harness for failure mechanisms, mitigation experiments, and regression testing.**

[![Test](https://github.com/aerenkolstein-code/llm-evaluation-lab/actions/workflows/test.yml/badge.svg)](https://github.com/aerenkolstein-code/llm-evaluation-lab/actions/workflows/test.yml)

## First Closed Loop

| Result | Measured value |
|---|---:|
| Baseline accuracy | 20% |
| With Closure Guard | 100% |
| Known regression failures caught | 4/4 |
| Evaluation tests | 15/15 |
| Executable MitigationSpec | Runtime-validated |

**Status:** Experimental / reproducible artifact  
**Evidence level:** E3 — reproducible public-safe evaluation

```mermaid
flowchart LR
  A[Observed failure] --> B[EvaluationCase]
  B --> C[Baseline]
  C --> D[Mitigation]
  D --> E[Metric]
  E --> F[Runtime Guard]
  F --> G[Regression]
```

LLM Evaluation Lab proves whether a protection works. The paired [Companion-Mind](https://github.com/aerenkolstein-code/Companion-Mind) repository implements the protection.

`EVAL-CASE-001` reproduces **Premature Parent Closure** across five deterministic, public-safe variants. The harness compares a known-bad baseline with Companion-Mind's `CM-GUARD-001`, records metrics, and deliberately reintroduces the bad policy to prove the regression suite catches the recurrence.

> In the current reproducible first-closed-loop evaluation, the implemented Closure Guard improved the tested cases from 20% baseline accuracy to 100%; broader generalization has not yet been established.

## Reproduce

Clone both repositories as siblings. Requires Python 3.11 or later; no model API, network call, or private dataset is used by the experiment.

```bash
python -m pip install -e ../Companion-Mind
python -m pip install -e .
python -m unittest discover -s tests -v
llm-eval --cases cases/anonymized/premature-parent-closure.md
llm-eval \
  --cases cases/anonymized/premature-parent-closure.md \
  --emit-mitigation /tmp/mitigation.json \
  --output /tmp/evaluation.json
companion-mind validate-mitigation --mitigation-spec /tmp/mitigation.json
```

The command validates the public-safe case contract, executes baseline and treatment,
grades every variant, calculates metrics, enforces the regression gate, and emits a
stable JSON or Markdown report. Exit code `1` means regression failure; invalid input
or missing runtime dependencies return `2`.

## Executable integration v0.3

The experiment now owns a complete `mitigation-spec/v1` contract, validates it,
emits canonical JSON, and instantiates Companion-Mind's real `ClosureGuard` from
that document. The evaluation report records the runtime-loaded mitigation ID,
safeguard ID, schema version, and canonical SHA-256 fingerprint. This makes the
boundary explicit: Eval Lab specifies and verifies; Companion-Mind implements.

## Evidence boundary

### Implemented

- dependency-free `llm-eval` CLI and deterministic evaluation harness;
- validated public-safe `EvaluationCase` loader;
- validated and emitted executable `MitigationSpec`;
- real Companion-Mind runtime loading with shared spec fingerprint;
- baseline and mitigation comparison;
- accuracy and premature-closure metrics;
- JSON and Markdown report output;
- checked result artifact and known-bad regression gate.

### Measured in the current demonstration

- baseline accuracy: **20%**;
- guarded accuracy: **100%**;
- premature closure rate: **100% → 0%**;
- known recurrence variants caught: **4/4**;
- evaluation tests: **15/15**;
- runtime integration status: **PASS**.

### Not claimed

- production deployment;
- broad model generalization;
- scientific benchmark validity;
- enterprise-grade reliability;
- live-LLM effectiveness or statistical significance.

## Artifact map

- `evaluation_lab.py` — loader, policies, grader, metrics, regression gate, and CLI
- `cases/anonymized/premature-parent-closure.md` — human-readable case card plus executable JSON fixture
- `experiments/closure-guard-mitigation.md` — mitigation, decision rule, and executable JSON contract
- `results/EVAL-CASE-001.json` — checked deterministic result
- `tests/test_evaluation.py` — loader, reproducibility, reporting, and regression assertions
- `schemas/` — shared evaluation and mitigation contracts

## Roadmap

**Historical Failure Corpus** — planned expansion from longitudinal real-world LLM failure observations. It is intentionally out of scope for this release candidate.

## Privacy

The case preserves the failure mechanism without publishing the private scene that revealed it. The repository contains no private Raw/L0 material, credentials, account data, client documents, personal records, or links to private archives.
