# SEARCH-CUP v2.3 T4 JE1 — offline replay executor

Status: **PHASE A RUN-READY CANDIDATE / KEEP DRAFT / INDEPENDENT ACCEPTANCE REQUIRED**.
**NO FORMAL JE1 REPLAY PERFORMED.** Implementation and tests do not authorize
merge or the future Phase B execution.

The [issued work order](https://docs.google.com/document/d/10KZRrMU-IeaTC9eGhKswKP6xghgpbO4t3VMjfiAdN9g/edit)
authorizes Phase A development from main
`c0e365360034ef5c45800563717bbffc7fc5c1b3`, tree
`71ec404d306ab8b45612a9931e121ad01ca8ad0f`. This change adds the executor,
its focused tests, this document and its dedicated workflow. The user approved
one additional existing path, `tests/test_search_cup_v23.py`, after the first
full-suite run exposed its blanket ban on importing `os` and `subprocess` in
all `v23_*.py` modules. The approval request named only that fifth path and
JE1 boundary checks; the user's reply was "批准". It does not authorize merge
or Phase B execution.

The amendment permits only JE1's local durability and source-probe imports.
The inherited transport/provider bans remain in effect for JE1, its accessible
`os`/`subprocess` members are checked, and all other protocol modules retain
the original restriction. Dedicated tests check fixed read-only Git commands,
an explicit non-secret subprocess environment, named public context reads,
forbidden scorer capabilities and the authority/main execution locks.
Published JE0, T4, SP3 and the ordinary Test workflow remain unchanged.

## Purpose and frozen identity

JE1 supplies durable execution and actual-run auditing around the existing
`v23_t4_execution` fixture. It imports `build_bundle`, `validate_bundle`,
`validate_planned_record` and `fixture_decision`, plus SP3 `validate_record`,
`JudgmentJournal` and `integrity_gate`. It adds no scoring implementation.

| Retained object | SHA-256 |
| --- | --- |
| Execution binding | `a87a0ad172d6292cc7be52580e1ed7d85615e1298582249f892032fea83fd11d` |
| Parent binding | `d8002784bd1a7b12052e204249229e95c0ef8f4cd5897b01a82d2cb96fb31222` |
| First-pass plan | `6c732494e49d91a9c1573ec5345de7f5b3f4ecd3a6d99f8c0c4e4ed35062d508` |
| Fixture A | `2012a82562ea1dcf1860ac73ad154ee5852d65a54ea2e02ac589756ec1a5cf77` |
| Fixture B | `a27b0b251f1655d406711287f20b0315769d45e436ba2cfdface02120611e900` |
| Integrity plan | `7d88295e3ab653f1711b1fb624e7de6030741954b45ceb44c7722df4c6d400ea` |
| JE0 authoring receipt | `614c060e4daf5bb067c4fc1c12bec4effefd274b6a27c625d340b6bef99ef1a6` |

JE0 reference artifact: ID `10490073947`, digest
`sha256:9f086a9efe8a3e5d0849a7c2f6c92d1b80d3f55aa11b4d261593db500033b997`.
The executor verifies independently retained pins against the rebuilt source
objects. An object's self-reported seal alone is insufficient.

Execution ID: `T4-JUDGMENT-PV-001-EXEC-V1`.
Exact future run ID:

```text
T4-JUDGMENT-PV-001-EXEC-V1:a87a0ad172d6292cc7be52580e1ed7d85615e1298582249f892032fea83fd11d:JE1-001
```

The frozen schedule is judge-alias ascending, then candidate-ID ascending:
two fixture judges times three candidates, six sequential first passes.
Alpha is ACCEPT; Beta and Gamma are UNKNOWN for both judges. Fixture A uses
0.95 / 0.50 / 0.50 confidence, and fixture B uses 0.90 / 0.25 / 0.25.
In particular, Beta's hard UNKNOWN remains UNKNOWN under the inherited SP3
rule. These constants are synthetic protocol fixtures, not measured model
quality or calibration. JE1 produces no HUMAN_OVERRIDE or synthesis.

## Phase A surfaces

Python 3.11 and the standard library suffice for the dedicated suite and CLI:

```sh
python -m unittest discover -s tests -p 'test_search_cup_v23_t4_je1.py' -v
python -m search_cup.v23_t4_je1 preflight --expected-binding a87a0ad172d6292cc7be52580e1ed7d85615e1298582249f892032fea83fd11d
python -m search_cup.v23_t4_je1 plan --expected-binding a87a0ad172d6292cc7be52580e1ed7d85615e1298582249f892032fea83fd11d
```

`preflight` and `plan` never call the scorer or create a replay store. Preflight
records source metadata, retained pins and zero formal execution/record/call
counts; `post_run_integrity=NOT_RUN`. The plan remains `PLANNED_NOT_EXECUTED`.
A successful preflight is preparation evidence, never Phase B permission.

Tests exercise the internal engine with an explicitly non-formal in-memory
store. Simulated records use the frozen schema identifiers so inherited
validators can be tested, but stay in process memory. Their enclosing receipts
say `test_only=true`, `formal_execution_performed=false`,
`formal_record_count=0`, and `run_identity_consumed=false`. They are not
exported as JE1-001 results. Disk durability tests use generic checkpoint bytes
only, never a formal record or run marker.

The PR-only conformance job checks the exact head, unchanged construction
baseline, four added paths and the one authorized existing-test modification.
It also executes the amended protocol boundary test. Its immutable artifact is
`search-cup-v23-t4-je1-run-ready-<exact-head-sha>` and contains only:

- `preflight.json`: zero formal execution and retained pins;
- `first-pass-plan.json`: frozen future plan;
- `retained-pins.json`: independently retained fingerprints;
- `ci-source.json`: exact base/head/tree, five paths, scope approval, CI run and test results;
- `focused-tests.log`;
- `boundary-tests.log`;
- `MANIFEST.sha256` for the six payload files.

Ordinary full-repository Test CI is also required. Dedicated CI must show its
formal job skipped on every PR event. The run-ready artifact contains no
`run-start.json`, formal first-pass journal, post-run integrity result or
formal authority receipt.

## Future Phase B lock — do not execute under Phase A

After independent acceptance and a separately authorized merge, a new explicit
Board decision must authorize one JE1-001 execution. The runtime interface is:

```text
python -m search_cup.v23_t4_je1 replay
  --authority-receipt <separate-non-secret-Board-receipt-id>
  --expected-source-sha <accepted-and-merged-40-hex-main-sha>
  --expected-binding <retained-binding-above>
  --run-id <exact-frozen-JE1-001-id-above>
  --output-dir <new-directory-outside-source-with-existing-parent>
```

All arguments are required; no standing authority value is supplied by code or
workflow. A receipt ID is an auditable reference, not a cryptographic verifier
of Board approval. The operator must establish the referenced authorization
before using this future interface.

The executor requires a clean checkout whose symbolic branch is
`refs/heads/main`, whose HEAD and local `origin/main` equal the expected SHA,
and whose frozen package matches the retained pins. It rejects detached or
PR merge refs, an arbitrary branch, dirty source, reused output directories
and output paths inside the source checkout. It never fetches Git refs.
Local execution therefore needs a fresh main checkout verified independently;
matching a stale local ref is not proof of current remote state.

In GitHub Actions it additionally requires `workflow_dispatch`, main ref,
exact `GITHUB_SHA`, a run ID and `GITHUB_RUN_ATTEMPT=1`. Partial CI context
fails closed. The workflow has four required non-secret dispatch inputs,
`contents: read` permission, checkout `persist-credentials: false`, and no
repository write. Its main checkout is compared against the supplied exact
SHA again by the executor, catching main drift after dispatch.

The PR and dispatch jobs are mutually exclusive. A formal job's rerun attempt
is rejected, and its concurrency group prevents overlapping formal jobs.
Fresh output directories prevent replay into an existing local journal.
These are not a distributed once-ever registry: a deliberately new dispatch
or another clean machine still requires governance to reject reuse of the
consumed JE1-001 authority. No automatic retry or resume command exists.

## Start boundary and durable records

1. Authority, source, binding, run ID, input and fresh-output checks precede
   execution. Failures return `PRESTART_NOT_EVALUABLE`, zero formal records,
   and no consumed formal result.
2. Initial empty journal/projection files are prepared. A durable
   `run-start.json` is written immediately before the decision loop. Its
   presence consumes the run identity even if the first decision fails.
3. Before each pair, the executor rebuilds the frozen bundle, checks source
   and pins, and verifies exact canonical blind bytes and their SHA-256.
4. It calls the frozen fixture once, constructs a sealed record using a real
   current UTC `committed_at`, and invokes both inherited record validators.
5. It verifies the durable journal still equals the prior prefix, appends via
   `JudgmentJournal`, and commits the canonical journal before the next pair.
   The write uses an exclusive temporary file, file fsync, atomic replace and
   directory fsync. The JSONL projection and per-delivery fingerprint audit
   follow each committed journal update.
6. Start/end comparison and actual outputs supply J1–J10. Only the inherited
   `integrity_gate` returning PASS, six valid records, exactly six scorer calls
   and no execution exception can yield a complete successful receipt.

After STARTED, any failure produces `NOT_EVALUABLE / PARTIAL` with no retry.
Previously committed records are not recomputed or replaced. The canonical
`judgment-journal.json` is authoritative: a crash may leave the JSONL projection
or delivery audit one commit behind. The handler reads back durable journal
bytes, including when atomic replacement succeeded before a later fsync error.

An abrupt kill, machine loss or persistent disk error can prevent a final
receipt or manifest from being written. The surviving marker/journal must then
be inspected; missing completion evidence never means PASS. Workflow artifact
upload uses `if: always()` to preserve surviving files when the runner remains
available. A new successor identity and separate recovery approval are required
after any started failure; JE1-001 cannot be resumed by this implementation.

## Actual-run integrity evidence

| Gate | Evidence computed from the future run |
| --- | --- |
| J1 | Start candidate/parent pins and exact six-pair journal coverage |
| J2 | Each delivery's canonical input, rubric, evidence and order fingerprints |
| J3 | Leakage audit of the canonical judge payload |
| J4 | Zero-resource receipt and trapped forbidden capability attempts |
| J5 | Valid append-only journal, six independent pairs, no peer observations |
| J6 | Actual records passing SP3 and retained-plan validation |
| J7 | Intact first-pass-only journal, zero overrides, frozen append-only policy |
| J8 | Matching start/end aggregation pins |
| J9 | Only blind bytes delivered; no hidden registry or provenance delivered |
| J10 | Matching source and all package/profile/roster/plan pins at start/end |

Each check includes a nonempty content-addressed reference to the corresponding
actual artifact data. Unit-test results are never substituted for run evidence.
Missing evidence or any failed gate makes the candidate NOT_EVALUABLE.

Only the canonical blind input is the judge-visible payload. Frozen fixture
profiles are internal scorer configuration; neither profiles nor roster,
source SHA, authority ID, synthetic provenance labels or peers enter the blind
bytes. Rebuilding the published JE0 parent creates its existing public
synthetic authoring objects in the coordinator; no hidden registry is opened
and no provenance ledger is supplied to the fixture function.

The trusted scorer is pure, pinned, sequential Python. During its invocation,
traps reject socket/URL calls, subprocess creation, environment access and
file opens, and count forbidden attempts. This is defense around trusted code,
not a hostile-code Python sandbox. Durable output I/O and fixed read-only local
Git probes are outside that scorer boundary. Only five named, non-secret GitHub
context variables are read by the coordinator; no credential lookup occurs.
CI checkout/artifact transport is outside the zero-network local replay scope.
Provider adapters, external search, live evidence, official competition prompts,
hidden registries and credit consumption are excluded.

## Future formal output and review boundary

A complete future run can emit eleven files: `preflight.json`, `run-start.json`,
`first-pass-records.jsonl`, `judgment-journal.json`, `input-delivery-audit.json`,
`leakage-audit.json`, `resource-receipt.json`, `integrity-checks.json`,
`run-end.json`, `post-run-receipt.json`, and `MANIFEST.sha256`.
The future immutable artifact is
`search-cup-v23-t4-je1-001-<exact-source-sha>`.

The formal receipt binds authority, source SHA/tree, execution/run identity and
binding to actual counts and terminal status. Successful expectations are six
formal records, six fixture calls, zero overrides, zero provider/search/network/
credential/credit/spend/retry counters, all J gates PASS and completion COMPLETE.
UNKNOWN values remain unresolved first-pass outputs; human adjudication needs
another package and authority.

Claims ceiling for every stage:
`SYNTHETIC_PROTOCOL_VALIDATION_ONLY / NOT_BENCHMARK / NO_MODEL_QUALITY / NO_LEADERBOARD`.

The Phase A handoff is a Draft PR plus exact-head tests, ordinary/dedicated CI
receipts and the run-ready artifact. Independent review, merge authorization
and later one-shot execution authorization remain separate gates.
