# Methodology

The lab predeclares case inputs, expected behavior and metrics before comparing baseline and treatment.

```text
Observe → Diagnose → Intervene → Stress-test → Measure → Regression-test
```

The first artifact uses invariant transformations: child wording and order change while the required closure decision does not. A valid treatment must also preserve the sensitive all-terminal case, avoiding the trivial strategy “never close anything.”

The historical benchmark adds a second construction method:

1. review longitudinal correction chains in the private evidence layer;
2. group raw categories by shared failure mechanism and required gate;
3. rewrite each mechanism as a neutral synthetic scenario;
4. create one invalid `TRAP` and one matched valid `CONTROL`;
5. validate the pair with one uniform evidence-and-constraint policy;
6. scan the public fixture for private locators before release.

The 89 observations are therefore evidence for clustering, not 89 executable rules.
The reference gate has no mechanism-specific branch and never reads the expected
label. A new mechanism can use the same gate when it exposes evidence state and
explicit constraint statuses.

Future model-based runs will keep the same separation between case owner, policy under test, grader, mitigation and checked-in result.

## Experiment records

An experiment run is immutable evidence, not a mutable dashboard row. The SQLite
store uses `run_id` as the primary key and rejects duplicate IDs. Every record
keeps the case-suite identity, model or policy, prompt version, git commit, UTC
timestamp, latency, token cost, baseline and treatment accuracy, regression
status, and canonical result JSON. Listing returns indexed metadata without
dumping the stored result payload.

Structured lifecycle logs use one JSON object per line and remain separate from
the report channel: `run_started`, `run_completed`, `run_persisted`, or
`run_failed`. This preserves machine-readable observability without changing the
deterministic report contract when tracking is not requested.

## Read-only query boundary

The FastAPI surface is a projection over immutable SQLite evidence. It opens the
database in URI `mode=ro`, enables SQLite `query_only`, and exposes only health,
metadata-list, and single-run-detail GET routes. List responses omit the stored
result payload; detail responses return the canonical result for one run. Tests
hash the database before and after all three queries to prove the query path does
not mutate the evidence file.

## Container reproduction

The Docker image fixes the Companion-Mind runtime to an explicit commit, copies
only the executable public-safe fixture and schema directories, installs the lab
in editable mode so checked fixtures remain addressable, and drops privileges to
UID 10001. CI treats the image as a black box: it verifies the version, executes
the historical regression, writes one SQLite run through a mounted directory,
then starts the API with that directory mounted read-only and queries it over HTTP.

The Python base tag and transitive package resolution are not locked by digest;
this is repeatable functional packaging, not bit-for-bit image reproducibility.
