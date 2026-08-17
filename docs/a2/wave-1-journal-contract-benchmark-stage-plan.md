# A2 Wave 1｜Journal / Contract Benchmark Stage Plan

**Status:** BOARD REVIEW / PLAN ONLY / NO IMPLEMENTATION AUTHORIZATION  
**Primary repo:** `aerenkolstein-code/llm-evaluation-lab`  
**A1 dependency:** `aerenkolstein-code/Companion-Mind` Issue #11 / Gate P0  
**Scope:** A2 Day-1 Journal / Contract benchmark planning only

## 1. Authority and stage boundary

This plan is governed by:

- `CM-MASTER-CONSTRUCTION v1.0`, which places A2 Journal / Contract benchmarking in Wave 1 and defines Gate E1｜Durability as the gate before higher A1 product runtime;
- `A023 Engineering Portfolio Child Plan v1.0`, which defines A1 as the system owner, A1-D as A1's first Durable Journal substage, and A2 as the independent measurement line;
- the merged legacy A-line reconciliation in PR #15, including its ownership split, reusable evaluation controls, and `CAN-RUN-NOW` / `WAIT-P0` / `WAIT-LATER-A1` gates;
- Companion-Mind Issue #11, the current hard Gate P0 and future unique engineering authority for the Canonical Event / RAW boundary after review and merge.

This document authorizes no implementation. It does not migrate legacy A-line code or tests, copy A1 runtime authority, invoke a live or paid model, rerun PR #8 / ENG-DIAG-03, enter Search Cup P2, or begin A1 Phase 1+.

## 2. Stage objective

Wave 1 gives the first A1-D candidate an independent, public-safe and reproducible answer to one question:

> Through A1's published boundary, does the Journal preserve what happened without loss, reordering, duplicate amplification, destructive correction, secret leakage, or semantic collapse across crash and restart?

A2 will prepare a Day-1 skeleton that can exist before P0 without guessing the future A1 schema. Once P0 is GREEN and a separately authorized implementation ticket exists, A2 binds that skeleton to the versioned A1 seam and evaluates only externally observable behavior.

## 3. Day-1 test skeleton

### 3.1 Goal

The Day-1 skeleton freezes case identities, expected invariants, metric names, verdict rules, evidence fields, and gate status before a Journal implementation is evaluated. It makes failures reproducible and comparable while keeping A1 implementation choices opaque to A2.

### 3.2 In scope

- synthetic/public-safe case families for text, structured payloads, attachment references, `complete / partial / failed`, duplicates, order perturbations, correction chains, synthetic secret sentinels, and the four UNKNOWN states;
- a contract-neutral case envelope whose A1 payload remains opaque until Gate P0 publishes the actual schema;
- deterministic manifest identity: case-set version, ordered case IDs, seed where relevant, fixture fingerprints, expected oracle version, A1 contract version when available, and A1/A2 commit identities;
- black-box observation records containing submitted input identity, observable acknowledgement/export/replay identity, status, fingerprints, metric outcomes, and terminal reason;
- evidence-registry fields and fail-closed validation;
- explicit `CAN-RUN-NOW`, `WAIT-P0`, and `WAIT-A1-D-CANDIDATE` markers so a placeholder can never be reported as a pass.

### 3.3 Out of scope

- Companion-Mind imports, runtime classes, persistence code, storage layout, prompt construction, observer/reducer behavior, or Persona/Relationship state;
- an A2 copy of the Canonical Event schema or any provisional substitute for Issue #11;
- real conversation bodies, private archive locators, credentials, or production secrets;
- provider/model quality scoring, live calls, paid calls, or longitudinal Persona/Relationship evaluation;
- migration or execution of legacy PR #4/#5/#7/#8 code, tests, workflows, corpora, or keys.

### 3.4 Planned skeleton inventory

These are future deliverables, not files created by this planning PR:

1. a public-safe rubric defining the eight Journal invariants and zero-tolerance failures;
2. a synthetic case catalog with stable case IDs and coverage tags;
3. a case-manifest contract for deterministic order and fingerprints;
4. an evidence-registry contract for immutable run/result lineage;
5. an offline runner shell with no provider dependency and an unbound A1 adapter port;
6. a Gate E1 report template with separate A1 conformance and A2 black-box receipts.

## 4. Evaluation metrics and oracles

All counts below are evaluated over the manifest's expected event set. Zero-tolerance invariants are not averaged into a weighted score. A missing required observation is `NOT EVALUABLE`, never an implicit pass.

| Dimension | Black-box metric / oracle | Gate-E1 pass condition | Required evidence |
|---|---|---|---|
| Durability | acknowledged user-event loss count; terminal assistant-event loss count; payload/status fingerprint mismatch count; canonical/replica mismatch count | All counts are `0` across at least 100 synthetic turns; every acknowledged event remains observable after the applicable recovery/readback boundary | Manifest and fixture fingerprints; acknowledgement receipt; pre/post export or replay fingerprints; replica readback receipt |
| Ordering | sequence inversion count; nondeterministic replay count; gap classification accuracy | `0` inversions and `0` replay divergence; a declared gap is not silently treated as reordering or filled data | Expected ordered IDs; observed ordered IDs; repeated replay fingerprint; explicit gap receipt |
| Dedupe | duplicate amplification count; duplicate-detection miss count; idempotent replay divergence count | All counts are `0` for exact duplicates and the duplicate classes defined by the P0 contract; replay does not create an additional canonical event | Submission/attempt ledger; A1-defined identity/dedupe key version; canonical event IDs before/after replay |
| Crash recovery | acknowledged-event loss; phantom completion; post-crash duplicate; recovery divergence | `0` for every A1-declared fault point; incomplete work remains `partial` or `failed` as required by the contract and is never promoted silently to `complete` | Fault-point ID; last acknowledged identity; recovered ordered IDs/statuses; recovery fingerprint and terminal reason |
| Restart recovery | event-set drift; order drift; identity drift; status/payload drift after a clean process restart | All drift counts are `0`; repeated restart/replay yields the same ordered IDs and content/status fingerprints | Pre-restart receipt; post-restart receipt; deterministic comparison result |
| Correction | destructive-overwrite count; broken `correction_of` reference count; correction-graph replay divergence | All counts are `0`; the original event remains present, the correction is a new append-only record, and the same correction graph replays deterministically | Original/correction IDs and fingerprints; reference validation; graph fingerprint before/after restart |
| Secret | unredacted synthetic-sentinel leak count; forbidden secret-field persistence count; evidence-registry leak count | All counts are `0`; every synthetic secret-like input is rejected or represented with the redaction state required by the P0 contract; no real secret is used | Sentinel inventory fingerprint; sanitized observable record; repository/evidence scan receipt |
| UNKNOWN | semantic-collapse count across `UNKNOWN`, `KNOWN_EMPTY`, `N/A`, and `NOT_LOOKED_UP`; false-negative inference count | All counts are `0`; each state survives the supported round trip distinctly, and missing Journal evidence is not emitted as a negative Current fact | Four-way fixture IDs; expected/observed semantic labels; round-trip fingerprint; boundary verdict |

Metric interpretation constraints:

- A2 does not define the canonical dedupe key, acknowledgement point, serialization, fault points, recovery envelope, or redaction mechanics. Those come from A1's versioned contract and test surface.
- `complete`, `partial`, and `failed` are distinct observable states. A transport/runtime failure is not converted into a behavioral score.
- Drive is an asynchronous replica, not a second Journal authority. A1 must publish the replica/readback completion condition; A2 then measures exact observable agreement within that declared envelope.
- Journal correction evidence does not authorize A2 to compute or mutate Current, Memory, Persona, or Relationship truth.

## 5. A1 conformance versus A2 black-box evaluation

| Concern | A1 internal conformance responsibility | A2 black-box evaluation responsibility |
|---|---|---|
| Contract ownership | Publish and version the one Canonical Event / RAW schema and adapter boundary; validate production serializers/adapters | Pin the published version; validate A2 fixtures at the public seam without copying the schema into A2 authority |
| Durability mechanism | Implement and prove USER-before-provider append + fsync, local canonical persistence, commit/ack semantics, and Drive replica/readback | Compare acknowledged inputs with observable export/replay/readback outcomes; report loss or mismatch without inspecting storage internals |
| Order and identity | Define stable identities, sequence rules, dedupe identity, and internal conformance tests | Submit controlled permutations/duplicates and score only observable IDs, order, and idempotence |
| Crash/restart | Own fault injection hooks, storage lifecycle, recovery algorithm, and internal crash-safety tests | Use only the sanctioned test surface; compare pre/post observable event sets and fingerprints |
| Correction | Own append-only representation and any product-side resolution rules | Verify original preservation, valid reference, and deterministic Journal replay; do not judge Current projection |
| Secret boundary | Own rejection/redaction before persistence and ensure real secrets never enter fixtures | Use synthetic sentinels and verify that no forbidden value appears in outputs, receipts, or evidence |
| UNKNOWN | Own canonical representation and prohibit unauthorized authority mutation | Verify four-way semantic preservation and absence-of-evidence handling at the public boundary |
| Verdict | Provide versioned A1 conformance receipts tied to a commit and contract | Produce independent manifest-bound A2 results and the Gate E1 black-box verdict |

Neither lane substitutes for the other. A1 tests answer whether its implementation conforms internally; A2 answers whether a consumer sees the promised behavior. A2 does not certify A1 internals, and A1 cannot self-declare the independent A2 benchmark passed.

## 6. Gate routing

### 6.1 CAN-RUN-NOW after a separate A2 authorization

The following work has no A1 contract dependency and may be prepared while Issue #11 remains open:

| Asset | Allowed now | Boundary |
|---|---|---|
| Public-safe rubric | Define the eight observable dimensions, zero-tolerance hard failures, `PASS / FAIL / NOT EVALUABLE / BLOCKED` semantics, and claims limits | No A1 field names, storage assumptions, or internal assertions |
| Synthetic case catalog | Define stable case IDs, scenario prose, expected invariant, coverage tags, and synthetic content for order/duplicate/status/correction/secret/UNKNOWN families | A1 payload stays opaque/unbound; no private or legacy corpus body |
| Manifest design | Define case-set/order/seed/fingerprint and source-version fields | No provider configuration or live execution path |
| Evidence-registry design | Define immutable run/result IDs, expected/observed fingerprints, terminal reason, contract version placeholder, A1 receipt reference, and A2 verdict | No secrets/private bodies; legacy PR #5/#8 aggregate records remain link-only until the Board resolves retention |
| Static review pack | Trace every planned case to an invariant, owner, gate, and required receipt | Review evidence is planning evidence, not E1 execution evidence |

`CAN-RUN-NOW` means dependency-safe, not automatically authorized by this plan.

### 6.2 WAIT-P0

The following must not begin until Issue #11 is reviewed, merged, and Gate P0 is explicitly GREEN:

- pinning/importing the real Canonical Event schema or typed contract;
- mapping case envelopes to canonical fields and statuses;
- validating A018/A019/A020 adapter outputs against the shared schema;
- implementing or executing A2 adapter-compatibility checks at the A1 seam;
- asserting A1-defined identity, sequence, dedupe, provenance, redaction, or UNKNOWN encoding;
- creating compatibility mappings for legacy runtime-v1/runtime-v2.

### 6.3 WAIT-A1-D-CANDIDATE

Even after P0 GREEN, the following runtime evaluation waits for a separately authorized A1-D candidate and sanctioned black-box test surface:

- actual Journal append/ack/export/replay evaluation;
- 100+ turn durability, order, and dedupe execution;
- crash injection and restart recovery evaluation;
- local durable-store and Drive replica/readback comparison;
- Gate E1 execution and final verdict.

Live/provider studies remain `WAIT-LATER-A1` and require separate Board, cost, secrets, and stop-condition authorization.

## 7. Gate E1｜Durability acceptance standard

Gate E1 may be declared GREEN only when all conditions below are met:

### 7.1 Preconditions

- Gate P0 is explicitly GREEN and the evaluated contract version is pinned.
- A1-D supplies a commit-pinned candidate plus a documented, sanctioned offline test surface.
- The A2 manifest contains at least 100 synthetic turns and covers all eight dimensions in Section 4, including distinct `complete / partial / failed` outcomes.
- No private corpus, real secret, live model, or paid provider is involved.

### 7.2 A1 conformance evidence

A1 provides GREEN, commit-pinned receipts for its own responsibilities, including USER-before-provider fsync, stable identity/order/dedupe rules, append-only correction, crash/restart recovery, local canonical storage, Drive replica/readback, status handling, secret exclusion, UNKNOWN semantics, provenance, and the authority boundary.

### 7.3 A2 black-box evidence

- `0` loss, disorder, duplicate amplification, payload/status drift, destructive overwrite, secret leak, and UNKNOWN semantic collapse;
- every declared crash point and clean restart case produces the expected observable status and deterministic recovered event set;
- canonical Journal and completed Drive replica/readback agree exactly for the evaluated manifest within A1's declared completion envelope;
- two executions of the same offline manifest produce the same normalized result fingerprint, excluding explicitly declared run-identity timestamps;
- every required evidence-registry field is populated with content-free/public-safe receipts and immutable fingerprints.

### 7.4 Verdict rule

E1 is an all-of gate, not a score average. Any zero-tolerance failure makes E1 `FAIL`; any missing contract, candidate, receipt, required observation, or supported test hook makes it `BLOCKED` or `NOT EVALUABLE`, never GREEN. Both the A1 conformance receipt and the independent A2 black-box receipt are required. Only after Board/Verification accepts E1 GREEN may higher A1 product runtime seek separate authorization.

## 8. Minimal implementation order after P0 GREEN

This is dependency order, not authorization to start:

1. **Contract intake:** verify P0 GREEN, pin the merged A1 contract/schema version and commit, and record the public seam without copying A1 authority.
2. **Skeleton bind:** map the already-reviewed public-safe case envelopes to the published fields/statuses; keep all A1 implementation details opaque.
3. **Adapter compatibility:** validate synthetic A2 inputs and A018/A019/A020-shaped outputs against the one A1 conformance target; stop on any schema/authority mismatch.
4. **Minimum Journal smoke:** exercise text/structured payload, attachment provenance, `complete / partial / failed`, correction, secret sentinel, and four-way UNKNOWN through the sanctioned offline surface.
5. **Deterministic 100+ turn batch:** evaluate durability, ordering, dedupe, identities, replay, and manifest reproducibility before fault injection.
6. **Fault lifecycle:** run A1-declared crash points, then clean restart/reopen cases; compare observable pre/post IDs, order, status, payload, and correction-graph fingerprints.
7. **Replica/readback:** after A1's declared completion condition, compare local canonical export with Drive replica/readback and record any lag or mismatch without treating Drive as authority.
8. **Evidence and Gate E1:** seal the evidence registry, obtain the distinct A1 and A2 receipts, issue `GREEN / FAIL / BLOCKED / NOT EVALUABLE`, and STOP for Board acceptance.

No step invokes a live/paid model, reuses PR #8 execution authority, enters Search Cup P2, or authorizes A1 higher runtime.

## 9. Stage exit

This planning stage exits when the Board accepts or revises:

- the Day-1 skeleton boundary;
- the eight metric/oracle definitions;
- the A1/A2 responsibility split;
- the `CAN-RUN-NOW` and wait lists;
- the Gate E1 all-of acceptance rule;
- the post-P0 minimum order.

After this docs-only plan is submitted for review, A2 stops. Implementation requires a separate accepted work order.
