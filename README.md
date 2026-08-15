# LLM Evaluation Lab

**A runnable evaluation harness for failure modes, longitudinal change, mitigation and regression.**

Portfolio Status: **CURRENT ARTIFACT** · Evidence Level: **E3 — reproducible public-safe evaluation**

This repository is the public-facing continuation of the earlier **AI Longitudinal Evaluation / third repository**. Failure taxonomy is its interface; the retained core is how concepts, priors and world models change across an experimental timeline.

## First closed loop

`EVAL-CASE-001` reproduces **Premature Parent Closure**: one local child action completes, another required child remains open, and the parent is incorrectly declared done.

The harness runs five order/status variants against:

- **baseline:** close when any child is done;
- **treatment:** Companion-Mind `CM-GUARD-001`, close only when every required child is terminal.

Measured result from `python evaluation_lab.py`:

| Policy | Accuracy | Premature closure rate | Regression failures |
|---|---:|---:|---:|
| Naive baseline | 20% | 100% | 4 |
| Closure Guard | 100% | 0% | 0 |

Accuracy moved by **+80 percentage points** on this deterministic fixture. The regression run deliberately applies the known-bad baseline and detects all four recurrence variants.

## Reproduce

Clone both core repositories as siblings, then run:

```bash
python -m pip install -e ../Companion-Mind
python -m unittest discover -s tests -v
python evaluation_lab.py
```

No model API, network call or private dataset is used.

## Artifact map

- `evaluation_lab.py` — case, baseline, treatment adapter, metrics and regression run
- `cases/anonymized/premature-parent-closure.md` — public-safe case card
- `experiments/closure-guard-mitigation.md` — mitigation and decision rule
- `results/EVAL-CASE-001.json` — checked-in deterministic result
- `tests/test_evaluation.py` — reproducibility and regression assertions
- `schemas/` — shared EvaluationCase and MitigationSpec contracts

## Longitudinal identity

The lab evaluates not only a single answer, but also **concept growth**, **prior lock-in**, **world-model drift**, recovery and **longitudinal evolution** across an **experimental timeline**. The current artifact is the smallest executable slice of that larger program.

## Limits and next step

This first result is structural and deterministic. It does not measure a live LLM, production traffic, statistical significance or cross-model generalization. The next step is a public-safe model-run adapter that preserves the same predeclared case, metric and regression contracts.

## Privacy

The case is abstracted to synthetic child-task states. No private Raw/L0, relationship history, account, company assessment, client document or archive link is included.

