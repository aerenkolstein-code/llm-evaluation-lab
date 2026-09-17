# T3 F1 retriever qualification package

This implements `WO-ENG-B1-SC-V23-T3-F1Q-01 v0.1` after the user's explicit
construction approval. It authors an offline qualification package. Its result
on the approved source is **NOT_EVALUABLE / CANDIDATE_AMBIGUOUS**. Package
conformance and retriever qualification are separate decisions: a correctly
produced negative package does not qualify a retriever or authorize T5.

## Source and scope

- Repository: `aerenkolstein-code/llm-evaluation-lab`.
- Approved main: `6c1b664a2264a021dc9ebca26514eca130ceaaec`.
- Approved main tree: `2fcc3b0f2bf641d01ab8a90ab6b771be4e5c7434`.
- Exactly four additions: `search_cup/v23_t3_f1q.py`,
  `tests/test_search_cup_v23_t3_f1q.py`, this document, and
  `.github/workflows/t3-f1-retriever-qualification-offline.yml`.

The existing protocol, shared search boundary, backend implementations, ordinary
Test workflow, and published T4/JE0/JE1 code are unchanged. The implementation
does not depend on the historical PR 17 branch. The earlier JE1 scope amendment
does not apply to this work order.

The governing freezes are SP1 (SearchSpec/resource contract), SP2 (track and
variable control), SP4 (fairness/accounting), and SP5 (migration disposition),
together with the completed JE1-001 receipt and this work order. Private authority
documents are not copied into the public qualification evidence.

## Discovery before assessment

The frozen current-main backend surface is `search_cup/search_pro.py` and
`search_cup/tools.py`. The builder parses their ASTs without importing or calling
either module. A top-level class with a `__call__` method accepting a typed
`SearchRequest`, or a top-level callable accepting that type, is inventoried.
This criterion includes production and fake implementations. A proxy, HTTP
transport helper, or URL reader is not itself such a backend.

| Discovered identity | Path and callable | Observable configuration limitation |
| --- | --- | --- |
| `search_cup.search_pro:SearchProBackend` | `search_cup/search_pro.py`, `SearchProBackend.__call__` | Source defaults exist; no exact configured instance or upstream-neutrality evidence is frozen. |
| `search_cup.tools:FakeSearchBackend` | `search_cup/tools.py`, `FakeSearchBackend.__call__` | Literal lookup with caller-supplied results; no exact corpus/configuration is selected. |

These are materially different implementations. The work order supplies no
selector. Being a production backend, a fake backend, previously successful,
or easier to qualify cannot choose one. Both identities retain exact source
SHA/tree, file and implementation hashes, line spans, and canonical seals.

Consequently `selected_candidate`, `candidate_id`, and `candidate_fingerprint`
are null, while the discovery inventory retains both identities. There is no
selected candidate class or selected configuration. Zero candidates would
produce `NOT_EVALUABLE / NO_CANDIDATE`; multiple candidates produce
`NOT_EVALUABLE / CANDIDATE_AMBIGUOUS`. The builder never silently reduces this
inventory to a preferred implementation.

The unique-candidate descriptor method binds implementation, source, proxy,
request/result schemas, normalization, configuration and its fingerprint,
result limit, retry/fallback policy, capabilities, and a canonical fingerprint.
It is exercised by synthetic method tests but is not invoked by the current
ambiguous package. Source defaults alone do not establish a frozen instance.
`search_pro` retains `NOT_YET_F1_ELIGIBLE_BY_DEFAULT` and the conservative frozen
integrated-stack disposition; the adapter's presence does not prove provider
internals. Fake lookup source alone does not establish a qualified frozen corpus.

This is a version-pinned discovery method, not a universal Python plugin scanner.
Changed source, a new backend surface, or a future explicit selector requires a
reviewed new baseline/package; the present CLI accepts no selection override.

## R1–R8 and evidence

| Criterion | Current status | Assessment |
| --- | --- | --- |
| R1 Query transparency | UNKNOWN | No unique candidate selected |
| R2 No hidden entrant-specific planning | UNKNOWN | No unique candidate selected |
| R3 No entrant-specific hidden rerank | UNKNOWN | No unique candidate selected |
| R4 Reproducible interface | UNKNOWN | No unique candidate selected |
| R5 Normalized result contract | UNKNOWN | No unique candidate selected |
| R6 Same capability envelope | UNKNOWN | No unique candidate selected |
| R7 No hidden paid/intelligent stack in the F1 resource unit | UNKNOWN | No unique candidate selected |
| R8 Traceability | UNKNOWN | No unique candidate selected |

These eight entries explicitly have assessment state
`NOT_ASSESSED_NO_UNIQUE_CANDIDATE`. They are not eight adverse judgments on each
of the two implementations. Each references `E-DISCOVERY` and `E-BOUNDARY`, which
explain the selection block and observable shared boundary; neither is promoted
to proof of neutrality.

The all-of method accepts exactly R1–R8, each with PASS/FAIL/UNKNOWN and an
evidence list. For a selected candidate any FAIL or UNKNOWN makes it
NOT_F1_ELIGIBLE. Eight PASS assertions still require bound nonhistorical evidence,
an actually frozen and equalized configuration, and an allowed class. This work
order names no separately Board-approved neutral non-RAW class. An integrated
stack cannot be relabeled RAW. The inherited v2.3 gate is reused; no protocol
semantics are changed.

Evidence entries record kind, stable locator, source identity/content hash,
supported proposition, limitation, frozen marker, and canonical fingerprint.
Repository locators bind the exact approved commit and line span; their hashes
bind the complete source files. Only compact declaration excerpts are exported.
`E-TEST-SOURCE` is a read of an existing injected-transport test's source, not a
claim that the builder ran that test or a provider search.

No provider documentation or historical live receipt is used. Public-document
entries, if used in a future reviewed package, need an exact public HTTPS URL,
content hash, and frozen short excerpt. Historical P1/P2 success alone cannot
satisfy neutrality. The metadata gate checks evidence binding and all-of logic;
independent review must still assess whether a proposition is supported. The
published builder uses its own deterministic frozen assessment and accepts no
caller-supplied PASS table.

## Build and verify

Python 3.11 and the standard library suffice. From this checkout:

```sh
python -m unittest discover -s tests -p 'test_search_cup_v23_t3_f1q.py' -v
python -m search_cup.v23_t3_f1q receipt \
  --expected-source-sha 6c1b664a2264a021dc9ebca26514eca130ceaaec \
  --expected-source-tree 2fcc3b0f2bf641d01ab8a90ab6b771be4e5c7434
python -m search_cup.v23_t3_f1q bundle \
  --expected-source-sha 6c1b664a2264a021dc9ebca26514eca130ceaaec \
  --expected-source-tree 2fcc3b0f2bf641d01ab8a90ab6b771be4e5c7434 \
  --output-dir /tmp/t3-f1q-new-output
```

The output directory must not already exist; its parent must exist. A conforming
negative/ambiguous qualification exits successfully. Mismatched source identity,
changed pinned bytes, invalid evidence, or mutated receipts fail closed.

The six-file standalone bundle contains:

1. `candidate-descriptor.json`: discovery inventory and nullable selection.
2. `r1-r8-qualification.json`: all eight statuses/evidence references and reason.
3. `evidence-manifest.json`: frozen evidence and the closed nine-file source pins.
4. `qualification-receipt.json`: separate conformance/qualification outcomes.
5. `resource-zero-receipt.json`: explicit resource and authorization boundary.
6. `MANIFEST.sha256`: sorted byte hashes for the five JSON payloads.

The package fingerprint is the canonical hash of the baseline plus the four
component seals (descriptor, qualification, evidence, resources). The receipt
has its own seal, avoiding a self-referential package hash. The expected package
fingerprint is
`55be768878c849a7efda8e7be9bd3cf627ba5aa7f86f4c1f4efa9a671443aa6c`.
There is no timestamp or runtime-dependent value in the core package.
`validate_bundle` verifies seals and compares all payloads against a fresh build;
resealing a changed result, resource count, or authorization flag is insufficient.

The builder validates the supplied baseline identity and all nine retained source
file hashes. It does not invoke Git or independently establish the checkout's
ancestry. The dedicated CI supplies that complementary proof: actual Git base
SHA/tree, baseline ancestry, exact PR head/tree, a clean worktree, and exactly
four added paths. This distinction permits deterministic source-byte validation
without giving the qualification builder process or environment access.

## CI, boundaries, and acceptance

The dedicated workflow is pull-request-only, checks out the exact PR head with
no persisted credentials, and has read-only repository permissions. It runs the
32 focused method tests and builds one immutable artifact named
`search-cup-v23-t3-f1q-01-<exact-head-sha>`. It adds `ci-source.json` and
`focused-tests.log` to the core payloads, then writes a seven-entry manifest.
CI provenance is outside the deterministic core fingerprint and inside that
manifest. GitHub's artifact ZIP digest is a third, distinct identity.

The builder reads only the closed public-source allowlist. Focused tests guard
network/process/environment access and test source mutation, selection failure,
all-of status/evidence rules, integrated-class rejection, history-only evidence,
receipt tampering, exact zeros, and manifest integrity. In-memory all-PASS fixtures
test the method only; they do not execute or qualify a real retriever. The
ordinary repository Test workflow remains a separate required regression gate.

The package authoring path does not import a search backend, provider, entrant
runner, or judge; it performs no search. GitHub checkout/setup/artifact transport
and CI Git metadata reads are infrastructure, not candidate execution. The
zero-operation receipt covers T3 qualification authoring, not the unrelated
ordinary Test workflow's existing synthetic demos and local service checks.

All provider/search/network-search/follow-link/retry/credential/credit/model/
entrant/E1 counts are zero; spend is USD 0. Formal retriever execution, official
prompt consumption, and hidden registry loading are false. Claims are capped at
`F1_RETRIEVER_QUALIFICATION_ONLY`; `t5_execution_authorized` and
`live_execution_authorized` are false.

`package_conformance=PASS` is the implementation's reproducible method result;
`independent_acceptance=PENDING` remains explicit. The developer returns the
Draft PR, exact source and artifact identities, tests, evidence fingerprints,
qualification, and zero receipt, then stops for independent acceptance. This
work order does not merge the PR or authorize T5/E1 execution.
