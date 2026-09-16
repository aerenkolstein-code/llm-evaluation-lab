# SEARCH-CUP v2.3 — T1 protocol implementation

Work order: [ENG-B1-SC-V23-T1, Issue #54](https://github.com/aerenkolstein-code/llm-evaluation-lab/issues/54).

Status: **IMPLEMENTATION CANDIDATE / OFFLINE ONLY / AWAITING BOARD–VERIFICATION / STOP ON RETURN**.

Exact authorized base: `6229e8d164831b8433c62b7d90820d4b0b4ce225` (tree `b9f4641c2e7e0613fb0522ca2c6ae87ac79fdfd5`).
Successor branch: `agent/b1-sc-v23-t1-protocol`.

Authority is the user-ratified SEARCH-CUP v2.3 architecture, Board-accepted Protocol Stage Plan, frozen SP1–SP4 v0.1 (G1), and accepted SP5 v0.1 (G2). This document transcribes their implementation boundaries; it does not replace them, select D1–D8, or import the v2.4 checkpoint. Private authority locators/source documents are deliberately not copied into public fixtures.

PR #17 remains historical/candidate lineage, Draft/open/unmerged at `f5c6519c4d8b3d9182871c23e27162c7cff930ae`. Its selected disposition is **A — SPLIT / SUPERSEDE**, not merge/rebase/cherry-pick/close. None of its branch history or historical provider configurations is imported.

## Surface and reproduction

```bash
# Standard-library-only T1 checks; no provider credentials or network needed.
python -m unittest discover -s tests -p 'test_search_cup_v23.py' -v
python -m search_cup.v23_offline schema
python -m search_cup.v23_offline receipt

# Existing full repository regression, with the existing Companion-Mind dependency.
python -m unittest discover -s tests -v
```

The existing Test workflow runs the full regression, regenerates and compares the schema and receipt, then uploads both with the exact PR head in the artifact name. No new dispatch, live workflow, credential, provider adapter, or third-party dependency is introduced.

| Path | Role |
| --- | --- |
| `search_cup/v23_schema.py` | Closed schema vocabulary and strict finite-JSON shape validation |
| `schemas/searchspec_v2.schema.json` | Exported JSON Schema, byte-content regeneration tested |
| `search_cup/protocol_v23.py` | Immutable SearchSpec, cross-field semantics, fairness/claims, instance gate, output/evidence and missingness |
| `search_cup/v23_accounting.py` | Immutable supplied-event accounting reducer and independently recomputed receipts |
| `search_cup/v23_judgment.py` | Deterministic candidate/dedupe/blind transform, frozen judgment contracts and append-only record validation |
| `search_cup/v23_offline.py` | Synthetic protocol probes and read-only stdout CLI; **no run command** |
| `tests/test_search_cup_v23.py` | Positive and adversarial contract, accounting, judgment and no-I/O checks |
| `results/search-cup/v23-protocol-offline.json` | Reproducible synthetic contract-validation receipt, not benchmark results |
| `.github/workflows/test.yml` | Existing offline CI extended with regeneration and artifact receipts |

The schema validates shape; `SearchSpecV2` is also mandatory for semantic validation. A plain JSON Schema PASS is not protocol conformance, instance approval, or execution permission.

## Identity, controls and execution boundary

- Canonical JSON reuses SP5 P0-01 with a finite/strict-JSON front gate. SHA-256 excludes only the object's top-level `canonical_fingerprint`; nested fingerprints remain covered. Unknown fields, booleans as counters, NaN/Infinity and non-JSON containers are rejected.
- A `SearchSpecV2` stores canonical immutable content and returns defensive copies. Both its constructor and `from_mapping` validate. Changing a frozen specification requires a new spec version, fingerprint and run identity; `require_successor` checks this transition.
- A0 is human/model co-design, frozen and unscored. Scope, task and resource bindings cannot be stale. A1 ownership and permitted behavior are explicit; external planning cannot masquerade as neutral E1 retrieval.
- F1 requires the identical SearchSpec, retriever capability surface, resource envelope and controls. F2 permits different disclosed components and internal call counts: its fixed control is the **disclosure standard**, not identical system components. A0's resource binding is the complete technical envelope for F1, common deadline for F2, and money/time package for F3. Full per-system envelopes remain fingerprinted in their SearchSpecs. E2 fixes accounting rules and the control-model identity rather than inventing raw-call equivalence between unlike stacks.
- `search_pro` without a qualification package returns `NOT_F1_ELIGIBLE_BY_DEFAULT`. R1–R8 require explicit PASS + evidence, bound to the exact backend/config/capability surface. Declared integrated planning contradicts neutrality even if an input asserts eight PASS labels.
- `compare_controls` rejects mixed tracks/fairness frames, changed non-principal controls and different F1 spec identities. Ablation changes exactly one declared capability and explicitly freezes all remaining capability classes.
- Instance bindings D1–D8 are external artifacts. Their hashes, exact spec identity and relevant task/roster/retriever/resources/corpus/judgment contents are checked, not only their FROZEN labels. Missing/deferred/inapplicable required decisions block the gate. Approval references are **untrusted declarations for Board verification**, not credential-bearing authority.
- Even a structurally complete synthetic instance returns `BLOCKED / T1_IMPLEMENTATION_ONLY / execution_allowed=false`. This is deliberate: T1 provides **no executor, no authorization switch and no transport callback**. Future execution requires separately authorized instance and runner work; it cannot be unlocked by editing a test fixture or approval boolean.

## SP1–SP4 conformance matrix

Test names below refer to `tests/test_search_cup_v23.py`; inherited P0/P1 safety regressions remain in `tests/test_search_cup.py`.

| Frozen obligations | Implementation | Offline evidence / representative counterexamples |
| --- | --- | --- |
| SP1 S1, S2, S9 — immutable schema/task/scope/UNKNOWN/stop/version | `SearchSpecV2`, `seal`, `require_successor` | required-field sweep; mapping-order invariance; nested mutation isolation; stale hashes; version+run transition tests |
| SP1 S3; SP2 T4–T5 — A0 unscored, A1 ownership/envelope | SearchSpec A0/A1 validators | `test_a0_never_scored_and_a1_no_hidden_planning`; stale task/scope/resource bindings |
| SP1 S4; SP2 T6; SP4 F3 — R1–R8 all-of | `f1_eligibility` | every R1–R8 FAIL/UNKNOWN/missing-evidence mutation; stale config; hidden synthesis; search_pro default denial |
| SP1 S5; SP4 F2, F7–F8, F13 — resources, retries, failures, receipts | `ResourceLedger`, `validate_resource_receipt` | failed attempt spends one; rejection spends zero; manual retry spends new ticket; auto retry chain cannot reset; raw overrun retained; rehashed tampering rejected |
| SP1 S6; SP2 T1, T8 — one track, separate overlays | track enum, overlay validators, `compare_controls` | all eight tracks; arrays/unknown aliases rejected; Live/Frozen swap and cross-track aggregation rejected |
| SP1 S7; SP2 T9; SP3 A5/J6 — output/evidence/terminals | `OUTPUT_SCHEMA`, `validate_output`, `validate_record` | exact requested/resolved model identity; resource/entrant/spec binding; no quality score on infrastructure failures; all six terminal states distinct |
| SP1 S8; SP3 A2/J3/J9 — privacy and hidden provenance | strict public-safe inputs, `pool_candidates`, `judge_view` | secret/private-locator sentinels; allowlist metadata rejection; embedded source-label rejection; separate provenance ledger; no ledger in view |
| SP2 T2–T3, T7; SP4 F1, F5, F11 — variable attribution and claims | principal matrix, control fingerprints, track claims enum | fixed E2 control model required; changed F1 budgets rejected; F2 differing native stacks accepted; E2 cannot claim bare-model advantage |
| SP2 T9 — no silent substitution | exact identity fields, resource/output bindings and typed non-comparable contract | unresolved identity cannot yield comparable PASS/FAIL; receipt/entrant mismatch rejected; no fallback implementation exists |
| SP3 A1/J1 — deterministic pooling/dedupe/collision | `pool_candidates`, `validate_pool` | source/order-independent IDs; Unicode/whitespace normalization policy; union evidence; conflicting target identities => UNKNOWN_IDENTITY, never automatic merge |
| SP3 A3/J2/J4 — identical inputs and zero search | `judgment_contract`, `judgment_package`, `judge_view` | byte-identical views; candidate/rubric/evidence/order/resource/SearchSpec bindings; zero search/follow-link limits; re-sealed extra tool rejected |
| SP3 A4/J8 — frozen rubric/aggregation | rubric thresholds, satisfying values, UNKNOWN and predeclared tie policy | rubric mutation invalidates binding; hard constraint cannot be soft-accepted; aggregation preserves UNKNOWN/disagreement |
| SP3 A6/J5 — independent first pass | `JudgmentJournal` | peer-output field must be empty; one first pass per judge/candidate; all first passes before adjudication; no overwrite |
| SP3 A7/J7 — trigger-bound append-only adjudication | chained HUMAN_OVERRIDE records | all prior machine fingerprints retained; frozen evidence only; absent trigger, new evidence, stale chain or early override rejected |
| SP3 A8 — aggregation surface | frozen aggregation method/tie/UNKNOWN policy | no actual consensus/scoring algorithm or judge invocation implemented; policy mutation invalidates package |
| SP3 A9 — Live/Frozen evidence boundary | source overlay, capture/adjudication cutoff, corpus/reference identity | missing evidence; wrong corpus; source overlays bound inside judgment contract |
| SP3 A10; SP4 F9 — explicit metric population/denominator/missingness | metric definition, `metric_ratio` | missing component => UNKNOWN; zero denominator => NOT_EVALUABLE/null, never 0%/100% |
| SP3 A11/J1–J10 — hard integrity checklist | `integrity_gate` | each FAIL/UNKNOWN/missing-evidence check rejects; checklist entries are declarations, not independent verification of a real run |
| SP4 F4–F6 — search-credit and economic distinctions | integrated unit declaration, F2 disclosure, F3 package | raw-call/stack-invocation mismatch; required currency/price/credit/time policies; money/time rather than call-count alignment |
| SP4 F7–F8, F13 — missing cost and paid failure | raw per-class money/time/token fields, immutable event history | unknown cost never zero; failed paid spend retained; all caps/units checked; price-source evidence required for known F3 cost |
| SP4 F10 — capability-matched ablation | one-target plus non-target capability fingerprints | zero/multiple changed classes rejected; remaining components must be explicitly frozen |
| SP4 F11–F12 — population/fairness claims ceiling | limited claim enum; exact scope identity | live absolute recall denied without exhaustive reference; no universal champion claim or merged F1/F2/F3 score |
| SP1 S10; SP2 T10; SP3 A12; SP4 F14 — no authority escalation | always-closed T1 instance gate, no run CLI | no-I/O mocks; AST import checks; complete synthetic instance still BLOCKED; no official/private/live/provider/judge/credit use |

Resource accounting is a **pure reducer of supplied offline facts**, not a backend or physical budget-enforcing runner. It preserves failed/over-budget facts and refuses to publish a compliant receipt for them. The inherited physical SearchProxy remains unchanged and regression-tested. A future authorized runner must apply these contracts at its own actual I/O boundary.

Judgment transformations/record validation are **not judge execution**. No actual candidate is judged or scored. The synthetic first-pass records are test inputs. The provenance scanner checks structural fields and known supplied source labels, not arbitrary semantic stylometry; future instance review must validate real blinding integrity. Credential/private-locator scanning is bounded pattern/field detection, not a claim of universal DLP coverage.

## SP5 migration disposition implementation

REUSE means reuse of the approved primitive or invariant, not promotion of old scores. ADAPT means explicit successor semantics; it does not authorize every possible adapter/runner change in T1. HISTORY-ONLY objects never enter v2.3 execution/scoring authority.

| SP5 assets | Frozen disposition | T1 treatment |
| --- | --- | --- |
| P0-01 | REUSE | imports canonical JSON/fingerprint, adds strict finite-JSON admission |
| P0-02 | REUSE, public-safe input only | unchanged CandidateCard; not substituted for SearchSpec v2 |
| P0-03 | HISTORY-ONLY | CompetitionSpec v1 rejected by v2 parser; unchanged |
| P0-04 | REUSE | existing normalized request/result/trace contracts unchanged; references preserved in v2 evidence |
| P0-05 | ADAPT | separate v2 output/resource/spec/fairness bindings; no silent v1 Submission relabeling |
| P0-06, P0-07 | REUSE | physical proxy/isolation unchanged and regression-tested; T1 adds no executable tool/registry handles |
| P0-08, P0-09 | ADAPT | new protocol gate/judgment seams only; no v1 runner/judge rewrite or execution authority |
| P0-10, P0-11 | ADAPT | separate synthetic `v23_offline` CLI; old demo/CLI semantics unchanged |
| P0-12 | ADAPT | provider/model identity contract only; no provider selection/implementation |
| P0-13 | REUSE, fixture only | existing candidate retained but not selected or loaded by T1 probes |
| P0-14 | HISTORY-ONLY | historical competition fixture retained; parser rejection test only |
| P0-15, P0-16 | REUSE | existing P0/P1 contract/isolation/freeze/budget/secret regressions retained |
| P1-01..P1-04 | REUSE | proxy/provenance/budget/failure invariants preserved; independent v2 accounting adds required fields |
| P1-05, P1-06 | ADAPT / REASSIGN | search_pro source/old CLI unchanged; explicit NOT_F1_ELIGIBLE_BY_DEFAULT in new protocol |
| P1-07, P1-08 | HISTORY-ONLY | old live receipts and accepted-head publication remain history; not scoring inputs |
| P2-L01 | ADAPT | four-provider adapter concept deferred; no PR17 implementation imported |
| P2-L02, P2-L03 | REUSE semantic requirement | requested/resolved identity and endpoint/config evidence; no inherited endpoint/model values |
| P2-L04, P2-L05 | REUSE semantic requirement; carrier ADAPT | common inert tool/output contracts and v2 validation; no old Submission authority |
| P2-L06, P2-L07 | REUSE | typed infrastructure/non-evaluable results, no fabricated quality score, explicit retry accounting |
| P2-L08..P2-L10 | HISTORY-ONLY | no old roster/live receipt/Gemini HTTP400 promotion; no Gemini repair |
| C01, C03, C13..C20 | ADAPT carriers | no PR17 carrier copied, rebased or cherry-picked; relevant v2 requirements re-materialized in new modules only |
| C02 | ADAPT | fresh-main Test workflow extended for T1; no PR17 workflow delta imported |
| C04..C12 | HISTORY-ONLY | no PR17 README/methodology/privacy/architecture/fairness/gate text promoted as current authority |

This inventory covers P0-01..16, P1-01..08, P2-L01..10, C01..20. Existing files outside the T1 changed-path inventory remain untouched. The new conformance document is the required T1 receipt, not separate T8 publication or T9 cleanup.

## Return and unresolved items

The Draft PR carries the exact head, changed-path inventory and CI URL. The checked receipt is deterministic and therefore intentionally contains no mutable head/timestamp; CI binds its uploaded artifact to the head. `PASS` in that receipt means an offline contract check only, **not Board approval or downstream GREEN**.

D1–D8 remain deferred external instance choices: first track; task/SearchSpec; Judgment candidates/rubric; Frozen corpus/index; exact model/judge roster/config; real R1–R8 retriever evidence; numeric budgets; system/economic/ablation package. No real instance, real retriever neutrality, model resolution, cost, outcome or leaderboard is established by synthetic fixtures.

No live/paid model, provider, search or judge call; no GLM credits; no official competition prompt; no hidden registry/private judge; no Gemini compatibility repair/rerun; no T4/E1 instance execution; no P3/P4/P5 implementation; no PR17 mutation; no self-merge or self-declared downstream GREEN. Full regression retains only the repository's existing synthetic/mock tests; they are not private/official judge runs.

Next legal action: Board/Verification reviews this exact Draft PR and its offline evidence. T1 stops here. Any instance selection, real execution, adapter work, T4/T5/T6 or PR17 cleanup needs its own authorization.
