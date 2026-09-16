# SEARCH-CUP v2.3 — T4 Judgment-only First-Instance Package

Work order: `ENG-B1-SC-V23-T4` / Issue #56.

Status: **INSTANCE AUTHORING CANDIDATE / SYNTHETIC PROTOCOL VALIDATION / NO JUDGE EXECUTION / AWAITING BOARD–VERIFICATION**.

Exact published T1 base: `b3b3a07d18950cdde2a6ad1e42b45fcda494b039`.

## What this package is

This is the first selected **Judgment-only protocol-validation instance** under SEARCH-CUP v2.3. It is intentionally synthetic and public-safe. It validates the frozen judgment pipeline without claiming to represent a real market, a real search result, a model-quality benchmark, or a leaderboard.

The package is generated deterministically by:

```bash
python -m search_cup.v23_t4_instance bundle --output-dir /tmp/search-cup-v23-t4
```

The generated directory contains:

- `manifest.json`
- `searchspec.json`
- `candidate-pool.json`
- `blind-judge-view.json`
- `provenance-ledger.json`
- `evidence-packet.json`
- `rubric.json`
- `adjudication.json`
- `judge-roster.json`
- `resource-envelope.json`
- `instance-bindings.json`
- `judgment-package.json`
- `receipt.json`

CI uploads this exact-head bundle as an artifact. The bundle is immutable by canonical fingerprints and SHA-256 for the byte-identical blind judge view.

## T1 D1–D8 mapping

T4 follows the **published T1 implementation semantics**, not the earlier human-readable numbering draft:

| Decision | T4 value |
| --- | --- |
| D1 | `JUDGMENT_ONLY` track binding — FROZEN |
| D2 | exact frozen `searchspec/v2` — FROZEN |
| D3 | exact frozen Judgment package — FROZEN |
| D4 | frozen corpus/index overlay — NOT_APPLICABLE |
| D5 | exact synthetic/not-connected judge roster — FROZEN |
| D6 | F1 retriever qualification — NOT_APPLICABLE |
| D7 | exact resource envelope — FROZEN |
| D8 | system/economic/ablation package — NOT_APPLICABLE |

The resulting T1 `instance_gate()` must report:

- `missing_decisions = []`;
- `terminal_status = BLOCKED`;
- `execution_allowed = false`;
- `reason_codes = ["T1_IMPLEMENTATION_ONLY"]`.

That combination is deliberate: T4 proves that the instance package is materially complete while still lacking any execution authority.

## Frozen synthetic task

The task is to judge each frozen synthetic remote-work opportunity candidate for:

1. **remote eligibility** — hard constraint;
2. **actionability** — hard constraint.

Only the frozen evidence packet may be used. Insufficient evidence is `UNKNOWN`, never an implicit `NO`.

The candidate set contains three synthetic cases:

- a clearly remote/actionable case;
- a clearly on-site/non-remote case;
- an intentionally under-specified case that exercises UNKNOWN discipline.

Candidate identities are derived from the frozen normalization/dedupe policy. The hidden provenance ledger is generated separately and does not appear in the judge-visible payload.

## Proposed judge roster

This protocol-validation package freezes two **synthetic, not-connected judge identities**:

- `t4-fixture-judge-a`;
- `t4-fixture-judge-b`.

They are configuration fixtures, not real model endpoints, and they are deliberately absent from the blind judge view. No judge invocation occurs in T4 authoring.

A later real-world/model-performance Judgment instance must use a separately authorized roster/package; this T4 package must not be silently relabeled.

## Resource envelope

The future protocol-validation judgment run is bounded by the frozen SearchSpec:

- search calls: 0;
- search turns: 0;
- search results: 0;
- follow links: 0;
- automatic retries: 0;
- external tools: none;
- total token ceiling: 6000 tokens;
- total runtime ceiling: 120000 ms;
- money ceiling: USD 0 for this synthetic not-connected validation instance.

This package does not itself run the future judgment records.

## Integrity and adjudication

The frozen package enforces:

- deterministic pooling/dedupe before judgment;
- provenance ledger separate from public/blind package;
- byte-identical judge view;
- rubric and aggregation frozen before outputs;
- independent first pass;
- UNKNOWN preservation;
- append-only human adjudication;
- frozen-evidence-only adjudication;
- predeclared triggers: disagreement, critical unknown, identity collision, contradiction, rubric edge;
- zero search and zero external-tool access.

## No-live receipt

T4 authoring must return and CI must verify:

- `execution_allowed = false`;
- `provider_calls = 0`;
- `search_calls = 0`;
- `judge_calls = 0`;
- `credit_consumption = 0`;
- `spend = USD 0`;
- `official_prompt_consumed = false`;
- `hidden_registry_loaded = false`;
- `real_world_candidate_claim = false`.

No PR #17 mutation, Gemini repair, E1 execution, P3/P4/P5, leaderboard, or model-quality claim is authorized.

## Exit

Return the Draft PR and exact-head CI artifact for Board / Verification.

**STOP after the instance package is authored and validated. A separate accepted package plus a separate execution work order are required before any judge call.**
