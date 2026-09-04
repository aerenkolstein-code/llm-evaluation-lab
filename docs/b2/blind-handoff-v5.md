# B2 Blind Handoff v5

Status: execution-only repair branch; no provider call is permitted until the
run-bound no-provider smoke has completed and the private orchestrator has
decrypted and verified its synthetic result.

## Repair boundary

This protocol repairs only the transport/orchestration failure that prevented
the accepted B2 blind-eval bridge from receiving its byte-frozen input.  It is
based on `main@901ba05b99c413d45415c474c71b5969c155dea1`; the workflow verifies
that the `b2/blind_eval.py` blob is byte-identical to that accepted base before
continuing.

The historical execution branch and its fixed `payload_pointer.json` plus
arbitrary payload URL are not valid v5 inputs.  v5 accepts exactly one payload
at:

```text
blind-handoff/v5/<workflow_run_id>/<input_public_key_sha256>/payload.json
```

It accepts the challenge acknowledgement only at the sibling path
`challenge-ack.json`.  The runner performs a same-origin GitHub Contents read
without redirect following; the payload contains no URL.

## Cryptographic and evidence binding

Every encrypted envelope is authenticated with canonical JSON additional data
that freezes:

- workflow run ID and exact execution head;
- accepted bridge main commit;
- ephemeral input public-key SHA-256;
- run-unique return public-key SHA-256;
- context and prompt SHA-256 plus exact byte counts;
- `smoke` or `live` mode and the evaluation run ID.

RSA-OAEP-SHA256 wraps a fresh AES-256 key. AES-GCM authenticates both the body
and all binding fields. Both RSA key pairs must contain at least 3072 bits.
Archives have an exact, flat member allowlist, per-member SHA-256/byte evidence,
duplicate-name rejection, and bounded compressed and uncompressed sizes.

## Return-key proof gate

The private orchestrator generates a new return key pair, a random challenge,
and a random acknowledgement key for every workflow run. Only the return public
key, challenge, and acknowledgement key enter the encrypted input package.

The runner must encrypt the challenge under the return public key. The private
orchestrator decrypts and compares the exact 32 challenge bytes, then publishes
a run-bound HMAC-authenticated acknowledgement. The runner verifies that HMAC
before opening the execution gate. A missing, stale, forged, or cross-run
acknowledgement fails closed before any provider credential lookup.

## No-provider smoke

`.github/workflows/b2_blind_handoff_v5_smoke.yml` exercises the whole handoff:

1. exact-base verification;
2. ephemeral input public-key artifact publication;
3. run-scoped encrypted payload receipt and frozen-input verification;
4. return-key challenge, private-side decryption, and authenticated ack;
5. deterministic synthetic result encryption and artifact publication;
6. private-side result decryption and evidence verification.

The workflow does not reference a provider credential, endpoint, or model. Its
receipt asserts `provider_attempts = 0` and `automatic_retries = 0`. A GitHub job
success alone is insufficient: the smoke is GREEN only after the private
orchestrator decrypts and verifies the final synthetic result.

## Publish order and cleanup

For each run, the input public-key artifact is published first. The external
orchestrator then commits the single complete encrypted payload. The challenge
artifact follows, and the authenticated acknowledgement is committed last as
the challenge gate marker. The encrypted result artifact is published only
after that gate.

Run-scoped rendezvous files are temporary public ciphertext/metadata and must be
deleted after the encrypted result is downloaded and privately verified. Input
and return private keys, plaintext inputs, raw model answers, and scoring
material never enter the public repository or workflow logs.

## Live-run boundary

A live workflow may be added only after the no-provider smoke is GREEN. It must
retain all v5 gates, invoke `b2.blind_eval` exactly once with
`automatic_retries = 0`, and encrypt either the complete PASS evidence pair or
the body-free `NOT_EVALUABLE`/`ERROR` receipt. Infrastructure or provider
failure is not a model-quality score and must not trigger an automatic retry.
