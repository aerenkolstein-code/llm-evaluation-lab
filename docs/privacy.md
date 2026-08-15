# Privacy and evidence policy

Public cases preserve the failure mechanism, expected behavior and reproducible structure—not the private scene that first revealed the problem.

Historical benchmark publication uses a one-way transformation: private
correction chains become mechanism identifiers, neutral synthetic scenarios,
explicit constraints and expected structural decisions. Real names, relationships,
quotations, source filenames, archive URLs, account identifiers, timestamps and
provider-specific private details are not copied into the public fixture.

CI checks the checked fixture for known private locator patterns. This check is a
release guard, not a claim that automated scanning can replace human review.

No file may expose or link to private Raw/L0, relationship or family records, adult material, medical/financial data, accounts, platform assessments, client material, unpublished manuscripts or internal archive/control documents. Uncertain material remains private.

SQLite stores and JSON logs may contain experiment metadata and full public-safe
result payloads. They are runtime evidence, not repository fixtures: database
files are ignored by git, and operators must not pass private prompts, credentials
or archive locations through model, prompt-version, git-commit or run-ID fields.

The query API returns stored metadata and, for a requested run, its canonical
result payload. It therefore defaults to loopback and ships without any write
route. This is not an authentication boundary: operators must not expose it to a
network or populate it with non-public evidence without adding deployment-specific
access controls outside this artifact.

The image contains only repository public-safe files and a pinned public
Companion-Mind runtime commit. No database, log, credential, environment file or
private archive path is copied into the image. Runtime evidence must enter through
an explicit volume; read-only API use should mount that volume with `:ro` and bind
the published host port to loopback.
