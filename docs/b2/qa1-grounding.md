# B2 QA1-A Grounding / RAG Fidelity

QA1-A is a deterministic, public-safe grounding profile built on three abstract seed families. It does not read private Errorbook bodies and does not measure a live model.

## Contracts

- `entity-attribute-binding`: every claim keeps entity, scope, attribute, and value bound to the supporting evidence.
- `inventory-evidence-scope`: only a current inventory/list/filter/account surface can establish a current count.
- `source-modality`: a claim may not assert a stronger provenance level than its source.

Required fields are frozen per family. Missing nested claim/source fields return `UNKNOWN`, set `evidence_complete=false`, and do not count as known-bad detection. For an allowed inventory surface, `current_count` is required; a detail-only surface remains an ordinary scope failure. Wrong binding, wrong source scope, or provenance upgrade is a hard failure and cannot be offset by a soft score.

The frozen suite contains three known-bad cases and three matched controls. Its receipt derives and fingerprints the exact three-family set, one known-bad/control pair per family, unique case IDs, and family-specific deterministic public seed digests.

## Boundary

The suite uses synthetic entities and sources. A passing receipt supports deterministic contract validation only, not broad RAG quality, production performance, or causal mechanism claims.
