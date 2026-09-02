# B2 QA0 Evidence Index

This index covers the frozen deterministic QA0 fixture set only.

| Family | Known-bad | Control | Capability profile | Public provenance |
|---|---|---|---|---|
| `entity-attribute-binding` | `B2-QA0-EAB-KB-001` | `B2-QA0-EAB-CTRL-001` | Grounding / Source Binding / Entity–Attribute Integrity | abstract synthetic-seed digest |
| `connector-schema` | `B2-QA0-CS-KB-001` | `B2-QA0-CS-CTRL-001` | Tool/Agent QA / Schema Validation / Retry & Readback | abstract synthetic-seed digest |
| `integrity-completeness` | `B2-QA0-IC-KB-001` | `B2-QA0-IC-CTRL-001` | End-to-End QA / Data Quality / Global Invariant Coverage | abstract synthetic-seed digest |
| `evidence-scope` | `B2-QA0-ES-KB-001` | `B2-QA0-ES-CTRL-001` | Grounding Verification / Evidence Scope / Source Reliability | abstract synthetic-seed digest |

## Deterministic gate

The generated receipt in `results/b2/qa0-contract-validation.json` is expected to show, for this frozen fixture set:

- 8 cases total / 4 known-bad / 4 controls;
- known-bad detection rate = 1.0;
- control false reject rate = 0.0;
- provenance trace rate = 1.0;
- evidence completeness rate = 1.0;
- stable fixture and receipt fingerprints across reruns.

These numbers **must not** be generalized to live models, production systems, or scientific benchmark performance.

## Independence boundary

Developer regression green is not the Independent QA verdict. QA0 closes only after the Draft PR packet is independently reviewed and the formal state is committed.

## Repository layout

The eight cases are stored in `cases/b2/public-safe/qa0-fixtures.json`; four mechanism specs are stored in `mechanisms.json`; normalized deterministic BugCases are stored in `results/b2/bugcases.json`.
