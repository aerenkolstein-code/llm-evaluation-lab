# B2 Generic Blind Eval Bridge v0.1

Status: Work Order implementation / pre-Independent-QA.

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
- no tools, no SearchProxy, no browsing, no Search Cup `Submission` contract.
- no hidden scorer/checkpoints are sent to the model.
- no input body or output body is copied into the sanitized receipt.
- API keys are environment-only and never rendered into receipts.
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
- requested/resolved model IDs
- SHA-256 fingerprints and byte counts
- timestamps/duration
- HTTP status/response ID when available
- token usage when available
- terminal status and safe error metadata
- git commit when supplied

Do not commit private inputs or answers into this public repository.

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

Draft PR only until Independent QA reviews the exact head/tree, verifies privacy/secret/terminal semantics and full regression CI, and returns PASS. Merge additionally requires explicit authorization.
