# T5 E1F EX1 — Phase A executor and zero-execution run-ready package

Authority: `WO-ENG-B1-SC-V23-T5-E1F-EX1 v0.1`, explicitly approved for
**Phase A only**. This document and PR authorize neither merge nor E1F-001.
Independent acceptance and publication precede a separate Phase B decision.

Construction base: `a6eec1fe6971802c72b84b8fbdc0ad40537ade4e`.
Construction tree: `64447897feb5694a13b2c12a4543a803f8f5e2dd`.
EX0 publication: `e5d52274827210df6d876d6fc83da31acf58991f`.
EX0 publication tree: `3b03dfb76454f72e6bd449e63c368dcd61d0ace8`.

Execution binding:
`7d4255fe28d0ee611465f88513d084c3371120d32afbc74d5cf4a3583d9082cb`.
Exact one-shot identity:
`T5-E1FROZEN-PV-001-EXEC-V1:7d4255fe28d0ee611465f88513d084c3371120d32afbc74d5cf4a3583d9082cb:E1F-001`.

## Scope and retained authority

Four additions: module, focused tests, this document, dedicated workflow.
One existing modification: `tests/test_search_cup_v23.py` admits EX1 alongside
JE1 in its existing local-executor exception. Its `os` member allowlist and
`subprocess.run` restriction are unchanged. `scope_gate` compares the whole
boundary file against exactly that two-line amendment; a sixth path fails.

EX0's source SHA-256 and all eleven component seals are independently retained
in the executor. `_frozen_bundle` rebuilds and validates EX0, including every
parent T5 source pin, the runtime, profiles, policy, queries, resources, reference
commitment and future output schemas. Any mismatch stops before construction
of a formal run context. The published parent sources remain unchanged.

## Phase A authoring

Python 3.11 and Unicode 14.0.0 are required. PR conformance checks out the exact
head, proves full-history ancestry and the five-path diff, tests the executor
and the existing global v23 boundary, and builds an immutable exact-head artifact.
The ordinary repository Test workflow remains an additional acceptance gate.

Safe authoring commands (output must be new and outside the checkout):

```text
python -m search_cup.v23_t5_e1f_ex1 preflight --expected-binding <retained binding>
python -m search_cup.v23_t5_e1f_ex1 plan --expected-binding <retained binding>
python -m search_cup.v23_t5_e1f_ex1 run-ready --expected-binding <retained binding> --output-dir <new external directory>
python -m unittest discover -s tests -p test_search_cup_v23_t5_e1f_ex1.py -v
python -m unittest discover -s tests -p test_search_cup_v23.py -v
```

The core authoring artifact contains `source-preflight.json`,
`retained-ex0-authority.json`, `replay-plan.json`, `run-ready-receipt.json`, and a
manifest. CI adds its source proof and two test logs, then renews the manifest.
It contains no formal entrant output, query provenance, metrics or adjudication.
The package fingerprint commits the three authoring component seals; the receipt
and byte manifest bind that package to the actual source and CI artifact.
I1–I10 remain **NOT_RUN**. All formal/provider/model/live/network/credential/query
counts and spend remain zero. Independent acceptance is PENDING.

Focused tests use a custom RAM store and custom synthetic backend. They exercise
BudgetedSearchProxy and the exact EX0 policy with synthetic strings, and keep all
run-shaped bytes in RAM. These are not E1F-001 executions and cannot be exported
through the test store. The published retriever's `__call__` is trapped throughout
the focused suite; test receipts count synthetic calls separately. Local disk
unit tests write only arbitrary primitive-test bytes, never a formal run-start.

## Later Phase B entrypoint — implemented, not authorized here

`replay` requires all of: an explicit nonempty governance receipt reference,
expected main SHA, retained binding, exact run ID, clean symbolic local main,
matching origin/main, exact tree, ancestry, unchanged retained sources, correct
runtime and a nonexistent output directory. It reads only five environment keys:
GITHUB_EVENT_NAME, GITHUB_REF, GITHUB_SHA, GITHUB_RUN_ATTEMPT, GITHUB_RUN_ID.
If any is present, all must form a complete workflow_dispatch/main/exact-SHA/
attempt-1 context. Arbitrary environment enumeration is not used.

The optional workflow_dispatch job has four non-secret required inputs. It gates
before checkout, then the module independently verifies local source again.
No standing authority receipt is embedded in the workflow. Contents permission
is read-only and checkout does not persist credentials. The Phase A job never
invokes replay. This change does not dispatch that job.

The receipt is a governance reference, not a credential or cryptographic token.
Presence alone does not bypass source, binding, run or context gates. An exclusive
append-only sidecar in the output parent prevents overlapping attempts and reuse
under a different directory name in that same local store. CI attempt >1 is
rejected. **Cross-runner/new-dispatch identity consumption is additionally an
external governance responsibility**, using the explicit one-shot receipt and
published STARTED evidence; a disposable runner cannot enforce a global ledger
with read-only repository permissions. Moving stores does not authorize a retry.

## State, durability and failures

PREPARED → STARTED → A_SUBMISSION_COMMITTED → B_SUBMISSION_COMMITTED →
REFERENCE_ACCESS_ENABLED → ADJUDICATED → COMPLETED.

PRESTART failure creates no formal output directory or queries. Source checks
and the EX0 authoring rebuild precede creation of the formal reference context.
EX0 authoring verification itself inspects the parent reference to validate the
published package; those contents are never fixture inputs. The formal reference
loader is a separate late capability, invoked only after both durable commits.

Run-start is written immediately before the first planned query. Once it exists,
the run ID is consumed even on failure. Each submission uses exclusive temporary
bytes, file fsync, atomic replace, directory fsync, byte readback, output SHA-256,
submission seal, and an append-only hash-linked receipt. Directory/fsync failure
cannot produce a valid submission receipt. The late loader verifies both distinct
receipts and bytes, and records its first load after the second commit.

A backend failure consumes the single attempted ticket and stops. There is no
retry, fallback, extra query or recovery ID. Partial runs preserve every created
byte, including temp files and an actual journal copy when possible. Run-end and
post-run NOT_EVALUABLE receipts are written if possible; unreached outputs and
metrics are never invented. An absent-integrity fingerprint is explicitly all
zeros in a partial terminal receipt, not an integrity PASS claim. A crash can
leave a reservation or incomplete bytes; these are retained for review.

A late storage fault may leave already committed terminal bytes. Consumers must
use `validate_complete` and the full manifest/evidence graph: an isolated PASS
receipt is insufficient. A missing payload, altered bytes, missing manifest or
partial-journal marker cannot establish complete success. No committed file is
rewritten to hide a later failure.

## Execution and evidence

A then B each receive a fresh four-ticket BudgetedSearchProxy over the same
immutable published retriever. Literal query schedules and the pure decision
function come from EX0. Fixtures receive only a SearchResult (title/url/snippet),
never labels, peers, budgets, files or environment. Deduplication preserves first
query/rank order; conflicting frozen identity/content is a protocol failure.

The production constructor reads only corpus/config/index material. It does not
load reference labels. The capability guard surrounds both backend calls and
fixture decisions and blocks provider, network, subprocess, environment and
fixture file reads. It is a guard around pinned trusted Python, not a sandbox
for arbitrary adversarial Python programs.

Resource checks enforce four attempts/turns, ten results per call, 1000 ms per
call, 60000 ms per entrant, no retries/links/fallback and USD 0. Time overruns are
detected on return; this local synchronous executor does not kill a hung Python
function mid-call. CI provides an outer timeout and uploads existing evidence.
Model/provider token consumption is zero for the deterministic fixtures; text
characters are not relabeled model tokens. The 8000-token consumption ceiling is
therefore not used as a character truncation policy.

I1–I10 are computed from actual source observations, retained pins, proxy traces,
query/result provenance, input delivery records, commit chains, visible-policy
recomputation and capability counters. Any failed hard gate stops with PARTIAL /
NOT_EVALUABLE. All ten passing gates need nonempty, exact-resolving evidence;
missing/UNKNOWN/FAIL is never comparable. PASS is limited to this synthetic
protocol validation, with no benchmark, model-quality or live-web claim.

Metrics use the parent equations: Recall@Budget over all reference RELEVANT docs;
Precision@K over the first ten returned rows, excluding UNKNOWN from the binary
denominator without backfilling rank; UNKNOWN_RETURN_COUNT separately. A zero
denominator yields null / NOT_EVALUABLE. Reference labels do not repair visible
fixture decisions. These values are not computed as formal results in Phase A.

The future thirteen JSON/JSONL schemas and fourteen-file complete set are exactly
EX0's frozen contracts. No schema or parent scoring policy is edited. Canonical
seals exclude only the top-level `canonical_fingerprint`; resource receipt links
hash the complete sealed receipt, as required by the parent contract.

`integrity_fingerprint` in metrics/post-run receipts commits the canonical verdict
projection `{run_id, checks: {I1: status, …, I10: status}, comparable_status}`.
The complete evidence-bearing integrity record has its own canonical seal.
This explicit commitment definition avoids a hash cycle: EX0 requires I9 evidence
to hash the actual post-run receipt, which itself contains `integrity_fingerprint`.
The verifier checks the projection and every actual evidence hash, plus full byte
manifest, schemas and seals. A bare verdict hash never substitutes for evidence.

## Handoff

Return the Draft PR exact base/head/tree, narrow five-path diff, focused/boundary
results, ordinary/dedicated CI runs, immutable artifact ID/name/digest, retained
binding/run ID, source-preflight and package fingerprints, and zero-run receipt.

**NO FORMAL E1F-001 REPLAY PERFORMED.**
**KEEP DRAFT / INDEPENDENT ACCEPTANCE REQUIRED.**
