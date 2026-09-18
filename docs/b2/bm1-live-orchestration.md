# BM1 Window-Controlled RUN-READY and Live Orchestration

Status: offline implementation surface only. This document does not authorize a
RUN-READY preparation, provider request, spend, merge, or live execution.

Authority: `WO-B2-BM1-PORTABILITY-01 v0.1`, approved for implementation on
2026-09-18; parent `WO-B2-BM1-RUNREADY-RECOVERY-01 v0.1`.

Dedicated Control Issue: [#50](https://github.com/aerenkolstein-code/llm-evaluation-lab/issues/50).
The issue number is an immutable code/workflow/test constant; it is not a
repository variable.

## 1. Refreshed admission baseline

The portability implementation fresh-pins:

- commit `a583f6042dbfd78d251434141cdbf9b86cb910a9`;
- tree `669c6cb0785aaa5cead04d0b009c14f70a7d98af`.

This is the exact draft-time baseline; all six recorded workflow/module/test/
runbook blobs match. The only changed paths are the two private workflows,
new `.github/workflows/b2_bm1_portability_offline.yml`, `b2/bm1.py`,
`b2/bm1_live.py`, their two existing test files, and the two existing BM1
runbooks. No manifest, schema, fixture, provider/scorer, ordinary CI or Blind/
B1/A2 path changes. A tenth path requires a separate scope approval.

The parent implementation admission baseline was `4b38aa52...` / tree
`61385d6...`; the current portability baseline above supersedes it for this PR.

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

The public-safe repository Actions variable `B2_BM1_RUNNER_OS` must equal
exactly `linux` or `windows`. Missing/invalid values fail the public gate before
any private job is eligible. It outputs the validated OS. Each workflow has two
mutually exclusive private jobs with cumulative labels:

| Selected OS | Required labels |
|---|---|
| `linux` | `self-hosted`, `linux`, `x64`, `b2-bm1-private` |
| `windows` | `self-hosted`, `windows`, `x64`, `b2-bm1-private` |

Both jobs use Python script steps, including summary publication, without bash
or PowerShell interpolation of private inputs. A credential-free first step
checks actual OS/architecture against the configured, gated and literal lane OS.
The same check repeats at runtime entry before credential/storage reads. On
Windows `IsWow64Process2` must confirm native AMD64, excluding x86 and ARM64
emulation. Self-hosted labels alone are insufficient evidence.

Changing the OS is configuration, never authorization. After RUN-READY, the
selected lane rederives both storage Authorities and compares them to the
archived receipt before creating transports. Changing platform/storage requires
a new RUN-READY; schemas v2/v3 remain unchanged. There is no macOS, ARM64,
Windows-as-WSL, or GitHub-hosted private execution lane.

Environment `b2-bm1-live` holds the protected configuration.
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
| `B2_BM1_RAW_BUNDLE_DIR` | Absolute path of a pre-existing persistent raw-bundle directory meeting the OS-specific policy below |
| `B2_BM1_ATTEMPT_CLAIM_DIR` | Absolute path of a separate pre-existing persistent claim directory meeting the OS-specific policy below |
| `OPENAI_API_KEY` | Present and non-empty |
| `GEMINI_API_KEY` | Present and non-empty |
| `GOOGLE_API_KEY` | Absent/empty; if present it creates forbidden ambiguity |
| `B2_BM1_GEMINI_KEY_AUTH_BINDING_HMAC_KEY` | Independent private HMAC key, at least 32 UTF-8 bytes; never reuse the Gemini credential |
| `B2_BM1_GEMINI_KEY_AUTH_IDENTITY_HMAC` | `hmac-sha256:<64hex>` computed from that HMAC key and the exact attested `GEMINI_API_KEY` value |

No private path, credential value, authorization header, request body, response
body, reasoning body, or final answer body is printed, placed in a comment,
written into a public receipt, or included in this runbook.

## 5. Google Auth-key evidence

Current Google policy says newly created AI Studio keys are Auth keys and
Standard keys are rejected beginning September 2026. The preferred path is a
manual rotation to a newly created AI Studio key, configured only as
`GEMINI_API_KEY`. If an existing key is retained, the user must inspect AI
Studio and attest that `Key Type=Auth`.

At the same manual attestation/rotation boundary, provision an independent
private HMAC key and calculate `HMAC-SHA256(binding key, exact GEMINI_API_KEY)`.
Store the key and the resulting `hmac-sha256:<64hex>` as the two private secrets
above. They must be rotated/recomputed together whenever the Gemini credential
changes. The HMAC key, expected HMAC, and credential value are never projected.

The runtime checks the explicit status and attestation, recomputes the identity
HMAC from the credential actually configured for that job, and compares it to
the attested value with a constant-time comparison. It then binds only a second,
public-safe SHA-256 fingerprint of the attestation/HMAC pair into credential
decision v2. Live repeats the private comparison before either provider
transport is constructed and also requires the resulting credential-decision
fingerprint to equal the RUN-READY receipt. Replacing `GEMINI_API_KEY` while
leaving its Auth evidence unchanged therefore fails closed before provider
traffic. The runtime still never infers key type from a secret prefix.

## 6. Storage Authority and durability

The runtime never creates or repairs storage directories/ACLs. Both OSes require
pre-existing absolute, separate, non-nested roots outside the workspace and
known temporary roots. Public receipts expose only opaque fingerprints.

### Linux x64

The original directory identity tuple remains byte-for-byte compatible:
`storage_kind + SHA-256(resolved path) + device + inode`, using the same JSON
keys and encoding. Effective UID ownership, exact `0700`, no target/ancestor
symlinks, and workspace/`/tmp`/`/var/tmp`/`/dev/shm` exclusions remain required.
Probes and archives are `0600`. One-shot files use exclusive create, file fsync,
parent-directory fsync, and readback; reads reject symlinks, wrong owners/modes
and hard links. The Linux probe retains durable deletion and directory fsync.

### Native Windows x64

Only a fixed local NTFS volume with persistent ACL support is accepted.
UNC/device paths, ADS, relative/trailing-dot/space aliases, remote/removable/
non-NTFS volumes and temporary/workspace roots fail closed. Canonical spelling
is checked using the opened handle; short-name aliases cannot hide a forbidden
root. Every ancestor and target is opened with `FILE_FLAG_OPEN_REPARSE_POINT`
and checked for reparse/temporary/type attributes. Junctions, mount points and
other reparse points are rejected. Ancestor handles remain held without write
or delete sharing throughout an operation, including close/reopen readback.

Approved ACL policy `bm1-windows-acl/v1`:

- Owner SID must equal the process token's runner service account SID;
  impersonated threads are rejected.
- DACL must be protected; only explicit simple allow ACEs are accepted.
- The runner must have explicit `FILE_ALL_ACCESS`. Optional SYSTEM and BUILTIN
  Administrators ACEs may grant only defined file rights. Every other SID,
  including Everyone, Authenticated Users and BUILTIN Users, is rejected.
- Inherited, inherit-only, deny, object and callback ACEs are rejected. Only
  object/container inheritance flags are allowed on explicit ACEs.
- Runtime reads security descriptors through Win32 APIs, never localized ACL
  command output. No third-party runtime dependency is introduced.

Windows Authority hashes `storage_kind`, platform `windows`, SHA-256 of the
canonical case-normalized handle path, 64-bit volume serial, 128-bit file ID,
and the validated owner/control/DACL fingerprint. SID, ACL and path bodies
remain private. Directory replacement, file/volume-ID change or an otherwise
approved ACL change produces a different Authority; unsafe ACL drift blocks.

Critical files are created via `CreateFileW(CREATE_NEW)` with a runner-owned,
protected runner-only DACL at creation, `FILE_FLAG_WRITE_THROUGH`, checked
`WriteFile`, and checked `FlushFileBuffers`. The file closes, reopens, rechecks
its identity/ACL and reads back all bytes. Failures leave an exclusive-create
tombstone and never permit overwriting/retrying that attempt. Raw evidence and
claim files reject hard links. No Windows directory-fsync surrogate is used.
Tiny immutable probe files remain private in the store to avoid representing
best-effort deletion as durable metadata. They must be included in future
private-storage retention planning; this implementation does no production
provisioning or deletion.

[Microsoft's CreateFileW documentation](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-createfilew)
describes NTFS metadata flushing for write-through requests.
[FlushFileBuffers](https://learn.microsoft.com/en-us/windows/win32/api/fileapi/nf-fileapi-flushfilebuffers),
[GetSecurityInfo](https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-getsecurityinfo)
and [GetFileInformationByHandleEx](https://learn.microsoft.com/en-us/windows/win32/api/winbase/nf-winbase-getfileinformationbyhandleex)
provide the flush, ACL and stable handle-identity interfaces used here.
Hardware that does not honor flush/write-through guarantees is outside the
accepted substrate; offline tests do not simulate sudden physical power loss.

### Revalidation and restart

Refreshing stores repeat private-boundary checks and durable probes when
`BM1Runner` reads Authority at construction, before claim, before provider send,
and after raw persistence. Replacement, identity/ACL drift, write/flush/readback
failure stops before the next provider boundary. The archived RUN-READY is
exclusive-created and read back. Reopening the same claim store in a fresh
process still rejects a previously claimed frozen attempt ID.

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

- exact nine-path diff against the pinned portability baseline;
- focused core/orchestration tests on native `ubuntu-latest` and `windows-latest` x64;
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

## 11. Portability CI and handoff

`.github/workflows/b2_bm1_portability_offline.yml` runs only offline tests on
hosted Linux/Windows x64. It has no production Environment, repository provider
secret reference, Issue #50 comment handling, or provider endpoint. The test
process rejects socket connection and DNS operations. All credentials, bodies
and events in tests are synthetic. Test-only ACL hardening never applies to
production stores. Existing complete repository CI remains unchanged on Linux.

Windows tests cover real NTFS handles/ACLs, broad/inherited and owner failures,
junctions/ancestor reparse, disjoint roots, directory replacement, ACL drift,
exclusive creation, flush/readback failure, cross-process claim reuse, and
post-claim/pre-send rejection. Remote/removable/non-NTFS classification failures
are fault-injected at the native API boundary. Actual attachment of these
unsupported volume types is NOT_EVALUABLE on hosted CI; no network share is
contacted. Non-native OS test groups are explicitly skipped on the other OS.

After exact-head Linux/Windows CI and full regression results are published,
STOP for distinct Independent QA. QA PASS does not authorize merge. A091 stays
PAUSED until independent acceptance, separate merge approval, merge and
post-merge CI. This work does not configure an Environment/runner/variable/
secret, read production credential values, create a production HMAC/storage
root, post an Issue #50 trigger, call a provider or incur spend.
