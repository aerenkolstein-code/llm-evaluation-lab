# T5 E1_FROZEN synthetic protocol-validation instance

Work order: `WO-ENG-B1-SC-V23-T5-E1F-PV-01 v0.1`.
Instance: `T5-E1FROZEN-PV-001`; SearchSpec: `SEARCH-CUP-V23-T5-E1FROZEN-PV-001`.

This authors a public-safe, deterministic, offline instance. It makes **no E1 run,
entrant invocation, benchmark, model-quality or live-web claim**. The claims ceiling
is `E1_FROZEN_PROTOCOL_VALIDATION_ONLY`. Independent acceptance is pending; neither
merge nor successor execution is authorized by this package.

## Authority and immutable inputs

Approved main: `4785c392eb0b9e5d04c8eef04289a4888c222839`.
Approved tree: `07849a3696009c47d284b896fd3f1676f617e98b`.
Exactly seven additions are listed in `APPROVED_PATHS`; no existing file changes.
The dedicated workflow checks the actual base/tree, ancestry, exact additions and
clean checkout, on the exact PR head. The builder also rejects a supplied baseline
mismatch and verifies all pinned source bytes. Its baseline arguments alone are
not a Git provenance proof. Ordinary Test uses a shallow merge checkout, so its
duplicate full-history scope test may skip; the dedicated workflow and focused
suite must perform that check with full history and no skips.

The unchanged retriever is
`search_cup.v23_frozen_retriever:FrozenLexicalRetriever`, candidate
`search-cup-v23-frozen-lexical-raw-v1`, backend
`search-cup-v23/frozen-lexical-raw-v1`, RAW_RETRIEVER.
Its descriptor fingerprint is
`6715a759a36dd3039dbf36bb15636eb683e107caec3953c68adb8e92c93d4281`.
Its accepted F1Q-R2 package fingerprint is
`ff59157de522b8d7b17cea5908a094449b76be7f606b13bffb9b703285721886`.
Python 3.11 and Unicode 14.0.0 are required. Other runtimes fail closed.

The PR69 binding is reconstructed from pinned source and published golden
observations and validated against that exact package fingerprint, without running
qualification probes. Its old nested receipts keep their original statuses and
historical call counts. They are evidence about PR69, not T5 activity. The current
authoring receipt records zero query calls and pending T5 independent acceptance.
The exact evidence-bound retriever object remains `F1_ELIGIBLE` under unchanged
`protocol_v23.f1_eligibility`. Its prior 14-record implementation fixture is not
substituted for this new 24-record corpus.

## Task and reference authority

Find every frozen synthetic opportunity that explicitly permits remote work,
explicitly requires Python and explicitly accepts applications. Return doc IDs
and their exact frozen evidence locators. Missing or ambiguous evidence is UNKNOWN,
never silently a negative. Each document has only `doc_id`, `title`, `url`, `text`.
The HTTPS URLs under `example.invalid` are inert evidence locators; they are never
fetched. They fit the accepted corpus constructor's HTTP(S) schema.

| Document IDs | Label | Independent authored reason |
|---|---|---|
| 001–006 | RELEVANT | All three predicates explicitly true, using varied wording |
| 007–012 | NOT_RELEVANT | Remote work explicitly forbidden; other predicates true |
| 013–018 | NOT_RELEVANT | Python explicitly optional/not required; other predicates true |
| 019–022 | NOT_RELEVANT | Applications explicitly closed; other predicates true |
| 023 | UNKNOWN | Remote-work arrangement unspecified |
| 024 | UNKNOWN | Application status unspecified |

All IDs have prefix `t5-pv-doc-`. The corpus is
`t5-e1frozen-pv-001-corpus`, version `1`; the independently authored reference set is
`t5-e1frozen-pv-001-reference`, version `1`. Each reference row records the label,
reason, `URL#text` locator, corpus fingerprint and verbatim evidence for each
predicate. Labels are literal source data, not retriever output or ranking-derived
truth. No actual market opportunity is represented.

The future reference adjudication contract joins valid returned IDs to that frozen
authority; no model judge, external verification or D3 Judgment-only package is
created. Recall@Budget divides retrieved positives by the six frozen positives.
Precision@K uses K=10 first-return unique IDs and counts only KNOWN labels in that
prefix, without backfilling UNKNOWN. UNKNOWN returns are counted separately. A
zero binary denominator is NOT_EVALUABLE. These are frozen definitions, not scores
from an execution. Any future entrant context must exclude reference labels and
adjudication materials even though this developer review bundle includes them.

## Bindings and contracts

| Decision | Status | Material |
|---|---|---|
| D1 | FROZEN | E1_FROZEN |
| D2 | FROZEN | Exact SearchSpec v2 |
| D3 | NOT_APPLICABLE | No Judgment-only track |
| D4 | FROZEN | Corpus, collection provenance, index, reference, reproduction |
| D5 | FROZEN | Two synthetic not-connected fixture agents |
| D6 | FROZEN | Exact published F1-eligible retriever object |
| D7 | FROZEN | Numeric resource envelope and concrete no-retry policy |
| D8 | NOT_APPLICABLE | No F2/F3/ablation package |

Every FROZEN decision resolves an artifact and an authoring approval reference in
`manifest.json`'s content-addressed artifact map. These references are inert
declarations for independent review. The current protocol's strict decision
objects are retained without extra fields. All required material validates, but
`instance_gate` must still return:

```json
{"missing_decisions":[],"terminal_status":"BLOCKED","execution_allowed":false,"reason_codes":["T1_IMPLEMENTATION_ONLY"]}
```

D5 contains `t5-fixture-agent-a` and `t5-fixture-agent-b`, requested/resolved model
IDs `fixture-agent-a-v1` and `fixture-agent-b-v1`. Both are KNOWN, AS_REQUESTED,
provider `synthetic-not-connected`, endpoint mode NOT_CONNECTED, alias evidence
null. Their explicit fixture configurations contain no connection details.

D7 permits at most four future raw backend attempts/four search turns, ten results
per call, zero follow links, zero automatic/manual retries and no fallback. Limits
are 1,000 ms per call, 60,000 ms total, 8,000 tokens and USD 0. Failures remain
infrastructure outcomes; exhaustion stops without expansion; budget rejection
uses no backend or ticket. These ceilings authorize no call in this work order.

A0 is frozen Human+Model program architecture and unscored. A1 stays entrant-owned:
QUERY_WORDING, SYNONYMS, SUBDIRECTION, BOUNDED_REFINEMENT, EVIDENCE_FOLLOWING only.
TASK, SCOPE, BUDGET, EVIDENCE and UNKNOWN_RULE cannot change. The future principal
variable is ENTRANT_MODEL_CONFIG. All other required controls resolve real frozen
material, including environment, prompt context and tools.

The environment is a Python/Unicode/source/descriptor identity predicate, not a
claim that a hosted runner image is permanently bit-identical. A later execution
order must recheck it or freeze a stronger image identity. Network and
provider/model/credential access are forbidden in this authoring path.

Output and evidence contracts include closed JSON schemas plus cross-field
provenance requirements. Future submissions bind spec, entrant, environment,
retriever, resource receipt, query/result provenance, exact frozen locators,
submission hash and typed terminal status. Identity or evidence failures cannot
be silently repaired. No submission, score or runner is produced here.

The unchanged generic SearchSpec schema names this track's permitted claim category
`EXECUTION_ON_FROZEN_ENVIRONMENT`. That enum is retained for schema compatibility;
it is not an execution receipt. The narrower T5 claims ceiling is bound in the
manifest, output, adjudication and receipt. T5 validation rejects expansion to
ABSOLUTE_RECALL, benchmark or model-quality claims even if another instance could
use a broader generic protocol category.

## Reproduction and fingerprint conventions

Run from the exact reviewed checkout with Python 3.11 / Unicode 14.0.0:

```sh
python -m unittest discover -s tests -p 'test_search_cup_v23_t5_e1f_instance.py' -v
python -m search_cup.v23_t5_e1f_instance bundle \
  --expected-source-sha 4785c392eb0b9e5d04c8eef04289a4888c222839 \
  --expected-source-tree 07849a3696009c47d284b896fd3f1676f617e98b \
  --output /tmp/t5-pv-new-directory
python -m search_cup.v23_t5_e1f_instance validate \
  --expected-source-sha 4785c392eb0b9e5d04c8eef04289a4888c222839 \
  --expected-source-tree 07849a3696009c47d284b896fd3f1676f617e98b \
  --output /tmp/t5-pv-new-directory
```

Each build constructs two fresh immutable indexes with the accepted lexical
implementation/config. Their canonical representation contains ordered doc IDs and
sorted character-ngram counts; their fingerprints must match the pinned input.
The representation is emitted in `index-descriptor.json`. No query is needed.
Wrong corpus/config/descriptor/source/runtime fails closed. Known transport,
environment, runner/judge and query seams are blocked; source pins and review
bound the permitted call graph. The guard is not a hostile-code sandbox.

`canonical_fingerprint` is SHA256 of canonical JSON excluding that object's own
top-level seal. New protocol references use SHA256 of the complete object,
including its seal, as required by `protocol_v23.reference`. The corpus content
fingerprint is the accepted FrozenCorpus schema/documents hash; it is distinct
from the versioned corpus artifact seal and its reference hash. Published PR69
reference semantics are preserved and checked by its unchanged validator.

The package fingerprint hashes the filename-to-seal map for the 14 core payloads
other than `receipt.json`, avoiding a self-reference. The receipt is separately
sealed and every final file is byte-hashed by MANIFEST.sha256. Standalone output:
15 JSON payloads plus MANIFEST. CI adds `ci-source.json` and `focused-tests.log`,
then finalizes a 17-entry byte manifest. CI provenance/log bytes are run-specific;
the 15 core JSON payloads are deterministic and compared across full builds.

Dedicated CI publishes one exact-head artifact for independent review. It records
negative blocked attempts separately from actual zero query/external calls. Git
provenance, checkout, setup and artifact upload are CI infrastructure, not instance
capabilities. The unchanged ordinary full suite may execute historical local
retriever regressions; those are outside T5's zero-query authoring receipt.

Stop after Draft PR, exact-head CI and artifact return. T5 acceptance, publication
and any later E1 execution are separate gates.
