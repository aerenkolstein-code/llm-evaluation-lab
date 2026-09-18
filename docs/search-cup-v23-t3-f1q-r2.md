# Renewed exact-candidate F1 method qualification

Authority: `WO-ENG-B1-SC-V23-T3-F1Q-R2-01 v0.1`, explicitly approved in the task thread.
Approved source: `34e147f26b582486474b4d4b29eae7494add2d4b`, tree
`311b541fddf212060476a3f994581e06c71d98f0` (published NFR candidate).
Exactly five additions are allowed. The published retriever, config, fixture,
protocol gate, prior F1Q record and ordinary Test workflow remain untouched.

The method assesses **only** `search-cup-v23-frozen-lexical-raw-v1`,
`search_cup.v23_frozen_retriever:FrozenLexicalRetriever`, a `RAW_RETRIEVER`.
It uses the explicit selector and tuple in
`configs/search-cup-v23-t3-f1q-r2-target.json`; no candidate discovery occurs.
The accepted descriptor fingerprint is
`6715a759a36dd3039dbf36bb15636eb683e107caec3953c68adb8e92c93d4281`.
Python **3.11** and Unicode data **14.0.0** are mandatory. A name-only match,
different descriptor or different Unicode database is not equivalent.

## Decision and acceptance

R1–R8 form a hard all-of gate. Each has PASS/FAIL/UNKNOWN, explicit propositions,
limitations and sealed, non-dangling evidence references. All PASS yields the
method result `F1_ELIGIBLE`; any FAIL/UNKNOWN yields `NOT_F1_ELIGIBLE`.
The exported RETRIEVER object goes through the unchanged
`protocol_v23.f1_eligibility`; this module does not replace its decision logic.
Metadata gate tests exercise negative statuses without changing the candidate.

The builder first checks the target. A mismatch yields a conformant negative
package: `NOT_EVALUABLE / TARGET_IDENTITY_MISMATCH`, no criterion assessment,
all eight UNKNOWN, zero fixture calls. Wrong source main SHA/tree raises
`BASELINE_DRIFT`. No probe runs against an unresolved candidate.

Every package retains `independent_acceptance=PENDING` and
`formal_f1_status=PENDING_INDEPENDENT_ACCEPTANCE`. Its claims ceiling is
`F1_RETRIEVER_QUALIFICATION_ONLY`. T5/E1/live authorization remains false.
No method result, seal, publication or historical NFR QA grants acceptance,
production corpus authority, execution authority or model-quality claims.

## Evidence and limitations

| Criterion | Active evidence IDs | Observation |
|---|---|---|
| R1 | E_IMPL, E_PROXY, E_QUERY | Original whitespace/fullwidth query survives request and proxy trace; normalization is explicitly lexical. |
| R2 | E_IMPL, E_ENTRANTS, E_IMMUTABLE | Four materially different entrant IDs share results; source has no entrant branch or query-time state writes; repeat after other queries is identical. |
| R3 | E_IMPL, E_CONFIG, E_RANKING | Integer multiset overlap, one ordering path, score-desc/doc_id-asc ties, ten-result cap and zero-score exclusion. |
| R4 | E_TARGET, E_CONFIG, E_SCHEMAS, E_REPRODUCIBILITY | Exact descriptor/runtime/source/config; two identical probe passes and deterministic package assembly. |
| R5 | E_IMPL, E_SCHEMAS, E_PROXY, E_TYPED | Actual typed response/results, document title/URL/text prefix and request/backend IDs. |
| R6 | E_IMPL, E_ENTRANTS, E_IMMUTABLE, E_CONFIG | Same object/config/corpus within each probe pass; five frozen-assignment rejections. |
| R7 | E_IMPL, E_GUARD, E_RESOURCES | Closed source inspection, execution-seam blockers and zero external/formal operation receipt. |
| R8 | E_TARGET, E_SCHEMAS, E_PROXY, E_SUCCESS, E_FAILURE, E_RESOURCES | Typed success/failure trace, timing fields, original query, request/call identity and no hidden retry. |

Source evidence is limited to the seven explicit allowed files: retriever,
config, fixture, contracts, tools, protocol and protocol schema. This method and
its target JSON are additionally read for method/selector provenance. No legacy
provider, T4/JE1 implementation, private authority, environment value, production
corpus or answer registry is used as evidence. The historical NFR descriptor is
reconstructed by its pure assembler to check identity. Its old baseline and
retained-source metadata remain historical; its eight conformance calls are
**not executed or claimed** in this qualification.

There are twelve success probes per pass: four equal queries across different
entrant IDs, NFKC/casefold, Chinese trigrams, short-span unigrams, punctuation,
zero-match, repeated query after intervening calls, multiplicity saturation and
title indexing. Only the published fourteen-document synthetic fixture is used.
It contains twelve positive alpha matches, enough to observe score ties and
truncation at ten. The fixture's short texts exercise exact prefix mapping;
the 240-codepoint bound is additionally established by the pinned source, not
by introducing another corpus. Finite probes complement, rather than replace,
inspection of the exact closed implementation.

Each pass also injects one typed local backend failure. The failure is marked
retryable to demonstrate the proxy still makes exactly one attempt. It does
not call the retriever. Traces preserve failure information and zero retries.
Proxy UUID/time providers are patched solely at the test boundary: request IDs
come from a fixed sequence, timestamps begin at 2000-01-01 UTC and durations
are a controlled 7 ms. These values demonstrate auditable trace propagation;
they are **not wall-clock timestamps or performance measurements**. The patch
does not replace request construction, backend invocation or trace logic.

Transport, provider, live-smoke, model-execution, fallback, environment and
subprocess seams are blocked while building/validating. No environment values
are read. Runtime retrieval itself performs no file I/O. The guard is defense
in depth for pinned source, not a general sandbox for hostile Python code.
Importing the package can load existing legacy class definitions via
`search_cup.__init__`; this does not invoke those implementations. CI checkout,
runtime installation, artifact upload and read-only Git provenance are separate
infrastructure. The ordinary repository workflow has its existing, separately
scoped local regression and service checks.

## Reproduce

Use Python 3.11 with `unicodedata.unidata_version == "14.0.0"`:

```sh
python -m unittest discover -s tests -p 'test_search_cup_v23_t3_f1q_r2.py' -v
python -m search_cup.v23_t3_f1q_r2 bundle \
  --expected-source-sha 34e147f26b582486474b4d4b29eae7494add2d4b \
  --expected-source-tree 311b541fddf212060476a3f994581e06c71d98f0 \
  --output-dir /tmp/f1qr2-new-package
python -m search_cup.v23_t3_f1q_r2 validate \
  --expected-source-sha 34e147f26b582486474b4d4b29eae7494add2d4b \
  --expected-source-tree 311b541fddf212060476a3f994581e06c71d98f0 \
  --output-dir /tmp/f1qr2-new-package
```

Output directory must be fresh. The six sealed payloads are target descriptor,
R1–R8 qualification, evidence manifest, runtime probes, resource receipt and
qualification receipt; `MANIFEST.sha256` binds their exact UTF-8 bytes.
The package fingerprint binds the five content payload seals; the qualification
receipt separately seals the decision and that package fingerprint.
The zero-call validator recomputes pinned-source/golden bindings and rejects
resealed observation, identity, acceptance, resource or execution mutations.
It is content validation, not cryptographic proof that an untrusted publisher
actually executed Python. Independent QA must examine source, tests and CI.

A successful build executes two complete identical passes:

| Quantity | Per build |
|---|---:|
| Qualification fixture retriever calls | 24 |
| Qualification proxy calls crossing the boundary | 26 |
| Injected local failure calls (included in proxy calls) | 2 |
| Additional calls from validation | 0 |
| External/formal/provider/model/network/credential/retry/fallback/subprocess operations | 0 |
| Spend | USD 0 |

Focused tests instrument actual calls independently and print
`F1QR2_TEST_COUNTS`: 46 tests, 97 retriever calls, 105 proxy calls,
9 injected failures and 24 negative guard attempts. Negative guard tests count blocked test attempts separately;
they never perform the blocked operation. Dedicated CI adds test totals and the
one artifact build, with zero validation calls. It verifies exact PR head,
approved base/tree, ancestry, five additions and clean checkout before probes.
It exports `ci-source.json`, `focused-tests.log` and a final eight-entry manifest
in one head-named artifact. Read-only Git subprocesses are individually listed
and counted in `ci-source.json`, outside qualification resource accounting.

Return the Draft PR and this package for independent acceptance. Do not merge,
promote formal F1 status or execute T5/E1 from this work order.
