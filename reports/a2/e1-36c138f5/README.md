# ENG-A2-E1-01 — independent A2 return

**Verdict: PASS / STOP / E1 NOT SELF-GREEN**

Work order: [Eval Lab Issue52](https://github.com/aerenkolstein-code/llm-evaluation-lab/issues/52).
A1 candidate: [Companion-Mind Draft PR27](https://github.com/aerenkolstein-code/Companion-Mind/pull/27).

| Identity | Exact value |
| --- | --- |
| Evaluated A1 head | `36c138f53912821732683d40cf994cc776cd1fc9` |
| A1 tree | `45a7426ac4af6f461b182375cb007677bf5c433f` |
| Contract commit | `63ac8d7de8eb35915cc291b0f7ea67c33b366922` / `canonical_event/v1` |
| A2 executed source head | `1e002c0e7995a44eac15ddeb0d48d66369e265d7` |
| A2 executed source tree | `77960381b86030a48dd3fb4760203b9a9ce286fa` |
| A1 manifest file SHA-256 | `4367f83f541d0335b79bef716b7f0a343516ce758336147fbcd9385c697ef645` |
| A2 case catalog fingerprint | `ec9499f3fad63d74838b1c9148a922baf712f5420afff2ea9830a6dd0166e991` |
| Ordered batch input fingerprint | `7db4fc3e266393a13f6bab3e30d365c84d4732035f872fad4cc9b453f4198e75` |
| Harness SHA-256 | `d0e3fe67460620ee141a7b56df2fb39364a3641287963542d8c0efaa4268c6ac` |
| Normalized overall result | `9cdd63f5fbd9e81170aafd414aff4c4373bf52d7a927a3e757596f4e0af32f8b` |
| Observation ledger SHA-256 | `0b622ec7717201673605947ba6eaf6f9fbfddf5a5e1443d89d41459ac367b161` |

The final evidence-package commit is returned in the Draft PR body, avoiding a
self-referential commit field. Its harness bytes must match the hash above.

A1 reference evidence remains separate: exact-head PR27 conformance reports
21 tests, zero failures/errors/skips, A1 internal PASS. Test 124 / run 34992621405
is SUCCESS; CI artifact 10406312340 is explicitly named for GitHub's synthetic
merge 715fc79cb369339b71649938bd3111ccb402cf4a. That synthetic merge is not the
A1 head evaluated by A2. A2 did not execute or import A1 conformance/tests/fixtures.

## Measured results

| Run | Synthetic turns | Complete / partial / failed | Canonical events | Normalized canonical fingerprint |
| --- | ---: | --- | ---: | --- |
| Fresh1 | 120 | 100 / 10 / 10 | 240 | `ac263f6b9bc5830cae75ddfab630d8120ca84f76e139a09f69993273f1dbd186` |
| Fresh2 | 120 | 100 / 10 / 10 | 240 | `ac263f6b9bc5830cae75ddfab630d8120ca84f76e139a09f69993273f1dbd186` |

The two runs use independently fresh store/replica directories and identical
input-derived events. Each turn is explicitly repeated to measure idempotency.
Both completed replica envelopes cover all 240 events; repeated remote IDs remain
stable. All three explicit reopens per run preserve the complete canonical
fingerprint and report zero provider invocations.

| Zero-tolerance metric | Observed deviations across checked snapshots |
| --- | ---: |
| `event_loss` | 0 |
| `sequence_disorder` | 0 |
| `duplicate_amplification` | 0 |
| `destructive_correction` | 0 |
| `synthetic_sentinel_leak` | 0 |
| `semantic_collapse` | 0 |
| `payload_status_drift` | 0 |

3494 checks across 783 CLI subprocess operations: zero failed checks,
zero missing observations. Seven A2 oracle mutation-control unit tests passed,
including loss, duplicate/order, phantom event, payload/status/identity changes,
UNKNOWN collapse, destructive correction, and fail-closed verdict controls.

## Fault and restart matrix

| Fault | Hard exit | Events immediately after recovery | Assistant status | Explicit recovery provider calls | Three reopens | Completed offline readback |
| --- | ---: | ---: | --- | ---: | --- | --- |
| F1 | 86 | 1 | none | 0 | PASS | READBACK_VERIFIED |
| F2 | 86 | 2 | failed | 0 | PASS | READBACK_VERIFIED |
| F3 | 86 | 2 | partial | 0 | PASS | READBACK_VERIFIED |
| F4 | 86 | 2 | complete | 0 | PASS | READBACK_VERIFIED |
| F5 | 86 | 2 | complete | 0 | PASS | READBACK_VERIFIED |
| F6 | 86 | 1 | none | 0 | PASS | READBACK_VERIFIED |
| F7 | 86 | 1 | none | 0 | PASS | READBACK_VERIFIED |
| F8 | 86 | 1 | none | 0 | PASS | READBACK_VERIFIED |
| APPEND_BEFORE_COMMIT | 86 | 0 | none | 0 | PASS | READBACK_VERIFIED |

F1 preserves USER / NOT_SENT, then one explicit same-attempt resume is permitted.
F2 preserves local failed / external UNKNOWN. F3 preserves exactly the first
safe visible frame as partial / external UNKNOWN. F4/F5 retain complete once.
F6–F8 preserve local evidence and recover through the same offline service.
The atomic append fault has zero canonical events and an empty public outbox
view; one explicit retry then appends successfully. No automatic provider replay.

## Boundary evidence

- **Ordering/correction:** controlled arrival 9→1→5 exports canonically 1→5→9;
  structured null/false/zero, attachments and provenance survive unchanged.
  Exact duplicates return original receipts; identity/sequence conflicts reject.
  Original, correction and revert remain present; absent correction targets and
  delete operations reject. No Current reducer is used.
- **Replica:** injected failure and corrupt readback remain INCOMPLETE with no
  agreement fingerprint. Explicit normal drain recovers; later local append
  requires a new high-water envelope. Physical-envelope hashes and canonical
  hashes are independently checked with their declared order.
- **Knowledge:** UNKNOWN, KNOWN_EMPTY, N_A and NOT_LOOKED_UP all survive export,
  restart and completed readback; invalid value-bearing unknown states reject.
  Missing facts do not acquire a synthesized negative Current assertion.
- **Provenance/ingest:** independently authored A018, A019 and A020 mappings enter
  the shared CLI; mismatched adapters and observed/imported relabeling reject.
  Inferred/projected source labels remain explicit.
- **Authority:** eight forbidden authority-mutation metadata keys and five
  unsupported Current/Memory/Persona/Relationship operations reject; the external
  A2 synthetic authority control stays unchanged. Invalid stable-identity
  templates reject before USER commit. Explicit new-attempt retry preserves the
  earlier failed event.
- **Secret:** structured sentinels and credentials split across frames become
  redacted; envelope secrets reject. Zero sentinel occurrences in raw observable
  stdout/stderr, canonical/recovery/control/replica receipts and sealed A2 evidence.
  No internal database/WAL/spool scan or real secret was used.

## Reproduction, evidence and limits

Environment: CPython 3.12.14, Linux 6.18.44 x86_64, glibc 2.39, POSIX local temporary
stores. Python standard library only; the child process has a minimal environment
and executes the exact A1 checkout through PYTHONPATH. Transport=OFFLINE_DRIVE_STUB.

See [reproduction and oracle rules](../../../docs/a2/e1-independent-verification.md),
[full receipt](receipt.json), [compressed operation ledger](observations.jsonl.gz),
[normalized result](normalized-result.json), [checksums](SHA256SUMS.json), and
[post-run remote drift check](postflight.json).

The claim is limited to process-crash recovery on this substrate and the sanctioned
offline seam. Physical power loss, production Google Drive, arbitrary secret
detection and hidden internal storage are not certified. A1 and A2 receipts remain
distinct. No A1 candidate modification, live/paid/provider call, real remote
integration, private archive fixture, B1/B2 change, PR merge or issue closure.

**Return to Board/Verification and STOP. A2 PASS does not itself make E1 GREEN.**

Publication provenance: the initial local source commit was tested first and
returned PASS. Local `git push` had no configured credentials; publication via
the connected GitHub Git-data API preserved the exact source tree but produced
a new commit identity. The final evidence above was therefore freshly executed
from that accessible remote source commit. Both validation pairs produced the
same normalized result. See [run lineage](run-lineage.json).

The stored ledger is deterministic gzip. `receipt.json.ledger_sha256` hashes its
uncompressed bytes. To inspect and verify the original output:

```sh
python3 -c "import gzip; from pathlib import Path; p=Path('observations.jsonl.gz'); Path('observations.jsonl').write_bytes(gzip.decompress(p.read_bytes()))"
```

`SHA256SUMS.json` and `package-manifest.json` hash the files as stored here.
The harness emits plain JSONL on reproduction; compression changes no evidence.
