# BM1 Window-Controlled RUN-READY and Live Orchestration

Status: offline implementation surface only. This document does not authorize a
RUN-READY preparation, provider request, spend, merge, or live execution.

Authority: `WO-B2-BM1-RUNREADY-RECOVERY-01 v0.1`.

Dedicated Control Issue: [#50](https://github.com/aerenkolstein-code/llm-evaluation-lab/issues/50).
The issue number is an immutable code/workflow/test constant; it is not a
repository variable.

## 1. Refreshed admission baseline

The work order was drafted against main `8a6582afbff96541030a997566966721f945fb11`.
Before implementation, main was re-frozen at:

- commit `4b38aa52cc71f12c31b69a61b7737092144b912e`;
- tree `61385d6a2eda8c7e800d3723440e4982f4b99c66`.

The intervening merge contains only the authorized R1b window-control surface
and has no overlap with this work order's five new BM1 paths. The BM1 manifest,
E11 TARGET/CONTROL pair, provider roster, scorer, oracle, attempt order, retry
policy, fallback policy, token ceilings, and spend ceiling remain unchanged.

Provider facts were refreshed from official sources on 2026-09-05. The accepted
provider-Authority fingerprint is
`sha256:b6c19fa563d0c5a110879546195ac7ad34aec34c51b0edac66bb5c8c0e998022`.
The reviewed facts remain:

- OpenAI `gpt-5.6-terra`, Responses API `/v1/responses`, reasoning effort
  `low`, standard text price USD 2.00/M input and USD 12.00/M output, Spain
  supported;
- Google `gemini-3.8-flash`, Interactions API `/v1beta/interactions`, thinking
  level `low`, provider-default sampling with `temperature`, `top_p`, and
  `top_k` omitted, standard price through 2026-12-31 of USD 0.75/M input and
  USD 3.75/M output, Spain supported.

Official sources:

- <https://developers.openai.com/api/docs/models/gpt-5.6-terra>
- <https://help.openai.com/en/articles/5347006-openai-api-supported-countries-and-territories>
- <https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash>
- <https://ai.google.dev/gemini-api/docs/interactions-overview>
- <https://ai.google.dev/gemini-api/docs/pricing>
- <https://ai.google.dev/gemini-api/docs/available-regions>
- <https://ai.google.dev/gemini-api/docs/api-key>

Any later model, API, region, price, or key-policy drift must fail closed and be
re-reviewed before a canonical RUN-READY receipt is prepared.

## 2. Two isolated workflows

| Workflow | Accepted comment | Private effect |
|---|---|---|
| `.github/workflows/b2_bm1_run_ready.yml` | `B2-BM1-RUNREADY-PREPARE/v1` | Presence/metadata/storage checks and one canonical `b2-bm1-run-ready/v2` receipt; zero provider requests and zero spend |
| `.github/workflows/b2_bm1_live.yml` | `B2-BM1-WINDOW-LIVE-APPROVAL/v1` | Loads the exact archived RUN-READY receipt and, only after all gates pass, executes the frozen four-attempt plan |

Both workflows accept only `issue_comment.created`. Before a private runner can
be selected, a public GitHub-hosted gate requires all of the following:

- repository `aerenkolstein-code/llm-evaluation-lab`;
- Control Issue `#50`, not a pull request;
- `github.actor`, `comment.user.login`, and event sender all equal
  `aerenkolstein-code`;
- `comment.author_association=OWNER`;
- repository default branch `main`, `GITHUB_REF=refs/heads/main`, and checked-out
  `HEAD=GITHUB_SHA`;
- reviewed workflow file loaded from `refs/heads/main`;
- first workflow attempt only; reruns are rejected;
- strict canonical ASCII JSON bytes, with no duplicate/extra keys, control
  characters, non-finite numbers, whitespace variants, or trailing newline.

Edited or deleted comments have no trigger and no authority. Public gates have
no credential or private-storage inputs.

## 3. Exact comment contracts

The RUN-READY preparation comment is exactly one line:

```json
{"comment_type":"B2-BM1-RUNREADY-PREPARE/v1"}
```

It grants only a zero-provider, zero-spend preparation. The workflow archives
and reads back the canonical receipt, publishes the public-safe receipt and its
fingerprint in the Actions summary, creates no live authorization, and stops.

A later live approval is also one canonical line, with reviewed concrete values
substituted for the placeholders:

```json
{"authorization_id":"<ONE-NEW-OPAQUE-ID>","comment_type":"B2-BM1-WINDOW-LIVE-APPROVAL/v1","confirm_four_attempts":true,"max_spend_usd":"0.20","run_ready_receipt_fingerprint":"sha256:<EXACT-64-LOWERCASE-HEX>"}
```

The exact RUN-READY fingerprint must also be the protected expected fingerprint.
The authorization ID is single-use, and the comment expires 3,600 seconds after
its GitHub `created_at`. A different receipt, a stale main commit/tree, a rerun,
or a locally constructed but unposted authorization fails before provider
traffic.

## 4. Private runtime prerequisites

The dedicated runner labels are `self-hosted`, `linux`, `x64`, and
`b2-bm1-private`. Environment `b2-bm1-live` holds the protected configuration.
Provisioning or changing these values is a separate manual operation and is not
authorized by this implementation work order.

Protected variables:

| Name | Required contract |
|---|---|
| `B2_BM1_PROVIDER_AUTHORITY_FINGERPRINT` | Exact accepted provider-Authority fingerprint above |
| `B2_BM1_PROVIDER_REVIEWED_AT` | UTC timestamp of a fresh official-source review, no older than 24 hours |
| `B2_BM1_GEMINI_KEY_AUTH_STATUS` | `ROTATED_NEW_AI_STUDIO_AUTH_KEY` or `EXISTING_AI_STUDIO_KEY_TYPE_AUTH_VERIFIED` |
| `B2_BM1_GEMINI_KEY_AUTH_ATTESTATION_FINGERPRINT` | Public-safe `sha256:<64hex>` attestation; never the key or screenshot body |
| `B2_BM1_RAW_BUNDLE_ID` | Opaque, non-path raw-store label |
| `B2_BM1_ATTEMPT_CLAIM_STORE_ID` | Opaque, non-path claim-store label |
| `B2_BM1_RUN_READY_RECEIPT_FINGERPRINT` | Set only after independent review of the exact prepared receipt; used by the live public gate |

Private secrets:

| Name | Required contract |
|---|---|
| `B2_BM1_RAW_BUNDLE_DIR` | Absolute path of a pre-existing, owner-only `0700`, persistent raw-bundle directory |
| `B2_BM1_ATTEMPT_CLAIM_DIR` | Absolute path of a separate pre-existing, owner-only `0700`, persistent claim directory |
| `OPENAI_API_KEY` | Present and non-empty |
| `GEMINI_API_KEY` | Present and non-empty |
| `GOOGLE_API_KEY` | Absent/empty; if present it creates forbidden ambiguity |

No private path, credential value, authorization header, request body, response
body, reasoning body, or final answer body is printed, placed in a comment,
written into a public receipt, or included in this runbook.

## 5. Google Auth-key evidence

Current Google policy says newly created AI Studio keys are Auth keys and
Standard keys are rejected beginning September 2026. The preferred path is a
manual rotation to a newly created AI Studio key, configured only as
`GEMINI_API_KEY`. If an existing key is retained, the user must inspect AI
Studio and attest that `Key Type=Auth`.

The runtime checks the explicit status plus a public-safe attestation
fingerprint. It never infers key type from a secret prefix. Credential presence,
Google precedence, Auth-key status, and attestation are canonicalized into a
body-free credential-decision fingerprint. Live execution recomputes that
fingerprint and requires it to equal the RUN-READY binding.

## 6. Storage Authority and durability

The runtime never creates replacement storage directories. It rejects missing,
relative, symlinked, non-`0700`, wrong-owner, workspace, `/tmp`, `/var/tmp`,
`/dev/shm`, overlapping, or nested roots.

For both stores it binds:

`storage kind + SHA-256(resolved path) + filesystem device + inode`.

Only the resulting Authority fingerprint and opaque label fingerprint enter the
RUN-READY receipt. The path does not. File `fsync`, directory `fsync`, and
readback probes run before use. Refreshing subclasses of the reviewed
`FileRawEvidenceSink` and `FileAttemptClaimStore` rederive and probe Authority
when `BM1Runner` reads it at construction, before a claim, immediately before a
provider send, and after raw evidence persistence. Directory replacement,
device/inode drift, probe failure, archive failure, or readback failure stops
before the next provider boundary.

The RUN-READY receipt is exclusive-created inside the private raw Authority,
fsynced, and read back canonically. The claim store persists across workflow and
process restarts; its reviewed BM1 claim semantics reject reuse of any frozen
attempt ID.

## 7. External AuthorityVerifier

`b2/bm1.py` continues to expose only the `AuthorityVerifier` protocol. The outer
runtime implements `GitHubIssueCommentAuthorityVerifier`, whose trust input is
the GitHub-provided event file plus the exact workflow-run environment and the
checked-out Git objects.

Every verification reloads and revalidates the event and binds:

- exact canonical RUN-READY receipt fingerprint;
- SHA-256 of the exact live-comment bytes;
- authorization ID;
- Control Issue `#50` and actual positive comment ID;
- OWNER actor/comment/sender identity;
- exact main commit and tree;
- exact reviewed live workflow ref and first workflow-run identity;
- the public-gate outputs carried into the private job.

A self-consistent local RUN-READY and authorization pair, a test double, or a
changed event file is therefore not sufficient to satisfy the production outer
verifier.

## 8. Frozen live execution semantics

The wrapper imports and instantiates the reviewed
`OpenAIResponsesHTTPTransport`, `GoogleInteractionsHTTPTransport`,
`FileRawEvidenceSink`, `FileAttemptClaimStore`, and `BM1Runner`. It imports no
`requests`, `httpx`, `socket`, `urllib`, provider endpoint, or other network-send
primitive. It calls `BM1Runner.run_all()` only; every actual provider opener
remains lexically and operationally owned by `BM1Runner.run_next()`.

The exact attempt order is:

1. `BM1-A01-OPENAI-TARGET`;
2. `BM1-A02-OPENAI-CONTROL`;
3. `BM1-A03-GOOGLE-TARGET`;
4. `BM1-A04-GOOGLE-CONTROL`.

Limits are four provider requests total, one request per attempt, zero automatic
retries, zero fallback/model substitution, 120-second timeout, 8,000 input
tokens and 2,000 output tokens per attempt, and USD 0.20 maximum spend.

Worst-case standard-token cost is:

- two OpenAI attempts: `2 × (8,000×2/1M + 2,000×12/1M) = USD 0.0800`;
- two Google attempts: `2 × (8,000×0.75/1M + 2,000×3.75/1M) = USD 0.0270`;
- four-attempt total: `USD 0.1070 < USD 0.2000`.

The first provider-local failure is recorded with no retry. A second
provider-local failure sets a global stop; unstarted attempts become
`BLOCKED/NOT_RUN`. Public summaries contain only typed status, IDs,
fingerprints, counts, and cost metadata. An HTTP 200 alone is not a quality
finding and no model ranking is authorized.

## 9. Operational stop points

1. Merge is not authorized by this work order. The draft PR must receive a
   distinct independent QA review first.
2. After a separately authorized merge, refresh main/tree, CI, provider facts,
   prices, region, key policy, credential presence/precedence, Auth-key evidence,
   and both storage Authorities.
3. Only then may the exact RUN-READY preparation comment be posted to Issue
   `#50`. Archive/read back the receipt, independently review its complete
   public-safe bytes, record its fingerprint, and **STOP**.
4. Do not set the protected expected receipt or post a live approval until the
   user separately authorizes that exact receipt, authorization ID, four
   attempts, and USD 0.20 ceiling.
5. A live workflow result is evidence to archive and review, not permission to
   retry. Any recovery requires a new work order and new authorization.

## 10. Offline verification gates

The implementation gate requires:

- exact five-new-path diff and no existing-path edit;
- focused orchestration tests;
- existing BM0/BM1 and complete repository tests;
- workflow trigger/static parsing;
- compile/static AST checks proving no wrapper network primitive or second send
  path;
- no-provider smoke with transport constructors asserted unused;
- credential/private-path/body leakage scans;
- distinct independent QA after publication.

Passing these gates establishes only that the production surface is ready for
independent review. It does not create a canonical RUN-READY receipt, authorize
live execution, spend money, or authorize merge.
