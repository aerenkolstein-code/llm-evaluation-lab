# NFR-01: frozen lexical RAW retriever candidate

This implements the explicitly approved `WO-ENG-B1-SC-V23-T3-NFR-01 v0.1`.
It creates one candidate and an explicit selector for later independent
qualification. **R1–R8 qualification is not performed and F1 eligibility is not
claimed.** The prior published T3 ambiguity finding remains unchanged.

## Source, identity, and scope

Approved main SHA: `db6ba8746e6776c02b5942e38919316aebf65fe0`.
Approved main tree: `52c37289c283ccbe89b974fae099ac0671aea678`.
This is the publication of the independently accepted F1Q-01 package.

| Identity | Frozen value |
| --- | --- |
| Candidate ID | `search-cup-v23-frozen-lexical-raw-v1` |
| Class | `RAW_RETRIEVER` |
| Module/class | `search_cup.v23_frozen_retriever:FrozenLexicalRetriever` |
| Backend ID | `search-cup-v23/frozen-lexical-raw-v1` |
| Interface | `SearchRequest -> SearchBackendResponse` |
| Future selector | `EXPLICIT_AUTHORITY_PIN_TO_CANDIDATE_ID` |
| Claims ceiling | `RETRIEVER_IMPLEMENTATION_EVIDENCE_ONLY` |

The selector names this exact candidate. It does not choose SearchProBackend or
FakeSearchBackend, modify historical discovery, or run a renewed qualification.
The candidate constructor requires an explicitly supplied `FrozenCorpus` and
`FrozenConfig`; there is no environment-based discovery, fallback, default live
backend, or implicit corpus.

Exactly six new paths are added:

- `search_cup/v23_frozen_retriever.py`
- `configs/search-cup-v23-frozen-retriever-v1.json`
- `fixtures/search-cup/v23-frozen-retriever-test-corpus-v1.json`
- `tests/test_search_cup_v23_frozen_retriever.py`
- `docs/search-cup-v23-frozen-retriever.md`
- `.github/workflows/t3-frozen-retriever-offline.yml`

No existing path changes. Shared schemas, proxy, backends, protocol, ordinary Test
workflow, published T3/T4/JE0/JE1, runners, judges, and historical PR 17 are retained.
Baseline/source checks verify their retained content hashes, while CI verifies
the complete base-to-head diff consists of exactly the six additions.

## Declared retrieval behavior

The versioned config freezes
`deterministic-character-ngram-overlap/v1`,
`unicode-nfkc-casefold-alnum-space/v1`,
`multiset-overlap-integer/v1`, result limit 10, score-zero exclusion, and
`doc_id-ascending` tie-breaking.

Normalization first applies Unicode NFKC, then casefold. Unicode categories L
(letters) and N (numbers) remain content. Every other run becomes one separator;
leading/trailing separators disappear. It is lexical normalization, with no
translation, dictionary, stemming, query plan, synonym expansion, or alternate
query.

Each normalized alphanumeric span of length at least three yields all contiguous
character trigrams, retaining multiplicity. Each shorter span yields its
individual characters. Units never cross a separator. The same procedure applies
to the query and the precomputed document text, which is exactly
`title + "\n" + text`. A short query therefore does not become a prefix search
over a longer span: `al` can overlap the `a` unit of `ab`, but cannot manufacture
unigrams inside `alpha`.

The score is the sum, over query units, of the smaller of query/document unit
counts. It is an integer, with no normalization or second ranking stage.
Documents with score zero are omitted. Sort by descending score, then ascending
doc_id using Python string/code-point order, and return at most ten results.

Result fields are exactly `title=document.title`, `url=document.url`, and
`snippet=document.text[:240]` (Unicode code points). Only the existing
SearchBackendResponse/SearchResult types cross the boundary. Backend ID and the
incoming request ID are retained; response_id is None. The original immutable
SearchRequest/query is unchanged. BudgetedSearchProxy supplies the existing
query/status/timing/count/request trace and failure accounting without modification.

The candidate has no call counter, mutable cache, history, query log, clock,
randomness, or entrant/provider/model-specific branch. Its corpus, config, and
precomputed index consist of frozen dataclasses, tuples, and strings. Call counts
belong to the conformance harness and tests, outside the candidate.

## Corpus and configuration integrity

Corpus documents have exactly four fields: doc_id, title, url, text. IDs must be
nonempty, unique, and free of surrounding whitespace; titles are nonblank;
text may be empty. URLs must be absolute HTTP(S) locations without credentials or
whitespace. They are provenance strings and are never fetched. Private-locator
and credential-pattern screening uses the existing protocol scanner.

Construction copies caller data, validates it, sorts by doc_id, and stores
canonical JSON plus its SHA-256. A supplied fingerprint must match. Malformed
documents, duplicate IDs, or mismatched fingerprints are rejected. Neither caller
mutation nor a query can alter the retained corpus. An explicitly supplied empty
corpus is valid and returns no results.

FrozenConfig accepts only the exact versioned configuration fingerprint. The
module pins the byte hashes of the materialized configuration and fixture inputs
for package authoring; a changed file fails closed. Runtime retrieval performs
no file access. Package authoring reads only a closed public-source allowlist.

| Reproducible input | Canonical fingerprint |
| --- | --- |
| Configuration | `2f60df7627f611c29f425dfccb94936cf606774fc619e48fe34c650f738ac7ca` |
| Synthetic corpus | `ec12c5e478b9b95c8f24104bca5147717ba7ca5018fea043cf8e9f658b7377d4` |

The 14-document fixture is deliberately synthetic: twelve overlap/tie/limit
records, one Unicode record, and one short-span record. It is **not** an E1 corpus,
D4 authority, benchmark, or reference/adjudication set. Its test expectations are
implementation checks only. The future production corpus and its judgments remain
separately gated.

Unicode normalization and casefold depend on Python's Unicode database. The
candidate descriptor explicitly binds `unicodedata.unidata_version`; a different
Unicode database produces a different candidate/package fingerprint. The dedicated
CI uses Python 3.11 (Unicode 14.0.0), while a local Python 3.12 run binds Unicode
15.0.0. Code/config/corpus hashes remain comparable, but those runtime-bound
candidate fingerprints must not be substituted for one another. A later
qualification must pin the exact descriptor and corresponding runtime. No
cross-Unicode-version equivalence is claimed.

## Package and verification

From the repository root, using the same Python/Unicode runtime as the artifact:

```sh
python -m unittest discover -s tests -p 'test_search_cup_v23_frozen_retriever.py' -v
python -m search_cup.v23_frozen_retriever receipt \
  --expected-source-sha db6ba8746e6776c02b5942e38919316aebf65fe0 \
  --expected-source-tree 52c37289c283ccbe89b974fae099ac0671aea678
python -m search_cup.v23_frozen_retriever bundle \
  --expected-source-sha db6ba8746e6776c02b5942e38919316aebf65fe0 \
  --expected-source-tree 52c37289c283ccbe89b974fae099ac0671aea678 \
  --output-dir /tmp/nfr-new-output
```

The output directory must be fresh and its parent must exist. Existing output is
rejected before any fixture call. The core package contains:

| File | Content |
| --- | --- |
| candidate-descriptor.json | Source/code/schema identity, config identity, selector, runtime and capabilities |
| candidate-config.json | Exact materialized configuration and fingerprint |
| test-corpus-descriptor.json | Synthetic purpose, canonical corpus, fingerprint and fixture instance binding |
| implementation-conformance.json | Eight deterministic fixture observations, implementation result, package fingerprint and pending independent acceptance |
| resource-zero-receipt.json | Zero external/formal operations and eight local fixture calls |
| MANIFEST.sha256 | Byte hashes for the five JSON payloads |

Each JSON payload has a canonical seal. The package fingerprint covers source,
candidate/config/corpus/resource seals, and fixture observations. The conformance
report carries this fingerprint and its own seal without creating a self-reference.
The code content hash binds the entire new module. A supplied source root must
contain the same implementation bytes as the executing module. The builder checks
baseline constants and retained source bytes; CI independently proves actual Git
ancestry and exact head/tree. The builder itself never invokes Git.

`build_bundle` executes exactly eight synthetic fixture calls. `validate_bundle`
checks seals and reproduces all expected payload bindings against the pinned
inputs and fixed synthetic expectations, without executing another query. It does
not attest arbitrary caller-provided results. Resealing modified claims, source
hashes, observations, or fixture-authority flags does not pass validation.

The implementation report says PASS only after its eight observations match the
synthetic expectations. Independent acceptance and candidate identity acceptance
remain PENDING. There is no R1–R8 status table or qualification_result in this
package.

## Tests, CI, and resource accounting

The 35 focused tests cover input/code/source binding, exact configuration,
immutable corpus/config/index, Unicode normalization, unit multiplicity, score
ordering, tie/limit behavior, zero results, typed output, original query/request
identity, entrant invariance, proxy traces and failures, no retry/fallback,
forbidden capabilities, closed source reads, package tampering, manifest hashes,
and the claims boundary. Negative malformed/changed inputs are deliberate test
variants of the same synthetic fixture, not additional formal corpora.

A test-only external wrapper counts every call to FrozenLexicalRetriever during
the focused suite, including package-building tests and rejected requests. The
suite emits `NFR_LOCAL_FIXTURE_RETRIEVER_CALLS=73`. A dedicated CI package build
then performs 8 more calls; validation performs 0. `ci-source.json` records these
separately and their total of 81 for that dedicated job. The core resource receipt
has the explicitly narrower scope ONE_SYNTHETIC_PACKAGE_CONFORMANCE_BUILD and
therefore records 8. Repeated developer invocations and ordinary repository tests
are separate runs, not silently included in or excluded from that job total.

The dedicated workflow is pull-request-only, checks out the exact head, checks
the approved base SHA/tree and ancestry, enforces six additions and a clean
checkout, runs focused tests, and uploads one immutable head-named artifact.
It adds `ci-source.json` and `focused-tests.log` to the five core payloads, then
writes a seven-entry manifest. GitHub's ZIP digest, those file byte hashes, and
the semantic package fingerprint are distinct audit identities.

The retrieval, fixture-test and package code paths perform zero live search,
provider/model/network calls, credential reads, credits, retries, subprocess
calls, E1 or T5 runs; spend is USD 0. CI checkout/setup/upload transport and
read-only Git provenance commands are infrastructure, outside the retriever's
operation receipt. The unchanged ordinary Test workflow has its own existing
synthetic demos and local service checks. The inherited package initializer
imports existing backend/runner/judge definitions; no such backend or entrant is
invoked by this implementation. Guards explicitly prohibit legacy backend calls,
live transport, environment reads, and subprocess invocation during conformance.

All outputs keep `r1_r8_qualification_performed=false`, `f1_eligible_claimed=false`,
`t5_execution_authorized=false`, and `live_execution_authorized=false` where claims
are stated. There is no workflow_dispatch or repository-secret input. Return the
Draft PR, exact CI/artifact/source identities, fingerprints, and receipts, then
stop for independent implementation and identity acceptance. Merge, renewed
qualification, and T5/E1 remain separate authorizations.
