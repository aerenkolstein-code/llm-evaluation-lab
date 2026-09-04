# B2 Blind Handoff v5.1

Status: durable review implementation for `WO-B2-BLIND-02`; offline and
deterministic only. Engineering completion does not approve a live run, mark
the historical Q1-R1 result scorable, satisfy Independent QA, or authorize a
merge.

## Authority and trigger boundary

The durable tree contains no live provider workflow. The historical push-bound
live workflow was removed, so pull requests, review-branch pushes, ordinary CI,
documentation changes, and the smoke workflow have no provider or credential
lane. A future live workflow requires a separately authorized work order and
must be reviewed as a new exact-head change before it can exist or run.

`.github/workflows/b2_blind_handoff_v5_smoke.yml` is intentionally safe to run
on pull requests, the PR #33 review branch, or manual dispatch. It imports no
credential, invokes no provider adapter, and asserts `provider_attempts = 0`,
`credential_lookups = 0`, and `automatic_retries = 0`.

The one-line `.github/workflows/test.yml` dependency change is necessary: the
full repository suite now imports the handoff module, whose optional
`blind-handoff` extra supplies `cryptography`. It does not add a live adapter or
credential path.

## Private and public boundary

Private-only material includes context and prompt bodies, input/return private
keys, acknowledgement keys, challenge plaintext, reasoning bodies, final-answer
bodies, credentials, authorization headers, scoring material, and private
locators. None may be committed to the repository or printed in workflow logs.

Public-safe evidence is limited to protocol/status labels, exact run and commit
identities, strict token-like provider metadata, timestamps/expiry, byte counts,
SHA-256 fingerprints, zero-retry/attempt counters, and encrypted envelopes.
Encryption does not make a real run object durable source code: the historical
run-scoped `payload.json` and `challenge-ack.json` are removed from the final
tree. Any future exchange objects must live in a separately authorized,
run-scoped ephemeral lane with explicit deletion; synthetic fixtures must say
that they are synthetic and non-private.

## Identity binding and freshness

Every v5.1 envelope authenticates the complete canonical binding as AEAD
additional data and repeats it inside the encrypted archive. The binding
contains:

- a run-unique `handoff_id` and `workflow_run_id`;
- exact execution-head and accepted bridge-main SHAs;
- ephemeral input and return public-key SHA-256 fingerprints;
- context and prompt SHA-256 plus exact byte counts;
- handoff mode, evaluation run ID, issue time, and expiry time.

The maximum lifetime is six hours, with only five minutes of forward clock skew.
Expired and not-yet-valid payloads, challenges, acknowledgements, and results
fail closed. A different run, head, bridge base, key, fingerprint, mode, or
evaluation ID is not accepted as “close enough.”

RSA-OAEP-SHA256 wraps a fresh AES-256 key and AES-GCM authenticates each body and
binding. RSA keys are at least 3072 bits. ZIP packages use exact flat-member
allowlists, duplicate-name rejection, bounded compressed/uncompressed size, and
per-member byte/hash evidence.

## Return proof, replay defense, and publication

The private side proves possession of the matching return private key by
decrypting an exact 32-byte challenge and returning a binding-bound HMAC
acknowledgement. The runner records the accepted acknowledgement as a one-time,
exclusive claim before any future provider gate may open. Payload, challenge,
acknowledgement, result-start, and result-accept claims cannot be overwritten;
reuse is a replay/collision error.

State directories and verified result directories are staged completely and
published by atomic rename. Existing/partial directories, parent-child path
collisions, same-file aliases, and symlink traversal fail closed. PASS output
publication remains a pair: a receipt cannot survive as PASS without its
matching private raw body, and a publication failure rolls the pair back.

## EMPTY_FINAL_CONTENT observability

The body-free v2 blind-eval receipt distinguishes transport success from
scorability. When supplied by the provider, it retains:

- HTTP status, strictly sanitized requested/resolved model IDs and response ID;
- strictly sanitized `finish_reason`;
- JSON, response-schema, and message-schema parse status;
- reasoning-field presence, UTF-8 byte count, and SHA-256 only;
- final-content-field presence, UTF-8 byte count, and SHA-256 only when non-empty;
- normalized non-negative usage/token metadata;
- provider-attempt count, `automatic_retries = 0`, terminal status, diagnostic
  error code, and `quality_score = null`.

Reasoning and final bodies never enter the receipt. HTTP 200 is not PASS.
Reasoning with a null/empty final is
`NOT_EVALUABLE / EMPTY_FINAL_CONTENT` and has no quality score. A non-empty final
permits bridge-level PASS only; it does not establish answer correctness or a
benchmark GREEN result.

## Deterministic smoke and cleanup

`python -m b2.blind_handoff deterministic-smoke` creates only labeled synthetic
bytes, performs input encryption/decryption, full binding checks, return-key
proof, authenticated acknowledgement, result encryption/decryption, and
evidence verification. It never looks up a credential or calls a provider.

The smoke uses one explicit ephemeral root and removes it through the protocol's
verified cleanup routine. Cleanup does not follow symlinks, rejects broad roots,
surfaces any deletion failure, and reports success only after the root is gone.
A cleanup failure is therefore an explicit non-PASS condition rather than
manual aftercare.

## Historical Q1-R1 status

The earlier run remains exactly:

`HISTORICAL-EXECUTION-ONLY / HTTP 200 / EMPTY_FINAL_CONTENT / NO SCORABLE ANSWER / NOT_EVALUABLE`

This repair adds the diagnostics that a future separately authorized run would
need. It does not retroactively manufacture missing evidence, relabel the run,
or authorize R1b.
