# B2 R1b One-Shot Live Orchestration

Status: **implementation and offline review only; no live execution authority**.

Authority:

- `PLAN-B2-BLIND-R1b v0.1` — Drive `1fR125gjS2WqSJaedAuQAxw2pcvXK8WJN00v8Rd_gOh0`;
- `WO-B2-BLIND-R1B-01 v0.1` — Drive `1v2X3H9Ke2Z1Veic7ZNMQRv09M12ix-7Ps1L0byFVzwg`;
- implementation issue `#36` and Draft PR `#37`;
- P0 baseline receipt — Drive `12GHMbw6jrAbF5A9bNo_KXpaxMqCpCfe5OYVy1iPYUjA`;
- construction baseline `main@0ba7c2572762afe38ccf6a71b012d9d8a6dae3a5`, tree
  `f88f3f77429a52639c0fa5b5444a9d10b01235d9`.

The A053 scope-expansion receipt authorizes exactly four changed paths: the new
live workflow, this contract, its new orchestration test, and the narrow legacy
assertion migration in `tests/test_b2_blind_handoff.py`. Core v5.2 protocol and
bridge code, schemas, dependencies, ordinary CI, and the deterministic smoke
workflow remain untouched.

## What this change does and does not do

`.github/workflows/b2_blind_handoff_v5_live.yml` defines a reviewed future
execution lane. Its only trigger is `workflow_dispatch`. It has no `push`,
`pull_request`, `schedule`, `repository_dispatch`, or `workflow_run` entry, and
therefore PRs, branch pushes, ordinary CI, documentation changes, and the
deterministic smoke cannot enter its provider or credential step.

The workflow is not usable from this unmerged review branch. Even after a
separately authorized merge, it remains closed until all protected environment
configuration is freshly frozen, a distinct `R1B-RUN-READY` receipt exists, a
one-shot authorization identifier is frozen, and the `b2-r1b-live` environment
approval is granted for the exact dispatch. This implementation does not set
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
be written to repository configuration, dispatch inputs, receipts, summaries,
or logs. It must be owned by a dedicated setgid exchange group with group
read/write/execute and no world permissions. The workflow masks the value,
verifies that boundary, creates a group-readable runner publication directory
and a group-writable private publication directory, and keeps its own state in
a separate mode-0700 `RUNNER_TEMP` root. The private orchestrator must run as a
distinct identity in the exchange group, have access only to the exchange
directory and its own private state/output roots, and have no access to the
runner's `RUNNER_TEMP` state. Its process must use `umask 0027` so its exchange
objects are never world-readable.

The `b2-r1b-live` protected environment is the human approval boundary. Its
non-secret variables freeze only public-safe exact metadata:

| Environment variable | Frozen value |
|---|---|
| `B2_R1B_EXECUTION_HEAD_SHA` | exact merged execution commit |
| `B2_R1B_BRIDGE_MAIN_SHA` | exact accepted v5.2 bridge commit |
| `B2_R1B_WORKFLOW_RUN_ID` | exact queued workflow run selected for the one-shot authorization |
| `B2_R1B_RUN_READY_RECEIPT_SHA256` | SHA-256 of the fresh run-ready receipt |
| `B2_R1B_AUTHORIZATION_ID` | unique one-shot authorization identifier |
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
| `B2_R1B_HANDOFF_TTL_SECONDS` | freshness window in `[300, 21600]` |

The environment secret `B2_R1B_PROVIDER_API_KEY` is the sole provider
credential slot. It is injected only into the one bridge step, after v5.2 has
accepted the encrypted input, generated a fresh return-key challenge, and
verified the private side's one-time acknowledgement. It is not present in
preflight, checkout, installation, input, challenge, result-encryption,
publication-verification, summary, or cleanup steps.

## Manual authorization gates

An authorized operator must dispatch the workflow on `main` with exactly three
inputs:

1. the SHA-256 of the already approved `R1B-RUN-READY` receipt;
2. its exact one-shot authorization identifier;
3. the explicit boolean one-shot confirmation.

The first two inputs must byte-for-byte equal the protected environment values.
The selected commit must equal `B2_R1B_EXECUTION_HEAD_SHA`; the run ref must be
`refs/heads/main`; `GITHUB_RUN_ATTEMPT` must be `1`; and `GITHUB_RUN_ID` must
equal `B2_R1B_WORKFLOW_RUN_ID`. The protected environment must require a human
reviewer: after a dispatch is queued, its newly assigned run ID is frozen into
that variable before the environment approval is granted. A rerun or a second
dispatch therefore has the wrong attempt or run identity and is rejected before
private-locator or provider-credential use. A new attempt requires a new
run-ready receipt, new authorization identifier, newly frozen workflow run ID,
and a fresh manual dispatch and environment approval.

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
| 1 | runner | validate dispatch against protected fresh-preflight values | no |
| 2 | runner | exact-head/core-blob checks; fresh input key | no |
| 3 | runner → private | `runner/input-public.pem`, then `runner/request.json` commit marker | no |
| 4 | private → runner | v5.2 `private/payload.json` | no |
| 5 | runner | `accept-input`; exact binding/freshness/input verification | no |
| 6 | runner → private | fresh `runner/challenge.enc.json` | no |
| 7 | private → runner | v5.2 `private/challenge-ack.json` | no |
| 8 | runner | `verify-ack` creates the exclusive `ack-accepted` claim | no |
| 9 | runner | exactly one `b2.blind_eval --authorize-live-call` invocation | step-local only |
| 10 | runner → private | v5.2 `runner/result.enc.json` | no |
| 11 | private | decrypt, validate, and atomically publish the private result pair | no |
| 12 | private → runner | result-accept marker, body-free verification receipt, cleanup receipt | no |
| 13 | runner | verify exact marker schemas/bindings, emit body-free summary, clean both roots | no |

There is one bridge invocation and no loop around it. The bridge contract fixes
`automatic_retries = 0`; the result bundle is rejected unless
`provider_attempts = 1`, all frozen input identities match, and
`quality_score = null`. HTTP 200 with null, empty, or whitespace-only final
content remains `NOT_EVALUABLE / EMPTY_FINAL_CONTENT`; reasoning presence does
not change that classification.

## Private-orchestrator contract

The private side must use the same exact v5.2 source and treat
`runner/request.json` as the publication commit marker. It must validate the
request schema and all values against the approved run-ready receipt before
using the separately frozen context and prompt. It then performs these existing
CLI operations with the exact arguments from the request:

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
is uploaded as an artifact or committed to Git.

The final GitHub step summary is body-free. It contains only workflow-run and
execution-head identities, terminal status, the fixed one-attempt/zero-retry
counters, and boolean verification labels for result publication and cleanup.
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
- static manual-trigger/no-retry/post-ACK-secret ordering audits;
- repository leak and changed-path-envelope scans.

Only after those checks may engineering emit
`READY FOR B2-BLIND-R1B INDEPENDENT QA` and stop. Distinct exact-head IQA PASS is
required before a separate merge decision. Merge would still not authorize a
provider run; fresh provider/model/endpoint/runtime preflight, exact
`R1B-RUN-READY`, protected-environment approval, and separate one-shot live
authorization would remain mandatory.

Historical Q1-R1 remains exactly:

`HISTORICAL-EXECUTION-ONLY / HTTP 200 / EMPTY_FINAL_CONTENT / NO SCORABLE ANSWER / NOT_EVALUABLE`.
