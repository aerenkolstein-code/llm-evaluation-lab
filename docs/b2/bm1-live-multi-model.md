# BM1 — Live Multi-Model Harness + Provenance Smoke

**Status:** P2 offline implementation / Pre-Live IQA repair. This document authorizes no provider call, credential lookup, spend, merge, RUN-READY, BM2 result, or model ranking.

BM1 carries the frozen BM0 measurement contract across two provider protocols on the same public-safe E11 TARGET/CONTROL pair. Its claim is evidence-chain validation, not comparative model quality.

The P2 baseline remains `main@74304a23d7e542b28dcd519f9b58d394447fc696`, tree `84f5bc1a56f8c93c92717cf928dc928a63ab118f`. Scope remains exactly five paths: `b2/bm1.py`, `schemas/bm1_live_smoke_manifest.schema.json`, `cases/b2/public-safe/benchmark/bm1-live-smoke-manifest.json`, `tests/test_b2_bm1.py`, and this file. Any sixth path requires separate explicit approval.

## 1. Frozen measurement object

BM0 entry E11 is fixed: family `constraint-action-persistence`, target class `MODEL_DIRECT`, TARGET `B2-QA2-R-CONSTRAINT-KB-001`, CONTROL `B2-QA2-R-CONSTRAINT-CTRL-001`, seed `QA2-SEED-A01`. Fixtures are synthetic/public-safe. The wrapper asks for one JSON `decision`; TARGET expects `DECLINE_CONFLICTING_ASSISTANCE`, CONTROL expects `PROVIDE_BOUNDARY_COMPATIBLE_HELP`. Provider/runtime/evidence failures stay separate from model failure.

## 2. Frozen roster and runtime

| Provider | Requested model | Endpoint | Reasoning | Sampling |
| --- | --- | --- | --- | --- |
| OpenAI | `gpt-5.6-terra` | Responses API | low | provider default; temperature/top_p omitted |
| Google | `gemini-3.8-flash` | Interactions API | low | provider default; temperature/top_p/top_k omitted |

Attempt order is OpenAI TARGET, OpenAI CONTROL, Google TARGET, Google CONTROL. Maximum planned provider requests = 4; automatic retries = 0; fallback/model substitution = 0; one provider request per attempt; input guard = 8,000 tokens; output guard = 2,000 tokens; timeout = 120 seconds; second provider-local error triggers global stop. USD 0.20 is a future live-smoke ceiling, not spending permission.

## 3. Pre-Live IQA Round-1 repair

Round 1 identified four live-boundary defects. P2 now closes them fail-closed without expanding the five-path envelope.

### 3.1 Network send is sealed behind the canonical runner

The public `call()` method of both live HTTP transports always raises `BM1AuthorizationError`; it cannot reach the opener/provider. An actual network send is available only through the internal prepared-call path after `BM1Runner` has validated live authority, checked the frozen attempt sequence and request/cost ceilings, consumed a durable attempt claim, and minted a runner-bound one-shot capability. The transport verifies the runner/provider/endpoint and authority fingerprints and rejects capability reuse before opening the network connection.

Direct transport invocation therefore cannot bypass the durable claim store, request ceiling, sequence guard, or no-rerun rule. Any rerun still requires a new `attempt_id` plus new explicit authorization.

### 3.2 RUN-READY and user approval use an independently anchored chain

Live authorization is `b2-bm1-live-authorization/v2`. A syntactically valid fingerprint or a self-hashed authorization object is not sufficient.

A live runner must receive:

1. an actual canonical `b2-bm1-run-ready/v1` receipt bound to the manifest, exact post-merge commit/tree, exact four attempts, runtime limits, provider/credential authority digests, and the frozen raw-bundle destination;
2. a separate `LiveAuthorityAnchor` supplied by the authorized runtime, containing the trusted expected RUN-READY receipt fingerprint and the trusted explicit-user-authorization fingerprint;
3. a live-authorization v2 object whose RUN-READY fingerprint, user-authorization fingerprint, raw destination fingerprint, attempt set, limits, head/tree, issue/expiry window, and self-fingerprint all match that trusted chain.

The harness never derives the trusted anchor values from the live-authorization object being validated. Arbitrary/unknown RUN-READY digests and self-minted user-approval digests fail before any provider call.

## 4. Authorization time is checked at use time

Authorization expiry is not a constructor-only check. The live authorization is revalidated immediately before the durable attempt claim and again inside the prepared HTTP send immediately before the opener is invoked. A process created while authorization is valid cannot sleep past expiry and then send. Expiry-after-initialization tests require zero provider/opener calls and no durable attempt claim.

## 5. Durable raw evidence is a live prerequisite

`InMemoryRawEvidenceSink` is explicitly test-only (`is_durable = False`) and cannot be used with a live runner.

RUN-READY freezes an opaque raw-bundle destination identity and its canonical destination fingerprint. Live execution requires a durable sink whose `destination_id` and `destination_fingerprint` match that RUN-READY object before any provider call. `FileRawEvidenceSink` writes one append-only attempt record with exclusive create, file `fsync`, directory `fsync`, and readback. The public attempt receipt exposes only durability and destination fingerprint, never the private filesystem path or provider body.

A volatile sink, missing destination, or wrong destination fails before provider invocation. After a live response, the runner also verifies `DURABLE_FSYNC_READBACK` and the exact destination fingerprint before accepting the evidence projection.

## 6. Durable one-shot attempt claim

The live claim schema is `b2-bm1-attempt-claim/v2`. Before a network send, `FileAttemptClaimStore` durably consumes the attempt ID using exclusive-create + file fsync + directory fsync + readback. The claim binds manifest, live-authorization fingerprint, trusted RUN-READY fingerprint, trusted user-authorization fingerprint, raw-bundle destination fingerprint, authorization ID, execution commit/tree, attempt/trial/sequence, provider/model, case and variant.

Crash after claim still consumes the attempt. Restarting with the same attempt is rejected before provider send. Claims are not silently deleted or rolled back by the harness.

## 7. Identity, receipts and replay

Requested model ID is not proof of resolved identity. Missing or mismatched resolved identity becomes `NOT_EVALUABLE / IDENTITY_NOT_AUDITABLE`; no alias substitution is silently accepted.

For a called attempt, the public receipt records only audit-safe metadata/fingerprints: manifest/trial/attempt/provider/endpoint/requested+resolved identity, adapter/wrapper/runtime controls, case/prompt/request fingerprints, durable attempt-claim fingerprint, timestamps/latency, provider/HTTP/terminal state, raw/final fingerprints and byte counts, usage/cost attribution, scorer/oracle fingerprints, evidence durability/destination fingerprint, and replay availability. It contains no request/response/final/reasoning body, credential, auth header, or private path.

`replay_scorer()` reads the private evidence, verifies request/raw/final fingerprints against the public receipt, and reruns the deterministic E11 scorer.

## 8. Provider and secret boundary

P2 code does not read process environment variables or repository secrets. Credential values can only be explicitly supplied to a future separately authorized live runtime. OpenAI uses symbolic reference `OPENAI_API_KEY`; Google uses `GEMINI_API_KEY`, and simultaneous `GEMINI_API_KEY` + `GOOGLE_API_KEY` references are rejected as ambiguous. Secrets remain only in the transport header construction and are excluded from request fingerprints, claims, raw-evidence receipts, public receipts and replay inputs.

## 9. Provider-free verification

`tests/test_b2_bm1.py` remains provider-free and covers the original BM1 contract plus Round-1 adversarial regressions:

- exact manifest/baseline/E11/roster/four-attempt/five-path binding;
- requested/resolved identity and no substitution;
- four attempts, zero retries/fallback, no fifth request;
- first-error/second-error stops, token/cost guards and replay tamper rejection;
- direct HTTP transport call denied with opener count zero;
- arbitrary RUN-READY and self-minted user approval rejected against trusted anchors;
- expiry-after-initialization rejected before claim/provider;
- in-memory and wrong-destination raw sinks rejected before provider;
- canonical live path consumes durable claim and writes durable destination-bound raw evidence;
- same-attempt restart rejected before second provider send;
- header isolation and absence of process-environment credential discovery/third-party HTTP dependencies.

Ordinary repository CI remains offline and no workflow modification belongs to BM1 P2.

## 10. Ordered gates

1. P2 offline repair: exact five paths; focused/adversarial + full offline CI; fresh engineering READY.
2. Distinct Pre-Live IQA Round 2 on the new exact head/tree.
3. Separate user merge authorization only after IQA GREEN.
4. Post-merge RUN-READY: fresh exact main/provider/model/API/region/pricing authority; credential presence/type without values; exact private raw-bundle destination; exact durable attempt-claim directory; actual RUN-READY receipt; independent trusted authority anchors.
5. Separate bounded live authorization: at most four predeclared requests, zero retry/fallback/substitution, within spend ceiling.
6. Final Independent QA: reconcile all attempts/claims, replay scoring, identity/provenance/cost/terminal distribution, publish public-safe evidence only.

Pre-Live IQA PASS does not itself authorize merge or live execution.

## 11. Claim ceiling

BM1 can support the claim that a vendor-neutral evidence-preserving evaluation harness was implemented and validated for two provider protocols on one frozen public-safe TARGET/CONTROL pair with exact identity accounting, zero hidden retry/fallback, durable one-shot consumption, bounded cost/attempt semantics, destination-bound replayable evidence, and a separately anchored authorization chain.

BM1 cannot support a model ranking, a model×family benchmark profile, a representative real-world error rate, or a population prevalence estimate. Code capability is not execution authority: the authorized P2 state remains zero credential lookup, zero authenticated provider calls, zero live execution, zero spend, and zero merge by implication.
