# PR #37: Four-Round Independent QA Retrospective

PR #37 built the one-shot manual-only R1b live-orchestration lane. It took three Independent QA failures before the fourth review passed.

That sequence is useful because the failures were not ordinary implementation mistakes. Each review exposed a deeper protocol invariant:

```text
approved values must not drift
→ execution identity must not rebind
→ crash/restart must not reopen execution authority
```

The final result was merged as `74304a23d7e542b28dcd519f9b58d394447fc696`.

## Review progression

| Round | Exact reviewed head | Verdict | Core finding |
|---|---|---|---|
| 1 | `9c8808758354cbad5a2b1408a2e8797122652319` | FAIL | The approved RUN-READY object did not machine-bind provider/model/endpoint/runtime values to the actual provider gate. |
| 2 | `8533de8e0abcfe35de9e1e0aa3101db80e58aee5` | FAIL | Provider/runtime binding was fixed, but the same approval could still be rebound to another dispatch/run identity. |
| 3 | `32a411973895657c994e5a63673ad5533b3096fa` | FAIL | The normal-path one-shot identity was fixed, but its two durable identity indexes were not crash-atomic. |
| 4 | `19b13961daf403b727c88e9d0aa28b7684e064c4` | PASS | A single authoritative durable claim boundary plus restart recovery closed the crash/replay window. |

PR: [#37](https://github.com/aerenkolstein-code/llm-evaluation-lab/pull/37)

## Round 1 — A receipt is not an authority unless execution derives from it

The first candidate already had many reassuring properties:

- exactly the approved changed paths;
- `workflow_dispatch` only;
- no automatic live execution from PR/push CI;
- provider-secret use after the handoff acknowledgement gate;
- one provider invocation path;
- `automatic_retries = 0`;
- deterministic no-provider smoke and full-suite CI green.

Remote evidence included:

- no-provider smoke run `33937532372`;
- full Test run `33937532379` with 255 tests.

Independent QA still rejected the design.

The approved RUN-READY digest and authorization ID were checked, but the actual provider label, requested model, endpoint, timeout, temperature, and token limit remained independent environment variables. The workflow did not reconstruct the approved canonical receipt and prove that the execution-critical values were exactly the reviewed values.

The system could therefore satisfy the approval check while executing a materially different request.

### Lesson

An approval artifact must be executable authority, not documentary evidence.

A safer chain is:

```text
canonical approval object
→ canonical bytes + digest
→ strict parse and reconstruction
→ exact equality
→ runtime derivation
```

Execution-critical values should not be overridable by an independent source after approval.

## Round 2 — One-shot authorization is an identity property, not a button-click property

The second candidate closed the Round-1 value-binding problem. The workflow now strictly decoded, hashed, parsed, reconstructed, and byte-compared the canonical RUN-READY object before exchange, secret, or provider access.

Remote evidence included:

- no-provider smoke run `33939042443`;
- full Test run `33939042467` with 260 tests.

Independent QA found a different issue: the approval still did not bind the complete one-shot execution identity.

The approved object did not fully bind the R1b run/handoff identity, while an expected workflow-run ID remained outside the hashed approval object. A second manual dispatch could move both the real GitHub run ID and the external expected value together while reusing the same approved receipt and authorization.

That meant the same user-reviewed approval could be rebound to another real execution.

### Lesson

A one-shot contract must bind the complete identity graph, not only a permission token.

At minimum, the protocol needs an auditable relationship among:

```text
authorization_id
run_id
evaluation_run_id
handoff_id
actual execution identity
```

If one of those can be regenerated or substituted after approval, the system is not truly one-shot.

## Round 3 — Durable does not mean atomic

The third candidate fixed normal-path rebinding. RUN-READY now bound the predeclared run/evaluation/handoff identities, the obsolete expected-run axis was removed, and the actual GitHub run was captured in a durable one-shot claim.

Remote evidence included:

- no-provider smoke run `33940556644`;
- full Test run `33940556521` with 263 tests.

The new problem was crash consistency.

The claim consumed two identities using two sequential durable index writes. Each write used strong primitives such as `O_EXCL` and `fsync`, but the two semantic updates did not share one transaction boundary.

A crash after the first durable index and before the second could leave:

```text
authorization identity: consumed
run/evaluation/handoff identity: not consumed
```

A later, newly authorized dispatch could then reuse the old run identity.

The existing tests checked that atomicity-related primitives appeared in the implementation. They did not inject a real interruption between the two durable writes.

### Lesson

Three properties must be reviewed separately:

- **durability** — does state survive a crash?
- **atomicity** — can one logical transition commit only halfway?
- **recoverability** — after a crash, can the system reconstruct the correct state and remain fail-closed?

Using `fsync` proves none of the latter two by itself.

## Round 4 — One authoritative commit point, derived indexes, and real failure injection

The fourth candidate introduced a single durable authority for claim consumption.

Under an exclusive ledger lock, the workflow first committed one canonical authoritative claim record with create-once semantics, restrictive permissions, file `fsync`, and directory `fsync`. Authorization and run-identity names were then published as hard-link indexes to that same authoritative inode.

On restart, the ledger scan treated any surviving valid authoritative record or valid index body as consuming both identities. Malformed, unexpected, unreadable, or inconsistent durable ledger state failed the whole gate closed instead of being silently ignored or deleted.

The tests also changed qualitatively. They now injected actual failure conditions, including:

- process exit immediately after the first index became durable;
- restart with a fresh authorization and the same run identity;
- durable second-index collision;
- continued operation against a corrupt or inconsistent ledger.

Remote evidence included:

- no-provider smoke run `33942289128`;
- full Test run `33942289133` with 264 tests.

Independent QA Round 4 passed exact head `19b13961daf403b727c88e9d0aa28b7684e064c4`.

## Eight reusable engineering lessons

### 1. CI green is not protocol green

Rounds 1, 2, and 3 all had green CI. The test counts moved from 255 to 260 to 263, yet Independent QA still found new contract-level defects.

Tests prove the properties they encode. They do not prove properties the design never made explicit.

### 2. Write invariants before implementation

For a high-stakes one-shot execution path, define the load-bearing invariants first:

```text
approved-value invariant
identity invariant
crash invariant
recovery invariant
gate invariant
```

A large fraction of the PR #37 rework could have been discovered at design time by attacking those statements directly.

### 3. Authorization should be a machine-executable contract

Do not maintain two competing sources of truth such as “approved receipt values” and “runtime environment values.”

The approved canonical object should determine the execution-critical request.

### 4. Identity is first-class protocol data

Run, evaluation, handoff, authorization, and actual execution identities should be explicit, comparable, and persistently bound.

Names generated late in the workflow are not substitutes for identity contracts.

### 5. Durability, atomicity, and recovery need separate proofs

A system can be durable and still enter a logically half-committed state.

Define one authoritative commit point, then define how restart reconstructs truth from it.

### 6. Failure injection is stronger than primitive-presence testing

Checking for `O_EXCL`, `fsync`, or a lock proves that the code uses those primitives. It does not prove crash semantics.

A stronger test kills the process at the dangerous point, restarts the system, and attempts the best available bypass.

### 7. Documentation must not overclaim implementation semantics

Words such as `atomic`, `exactly-once`, `durable`, `non-rebindable`, and `fail-closed` are testable protocol claims.

If a document uses those terms, review should demand the corresponding failure model and adversarial evidence.

### 8. Narrow scope and separate gates improve convergence

PR #37 stayed inside the approved four-path implementation envelope through all four reviews. It did not use repeated QA failures as an excuse for an unrelated core rewrite.

Implementation, Independent QA, merge authorization, and live authorization also remained separate gates.

That made each failure attributable to one exact reviewed head and one newly identified invariant.

## A reusable invariant set for future one-shot systems

### Approved-value invariant

The approved canonical bytes determine every execution-critical value. Any receipt-external mismatch fails before credential/provider access.

### Identity invariant

The same authorization or the same run/evaluation/handoff identity cannot produce a second real execution.

### Crash invariant

A crash after claim consumption begins cannot make an already-consumed semantic identity reusable.

### Recovery invariant

Restart reconstructs truth from one durable authoritative record. Indexes and caches are derived evidence, not independent truth.

### Gate invariant

Value, identity, freshness, possession, and claim checks must all succeed before the credential/provider path becomes reachable.

## Recommended adversarial-test order

Before adding more happy-path coverage, test these failure classes:

1. approved receipt unchanged while provider/model/endpoint/runtime values are substituted;
2. approval unchanged while a second dispatch moves all externally mutable run-identity values together;
3. crash immediately after the first durable claim-related write;
4. second-index collision or partial ledger state;
5. malformed or unexpected durable state on restart.

Only after those paths fail closed should the normal success path be treated as meaningful evidence.

## Closing principle

> **A reliable one-shot system is not merely one that calls the provider once on the happy path. Its approved values cannot drift, its execution identity cannot be rebound, and a crash cannot reopen execution authority.**

PR #37 mattered because it evolved from a workflow that could run into a protocol with explicit authority, identity, transaction boundaries, recovery semantics, and adversarially testable guarantees.
