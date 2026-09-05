# B2 R1b One-Shot Live Orchestration

Status: **implementation and offline review only; no live execution authority**.

Authority:

- `PLAN-B2-BLIND-R1b v0.1` — Drive `1fR125gjS2WqSJaedAuQAxw2pcvXK8WJN00v8Rd_gOh0`;
- `WO-B2-BLIND-R1B-01 v0.1` — Drive `1v2X3H9Ke2Z1Veic7ZNMQRv09M12ix-7Ps1L0byFVzwg`;
- `WO-B2-BLIND-R1B-COMPAT-01 v0.1` — Drive `1rZaLiVZVqE5Sb1GGcBelg1m4UHrOincM5H1unp3MMvU`;
- `WO-B2-BLIND-R1B-WINDOW-CONTROL-01 v0.1` — Drive `1UMen4kMvv9YF2L1-ljT3f8_KaR7YYRdhgH21MpKRIMA`;
- frozen Window Approval Control Issue `#47`;
- P0 baseline receipt — Drive `12GHMbw6jrAbF5A9bNo_KXpaxMqCpCfe5OYVy1iPYUjA`;
- window-control construction baseline
  `main@8a1fe28f1cf79d9cf915abd2c5a37ba1a427a2f5`, tree
  `54c56f73e2f67e25d65d8214c8e30035b08ca50a`.

PR `#37` established the one-shot orchestration and PR `#45` merged the
reasoning-compatibility repair. A078 authorizes this control-plane repair:
create the single dedicated Control Issue and modify this workflow, its focused
test, and this document. A subsequent explicit scope extension authorizes one fourth
path, `tests/test_b2_blind_handoff.py`, solely to replace its obsolete
`workflow_dispatch` trigger assertion with the new sole
`issue_comment(created)` contract. Core v5.2 handoff code, generic blind-eval
transport and test semantics, schemas, dependencies, ordinary CI,
deterministic smoke, BM0/BM1, credentials, and private context/prompt bodies
remain untouched.

## What this change does and does not do

`.github/workflows/b2_blind_handoff_v5_live.yml` defines a reviewed future
execution lane. Its only trigger is `issue_comment` with `types: [created]`.
There is no retained `workflow_dispatch` live surface. It has no `push`,
`pull_request`, `schedule`, `repository_dispatch`, or `workflow_run` entry, and
therefore PRs, branch pushes, ordinary CI, documentation changes, and the
deterministic smoke cannot enter its provider or credential step.

The trigger is hard-bound to Control Issue `#47`, repository-owner identity
`aerenkolstein-code`, `author_association = OWNER`, a non-PR issue comment, the
default `main` ref/head, and strict canonical approval JSON. Obvious metadata
mismatches skip before any runner. A public-safe `ubuntu-latest` gate performs
the full approval/RUN-READY comparison before the protected private runner job
can be scheduled.

The workflow is not usable from this unmerged review branch. Even after a
separately authorized merge, it remains closed until all protected environment
configuration is freshly frozen, a distinct `R1B-RUN-READY` receipt exists, a
one-shot authorization identifier is frozen, and a later user approval in the
ChatGPT window is projected as one exact Control Issue comment. This
implementation does not set
any of those values, configure a provider, read a credential, call a provider,
spend money, run R1b, score C1-C19, create BM1, or authorize merge.

## Runtime trust split

The workflow deliberately does not place real handoff objects in Git commits,
branches, pull-request comments, workflow inputs, Actions artifacts, caches, or
public logs. It targets a dedicated self-hosted runner with labels
`self-hosted`, `linux`, `x64`, and `b2-r1b-private`. The runner and the private
orchestrator exchange objects through one local run-scoped directory beneath
the runner-service environment variable `B2_R1B_EXCHANGE_BASE`.

`B2_R1B_EXCHANGE_BASE` is a private locator. It must be provisioned on the
dedicated runner, must name a real absolute non-symlink directory, and must not
be written to repository configuration, approval comments, receipts, summaries,
or logs. It must be owned by a dedicated setgid exchange group with group
read/write/execute and no world permissions. The workflow masks the value,
verifies that boundary, creates a group-readable runner publication directory
and a group-writable private publication directory, and keeps its own state in
a separate mode-0700 `RUNNER_TEMP` root. The private orchestrator must run as a
distinct identity in the exchange group, have access only to the exchange
directory and its own private state/output roots, and have no access to the
runner's `RUNNER_TEMP` state. Its process must use `umask 0027` so its exchange
objects are never world-readable.

The dedicated runner must also provision `B2_R1B_ONE_SHOT_CLAIM_BASE` as a
real absolute, non-symlink, runner-owned mode-0700 directory. It is a durable,
private authorization-claim ledger, not an exchange directory. After all
canonical receipt and window-approval checks pass, but before checkout or
any exchange, secret, or provider step, the workflow takes an exclusive
`ledger.lock`, scans every durable entry, and transactionally consumes one
mode-0600 body-free claim. It first writes and file-plus-directory-fsyncs a
canonical authoritative `claim-<claim-sha256>.json` record. Only after that
commit does it create and directory-fsync two `O_EXCL` hard-link indexes: one
keyed by the SHA-256 of the authorization ID and one by the SHA-256 of the
canonical run/evaluation/handoff identity triple. The record and any indexes
are deliberately never removed by per-run cleanup. A valid record or index
body independently consumes both identities, so a crash after the first index
cannot leave the run identity reusable. A malformed, unreadable, wrongly
named, or unexpected ledger entry fails the whole claim gate closed pending
manual forensic repair; it is never ignored or automatically deleted.

The `b2-r1b-live` protected environment is the human approval boundary. Its
non-secret variables freeze only public-safe exact metadata:

| Environment variable | Frozen value |
|---|---|
| `B2_R1B_EXECUTION_HEAD_SHA` | exact merged execution commit |
| `B2_R1B_BRIDGE_MAIN_SHA` | exact accepted v5.2 bridge commit |
| `B2_R1B_RUN_READY_RECEIPT_SHA256` | lowercase SHA-256 of the exact canonical run-ready receipt bytes |
| `B2_R1B_RUN_READY_RECEIPT_B64` | strict standard-base64 encoding of those exact public-safe canonical bytes |
| `B2_R1B_AUTHORIZATION_ID` | unique one-shot authorization identifier |
| `B2_R1B_MAX_SPEND_USD` | exact approved positive decimal string, bound into RUN-READY and the approval comment |
| `B2_R1B_RUN_ID` | exact predeclared R1b run identifier |
| `B2_R1B_HANDOFF_ID` | exact predeclared v5.2 handoff identifier |
| `B2_R1B_EVALUATION_RUN_ID` | exact R1b evaluation run identifier |
| `B2_R1B_CONTEXT_SHA256`, `B2_R1B_CONTEXT_BYTES` | frozen private context fingerprint and size |
| `B2_R1B_PROMPT_SHA256`, `B2_R1B_PROMPT_BYTES` | frozen private prompt fingerprint and size |
| `B2_R1B_PROVIDER_LABEL` | public-safe provider label |
| `B2_R1B_PROVIDER_PROTOCOL` | `openai-compatible-chat-completions/v1` |
| `B2_R1B_REQUESTED_MODEL_ID` | exact strict-token model identifier |
| `B2_R1B_PROVIDER_ENDPOINT` | exact bounded HTTPS endpoint |
| `B2_R1B_TIMEOUT_SECONDS` | one-attempt timeout in `[1, 600]` |
| `B2_R1B_TEMPERATURE` | exactly `0` |
| `B2_R1B_MAX_TOKENS` | positive frozen maximum, at most `262144` |
| `B2_R1B_THINKING_MODE` | exactly `disabled` |
| `B2_R1B_REASONING_EFFORT_JSON` | exact canonical JSON literal `null` |
| `B2_R1B_HANDOFF_TTL_SECONDS` | freshness window in `[300, 21600]` |

### Canonical RUN-READY machine binding

`R1B-RUN-READY` is an exact public-safe JSON object, not a prose approval and
not a digest standing alone. A078 introduces the closed
`b2-r1b-run-ready/v4` schema without mutating v3 semantics:

```json
{
  "approval_channel": "chat-window-control-issue",
  "approval_schema_version": "b2-r1b-window-approval/v1",
  "authorization_id": "<one-shot authorization ID>",
  "automatic_retries": 0,
  "bridge_main_sha": "<40 lowercase hex>",
  "control_issue_number": 47,
  "context_bytes": 1,
  "context_sha256": "<64 lowercase hex>",
  "evaluation_run_id": "<evaluation ID>",
  "execution_head_sha": "<40 lowercase hex>",
  "git_ref": "refs/heads/main",
  "handoff_id": "<predeclared handoff ID>",
  "handoff_ttl_seconds": 3600,
  "max_provider_attempts": 1,
  "max_spend_usd": "<exact approved decimal>",
  "mode": "live",
  "prompt_bytes": 1,
  "prompt_sha256": "<64 lowercase hex>",
  "provider_endpoint": "https://<approved-host>/<approved-path>",
  "provider_label": "<public-safe provider label>",
  "provider_max_tokens": 8192,
  "provider_protocol": "openai-compatible-chat-completions/v1",
  "provider_reasoning_effort": null,
  "provider_temperature": 0,
  "provider_thinking_mode": "disabled",
  "provider_timeout_seconds": 180,
  "receipt_type": "R1B-RUN-READY",
  "repository": "aerenkolstein-code/llm-evaluation-lab",
  "requested_model_id": "<exact requested model ID>",
  "run_id": "<predeclared R1b run ID>",
  "schema_version": "b2-r1b-run-ready/v4",
  "trigger_event": "issue_comment",
  "workflow_path": ".github/workflows/b2_blind_handoff_v5_live.yml",
  "workflow_run_attempt": 1,
  "work_order": "WO-B2-BLIND-R1B-WINDOW-CONTROL-01 v0.1"
}
```

The displayed indentation is explanatory only. The approved byte form is
exactly Python
`json.dumps(receipt, ensure_ascii=True, sort_keys=True,
separators=(",", ":")).encode("ascii")`, with no BOM, whitespace, duplicate
key, non-finite number, or trailing newline. `B2_R1B_RUN_READY_RECEIPT_B64` is
the standard padded base64 of those bytes, and
`B2_R1B_RUN_READY_RECEIPT_SHA256` is their lowercase hexadecimal SHA-256.
Neither value contains a credential, private locator, input body, or output
body, but both remain protected approval state.

The first workflow step strictly decodes the base64, re-encodes it to reject
aliases, recomputes the SHA-256, parses strict ASCII JSON, reconstructs the
entire expected object from the protected variables plus fixed repository,
workflow, ref, mode, one-attempt, and zero-retry constants, and compares the
canonical bytes byte-for-byte. Consequently a stale receipt cannot authorize a
different provider label, requested model, endpoint, timeout, temperature,
maximum token count, thinking mode, reasoning effort, TTL, input identity,
bridge commit, execution head,
R1b run identity, evaluation-run identity, handoff identity, spend ceiling, or
authorization ID. These checks execute on the public-safe gate and finish
before the private runner, checkout, exchange-directory access, secret
injection, or provider execution.

For this recovery lane, `provider_thinking_mode = "disabled"` and
`provider_reasoning_effort = null` are fixed policy, not provider defaults.
The protected effort variable must be the exact JSON bytes `null`; a non-null
effort with disabled thinking fails closed. A canonical v3
`workflow_dispatch` receipt lacks the v4 approval fields and cannot authorize
this lane even if its digest is freshly recomputed.

### Canonical ChatGPT-window approval

A later exact user authorization is projected as one issue comment on `#47`.
The comment is canonical ASCII JSON with no Markdown wrapper, BOM, whitespace,
newline, duplicate key, non-finite value, credential, private locator, or body:

```json
{"approval_type":"B2-R1B-WINDOW-APPROVAL","authorization_id":"<exact one-shot authorization ID>","confirm_one_shot":true,"max_spend_usd":"<exact approved decimal>","run_ready_receipt_sha256":"<exact RUN-READY v4 SHA-256>","schema_version":"b2-r1b-window-approval/v1"}
```

The hosted gate reconstructs those bytes from protected canonical state and
requires byte-for-byte equality with the newly created comment. Wrong issue,
PR comment, wrong actor, non-OWNER association, edited/deleted events,
malformed/noncanonical JSON, changed digest, authorization, ceiling, schema,
or confirmation fail before the private runner. The gate passes the actual
comment ID, exact comment-body SHA-256, and RUN-READY digest as immutable job
outputs to the private lane, which rehashes them before claim consumption.
The private job-level condition depends only on the successful hosted gate. It
does not read environment-level `vars` there, because GitHub makes those
available only after the environment is declared by a runner. Once the private
job starts, its first step compares the gate outputs against the now available
protected variables before consuming the durable claim.

The next step consumes the approved authorization exactly once. Under the
exclusive ledger lock it validates every existing canonical
`b2-r1b-one-shot-claim/v2` record or index and treats the body of any valid
entry as consuming both its authorization and run identity, even when a prior
crash left only a subset of the expected names. It then commits one
authoritative claim record with `O_EXCL`, mode 0600, file `fsync`, and directory
`fsync`, before creating either identity index as a hard link to that same
inode. Each index link is followed by another directory `fsync`. The claim
binds the approved receipt digest, actual approval comment ID and comment-body
digest, and its run/evaluation/handoff/authorization/head identities to the
first actual GitHub workflow run ID and attempt that reaches the gate.

A second valid-looking comment therefore fails closed if it reuses either the authorization
or the run identity—even if an operator changes both the fresh
`GITHUB_RUN_ID` and any obsolete out-of-band expected-run value together. If
the process stops after the authoritative record or first index, the next
locked scan recovers that valid body and keeps both identities consumed. If
either index collides after the authoritative commit, the attempt fails and the
retained authoritative record likewise burns both identities. Incomplete
noncanonical bytes cannot be safely attributed, so their presence quarantines
the entire ledger fail-closed rather than reopening either identity. Claim
consumption precedes checkout, exchange creation, provider-secret injection,
and the provider process. If a later step fails, another attempt requires a new
receipt, new authorization ID, and new run/evaluation/handoff identity.

The exact closed claim object is canonical ASCII JSON with this shape:

```json
{
  "approval_comment_id": 123456789,
  "approval_comment_sha256": "<SHA-256 of exact canonical approval comment bytes>",
  "authorization_id": "<approved authorization ID>",
  "bridge_main_sha": "<40 lowercase hex>",
  "evaluation_run_id": "<evaluation ID>",
  "execution_head_sha": "<40 lowercase hex>",
  "handoff_id": "<predeclared handoff ID>",
  "receipt_type": "R1B-ONE-SHOT-AUTHORIZATION-CLAIM",
  "repository": "aerenkolstein-code/llm-evaluation-lab",
  "run_id": "<predeclared R1b run ID>",
  "run_identity_sha256": "<SHA-256 of canonical run/evaluation/handoff triple>",
  "run_ready_receipt_sha256": "<approved RUN-READY SHA-256>",
  "schema_version": "b2-r1b-one-shot-claim/v2",
  "workflow_path": ".github/workflows/b2_blind_handoff_v5_live.yml",
  "workflow_run_attempt": 1,
  "workflow_run_id": "<first consuming GitHub run ID>"
}
```

The authoritative record and both indexes expose these identical bytes and,
after a successful transaction, are three hard links to the same inode. The
request reads the authoritative record, verifies both indexes against it, and
carries the exact claim plus its SHA-256 so the private side can validate the
actual workflow-run binding without receiving the private ledger path.

After that comparison, the runner writes those exact canonical bytes create-once
as mode-0600 `run-ready.json` inside its mode-0700 root. Immediately before the
single provider attempt, the provider step rehashes and reparses that file and
constructs the bridge argument vector exclusively from its provider, model,
endpoint, timeout, temperature, maximum-token, thinking-mode, null-effort,
evaluation-ID, and bridge-commit fields. It passes `--thinking-mode disabled`,
derives omission of `--reasoning-effort` from the approved null, and does not
take those execution arguments from independently mutable shell variables after
the initial binding check. The following body-free v3 bridge receipt gate also
derives its expected provider/model/reasoning/input/commit values from the same
hashed canonical file.

The GitHub-assigned workflow run ID does not exist when the approval comment is
created, so the receipt does not pretend to predict it and there
is no independently mutable `B2_R1B_WORKFLOW_RUN_ID`. Instead, the durable
claim binds the already approved authorization and complete predeclared R1b
identity to exactly the first actual GitHub run that consumes it. The request
later carries that claimed workflow run ID, the exact receipt and digest, and
the durable claim digest.

The environment secret `B2_R1B_PROVIDER_API_KEY` is the sole provider
credential slot. It is injected only into the one bridge step, after v5.2 has
accepted the encrypted input, generated a fresh return-key challenge, and
verified the private side's one-time acknowledgement. It is not present in
preflight, checkout, installation, input, challenge, result-encryption,
publication-verification, summary, or cleanup steps.

## ChatGPT-window authorization gate

After merge and fresh preflight, the operator freezes and reviews RUN-READY
v4, its base64/digest, every matching protected parameter, the exact spend
ceiling, and the unique one-shot authorization ID. The user then approves that
exact object in the ChatGPT window. ChatGPT projects the approval through the
already governed issue-comment write as exactly one canonical JSON comment on
Control Issue `#47`; the user does not need to open GitHub Actions.

GitHub's `issue_comment(created)` event binds the actual comment ID, actor,
association, default ref/head, and workflow run. The public-safe gate requires
the exact owner identity and canonical bytes before the private job can run.
The RUN-READY digest is recomputed from protected bytes and every provider,
runtime, input, head, run/evaluation/handoff, approval-channel, issue-number,
and spend value must match. `GITHUB_RUN_ATTEMPT` must equal `1`. A rerun fails;
a second valid-looking comment with the same authorization or run identity
fails at the durable claim gate before checkout, exchange, secret, or provider.
A new attempt requires a new receipt, authorization, run/evaluation/handoff
identity, and a new explicit ChatGPT-window approval.

This workflow does not change the `b2-r1b-live` environment protection rules.
After merge, pre-live inspection must determine whether a required reviewer or
Prevent self-review rule still adds a GitHub approval step. If so, stop for a
separate governance decision; do not remove or bypass that rule here.

The checkout disables persisted Git credentials. Before any handoff object is
created, the workflow proves that the accepted bridge commit is an ancestor of
the execution head and that both `b2/blind_eval.py` and
`b2/blind_handoff.py` are byte-identical to their accepted bridge versions. The
dedicated runner must already contain the reviewed Python runtime and
`cryptography>=42,<47`; the workflow verifies those facts without a package
download or dependency mutation.

## One-shot protocol sequence

The run creates two fresh roots:

- a runner-only root under `RUNNER_TEMP`, containing the input private key,
  decrypted input, challenge plaintext, acknowledgement key, raw answer, and
  temporary receipts;
- an exchange root named `<workflow-run-id>-1-<execution-head>` beneath the
  private exchange base, containing only public metadata/keys or encrypted and
  authenticated exchange objects.

Every output is create-once. Existing roots/files, non-regular publications,
symlinks, oversize envelopes, stale bindings, hash/byte mismatches, a second
claim, or an expired/not-yet-valid object fail closed.

| Order | Side | Create-once object or gate | Provider credential present? |
|---:|---|---|---:|
| 1 | hosted gate | require created non-PR comment on `#47` by owner; reconstruct and byte-compare approval plus RUN-READY v4 | no |
| 2 | private runner | rebind actual comment ID/body digest and lock/recover the durable ledger; commit one authoritative claim plus both identity indexes | no |
| 3 | private runner | exact-head/core-blob checks; fresh input key | no |
| 4 | runner → private | `runner/input-public.pem`, then v3 `runner/request.json` containing the exact run-ready object, v2 claim, and both digests | no |
| 5 | private → runner | v5.2 `private/payload.json` | no |
| 6 | runner | `accept-input`; exact binding/freshness/input verification | no |
| 7 | runner → private | fresh `runner/challenge.enc.json` | no |
| 8 | private → runner | v5.2 `private/challenge-ack.json` | no |
| 9 | runner | `verify-ack` creates the exclusive `ack-accepted` claim | no |
| 10 | runner | exactly one `b2.blind_eval --thinking-mode disabled --authorize-live-call` invocation; reasoning effort omitted | step-local only |
| 11 | runner → private | v5.2 `runner/result.enc.json` | no |
| 12 | private | decrypt, validate, and atomically publish the private result pair | no |
| 13 | private → runner | result-accept marker, body-free verification receipt, cleanup receipt | no |
| 14 | runner | verify exact marker schemas/bindings, emit body-free summary, clean both ephemeral roots | no |

There is one bridge invocation and no loop around it. The bridge contract fixes
`automatic_retries = 0`; the result bundle is rejected unless
`provider_attempts = 1`, all frozen input identities match, and
`quality_score = null`. The body-free `b2-blind-eval-bridge/v3` receipt must
also report `requested_thinking_mode = "disabled"` and
`requested_reasoning_effort = null`. HTTP 200 with null, empty, or whitespace-only final
content remains `NOT_EVALUABLE / EMPTY_FINAL_CONTENT`; reasoning presence does
not change that classification.

## Private-orchestrator contract

The private side must use the same exact v5.2 source and treat
`runner/request.json` as the publication commit marker. It must require
`b2-r1b-live-request/v3`, canonicalize its nested `run_ready_receipt` by the
rule above, recompute and compare `run_ready_receipt_sha256`, and compare both
against its independently held approved receipt. It must also canonicalize the
nested `one_shot_claim`, recompute `one_shot_claim_sha256`, require the exact
closed `b2-r1b-one-shot-claim/v2` schema, and verify that its approval comment
ID/body digest, receipt digest, authorization/run/evaluation/handoff identities,
execution/bridge heads, repository/workflow, actual workflow run ID, and
attempt match the request.
It must then compare every overlapping top-level request identity—including
execution/bridge commits, input hashes and sizes, mode, R1b run ID, evaluation
ID, handoff ID, workflow run ID, and authorization ID—to those two bound
objects before using the context and prompt. A missing/extra receipt or claim
field or any provider,
model, endpoint, timeout, temperature, token, thinking mode, reasoning effort,
TTL, input, head, or
authorization mismatch fails closed. It then performs these existing CLI
operations with the exact arguments from the request:

1. `prepare-input`, using `runner/input-public.pem`, the frozen private input
   files, a fresh private state directory outside the exchange root, and
   `private/payload.json` as its create-once output;
2. `verify-challenge`, using `runner/challenge.enc.json` and publishing
   `private/challenge-ack.json` create-once;
3. `verify-result`, using `runner/result.enc.json`, its private state, and a new
   final private output directory outside every ephemeral root.

`verify-result` atomically publishes the verified private output directory and
only then creates `result-accepted.json` in private state. The private operator
must atomically copy that exact marker and the body-free `verify-result` stdout
to `private/result-accepted.json` and
`private/result-verification-receipt.json`. It must then run
`b2.blind_handoff cleanup` on its ephemeral private state and atomically publish
that command's exact body-free stdout as
`private/private-cleanup-receipt.json` **last**. The last file is the private
side's finalization commit marker; publishing it without successful result
verification, atomic output publication, and state deletion violates this
contract.

The runner accepts only the exact key sets emitted by v5.2. It recomputes the
binding and encrypted-result SHA-256 values, requires the `result-accepted`
claim to match both, requires the result receipt to report `RESULT_VERIFIED`,
`mode = live`, and `provider_attempts = 1`, and requires the cleanup receipt to
equal `EPHEMERAL_CLEANUP_COMPLETE`. Extra fields are rejected so no private body
or locator can be smuggled into the public summary.

## Cleanup, failure, and evidence semantics

The final workflow step runs under `always()` and uses the reviewed v5.2 cleanup
command on both the runner-only root and exchange root, attempting both even if
one cleanup reports failure. Cleanup follows no
symlinks, rejects broad roots, surfaces any removal failure, and is successful
only when both exact roots no longer exist. No real payload, acknowledgement,
challenge, result envelope, private input, key, raw answer, or temporary receipt
is uploaded as an artifact or committed to Git. The body-free durable
authorization record, its identity indexes, and ledger lock are outside both
ephemeral roots and are intentionally retained; deleting any of them would
weaken replay evidence and is not part of run cleanup.

The final GitHub step summary is body-free. It contains only R1b run,
evaluation, handoff, workflow-run, approval-comment ID/body digest, and
execution-head identities, the consumed claim status, terminal status, the
fixed one-attempt/zero-retry counters, and boolean verification labels for
result publication and cleanup.
It contains no context/prompt/reasoning/final body, key, credential,
authorization header, endpoint, model response body, score, or private locator.

Any missing/mismatched configuration, replay, rerun, wrong ref/head/blob,
unavailable credential, malformed or late publication, failed provider
attempt, invalid result, publication failure, or cleanup failure is non-PASS.
The workflow never retries the provider and never converts an infrastructure or
evidence failure into a model-quality score.

## Offline review evidence required before IQA

Engineering must bind its receipt to the exact PR head/tree and record:

- `python -m unittest tests.test_b2_r1b_live_orchestration -v`;
- `python -m unittest tests.test_b2_blind_eval tests.test_b2_blind_handoff -v`;
- `python -m unittest discover -s tests -v`;
- the existing deterministic `b2.blind_handoff deterministic-smoke` with
  `provider_attempts = 0`, `credential_lookups = 0`, zero retries, return-key
  possession proof, result decryptability, and verified cleanup;
- static sole-`issue_comment(created)`/no-retry/post-ACK-secret ordering audits;
- canonical approval and receipt digest/parse/equality tests, including wrong
  issue, PR comment, actor/association, malformed/duplicate/noncanonical JSON,
  changed receipt SHA/authorization/ceiling/confirmation, stale-digest and
  valid-but-changed provider/model/endpoint/runtime/thinking/effort/run/handoff
  adversarial cases, non-null effort with disabled thinking, and rejection of
  stale v3 `workflow_dispatch` RUN-READY;
- a two-comment replay test in which the second actual comment and workflow-run
  identities change while the approved receipt/digest and authorization stay
  unchanged; the second comment must fail at the durable
  claim gate before checkout, exchange, secret, or provider;
- crash/restart injection immediately after the first identity index becomes
  durable, proving that a fresh authorization cannot reuse the recorded
  run/evaluation/handoff identity;
- injected second-index collision after the authoritative claim commit,
  proving that the failed attempt leaves both identities fail-closed and does
  not create a rollback/reuse window;
- repository leak and changed-path-envelope scans.

Only after those checks may engineering emit
`READY FOR B2-BLIND-R1B-WINDOW-CONTROL INDEPENDENT QA` and stop. Distinct exact-head IQA PASS is
required before a separate merge decision. Merge would still not authorize a
provider run; fresh provider/model/endpoint/runtime preflight, exact
`R1B-RUN-READY` v4, environment inspection, and separate exact ChatGPT-window
one-shot live authorization would remain mandatory. The prior P4 SHA
`a289a3f73eac981bc36c501d0e4ac2a1b115837006248e179b939ee70003376a`
is invalid for the repaired lane and must not be reused.

Historical Q1-R1 remains exactly:

`HISTORICAL-EXECUTION-ONLY / HTTP 200 / EMPTY_FINAL_CONTENT / NO SCORABLE ANSWER / NOT_EVALUABLE`.
