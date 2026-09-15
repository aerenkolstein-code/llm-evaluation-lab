# A2 E1 independent offline verification

Work order: [ENG-A2-E1-01 / Issue 52](https://github.com/aerenkolstein-code/llm-evaluation-lab/issues/52).
System under test: Companion-Mind PR27, exact head
`36c138f53912821732683d40cf994cc776cd1fc9`.
Contract: `canonical_event/v1` at `63ac8d7de8eb35915cc291b0f7ea67c33b366922`.

`tools/a2_e1.py` is an independent consumer of the published JSON CLI. It imports
no Companion-Mind module, test, fixture factory or conformance runner. It reads
only public contract/manifest/handoff files and git metadata. It never reads the
local Journal database, WAL, spool, outbox, or fake remote files. All runtime
observations come from separate CLI processes. A1 conformance remains a distinct
reference receipt and is never the A2 oracle.

The case catalog in `cases/a2/e1-case-catalog.json` maps every required section to
its rubric and evidence. Input-derived event oracles compare the entire JSON
mapping, including identities, provenance, attachments, correction edges and
knowledge states. SHA-256 uses finite UTF-8 JSON, sorted keys, compact separators,
and `ensure_ascii=False`. False, zero, null and absent fields remain distinct.
No canonical field is normalized away. Raw operational IDs remain in the
observation ledger; deterministic result comparisons omit those operational IDs.

## Reproduce

Use Python 3.11+ and a POSIX local filesystem. Check out both exact repository
commits and keep them clean. No dependency install, credentials, provider SDK or
real remote transport is needed. The existing A2 baseline CI need not be changed
to point its unrelated integration tests at the new A1 candidate.

1. Refresh GitHub PR27, Test run `34992621405`, Issue52 and the pinned handoff and
   manifest. Stop if the head, Draft/open state, successful CI or contract differs.
2. Save a public-safe connector observation to a JSON file outside this checkout,
   with `observed_at` (UTC ISO timestamp), `a1_pr_state="open"`,
   `a1_pr_draft=true`, `a1_head`, `contract_commit`,
   `a1_ci_run_id=34992621405`, `a1_ci_conclusion="success"`, and `a1_ci_head`.
   The pinned heads must equal those above. Add the source URLs and distinct A1
   receipt/CI artifact references. This is an observation receipt, not a signed
   GitHub attestation or an execution lock. The harness rejects observations over
   one hour old; the operator must refresh GitHub again before the final return.
3. Run the sealed A2 harness once; it performs both independent fresh 120-turn
   runs, 100 complete / 10 partial / 10 failed, within that one evaluation.

```sh
python3 -B -m unittest discover -s tests -p test_a2_e1.py -v
python3 -B tools/a2_e1.py \
  --a1-checkout /absolute/path/to/Companion-Mind \
  --preflight-receipt /absolute/path/to/fresh-preflight.json \
  --output-dir /absolute/path/to/new-evidence-directory
```

The output directory must not already exist and should be outside both checkouts.
The harness uses disposable fresh store/replica directories and deletes them on
exit after preserving all public-safe observable evidence. A2 code must be committed
before the formal run; `a2_execution_head/tree` identifies the executed code.
The later evidence commit contains those unchanged harness bytes, verified through
`harness_sha256`. The final Draft PR head/tree is returned separately to avoid a
self-referential commit field.

## Evidence and interpretation

- `receipt.json`: preflight, environment, every check, two run receipts,
  zero-tolerance table, F1–F8 plus atomic-fault matrix, restart, replica,
  secret/knowledge/authority/provenance receipts, missing evidence and one verdict.
- `observations.jsonl`: operation/request fingerprints, exact exit codes,
  public responses, raw stdout/stderr fingerprints and sentinel scan results.
  If a sentinel leaks, its raw hash/count remains evidence and its readable value
  is replaced before the ledger is written. The sentinels are synthetic.
- `normalized-result.json`: deterministic metrics, case/invariant outcomes and
  complete canonical batch fingerprints. No operational IDs or wall-clock fields.
- `SHA256SUMS.json`: hashes of the produced evidence files.

Each CLI invocation reopens the same per-case store; explicit recovery cases add
three more separate-process reopen checks. F1 requires USER only / NOT_SENT and
permits one explicit resume. F2 requires local failed / external UNKNOWN with no
automatic retry. F3 retains the first durable safe frame as partial / UNKNOWN.
F4 and F5 preserve complete exactly once. F6–F8 preserve local evidence and
reconcile the same offline remote target. `APPEND_BEFORE_COMMIT` must leave no
observable canonical event or outbox, followed by one explicit successful retry.

The `drain` completion envelope is physical journal high-water order. Its
`ordered_fingerprint` is therefore checked against expected physical append order.
A2 separately sorts completed readback with the published canonical key and
compares every event against canonical export and its input-derived oracle.
Permuted/late imports deliberately distinguish these two orders; the fingerprints
must not be conflated. Lag, transport error and mismatched readback cannot count
as verified agreement. Later appends require a new completion envelope.

The oracle mutation controls prove that dropped, duplicated, reordered, fabricated,
overwritten, status-changed, identity-changed and UNKNOWN-collapsed events cannot
silently pass. These are tests of A2's measurement logic, not copied A1 tests.

Any observed invariant failure is `FAIL`. Missing required observations are
`NOT_EVALUABLE`; preflight drift is `BLOCKED`. Zero-valued metrics are counts over
all checked snapshots, not weighted scores. The only success verdict is `PASS`.
A2 PASS is not E1 GREEN: Board/Verification must accept separate A1 and A2 receipts.
Return the Draft PR and evidence, then STOP.

Limits: this evaluates process crashes on one POSIX local substrate, not physical
power loss or all filesystems. Offline fake transport does not establish live
Google Drive integration. Observable secret exclusion does not certify hidden
storage or arbitrary unlabeled secrets. Unsupported authority requests and unchanged
external synthetic controls are bounded negative evidence, not a proof of all
possible filesystem behavior. No Companion-Mind mutation, live/paid call, private
fixture, B1/B2 change, merge, issue closure or next-stage transition is performed.
