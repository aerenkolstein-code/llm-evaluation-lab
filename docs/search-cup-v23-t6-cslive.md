# T6 controlled-source offline component return

Authority: **WO-ENG-B1-SC-V23-T6-CSLIVE-OFFLINE-01 v0.1**, eight new paths only.
Base commit: `72932d41c862753d489ef2d2e1c6a2619f34a2d9`.
Base tree: `05c0953bfe67f9d684160a79ef7c9307dcd2a3a4`.
Candidate identity: `t6-controlled-source-fts5-v1`.

This is an offline component, not an admitted RSS integration or an E1_LIVE run.
Keep the implementation PR Draft/unmerged pending independent QA. The unrelated
Brave PR #79 and its negative qualification evidence are not changed or imported.

## Measurement and authority boundaries

| Field | Meaning |
| --- | --- |
| Component tests | Actual execution of the named synthetic mechanism tests |
| Scoped R1-R8 | Derived from named tests and the exact eight-file source evidence; synthetic client-path scope only |
| Production source admission | `NOT_ADMITTED` |
| Production F1 eligibility | `NOT_F1_ELIGIBLE`; not upgraded by client tests |
| Independent QA | `PENDING` |
| Live validation | `NOT_RUN` |

No real-source requests, supplier contact, credentials, paid API, scheduling,
`workflow_dispatch`, production merge, or E1F-001 replay are implemented or
permitted. Package setup, source checkout, artifact upload and source-bundle
retrieval are CI/control-plane operations, not evidence of zero networking for
the entire runner. The candidate execution is tested with network and environment
access denied. No external provider key is provisioned or read.

## Source and epoch contract

`EpochStore` accepts explicit bytes and an injected clock, not a transport. Its
closed policy accepts only a synthetic `.invalid` source and has no default
network implementation. The Himalayas URL in config is candidate metadata with
`NOT_ADMITTED`/`NOT_VERIFIED`; it is never fetched. Real-source transport and source
admission require a later, separately approved scope.

Limits are 2 MiB input, 100 input items per epoch (including duplicates), 32 KiB
combined description/content per item, and 4 KiB individual metadata fields.
Over-limit input fails explicitly rather than disappearing through truncation.
Only UTF-8 RSS is accepted; DTD/entities, unsafe HTML, nested field XML, malformed
source links, source substitution and redirects are rejected. HTML is converted
to text without script/image loading or model-generated summaries. Source text is
untrusted data. Neither ingestion nor retrieval judges job eligibility.

Dates preserve the original text. ISO 8601 and RFC822 timestamps with explicit
zones are recognized; missing/invalid/naive dates remain `UNKNOWN`. GUIDs are
opaque; a missing GUID falls back to the validated link. Identical duplicate IDs
are counted, conflicting duplicate IDs reject the epoch. Records are sorted by
identity before immutable epoch construction; shuffled input is not content drift.

Each attempted refresh invalidates the current view before validating the clock,
status or bytes. Failed refreshes cannot silently serve the old epoch, but previous
immutable epochs remain available as explicitly historical evidence. Successful
snapshots form a parent-fingerprint chain and all ingest outcomes form a separate
hash chain. There is no automatic fallback or retry. Minimum polling interval is
24 hours, measured against the last admitted attempt. An invalid clock, backwards
clock or early invocation is typed; no scheduler exists.

The two self-authored fixture epochs contain additions, changes and withdrawals.
Their timestamps are simulated inputs, not claims of current or future network
execution. Identical semantic content yields `NO_DRIFT_OBSERVED`; the system does
not refetch to manufacture drift. Real daily-source epochs cannot be substituted
silently for the earlier ten-minute live experiment. A single immutable snapshot
is a frozen experiment; any future refreshed-source E1_LIVE interpretation still
needs its own source, instance, timing, resource and claims review.

## Query and ranking contract

`ControlledSourceRetriever` opens only an in-memory SQLite database on explicit
construction. FTS5 `unicode61 remove_diacritics 0` is fixed, with equal title/body
BM25 weights. The original query string is supplied unchanged as the bound MATCH
parameter, never SQL-interpolated or sent to an external service. FTS syntax errors
are typed failures consuming the attempted call; no spelling correction, synonym
expansion, query decomposition, hidden second query or retry occurs.

Provider/entrant identities do not enter SQL or ranking. Results are sorted by
BM25 ascending, then binary `(source_id,item_id)` order. Both entrants see the same
immutable epoch/configuration. There are at most four attempted calls per entrant
per epoch and ten results per call. The configured schedule is balanced
A1/B1/B2/A2/A3/B3/B4/A4. Query/epoch configuration fingerprints, sequence numbers,
result fingerprints, rank, score, source identity and event hash links are emitted.
Binding mutations and queries timestamped before their epoch are rejected.

Python version, SQLite version, `sqlite_source_id()`, FTS configuration and SQL/schema
hashes are included in `runtime.json`. Each evidence execution establishes one
runtime pin reused by all indices in that run; an unexpected requested runtime pin
is rejected. Local and CI environments are separate, explicitly recorded profiles,
not interchangeable replay identities. No FTS5 support means `FTS5_UNAVAILABLE`.

## Verification commands

From an exact clean candidate Git checkout with the approved base in history:

```sh
python -m unittest discover -s tests -p 'test_search_cup_v23_t6_cslive.py' -v
PYTHONPATH=. python tests/test_search_cup_v23_t6_cslive.py --artifact /tmp/t6-cslive-new-output
```

The artifact destination must be new and outside the repository. The harness first
checks base/tree, ancestry, eight added paths, absence in base, and clean tracked
source; then runs tests and generates evidence. It rejects artifact overwrite.
It returns nonzero on mechanism test failure. Pending source/F1/live admission is
reported separately, not converted into a fake mechanism test failure or a PASS.

Full repository regression remains the unchanged ordinary Test workflow and a
separate full local run with the repository's pinned Companion-Mind dependency.
The new PR-only workflow also exports read-only Git bundles of these exact sources
so a disconnected local runner can verify Git objects and run the full regression.
Bundles contain Git objects, not checkout credentials or `.git/config`.

## Evidence and review

The output includes config, source policy, runtime, immutable epochs, epoch delta,
ingest/query/result provenance, actual resource receipt, exact base/head/tree and
source hashes, named test records, scoped R1-R8 evidence, qualification receipt,
test log and SHA-256 manifest. Qualification PASS statuses require the particular
named evidence; missing evidence is UNKNOWN and a failed required test is FAIL.
No production F1 or source-admission PASS is produced by this package.

Reviewers should independently check source scope, malicious/limit cases, runtime
pinning, raw MATCH parameter preservation, lack of network/credential path, epoch
immutability, stable ordering, failed-refresh behavior and every evidence hash.
Source permissions, RSS accessibility/schema/freshness, real-source compatibility,
full instance acceptance and production execution all remain outside this return.

Technical reference: SQLite FTS5 https://www.sqlite.org/fts5.html . This explains
the selected mechanism; it is not source-admission or benchmark-qualification
proof. The published result claims only synthetic offline component validation.
