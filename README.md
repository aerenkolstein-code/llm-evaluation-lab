# LLM Evaluation Lab

**Reproducible LLM evaluation harness for failure mechanisms, mitigation experiments, and regression testing.**

[![Test](https://github.com/aerenkolstein-code/llm-evaluation-lab/actions/workflows/test.yml/badge.svg)](https://github.com/aerenkolstein-code/llm-evaluation-lab/actions/workflows/test.yml)

## First Closed Loop

| Result | Measured value |
|---|---:|
| Baseline accuracy | 20% |
| With Closure Guard | 100% |
| Known regression failures caught | 4/4 |
| Evaluation tests | 32/32 |
| Container CLI/API smoke | PASS |
| Executable MitigationSpec | Runtime-validated |
| SEARCH-CUP-02 P0 offline tests | 21/21 |
| Full repository tests | 53/53 |

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

## Historical Failure Benchmark v0.4

The second executable suite compresses longitudinal error observations into a
small mechanism benchmark without publishing the private source material or
encoding one rule per historical correction.

| Benchmark signal | Measured value |
|---|---:|
| Source observations reviewed | 89 |
| Raw failure categories | 18 |
| Mechanism clusters | 12 |
| Synthetic public-safe cases | 24 |
| Confidence-only baseline | 50% |
| Uniform constraint gate | 100% |
| Known-bad traps caught | 12/12 |
| Per-observation rules | 0 |

Each cluster contains a minimal pair: one fluent but structurally invalid `TRAP`
and one matched `CONTROL`. The reference gate accepts only supported candidates
whose explicit constraints all pass. It is the same policy for all 24 cases—there
are no mechanism-specific branches and no 89-item `if/else` table.

These figures describe a deterministic, mechanism-preserving synthetic benchmark.
They do not establish live-model effectiveness, corpus representativeness or
scientific benchmark validity.

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
llm-eval \
  --suite historical \
  --cases cases/anonymized/premature-parent-closure.md \
  --output /tmp/historical-benchmark.json
companion-mind validate-mitigation --mitigation-spec /tmp/mitigation.json
```

The command validates the public-safe case contract, executes baseline and treatment,
grades every variant, calculates metrics, enforces the regression gate, and emits a
stable JSON or Markdown report. Exit code `1` means regression failure; invalid input
or missing runtime dependencies return `2`.

## Persistent experiment tracking v0.5

Runs can now be written atomically to a dependency-free SQLite store. The store
keeps immutable execution identity, suite version, model/policy, prompt version,
metrics, latency, token cost, git commit, UTC timestamp and the canonical result
JSON. A duplicate `run_id` is rejected instead of silently overwriting evidence.

```bash
llm-eval \
  --suite historical \
  --cases cases/anonymized/premature-parent-closure.md \
  --store /tmp/eval-runs.sqlite3 \
  --model deterministic-reference \
  --prompt-version hfb-v1 \
  --git-commit "$(git rev-parse HEAD)" \
  --log-json \
  --output /tmp/historical-run.json

llm-eval \
  --store /tmp/eval-runs.sqlite3 \
  --list-runs 10
```

Structured lifecycle events are emitted to `stderr`, leaving the JSON or
Markdown report on `stdout` or in `--output`. SQLite files are runtime evidence
and are ignored by git; they are not checked into the public repository.

## Read-only query API v0.6

An optional FastAPI surface exposes the immutable experiment store without
adding any write route. It binds to loopback by default and opens SQLite with
`mode=ro` plus `PRAGMA query_only=ON`.

```bash
llm-eval-api --store /tmp/eval-runs.sqlite3

curl http://127.0.0.1:8000/healthz
curl 'http://127.0.0.1:8000/v1/runs?limit=10'
curl http://127.0.0.1:8000/v1/runs/RUN-ID
```

The list endpoint returns indexed metadata only. The detail endpoint returns one
stored public-safe canonical result. There is no create, update or delete API,
no authentication layer, and no claim that this local demonstration is ready for
network or production exposure.

## Docker reproducibility (introduced in v0.7)

The repository includes one minimal Dockerfile. It pins the Companion-Mind runtime
to commit `c6a2128271532746a5570b99ce0ccdea4618db4e`, installs the evaluation
package, and runs as an unprivileged user.

```bash
docker build -t llm-evaluation-lab:0.8 .

docker run --rm llm-evaluation-lab:0.8 \
  --suite historical \
  --cases cases/anonymized/premature-parent-closure.md
```

To query a previously created store, mount it read-only and publish only to host
loopback:

```bash
docker run --rm \
  -p 127.0.0.1:8000:8000 \
  -v /absolute/path/to/data:/data:ro \
  --entrypoint llm-eval-api \
  llm-evaluation-lab:0.8 \
  --store /data/eval-runs.sqlite3 \
  --host 0.0.0.0 \
  --allow-network
```

CI builds the image from a clean checkout, verifies version `0.8.0`, executes the
24-case historical regression, creates a mounted SQLite record, then queries the
containerized API over HTTP. This is reproducible local packaging, not a published
registry image or production deployment.

## SEARCH-CUP-02 Offline Fairness Harness v0.8

`ENG-SC-01-P0` adds a closed-book, provider-neutral search-benchmark skeleton.
It is intentionally offline: four deterministic fake entrants receive the same
canonical Candidate Card and CompetitionSpec; each gets an isolated search tool
with a hard 20-call budget; submissions are frozen and SHA-256 hashed before a
synthetic hidden registry can be opened; the judge then produces a deterministic
dimension-preserving scoreboard.

```bash
llm-search-cup preflight
llm-search-cup demo --format markdown
```

The P0 CLI contains no live provider adapter, real search backend, credential
path, or official-match command. It cannot spend model/search quota or run the
authorized-but-not-approved 80-search-call match. The included employers, URLs,
registry, and scores are synthetic fixtures and are not job leads.

P0 evidence:

- call 21 is rejected before the backend executes;
- failed backend attempts consume one explicit budget event;
- all four successful submissions share identical contract fingerprints;
- one provider failure preserves other entrants' frozen evidence;
- hidden-registry access fails until all four submissions are frozen and entrant execution is closed;
- repeated judging is byte-identical and requires no model call;
- Apply-Now errors receive the specified 2× penalty.

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
- validated 12-cluster, 24-case Historical Failure Benchmark;
- one uniform evidence-and-constraint gate with zero per-observation rules.
- immutable SQLite experiment-run persistence and metadata query;
- structured JSON lifecycle logging.
- loopback-first read-only FastAPI health, list and detail endpoints.
- non-root Docker packaging with pinned Companion-Mind runtime commit.

### Measured in the current demonstration

- baseline accuracy: **20%**;
- guarded accuracy: **100%**;
- premature closure rate: **100% → 0%**;
- known recurrence variants caught: **4/4**;
- runtime integration status: **PASS**.
- historical benchmark baseline: **50%**;
- uniform constraint gate: **100%**;
- historical traps caught: **12/12**;
- evaluation tests: **32/32**;
- SQLite persistence and readback: **PASS**;
- duplicate run protection: **PASS**.
- API route write methods exposed: **0**;
- read-only query mutation check: **PASS**.
- Docker image build: **PASS**;
- containerized CLI/API smoke: **PASS**.

### Not claimed

- production deployment;
- broad model generalization;
- scientific benchmark validity;
- enterprise-grade reliability;
- live-LLM effectiveness or statistical significance.
- authenticated or production-ready API deployment.
- bit-for-bit dependency or base-image reproducibility.

## Artifact map

- `evaluation_lab.py` — loader, policies, grader, metrics, regression gate, CLI, and read-only API
- `search_cup/` — P0 contracts, budgeted tools, fake providers, isolated runner, hidden judge, and offline CLI
- `candidates/` and `competitions/` — canonical public-safe P0 inputs and fingerprints
- `cases/anonymized/premature-parent-closure.md` — first-loop case card plus executable 24-case historical benchmark
- `experiments/closure-guard-mitigation.md` — mitigation, decision rule, and executable JSON contract
- `results/EVAL-CASE-001.json` — checked deterministic result
- `tests/test_evaluation.py` — loader, reproducibility, reporting, and regression assertions
- `schemas/` — shared evaluation and mitigation contracts
- `Dockerfile` — non-root container build for CLI and read-only API reproduction

## Roadmap

**SEARCH-CUP-02 P0 complete; live phases locked** — the fully offline fairness
harness is implemented. SearchProxy integration, live provider adapters, immutable
SQLite match evidence, the private judge snapshot, and any paid official match
remain separate gated phases under Issue #8.

## Privacy

The fixtures preserve failure mechanisms without publishing the private scenes that revealed them. The historical suite uses synthetic neutral scenarios and excludes source quotations and archive locators. The repository contains no private Raw/L0 material, credentials, account data, client documents, personal records, or links to private archives.

The API returns whatever canonical result was stored by the operator. Only
public-safe runs belong in a publicly reachable deployment; this artifact binds
to localhost by default and intentionally provides no authentication.
