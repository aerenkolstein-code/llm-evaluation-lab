# B2 Generic Blind Eval Bridge v0.1

Status: accepted generic bridge plus `WO-B2-BLIND-02` observability hardening;
pre-Independent-QA review and not live-authorized.

This bridge is a thin private-lane-friendly invocation layer for B2 continuous evaluation. It exists because B2 already has case/rubric/oracle, typed terminal semantics, evidence receipts, regression infrastructure, and quality projection, but `main` previously had no generic way to send one byte-frozen long context plus one byte-frozen prompt to a live model.

## Contract

```text
context_file + prompt_file
→ fixed versioned blind-input envelope
→ exactly one provider request
→ raw model answer (private/local)
→ body-free sanitized receipt
→ independent scorer/oracle outside this bridge
```

The bridge does **not** score correctness. A bridge `PASS` means only that one authorized provider request returned a non-empty model output. Provider/network/schema failures are `NOT_EVALUABLE`, never low model-quality scores.

## Current provider protocol

v0.1 implements one generic protocol:

`openai-compatible-chat-completions/v1`

The provider label, endpoint, requested model ID, and API-key environment variable are supplied at runtime. The code does not make a brand capability claim. Other provider protocols require a later amendment/Work Order.

## Hard gates

- `--authorize-live-call` is mandatory before credential lookup or network access.
- `automatic_retries = 0`.
- redirects are disabled and fail closed; a 30x is one failed provider attempt, never a follow-up request, so the Bearer credential is not forwarded to a redirect target.
- no tools, no SearchProxy, no browsing, no Search Cup `Submission` contract.
- no hidden scorer/checkpoints are sent to the model.
- no input body or output body is copied into the sanitized receipt.
- provider-controlled metadata is not trusted verbatim: requested/resolved model IDs, response IDs, and finish reasons are retained only when they satisfy strict short ASCII token policies; otherwise they are omitted or rejected before credential lookup.
- provider HTTP error bodies are never copied into receipts because a provider may echo private request content.
- API keys are environment-only and never rendered into receipts.
- raw-output and receipt-output must resolve to distinct paths; aliasing is rejected before execution.
- output publication is fail closed: both artifacts are staged before PASS publication, raw is published before receipt, a receipt-publication failure rolls back raw, and a non-PASS run removes any stale raw from a previous run.
- CI uses deterministic fake transports only; no live or paid call is allowed in CI.

## Input envelope

The adapter sends no system semantic instruction. The single user message is a fixed versioned envelope:

```text
===== LONG_CONTEXT | b2-blind-input-envelope/v1 =====
<exact UTF-8 context bytes decoded as text>
===== TASK =====
<exact UTF-8 prompt bytes decoded as text>
```

The envelope version and all input fingerprints are recorded. A future envelope change is a protocol change and must not be silently compared to v1 runs.

## Private/public split

Private lane may retain:

- real long context
- real prompt
- raw model answer
- private scorecard/oracle
- private run notes

Public-safe receipt may retain only metadata/fingerprints such as:

- run ID
- protocol/envelope versions
- provider label/protocol
- requested model ID plus sanitized/validated resolved model ID when safe
- SHA-256 fingerprints and byte counts
- timestamps/duration
- HTTP status plus sanitized/validated response ID and finish reason when safe
- JSON/response/message schema parse booleans
- reasoning-field presence, UTF-8 byte count, and SHA-256 (never its body)
- final-content-field presence, UTF-8 byte count, and SHA-256 only when non-empty
- normalized non-negative token usage when available
- provider-attempt count, `automatic_retries = 0`, and `quality_score = null`
- terminal status and safe error metadata
- git commit when supplied

Do not commit private inputs or answers into this public repository.

The hardened receipt schema is `b2-blind-eval-bridge/v2`. HTTP 200 alone is not
PASS: a null, empty, or whitespace-only final remains
`NOT_EVALUABLE / EMPTY_FINAL_CONTENT`, even when reasoning metadata is present.
Only a non-empty final may produce bridge-level PASS, which still does not score
answer quality.

The transport boundary is separately specified in
[B2 Blind Handoff v5.2](blind-handoff-v5.md). The durable review tree contains
no live workflow; any future provider run requires separate authorization and a
new reviewed exact-head orchestration change.

## Private output-pair semantics

`--raw-output` and `--receipt-output` are one evidence pair, not two unrelated files.

- Their resolved paths must be distinct; an existing hard-link alias is also rejected.
- PASS stages both files in their destination directories before replacing either target.
- PASS publishes the private raw answer first and the sanitized receipt last. Therefore a visible PASS receipt is the commit marker for the pair.
- If raw publication fails, neither target remains.
- If receipt publication fails after raw publication, both targets are removed.
- NOT_EVALUABLE / ERROR publishes only the new receipt and guarantees any old raw answer at the requested raw path is removed.

This prevents a new failure receipt from being paired with an old answer and prevents a PASS receipt from surviving without its corresponding raw artifact.

## IQA Round-1 repair coverage

The first Independent QA review identified three blockers. This revision adds deterministic regression coverage for each:

1. redirect suppression: `_NoRedirectHandler` refuses a follow-up request and the default transport returns 30x as the single attempt result;
2. evidence-pair commit: stale raw removal, path alias rejection, raw-publication failure, and receipt-publication rollback are tested;
3. provider-controlled metadata: private-looking/URL-like or over-length `model` / `id` values are omitted from receipts.

`WO-B2-BLIND-02` adds deterministic coverage for reasoning-only, null/empty
finals, finish-reason capture, schema diagnostics, body-free hashes/counts,
strict requested-model validation, and exact one-attempt behavior on provider,
schema, redirect, and transport failures.

These repairs do not themselves constitute Independent QA PASS. Re-review must bind to the new exact head/tree and successful CI.

## CLI

```bash
python -m b2.blind_eval \
  --context-file /private/context.txt \
  --prompt-file /private/prompt.txt \
  --provider provider-a \
  --model exact-model-id \
  --endpoint https://provider.example/v1/chat/completions \
  --api-key-env PROVIDER_API_KEY \
  --raw-output /private/run-001.raw.txt \
  --receipt-output /private/run-001.receipt.json \
  --authorize-live-call
```

Without `--authorize-live-call`, the command must terminate `NOT_EVALUABLE` before credential lookup and before network access.

## Relationship to B1 and B2

B1 Search Cup remains independent. This bridge does not modify B1 PR #17 and does not reuse Search Cup search/tool/submission semantics.

This bridge is B2 infrastructure, not a formal Evaluation Family. It therefore does not invent an Errorbook seed merely to justify infrastructure. Any model failure observed through this bridge still enters the normal B2 continuous-operation path: Errorbook intake → mechanism → public-safe transformation → formal regression family only when the B2 Seed Gate is satisfied.

## Merge boundary

Draft PR only until Independent QA reviews the exact repaired head/tree, verifies privacy/secret/redirect/output-commit/terminal semantics and full regression CI, and returns PASS. Merge additionally requires explicit authorization.
