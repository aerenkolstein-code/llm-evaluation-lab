# T6 Live RAW retriever: offline candidate and qualification

Work order: **WO-ENG-B1-SC-V23-T6-LIVE-F1Q-01 v0.1**.
Construction base: `72932d41c862753d489ef2d2e1c6a2619f34a2d9`,
tree `05c0953bfe67f9d684160a79ef7c9307dcd2a3a4`.

## Status and claim ceiling

This is a seven-new-path **offline candidate/evidence package**, not a T6 live
runner. No existing file is changed. There is no default network transport,
secret lookup, live smoke, merge permission or provider spending authority.
The constructor requires an explicitly injected transport; tests inject only
synthetic responses. An authenticated transport and its physical timeout
behavior require separate authority and qualification before future live use.

**Current strict qualification is NOT_F1_ELIGIBLE. R2 and R7 remain UNKNOWN.**
The mock suite verifies the client boundary, not undisclosed provider internals.
The official documentation specifies ordinary Web Search and optional enhanced
surfaces, but the evidence inspected here does not establish every stronger
server-side absence claim in the Work Order. This package records that gap;
it does not replace missing evidence with passed client tests.

A successful unit-test run is implementation evidence only. The dedicated
qualification command deliberately exits `1` for the negative eligibility
verdict and still preserves its artifact. This is a closed qualification gate,
not authority to retry with broader capabilities. Stop after returning evidence
for independent review. D6 and all live actions remain locked.

## Exact candidate

`search-cup-v23-live-brave-web-raw-v1` selects the Brave Web Search GET endpoint
with `Api-Version: 2023-01-01`, `result_filter=web`, count 10, US locale and
English language. The complete profile is frozen in the JSON config; extra keys,
value changes and boolean/integer coercions are rejected.

The API version is supported by both the official versioning example and the
Web Search changelog entry for the initial resource. This pins the documented
interface, **not** the live index or ranking. The evidence file stores compact
paraphrases, source URLs, observation qualification and record fingerprints.
Those hashes cover the compact evidence records, not complete captured webpages.
No provider documentation is fetched by the qualification process.

Official sources:
- <https://api-dashboard.search.brave.com/api-reference/web/search/get>
- <https://api-dashboard.search.brave.com/documentation/guides/versioning>
- <https://api-dashboard.search.brave.com/app/documentation/web-search>

The US profile does not silently revise parent T6 D2 geography. Final task scope,
D7 resources, live transport, costs and credentials remain separate decisions.

## Client behavior

One valid call creates one explicit HTTP-shaped request. The entrant query is
preserved through URL encoding; entrant identity does not change wire parameters.
No local query expansion, decomposition, synthesis, reranking, cross-query plan,
retry or fallback exists. The shared `BudgetedSearchProxy` remains unchanged.

Spelling changes, observable fallback and enhanced-result signals cause typed,
non-comparable failures. Only `web.results` title, URL and description are mapped;
provider order is preserved. More than ten results are rejected, not silently
truncated. Missing or malformed fields, duplicate/non-finite JSON, unsafe URLs,
oversized bodies and credential-shaped content are rejected. A credential-free
response body is hashed only after safety validation. Failed/unsafe body hashes
remain unavailable rather than retaining private content.

Every attempted injected transport call records local identity, query, call
number, UTC start, elapsed time, fixed backend/config identity, HTTP status,
result count, typed error, retryability and observable query state. Error strings
do not interpolate response bytes or transport exception messages. Returned
receipt copies cannot mutate the adapter's retained history. Content safety is
bounded, not a universal data-loss-prevention claim; inputs must be public-safe.

## Qualification evidence

R1, R3, R4, R5, R6 and R8 are assessed using documented interface controls,
inspected client source and named passing test cases. R2 and R7 additionally
carry explicit unresolved provider-capability evidence. The all-of predicate is
`protocol_v23.f1_eligibility`: a single FAIL/UNKNOWN prevents eligibility.
A status cannot be upgraded by weighting other checks or editing a receipt.

Source validation binds the actual head/tree, approved base/tree, seven `A`
paths, their file hashes and a clean worktree. The qualification process blocks
socket creation, DNS, common HTTP entrypoints and secret environment reads.
Negative guard tests demonstrate rejection without making those calls.
GitHub checkout/setup and artifact upload are **control-plane networking**, not
part of the qualification's zero-network measurement boundary.

## Commands

Run focused tests on a complete repository checkout:

```sh
python -m unittest discover -s tests -p 'test_search_cup_v23_t6_live_f1q.py' -v
```

Produce an artifact in a fresh directory outside the repository:

```sh
python tests/test_search_cup_v23_t6_live_f1q.py --qualify --output /tmp/t6-f1q-new-artifact
```

Exit codes: `0` eligible; `1` explicitly not eligible; `2` source/evidence/output
precondition failure. Never override the exit code as proof of F1 eligibility.
The checked-in document pin and its records are verified before qualification.
A changed evidence basis requires review, not silent rehashing.

## Artifact and next gate

The artifact includes manifest, descriptor, config, official-doc and source
records, R1–R8 matrix, capability and request/result contracts, named test
outcomes, qualification receipt, test log and a SHA-256 payload manifest.
It records zero live API/provider/model requests, secret reads, search credits,
spend and T6 runs. It does not represent independent QA or publication.

Return the Draft PR, exact source and CI/artifact evidence, then STOP. Independent
review must decide whether more provider evidence is needed or a separately
approved protocol clarification is appropriate. No R2/R7 waiver, live probe,
merge, key provisioning, E1F rerun or successor execution is inferred here.

## First-pass integration repair

The first ordinary Test run detected `os` imported by the new `v23_` qualification
module. The repository's existing inert-protocol guard is preserved unchanged.
The bounded repair separates pure descriptor/evidence assembly from test harness
orchestration: the former remains in `search_cup/v23_t6_live_f1q.py`, and the
latter moves into the already-authorized focused test file. Read-only Git probes,
network/secret denial, test execution and artifact writing are explicit harness
operations. The protocol module does not dynamically import the harness or hide
forbidden imports. A regression test verifies this separation.

This repair changes only four of the seven newly added paths. It neither changes
the baseline guard nor resolves the independent R2/R7 provider-evidence gaps.
