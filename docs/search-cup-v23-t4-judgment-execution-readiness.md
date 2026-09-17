# T4 JE0 — Judgment execution readiness and fixture semantics

Work order: `WO-ENG-B1-SC-V23-T4-JE0 v0.1`.

Status: **READINESS CANDIDATE / INDEPENDENT ACCEPTANCE PENDING / NO FORMAL EXECUTION**.

T4 froze two synthetic judge identities without executable behavior. JE0 adds a
distinct successor execution binding whose deterministic behavior is explicit
before any future replay. This is synthetic protocol validation, with no model
quality, benchmark, leaderboard or real-world opportunity claim.

## Source and scope

- Fresh baseline: `82fcbe64027d94e0b5115d2ef412000c004c32e2`.
- Baseline tree: `1321e37917e69472586517628aa18e4c5e97e074`.
- Accepted parent: `T4-JUDGMENT-PV-001`, PR #58.
- Accepted reviewed head: `4ff845a2b15166175c0eb01d03a2ebe770f6ba2e`.
- Parent artifact: `10448455537`.
- Parent artifact digest: `sha256:cde541471a561353c3419086db467c560c5f59a3be4dc612cecb125e84eaf4be`.
- Successor: `T4-JUDGMENT-PV-001-EXEC-V1`, version `1`.
- Mode: `OFFLINE_FIXTURE_PROTOCOL_VALIDATION`.

Exactly four new paths implement this work order: the JE0 module, its focused
tests, this document, and its dedicated offline workflow. The accepted T4
module/tests/docs/workflow, SP3 core, protocol core, provider/search paths,
ordinary Test workflow and PR #17 lineage are unchanged.

`PARENT_HASHES` pins the complete canonical bytes of the accepted manifest,
Judgment package, candidate pool, evidence packet, rubric, adjudication policy,
SearchSpec, D5 roster, instance bindings, resource envelope and blind input.
The parent artifact ID/digest is a lineage pin from its GitHub metadata; the
offline module does not download an artifact. Parent drift fails closed.

## Frozen behavior

Each profile is an explicit lookup table over the exact frozen blind package.
It binds the candidate identity and candidate bytes to dimensions, confidence,
frozen evidence references and reason codes. The input must be canonical JSON
with the accepted blind-input SHA-256. Unknown candidates, extra fields,
new evidence and unrecognized profile semantics are rejected.

| Synthetic case | Remote eligibility | Actionability | Frozen state |
| --- | --- | --- | --- |
| Alpha | YES | YES | ACCEPT |
| Beta | NO | UNKNOWN | UNKNOWN |
| Gamma | UNKNOWN | UNKNOWN | UNKNOWN |

Beta is explicitly on-site. Its frozen evidence does not establish application
status or compensation. The accepted SP3 implementation rejects *both* ACCEPT
and REJECT records with any hard-constraint UNKNOWN. JE0 therefore preserves
Beta's unresolved actionability and returns UNKNOWN. It does not invent an
actionability=NO fact to obtain a desired negative example. REJECT remains a
distinct, tested schema state; the frozen T4 fixtures need not exercise every
state. A different hard-failure precedence rule would require a separate SP3
scope decision; JE0 does not alter that rule.

Both aliases use these dimensions and states. Fixture A assigns confidence
0.95 to ACCEPT and 0.5 to UNKNOWN; fixture B assigns 0.9 and 0.25 respectively.
These are explicit synthetic constants for protocol testing, not empirical
calibration or estimates of real-world truth. Neither profile reads the other
profile's output. `fixture_decision(blind_bytes, profile, candidate_id)` has no
peer, environment, source ledger, tool, network or journal parameter.

The profiles are sealed separately and their fingerprints are included in the
successor binding. Each successor roster entry keeps its accepted alias,
synthetic model identity and NOT_CONNECTED endpoint, while deriving a new
configuration fingerprint from the parent identity, execution ID and profile.
The accepted D5 roster is never overwritten.

## Future first-pass contract

The plan contains exactly two judges by three candidates, six planned entries,
ordered by judge alias and then `CANDIDATE_ID_ASC`. Both judges receive exactly
the same canonical `blind-input.json` bytes. The roster, parent lineage, plan
and audit metadata are not part of that judge-visible input.

The run namespace is:

```text
T4-JUDGMENT-PV-001-EXEC-V1:<full-execution-binding-SHA256>:JE1-001
```

Every planned entry has `observed_peer_records=[]` and permits only the
candidate's frozen evidence. It has no decision state or commit timestamp and
is marked `PLANNED_NOT_EXECUTED`. Profile changes alter the binding fingerprint
and therefore the run namespace. `validate_bundle` requires a separately
retained review fingerprint and rejects resealed mutations too.

`validate_planned_record` validates a supplied record against the inherited
SP3 schema plus the exact successor run, record ID, roster and behavior table.
It does not produce or commit a record. The inherited `JudgmentJournal` forbids
first-pass replacement, requires all six first passes before HUMAN_OVERRIDE,
preserves all machine records, and checks the append-only override hash chain.
Future JE1 must use both record validation and the journal, and independently
verify the accepted review pin. JE0 supplies no execute command or authorization
toggle. Formal execution remains blocked.

## J1–J10 evidence plan

| Gate | Required future evidence |
| --- | --- |
| J1 | Accepted candidate-set pin and first-pass journal match |
| J2 | Identical rubric/evidence bytes and ordering delivery digests |
| J3 | Blind-input leakage audit |
| J4 | Zero search/live retrieval/follow-link/tool receipt |
| J5 | Six independent commits before any synthesis |
| J6 | Typed-state validation preserving UNKNOWN and non-evaluable states |
| J7 | Auditable append-only override chain and original records |
| J8 | Pre-output aggregation pin |
| J9 | Input-delivery audit excluding provenance ledger |
| J10 | Identical start/end parent, behavior, roster and successor pins |

The artifact records every gate as `NOT_RUN`. Future PASS requires all ten
checks to be PASS with nonempty evidence; a failed check or missing evidence
yields NOT_EVALUABLE. Unit-test gate probes are not post-run evidence.

## Build and verify

The dedicated workflow requires only the Python standard library and checks
out the exact PR head, rather than the synthetic merge ref.

```bash
python -m unittest discover -s tests -p 'test_search_cup_v23_t4_execution.py' -v
python -m search_cup.v23_t4_execution bundle --output-dir /tmp/je0-new-directory
python -m search_cup.v23_t4_execution receipt
```

The output directory must not already exist. This prevents old judgment files
from being retained in a new readiness artifact. The eight canonical files are:

- `parent-binding.json`
- `blind-input.json`
- `fixture-profiles.json`
- `execution-roster.json`
- `execution-binding.json`
- `first-pass-plan.json`
- `integrity-plan.json`
- `receipt.json`

CI adds `focused-tests.log`, `ci-source.json` and `MANIFEST.sha256`, then uploads
`search-cup-v23-t4-je0-readiness-<exact-head-SHA>` using immutable artifact v4.
The source receipt verifies exactly four added paths against the fresh baseline
and records head/tree, focused-test count and binding fingerprint. The ordinary
Test workflow remains the full-repository regression gate.

Focused tests include parent/profile/roster/candidate/rubric mutations, exact
six-record cardinality, byte stability, peer/evidence injection, all six typed
states, overwrite rejection, every incomplete override barrier, append-only
chains, every failed or unevidenced J gate, provenance exclusion and capability
traps on authoring. Test records exist only in memory within the test suite.

## Receipt meaning and exit

The authoring path performs zero fixture decision calls, provider calls, search
calls, network calls, follow links, retries, credential reads, credit use and
spend. External tools are empty. Official prompt and hidden registry are not
loaded; `formal_record_count=0`, `formal_execution_performed=false` and
`execution_allowed=false`.

These counters describe the JE0 authoring path. GitHub checkout, dependency
installation for repository regression tests and artifact transport are
engineering infrastructure, not judge execution; they are not claimed to have
zero network traffic. The inherited public-safe synthetic provenance ledger
may be constructed internally by the unchanged parent builder, but no ledger
is exported to the JE0 artifact or passed to fixture behavior.

Return the Draft PR, exact head/tree, CI receipts, artifact ID/digest and
successor fingerprints for independent Board/Verification. JE0 acceptance is
pending that independent decision even after engineering tests pass.
**Keep Draft and stop. JE1 replay and merge require separate authorization.**
