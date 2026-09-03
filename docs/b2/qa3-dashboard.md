# B2 QA3 Quality Evidence Dashboard

QA3 produces a static, read-only projection of checked B2 receipts. The JSON and
HTML reports are derived views, not a new truth store. Removing either report
does not remove or change a checked receipt or an immutable SQLite run.

## Authority boundary

Only two source kinds are accepted:

- `B2_RECEIPT`: a checked receipt whose fingerprint reproduces and whose gate is
  `PASS`;
- `SQLITE_RUN`: an immutable run loaded from the existing schema-v1 experiment
  store in SQLite read-only mode.

Every source is represented by a `CanonicalEvidenceRef` with a typed source ID,
repository-local locator or run locator, source fingerprint, full Git commit,
and explicit scope. The dashboard is always marked
`DERIVED_READ_ONLY_PROJECTION`. It has no writeback path.

The checked static report uses all five declared receipt sources:

| Projection profile | Canonical checked receipt |
|---|---|
| QA0 | `results/b2/qa0-contract-validation.json` |
| QA1 Grounding | `results/b2/qa1-grounding-validation.json` |
| QA1 Tool/Agent | `results/b2/qa1-tool-workflow-validation.json` |
| QA2 Safety/Robustness | `results/b2/qa2-robustness-validation.json` |
| QA3-A Projection Integrity | `results/b2/qa3-quality-delta-validation.json` |

A global projection is rejected when a declared source is missing, duplicated,
ambiguous, or bound to a different Git snapshot. A valid fingerprint alone is
not sufficient: verification rechecks the complete manifest, counts,
one-to-one profile/source mapping, scopes, terminal visibility, and every
no-baseline delta row.

## QA3-A frozen projection-integrity cases

The public-safe set contains three exact abstract lineages, each with one
`KNOWN_BAD` case and one matched `CONTROL`:

| Public lineage | Family | Contract attacked |
|---|---|---|
| `QA3-SEED-P01` | `full-set-projection-completeness` | A sampled subset cannot establish global completeness. |
| `QA3-SEED-P02` | `metric-attribution-provenance-separation` | A real value cannot upgrade unknown provenance or causal attribution. |
| `QA3-SEED-P03` | `dashboard-field-semantics-scope-lock` | Similar field names cannot exchange semantics or personal/current/history/global scope. |

The fixture body contains only synthetic identities and abstract public seed
digests. It contains no private source body or locator.

## Quality-delta contract

A delta is computed only when the following comparison key is identical for the
current and baseline observations:

- profile;
- suite identity;
- metric ID, version, and definition;
- case-set fingerprint;
- terminal-semantics version;
- aggregation rule;
- scope type and scope identity.

Terminal behavior is fail-closed:

| Condition | Output terminal | Delta |
|---|---|---:|
| Complete and comparable | `PASS / COMPARABLE` | computed |
| No baseline | `NOT_EVALUABLE / NO_BASELINE` | `null` |
| Required evidence unresolved | `UNKNOWN` | `null` |
| Incompatible comparison | `FAIL / NOT_COMPARABLE` | `null` |
| Infrastructure terminal | `ERROR` | `null` |
| Hard-invariant failure | `FAIL / HARD_INVARIANT_FAILURE` | `null` |

`UNKNOWN`, `NOT_EVALUABLE`, `ERROR`, and a hard failure are never converted to
zero, `PASS`, or an average. Because the selected checked receipts form one
snapshot and contain no compatible earlier snapshot, the checked report emits
`NOT_EVALUABLE / NO_BASELINE` for every profile. It does not invent a trend,
recurrence series, causal improvement, latency, token, or cost metric.

## Reproducible build

`build_checked_dashboard` reads the five checked receipts, verifies their
fingerprints, binds them to one full source commit, and produces canonical JSON.
`render_dashboard_html` verifies that JSON before rendering it.

The report's `source_snapshot.git_commit` names the commit that contains the
canonical source receipts. The later commit that adds the derived JSON/HTML can
therefore have a different identity without creating a self-referential hash.
Given the same source files, source commit, and explicit UTC timestamp, both
outputs rebuild byte-for-byte.

Run the bounded verification with:

```bash
python -m unittest tests.test_b2_qa3 -v
```

The generated files are:

- `reports/b2/qa3-quality-delta.json` — machine-readable projection;
- `reports/b2/qa3-quality-delta.html` — recruiter-readable static view.

Both preserve source IDs, fingerprints, commit context, scope, definitions, and
limitations. No brand-specific adapter is selected and no brand-specific claim
is unlocked.
