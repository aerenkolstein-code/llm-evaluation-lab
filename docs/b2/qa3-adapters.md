# B2 QA3 Vendor-neutral Reference Adapter

QA3 includes one deterministic, offline reference adapter that demonstrates an
interoperability contract without an external account, credential, network
request, paid service, SDK, or brand-specific claim.

## Data path

The one-way path is:

`Canonical evidence → neutral projection record → adapter representation → reconciliation`

The adapter representation is disposable. Canonical SQLite rows and checked B2
receipts remain the only authorities, and reconciliation never writes back to
them.

## Field mapping

| Canonical field | Adapter field | Reconciliation rule |
|---|---|---|
| Full canonical record | `source_digest` | Must equal the canonical JSON fingerprint. |
| `evidence_ref` | `canonical_ref` | Must be identical, including source identity, fingerprint, commit, and scope. |
| `metric.metric_id` | `metric.metric_id` | Exact match. |
| `metric.metric_version` | `metric.metric_version` | Exact match. |
| `metric.definition` | `metric.definition` | Exact match. |
| `metric.value` | `metric.value` | Exact typed value match. |
| `metric.unit` | `metric.unit` | Exact match. |
| `metric.scope_type` / `scope_id` | Same names | Exact match; no scope upgrade. |
| `metric.observed_at` | `metric.observed_at` | Exact match. |
| Provenance and causal attribution | Same names | Exact typed-state match. |
| `terminal_status` | `terminal_status` | Exact match; no coercion. |
| `hard_invariant_pass` | `hard_invariant_pass` | Exact match; no soft-score override. |
| Optional metadata | omitted only when declared | Omission must appear in `limitations`. |

The adapter may create only a deterministic derived alias named from the
canonical digest. It cannot allocate or replace a canonical run ID, case ID,
receipt fingerprint, or source reference. `writeback_permitted` is a schema
constant of `false`.

## Frozen reconciliation matrix

The public-safe fixture set executes all nine required scenarios:

| Scenario | Expected result |
|---|---|
| `EXACT_ROUNDTRIP` | `PASS / RECONCILED` |
| `DIGEST_MISMATCH` | `FAIL / NOT_RECONCILED` |
| `METRIC_SEMANTICS_MISMATCH` | `FAIL / NOT_RECONCILED` |
| `TERMINAL_MISMATCH` | `FAIL / NOT_RECONCILED` |
| `SCOPE_MISMATCH` | `FAIL / NOT_RECONCILED` |
| `VALUE_MISMATCH` | `FAIL / NOT_RECONCILED` |
| `ADAPTER_UNAVAILABLE` | `ERROR / ADAPTER_UNAVAILABLE`; canonical quality unchanged |
| `LOSSY_OPTIONAL_EXPLICIT` | `PASS / RECONCILED` with an explicit limitation |
| `SILENT_CRITICAL_DROP` | `FAIL / NOT_RECONCILED` |

Malformed adapter output also fails closed as an adapter-schema mismatch.
Adapter failure is an infrastructure condition; it never rewrites the native
quality verdict or becomes evidence of model regression.

## Contract artifacts

- `schemas/external_eval_adapter.schema.json` freezes the neutral record,
  adapter representation, typed evidence reference, and reconciliation shapes.
- `cases/b2/public-safe/adapters/qa3-reference-adapter-fixtures.json` contains
  the nine synthetic scenarios.
- `results/b2/qa3-adapter-validation.json` is the reproducible checked receipt.
- `b2/qa3.py` contains the standard-library-only reference implementation.

Run the contract verification with:

```bash
python -m unittest tests.test_b2_qa3.B2QA3Tests.test_adapter_fixture_set_is_exact_and_all_outcomes_match -v
```

No brand-specific adapter is selected in QA3 v0.1. Adding one requires a
separate amended authorization, real implementation and execution evidence,
and a new independent review.
