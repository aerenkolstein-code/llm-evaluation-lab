# T5 E1 Frozen execution readiness (EX0)

Work order: `WO-ENG-B1-SC-V23-T5-E1F-EX0 v0.1`.
The pre-construction instruction in the development conversation was
`WO-ENG-B1-SC-V23-T5-E1F-EX0 v0.1批准并施工`.
It authorizes these four new paths and offline readiness authoring. Independent
acceptance is **PENDING**; merge and formal execution are not authorized.

The accepted T5 parent freezes the instance but not entrant behavior. EX0 adds a
separate deterministic successor binding: `T5-E1FROZEN-PV-001-EXEC-V1`, mode
`OFFLINE_SYNTHETIC_E1_FROZEN_PROTOCOL_VALIDATION`, class
`SYNTHETIC_FIXTURE_REPLAY`. Its claim ceiling is
`E1_FROZEN_SYNTHETIC_PROTOCOL_VALIDATION_ONLY`. These fixtures are local programs,
not models; readiness supplies no benchmark, model-quality or live-web result.

## Publication and scope

| Identity | Exact value |
|---|---|
| Approved main | `a583f6042dbfd78d251434141cdbf9b86cb910a9` |
| Approved tree | `669c6cb0785aaa5cead04d0b009c14f70a7d98af` |
| Parent | `T5-E1FROZEN-PV-001` |
| Parent core package | `dd4742c12343b602a1f755093cc7267b442fae2fa5cbb96570f7a5107bd227bf` |
| Parent receipt | `eac316a162a46561f0856dc881b229cca94b930e184ffa0c35efd58ea3973b20` |
| Accepted parent artifact | `10543468788` |
| Parent artifact ZIP SHA256 | `7781d887f52475c390820dbe74acb6efbf7044950242271296a0d39fdf70e010` |
| Runtime | Python 3.11 / Unicode 14.0.0 |

Exactly four additions are permitted:

- `search_cup/v23_t5_e1f_execution_readiness.py`
- `tests/test_search_cup_v23_t5_e1f_execution_readiness.py`
- `docs/search-cup-v23-t5-e1f-execution-readiness.md`
- `.github/workflows/t5-e1f-execution-readiness-offline.yml`

All existing files, including the T5 parent, retriever, qualification, protocol,
schemas, tools, T4 lineage, runner, judge, providers and ordinary Test workflow,
remain byte-identical. Dedicated full-history CI checks the approved base/tree,
ancestry, exactly four additions, exact PR head and clean checkout. The authoring
module does not itself run Git; caller-supplied baseline strings are not a fresh
Git observation. The CI provenance records that independent observation.

## Entrant-visible semantics

`visible_decision(SearchResult)` is a pure transform of **title, url, snippet**.
It accepts no profile, context handle, reference, peer, filesystem, environment,
tool or provider argument. Tests inspect its closed global dependency set and
exercise it with synthetic in-memory records only. This is audited pinned Python
code, not a sandbox for hostile programs.

Both profiles commit to the same `shared-decision-policy.json`, which contains
every exact positive and negative phrase from the work order. Matching uses a
case-sensitive literal substring within each field separately; it performs no
case folding, punctuation removal, Unicode normalization, cross-field joining,
paraphrase inference or missing-evidence repair. Consequently the retriever's
normalization must not be reused as the visible truth classifier.

| Positive phrase | Negative phrase | Predicate result |
|---|---|---|
| Present | Absent | TRUE |
| Absent | Present | FALSE |
| Absent | Absent | UNKNOWN / INSUFFICIENT_VISIBLE_EVIDENCE |
| Present | Present | UNKNOWN / CONTRADICTORY_VISIBLE_EVIDENCE |

Return a match only when all three predicates are TRUE. Any FALSE rejects the
document; otherwise UNKNOWN rejects it. A FALSE on another predicate still
rejects a record containing a contradiction. Matching phrases are retained as
visible reasons, not hidden-reference labels.

| Query | Fixture A: BROAD_DECOMPOSED_QUERY_V1 | Fixture B: SYNONYM_SWEEP_QUERY_V1 |
|---|---|---|
| 1 | `remote work` | `working from home python mandatory accepting applications` |
| 2 | `python required` | `fully remote python recruitment open` |
| 3 | `applications open` | `telecommuting python required applications accepted` |
| 4 | `remote python applications open` | `home-based python recruiting open` |

Aliases remain `t5-fixture-agent-a` and `t5-fixture-agent-b`, with the original
synthetic-not-connected parent identities. All queries are fixed before STARTED;
no query adaptation or peer access is permitted. Results are deduplicated by
exact frozen URL/doc ID, retaining first query order and then rank. Conflicting
content for the same identity is a typed protocol failure, not a merge rule.
The final order is this union filtered by the shared policy. EX0 never invokes
either profile or calls the retriever/proxy.

## Future resource and reference boundaries

Each entrant receives a fresh `BudgetedSearchProxy` with four tickets. No tickets,
traces, peer query/result/output or mutable state are shared. Each has four turns,
ten results per call, zero follow links, zero automatic/manual retries, no
fallback, 1000 ms per call, 60000 ms total, 8000 tokens and USD 0. Rejected
pre-backend calls use no backend and no ticket. The existing proxy enforces its
ticket limit; a later executor must enforce and receipt all other ceilings.
Unmeasured consumption cannot be silently declared zero or comparable.

The frozen future order is A then B, with two submissions, at most eight backend
attempts and 80 result rows. Failures stop, preserve the partial record and yield
NOT_EVALUABLE; missing submissions or metrics must not be invented.

The reference barrier requires both distinct exact-run submissions to be
durably committed: output fsync, atomic commit, directory fsync and hash-linked
commit receipt. Only then may the adjudicator join hidden labels. Fixture code
never receives them, including after the barrier. EX0's author-side validation
reconstructs the accepted parent to verify its seals; that identity check is not
entrant input or a future formal replay. A later executor must maintain this
separation and must not call the authoring loader inside fixture behavior.

## Immutable package and output schemas

The core bundle contains 11 sealed JSON payloads and `MANIFEST.sha256`:
parent binding, execution binding, two profiles, shared policy, query plan,
future run plan, environment recheck, resource plan, integrity plan and receipt.
The execution binding commits all nine independent components and the exact
implementation SHA256. The receipt is derived and separately sealed; validation
rebuilds it rather than trusting mutable counters. Components contain a run-ID
template to avoid a fingerprint cycle. The receipt resolves the complete ID:

```text
T5-E1FROZEN-PV-001-EXEC-V1:<execution-binding-fingerprint>:E1F-001
```

Every component seal is exposed in the binding and receipt. Later acceptance and
execution must pin the full binding fingerprint from independently retained
review authority. Rehashing an edited package does not make it acceptable.

`future-run-plan.json` freezes JSON Schema contracts for preflight, run-start,
both entrant outputs, query/result JSONL provenance, resource receipts,
hidden-reference barrier audit, adjudication, metrics, integrity checks,
run-end and post-run receipt, plus final byte-manifest semantics. None of those
formal run files are emitted by EX0. `MANIFEST.sha256` is also the conventional
name of the readiness package's own manifest; it is not a run output.

The parent output schema remains untouched. A new outer execution envelope
supplies run ID, binding, entrant alias and the complete sealed resource receipt
around the exact parent submission. Cross-record checks require agreement of
alias, namespace, call/request/backend/rank, URL/doc ID, evidence locator,
submission and resource fingerprints. Preflight/start/end require the complete
named pin set. Schema shape alone is not proof of these relationships.

The parent metric definitions are copied unchanged into the future plan.
UNKNOWN labels remain separate; they are excluded from binary truth
denominators without backfill. Zero denominators are NOT_EVALUABLE. No metrics
are computed in EX0.

| Gate | Required future evidence |
|---|---|
| I1 | Unchanged complete parent identity |
| I2 | Exact runtime, F1 descriptor and configuration |
| I3 | Equal independent resource envelopes and receipts |
| I4 | Exact profiles, literal policy and query schedule |
| I5 | Both durable commits before the first reference load |
| I6 | No peer state or reference-bearing fixture context |
| I7 | Complete typed query, result and final evidence provenance |
| I8 | Visible TRUE/FALSE/UNKNOWN and contradictions preserved |
| I9 | Zero external/model/provider/live/network/credential/follow/fallback/spend; no official prompt or registry |
| I10 | Identical complete immutable pins at start and end |

All ten are **NOT_RUN**, with empty actual evidence, in EX0. A later comparable
PASS requires all ten PASS with nonempty resolvable actual evidence for that
exact run. A plan, asserted PASS, missing evidence or UNKNOWN gate is insufficient.

## Reproduction and checks

Use Python 3.11 / Unicode 14.0.0. These commands author or validate readiness only:

```sh
python -m unittest discover -s tests -p 'test_search_cup_v23_t5_e1f_execution_readiness.py' -v
python -m search_cup.v23_t5_e1f_execution_readiness bundle \
  --expected-source-sha a583f6042dbfd78d251434141cdbf9b86cb910a9 \
  --expected-source-tree 669c6cb0785aaa5cead04d0b009c14f70a7d98af \
  --output /tmp/t5-ex0-new-directory
python -m search_cup.v23_t5_e1f_execution_readiness validate \
  --expected-source-sha a583f6042dbfd78d251434141cdbf9b86cb910a9 \
  --expected-source-tree 669c6cb0785aaa5cead04d0b009c14f70a7d98af \
  --expected-fingerprint FULL_INDEPENDENTLY_RETAINED_BINDING_HASH \
  --output /tmp/t5-ex0-new-directory
```

The CLI has only `receipt`, `bundle`, `validate`; no execute/replay command.
It refuses an existing output directory. Validation checks all canonical seals,
exact rebuilt content, retained review pin, full file set and byte hashes;
symlinks and unexpected files are rejected.

The dedicated PR-only workflow checks out the exact head with full history,
runs the focused tests, builds twice with byte identity, checks all parent and
successor pins, and verifies the zero-execution receipt. It adds `ci-source.json`
and `focused-tests.log`, yielding **13 manifest entries / 14 archive files**, and
uploads one artifact named `search-cup-v23-t5-e1f-ex0-<full-head-sha>`.
It has read-only contents permission, no secret input or manual dispatch.
Checkout/setup/Git/artifact transport are CI infrastructure, not formal execution.

Ordinary Test remains unchanged. Its shallow PR-merge checkout skips the existing
parent historical seven-addition scope test; the dedicated EX0 full-history
workflow proves the successor's four-addition scope. Ordinary legacy regression
queries and local API smoke tests remain separate from the EX0 zero-call receipt.

The developer handoff records exact base/head trees, all four paths, focused and
ordinary/dedicated CI results, artifact ID/digest, each requested component
fingerprint and the complete planned run namespace. Formal E1_FROZEN execution
is **NOT PERFORMED**, independent acceptance remains **PENDING**, and merge is
**NOT AUTHORIZED**. A separate accepted executor and execution authority are
required after EX0 acceptance/publication.
