"""B2 QA3: deterministic quality projection and neutral adapter contracts.

The module treats SQLite runs and checked B2 receipts as canonical evidence.
Dashboards and adapter representations are disposable, read-only projections.
Only public-safe synthetic aliases and repository-local evidence paths belong in
the public lane.
"""

from __future__ import annotations

import hashlib
import html
import json
import re
import sqlite3
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

from .qa0 import (
    CaseResult,
    TERMINAL_STATUSES,
    abstract_seed_digest,
    assert_public_safe,
    canonical_json,
    sha256_json,
    validate_public_seed,
)

QA3_RECEIPT_SCHEMA_VERSION = "b2-qa3-projection-integrity-receipt/v1"
QUALITY_PROJECTION_SCHEMA_VERSION = "b2-qa3-quality-delta-projection/v1"
NEUTRAL_RECORD_SCHEMA_VERSION = "b2-qa3-neutral-projection-record/v1"
REFERENCE_ADAPTER_SCHEMA_VERSION = "b2-qa3-reference-adapter/v1"
RECONCILIATION_SCHEMA_VERSION = "b2-qa3-adapter-reconciliation/v1"
ADAPTER_RECEIPT_SCHEMA_VERSION = "b2-qa3-adapter-validation-receipt/v1"

PROJECTION_FAMILIES = {
    "full-set-projection-completeness",
    "metric-attribution-provenance-separation",
    "dashboard-field-semantics-scope-lock",
}
SEED_LINEAGE = {
    "full-set-projection-completeness": "QA3-SEED-P01",
    "metric-attribution-provenance-separation": "QA3-SEED-P02",
    "dashboard-field-semantics-scope-lock": "QA3-SEED-P03",
}
DETECTION_ORACLES = {
    "full-set-projection-completeness": {
        "declared_source_set_complete",
        "sample_not_global_evidence",
        "source_identity_unambiguous",
        "unique_source_identity",
    },
    "metric-attribution-provenance-separation": {
        "causal_attribution_evidenced",
        "metric_value_provenance_separated",
        "no_baseline_not_zero_delta",
    },
    "dashboard-field-semantics-scope-lock": {
        "field_semantics_preserved",
        "field_scope_preserved",
    },
}

PROJECTION_INPUT_FIELDS = {
    "full-set-projection-completeness": {
        "selection_predicate",
        "declared_source_ids",
        "available_source_ids",
        "sampled_source_ids",
        "projected_source_ids",
        "source_identities_unambiguous",
        "output_envelope_fingerprint_valid",
        "claim_scope",
    },
    "metric-attribution-provenance-separation": {
        "metric_id",
        "metric_version",
        "metric_definition",
        "metric_value",
        "source_identity",
        "scope_type",
        "scope_id",
        "observed_at",
        "source_ref",
        "provenance_state",
        "attribution_state",
        "causal_evidence_state",
        "causal_narrative",
        "baseline_ref",
        "claimed_delta",
    },
    "dashboard-field-semantics-scope-lock": {
        "field_id",
        "field_semantics",
        "source_semantics",
        "scope_type",
        "source_scope_type",
        "scope_id",
        "source_scope_id",
        "observed_at",
        "source_ref",
        "displayed_value",
        "source_value",
        "aggregation_eligible",
    },
}

SCOPE_TYPES = {
    "PERSONAL_CURRENT",
    "PERSONAL_HISTORY",
    "GLOBAL_CURRENT",
    "GLOBAL_HISTORY",
    "RUN",
    "PROFILE",
    "UNKNOWN",
}
PROVENANCE_STATES = {"VERIFIED", "USER_REPORTED", "INFERRED", "UNKNOWN"}
COMPARABILITY_FIELDS = (
    "profile",
    "suite_id",
    "metric_id",
    "metric_version",
    "metric_definition",
    "case_set_fingerprint",
    "terminal_semantics_version",
    "aggregation_rule",
    "scope_type",
    "scope_id",
)

ADAPTER_REQUIRED_SCENARIOS = {
    "EXACT_ROUNDTRIP",
    "DIGEST_MISMATCH",
    "METRIC_SEMANTICS_MISMATCH",
    "TERMINAL_MISMATCH",
    "SCOPE_MISMATCH",
    "VALUE_MISMATCH",
    "ADAPTER_UNAVAILABLE",
    "LOSSY_OPTIONAL_EXPLICIT",
    "SILENT_CRITICAL_DROP",
}
ADAPTER_MISMATCH_SCENARIOS = ADAPTER_REQUIRED_SCENARIOS - {
    "EXACT_ROUNDTRIP",
    "ADAPTER_UNAVAILABLE",
    "LOSSY_OPTIONAL_EXPLICIT",
}


@dataclass(frozen=True)
class QA3CaseResult(CaseResult):
    provenance_digest: str
    seed_lineage: str


def _obj(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _text(document: Mapping[str, Any], key: str, label: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}.{key} must be a non-empty string")
    return value.strip()


def _string_list(value: object, label: str, *, allow_empty: bool = True) -> list[str]:
    if not isinstance(value, list) or (not allow_empty and not value):
        raise ValueError(f"{label} must be a string array")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ValueError(f"{label} must contain non-empty strings")
    return [item.strip() for item in value]


def _number(value: object, label: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError(f"{label} must be numeric")
    return float(value)


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"sha256:[0-9a-f]{64}", value) is not None


def _is_git_commit(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{40}", value) is not None


def _case_complete(data: Mapping[str, Any], family: str) -> bool:
    required = PROJECTION_INPUT_FIELDS[family]
    nullable = {"baseline_ref", "claimed_delta"}
    return all(key in data and (data[key] is not None or key in nullable) for key in required)


def _validate_projection_input(data: Mapping[str, Any], family: str) -> None:
    unknown = set(data) - PROJECTION_INPUT_FIELDS[family]
    if unknown:
        raise ValueError(f"unsupported QA3 input fields: {sorted(unknown)!r}")
    if family == "full-set-projection-completeness":
        for key in (
            "declared_source_ids",
            "available_source_ids",
            "sampled_source_ids",
            "projected_source_ids",
        ):
            if key in data:
                _string_list(data[key], f"input.{key}")
        for key in ("source_identities_unambiguous", "output_envelope_fingerprint_valid"):
            if key in data and not isinstance(data[key], bool):
                raise ValueError(f"input.{key} must be boolean")
        if "claim_scope" in data and data["claim_scope"] not in {"GLOBAL", "SUBSET"}:
            raise ValueError("input.claim_scope is unsupported")
        if "selection_predicate" in data:
            _text(data, "selection_predicate", "input")
    elif family == "metric-attribution-provenance-separation":
        for key in (
            "metric_id",
            "metric_version",
            "metric_definition",
            "source_identity",
            "scope_id",
            "observed_at",
            "source_ref",
        ):
            if key in data:
                _text(data, key, "input")
        if "metric_value" in data:
            _number(data["metric_value"], "input.metric_value")
        if "claimed_delta" in data and data["claimed_delta"] is not None:
            _number(data["claimed_delta"], "input.claimed_delta")
        if "baseline_ref" in data and data["baseline_ref"] is not None:
            if not isinstance(data["baseline_ref"], str) or not data["baseline_ref"].strip():
                raise ValueError("input.baseline_ref must be null or a non-empty string")
        for key in ("provenance_state", "attribution_state", "causal_evidence_state"):
            if key in data and data[key] not in PROVENANCE_STATES:
                raise ValueError(f"input.{key} is unsupported")
        if "scope_type" in data and data["scope_type"] not in SCOPE_TYPES:
            raise ValueError("input.scope_type is unsupported")
        if "causal_narrative" in data and not isinstance(data["causal_narrative"], bool):
            raise ValueError("input.causal_narrative must be boolean")
    else:
        for key in (
            "field_id",
            "field_semantics",
            "source_semantics",
            "scope_id",
            "source_scope_id",
            "observed_at",
            "source_ref",
        ):
            if key in data:
                _text(data, key, "input")
        for key in ("scope_type", "source_scope_type"):
            if key in data and data[key] not in SCOPE_TYPES:
                raise ValueError(f"input.{key} is unsupported")
        if "aggregation_eligible" in data and not isinstance(data["aggregation_eligible"], bool):
            raise ValueError("input.aggregation_eligible must be boolean")
        if "displayed_value" in data and not isinstance(data["displayed_value"], (str, int, float, bool)):
            raise ValueError("input.displayed_value has unsupported type")
        if "source_value" in data and not isinstance(data["source_value"], (str, int, float, bool)):
            raise ValueError("input.source_value has unsupported type")


def validate_qa3_case(document: object) -> dict[str, Any]:
    raw = _obj(document, "QA3 case")
    expected_keys = {
        "schema_version",
        "family_id",
        "seed_lineage",
        "case_id",
        "variant",
        "capability_profile",
        "privacy",
        "provenance",
        "input",
        "expected",
        "limitations",
    }
    if set(raw) != expected_keys:
        raise ValueError("QA3 case has an invalid top-level shape")
    lineage = raw.get("seed_lineage")
    case = validate_public_seed(raw)
    family = case["family_id"]
    if family not in PROJECTION_FAMILIES:
        raise ValueError(f"family {family!r} is not in QA3-A")
    if lineage != SEED_LINEAGE[family]:
        raise ValueError("seed_lineage does not match frozen public alias")
    _validate_projection_input(case["input"], family)
    case["seed_lineage"] = lineage
    return case


def _score_projection(data: Mapping[str, Any], family: str):
    if not _case_complete(data, family):
        return "UNKNOWN", False, ("evidence_complete",)

    failed: list[str] = []
    unresolved = False
    if family == "full-set-projection-completeness":
        declared = list(data["declared_source_ids"])
        available = list(data["available_source_ids"])
        sampled = list(data["sampled_source_ids"])
        projected = list(data["projected_source_ids"])
        if any(len(values) != len(set(values)) for values in (declared, available, sampled, projected)):
            failed.append("unique_source_identity")
        if not data["source_identities_unambiguous"]:
            failed.append("source_identity_unambiguous")
        if set(declared) != set(available):
            failed.append("declared_source_set_complete")
        if data["claim_scope"] == "GLOBAL" and set(projected) != set(declared):
            failed.append("declared_source_set_complete")
        if data["claim_scope"] == "GLOBAL" and set(sampled) != set(declared):
            failed.append("sample_not_global_evidence")
        if not data["output_envelope_fingerprint_valid"]:
            failed.append("projection_envelope_fingerprint_valid")
    elif family == "metric-attribution-provenance-separation":
        if data["provenance_state"] == "UNKNOWN" and data["attribution_state"] != "UNKNOWN":
            failed.append("metric_value_provenance_separated")
        if data["causal_narrative"] and data["causal_evidence_state"] != "VERIFIED":
            failed.append("causal_attribution_evidenced")
        if data["baseline_ref"] is None and data["claimed_delta"] is not None:
            failed.append("no_baseline_not_zero_delta")
        if not str(data["source_ref"]).startswith(("B2_RECEIPT:", "SQLITE_RUN:")):
            failed.append("canonical_evidence_ref_present")
        if data["scope_type"] == "UNKNOWN":
            unresolved = True
    else:
        if data["field_semantics"] != data["source_semantics"]:
            failed.append("field_semantics_preserved")
        if (
            data["scope_type"] != data["source_scope_type"]
            or data["scope_id"] != data["source_scope_id"]
        ):
            failed.append("field_scope_preserved")
        if data["displayed_value"] != data["source_value"]:
            failed.append("displayed_value_reproducible")
        if not str(data["source_ref"]).startswith(("B2_RECEIPT:", "SQLITE_RUN:")):
            failed.append("canonical_evidence_ref_present")
        if "UNKNOWN" in {data["scope_type"], data["source_scope_type"]}:
            if data["aggregation_eligible"]:
                failed.append("ambiguous_scope_not_aggregated")
            else:
                unresolved = True

    unique = tuple(sorted(set(failed)))
    if unique:
        return "FAIL", False, unique
    if unresolved:
        return "UNKNOWN", False, ("scope_unresolved",)
    return "PASS", True, ()


def score_qa3_case(document: object) -> QA3CaseResult:
    case = validate_qa3_case(document)
    family = case["family_id"]
    status, hard_pass, failed = _score_projection(case["input"], family)
    complete = "evidence_complete" not in failed
    digest = str(case["provenance"].get("seed_digest", ""))
    traceable = digest == abstract_seed_digest(family)
    if case["variant"] == "CONTROL":
        detected = status == "PASS"
    else:
        detected = (
            complete
            and status == "FAIL"
            and bool(set(failed) & DETECTION_ORACLES[family])
        )
    return QA3CaseResult(
        case_id=case["case_id"],
        family_id=family,
        variant=case["variant"],
        terminal_status=status,
        hard_invariant_pass=hard_pass,
        detected=detected,
        failed_invariants=failed,
        evidence_complete=complete,
        provenance_traceable=traceable,
        fixture_fingerprint=sha256_json(case),
        provenance_digest=digest,
        seed_lineage=case["seed_lineage"],
    )


def build_qa3_receipt(results: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = sorted((dict(row) for row in results), key=lambda row: row["case_id"])
    known_bad = [row for row in rows if row["variant"] == "KNOWN_BAD"]
    controls = [row for row in rows if row["variant"] == "CONTROL"]
    composition = {
        family: {
            "case_count": sum(row["family_id"] == family for row in rows),
            "variants": sorted(row["variant"] for row in rows if row["family_id"] == family),
            "seed_lineages": sorted({row.get("seed_lineage") for row in rows if row["family_id"] == family}),
            "provenance_digests": sorted({row.get("provenance_digest") for row in rows if row["family_id"] == family}),
        }
        for family in sorted({row["family_id"] for row in rows})
    }
    expected_families = sorted(PROJECTION_FAMILIES)
    exact_pairing = (
        sorted(composition) == expected_families
        and all(info["case_count"] == 2 and info["variants"] == ["CONTROL", "KNOWN_BAD"] for info in composition.values())
        and all(info["seed_lineages"] == [SEED_LINEAGE[family]] for family, info in composition.items())
        and all(info["provenance_digests"] == [abstract_seed_digest(family)] for family, info in composition.items())
    )
    receipt = {
        "schema_version": QA3_RECEIPT_SCHEMA_VERSION,
        "profile": "PROJECTION_INTEGRITY",
        "run_id": "B2-QA3-PROJECTION-INTEGRITY-DETERMINISTIC-001",
        "runner": "python-unittest-compatible/deterministic",
        "scope": "FROZEN_DETERMINISTIC_SYNTHETIC_QA3_A_FIXTURE_SET",
        "case_count": len(rows),
        "known_bad_count": len(known_bad),
        "control_count": len(controls),
        "family_count": len(composition),
        "expected_families": expected_families,
        "observed_families": sorted(composition),
        "family_composition": composition,
        "unique_case_id_count": len({row["case_id"] for row in rows}),
        "exact_family_pairing": exact_pairing,
        "known_bad_detection_rate": (
            sum(bool(row["detected"]) for row in known_bad) / len(known_bad)
            if known_bad else None
        ),
        "control_false_reject_rate": (
            sum(row["terminal_status"] != "PASS" for row in controls) / len(controls)
            if controls else None
        ),
        "provenance_trace_rate": (
            sum(bool(row["provenance_traceable"]) for row in rows) / len(rows)
            if rows else None
        ),
        "evidence_completeness_rate": (
            sum(bool(row["evidence_complete"]) for row in rows) / len(rows)
            if rows else None
        ),
        "terminal_statuses": sorted({row["terminal_status"] for row in rows}),
        "fixture_fingerprints": {row["case_id"]: row["fixture_fingerprint"] for row in rows},
        "limitations": [
            "Frozen synthetic deterministic projection-integrity cases only.",
            "No live model, provider, private source body, or brand-specific adapter is evaluated.",
            "A single checked snapshot does not establish a model trend or broad generalization claim.",
        ],
    }
    receipt["gate_criteria"] = {
        "case_count": 6,
        "known_bad_count": 3,
        "control_count": 3,
        "family_count": 3,
        "observed_families": expected_families,
        "unique_case_id_count": 6,
        "exact_family_pairing": True,
        "known_bad_detection_rate": 1.0,
        "control_false_reject_rate": 0.0,
        "provenance_trace_rate": 1.0,
        "evidence_completeness_rate": 1.0,
    }
    receipt["gate"] = (
        "PASS"
        if all(receipt.get(key) == value for key, value in receipt["gate_criteria"].items())
        else "FAIL"
    )
    receipt["receipt_fingerprint"] = sha256_json(receipt)
    return receipt


def verify_checked_receipt(receipt: object) -> dict[str, Any]:
    document = dict(_obj(receipt, "checked receipt"))
    fingerprint = document.pop("receipt_fingerprint", None)
    if not _is_sha256(fingerprint) or fingerprint != sha256_json(document):
        raise ValueError("checked receipt fingerprint does not reproduce")
    if document.get("gate") != "PASS":
        raise ValueError("only PASS checked receipts may enter a GREEN projection")
    document["receipt_fingerprint"] = fingerprint
    return document


def validate_evidence_ref(reference: object) -> dict[str, Any]:
    ref = dict(_obj(reference, "CanonicalEvidenceRef"))
    required = {
        "kind",
        "source_id",
        "source_locator",
        "source_fingerprint",
        "git_commit",
        "scope",
    }
    if set(ref) != required:
        raise ValueError("CanonicalEvidenceRef has an invalid shape")
    if ref["kind"] not in {"B2_RECEIPT", "SQLITE_RUN"}:
        raise ValueError("CanonicalEvidenceRef.kind is unsupported")
    for key in ("source_id", "source_locator", "scope"):
        _text(ref, key, "CanonicalEvidenceRef")
    if not _is_sha256(ref["source_fingerprint"]):
        raise ValueError("CanonicalEvidenceRef fingerprint is invalid")
    if not _is_git_commit(ref["git_commit"]):
        raise ValueError("CanonicalEvidenceRef git_commit must be a full commit SHA")
    expected_prefix = "B2_RECEIPT:" if ref["kind"] == "B2_RECEIPT" else "SQLITE_RUN:"
    if not ref["source_id"].startswith(expected_prefix):
        raise ValueError("CanonicalEvidenceRef source_id does not match its kind")
    assert_public_safe(ref)
    return ref


def _bounded_receipt_path(path: object) -> str:
    if not isinstance(path, str) or not path.strip():
        raise ValueError("receipt path must be a non-empty string")
    normalized = path.strip()
    if (
        PurePosixPath(normalized).is_absolute()
        or ".." in PurePosixPath(normalized).parts
        or PurePosixPath(normalized).as_posix() != normalized
        or not normalized.startswith("results/b2/")
    ):
        raise ValueError("receipt path must be a bounded repository-relative B2 result path")
    return normalized


def receipt_evidence_ref(path: str, receipt: object, git_commit: str) -> dict[str, Any]:
    path = _bounded_receipt_path(path)
    checked = verify_checked_receipt(receipt)
    return validate_evidence_ref(
        {
            "kind": "B2_RECEIPT",
            "source_id": f"B2_RECEIPT:{path}",
            "source_locator": path,
            "source_fingerprint": checked["receipt_fingerprint"],
            "git_commit": git_commit,
            "scope": str(checked.get("scope", "UNKNOWN")),
        }
    )


def _normalize_receipt_sources(
    receipt_sources: Iterable[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for index, source_value in enumerate(receipt_sources):
        source = dict(_obj(source_value, f"receipt source {index}"))
        if set(source) != {"path", "git_commit", "receipt"}:
            raise ValueError(f"receipt source {index} has an invalid shape")
        path = _bounded_receipt_path(source["path"])
        git_commit = str(source["git_commit"])
        checked = verify_checked_receipt(source["receipt"])
        normalized.append(
            {
                "receipt": checked,
                "evidence_ref": receipt_evidence_ref(path, checked, git_commit),
            }
        )
    return normalized


def _receipt_at_git_commit(
    repository_root: str | Path,
    *,
    path: str,
    git_commit: str,
) -> object:
    root = Path(repository_root)
    if not root.is_dir():
        raise ValueError("canonical receipt repository root does not exist")
    path = _bounded_receipt_path(path)
    if not _is_git_commit(git_commit):
        raise ValueError("canonical receipt git_commit must be a full commit SHA")
    object_type = subprocess.run(
        ["git", "-C", str(root), "cat-file", "-t", git_commit],
        check=False,
        capture_output=True,
    )
    if object_type.returncode != 0 or object_type.stdout.strip() != b"commit":
        raise ValueError("canonical receipt git_commit is not a Git commit object")
    completed = subprocess.run(
        ["git", "-C", str(root), "show", "--no-ext-diff", f"{git_commit}:{path}"],
        check=False,
        capture_output=True,
    )
    if completed.returncode != 0:
        raise ValueError("canonical receipt is unavailable at its declared path+commit")
    try:
        return json.loads(completed.stdout.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(
            "canonical receipt at the declared path+commit is invalid JSON"
        ) from exc


def _load_receipt_paths_at_git_commit(
    paths: Sequence[str],
    git_commit: str,
    repository_root: str | Path,
) -> list[dict[str, Any]]:
    return [
        {
            "path": _bounded_receipt_path(path),
            "git_commit": git_commit,
            "receipt": _receipt_at_git_commit(
                repository_root,
                path=path,
                git_commit=git_commit,
            ),
        }
        for path in paths
    ]


def _load_receipt_sources_at_git_commit(
    evidence_refs: Sequence[Mapping[str, Any]],
    repository_root: str | Path,
) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for reference in evidence_refs:
        ref = validate_evidence_ref(reference)
        if ref["kind"] != "B2_RECEIPT":
            raise ValueError("dashboard profiles require B2_RECEIPT canonical sources")
        path = _bounded_receipt_path(ref["source_locator"])
        if ref["source_id"] != f"B2_RECEIPT:{path}":
            raise ValueError("canonical receipt locator is not a bounded B2 path")
        sources.append(
            {
                "path": path,
                "git_commit": ref["git_commit"],
                "receipt": _receipt_at_git_commit(
                    repository_root,
                    path=path,
                    git_commit=ref["git_commit"],
                ),
            }
        )
    return sources


def _bind_receipt_sources_to_git(
    receipt_sources: Iterable[Mapping[str, Any]],
    repository_root: str | Path,
) -> list[dict[str, Any]]:
    """Return exact-Git sources only after rejecting any claimed-source mismatch."""

    claimed = _normalize_receipt_sources(receipt_sources)
    exact = _normalize_receipt_sources(
        _load_receipt_sources_at_git_commit(
            [item["evidence_ref"] for item in claimed],
            repository_root,
        )
    )
    claimed_by_id = {
        item["evidence_ref"]["source_id"]: item for item in claimed
    }
    exact_by_id = {item["evidence_ref"]["source_id"]: item for item in exact}
    if (
        len(claimed_by_id) != len(claimed)
        or len(exact_by_id) != len(exact)
        or claimed_by_id != exact_by_id
    ):
        raise ValueError(
            "claimed receipt sources do not match exact Git path+commit evidence"
        )
    return exact


def _profile_id(receipt: Mapping[str, Any]) -> str:
    schema = receipt.get("schema_version")
    if schema == "b2-qa0-receipt/v1":
        return "QA0"
    if schema == "b2-qa1-receipt/v1" and receipt.get("profile") in {"GROUNDING", "TOOL_AGENT"}:
        return f"QA1-{receipt['profile']}"
    if schema == "b2-qa2-receipt/v1" and receipt.get("profile") == "SAFETY_ROBUSTNESS":
        return "QA2-SAFETY_ROBUSTNESS"
    if schema == QA3_RECEIPT_SCHEMA_VERSION and receipt.get("profile") == "PROJECTION_INTEGRITY":
        return "QA3-A-PROJECTION_INTEGRITY"
    raise ValueError("unsupported checked receipt profile")


def _family_count(receipt: Mapping[str, Any]) -> int:
    value = receipt.get("family_count")
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    composition = receipt.get("family_composition")
    if isinstance(composition, Mapping):
        return len(composition)
    if receipt.get("schema_version") == "b2-qa0-receipt/v1":
        known_bad = receipt.get("known_bad_count")
        controls = receipt.get("control_count")
        if isinstance(known_bad, int) and known_bad == controls:
            return known_bad
    raise ValueError("checked receipt does not expose an auditable family count")


def _receipt_profile_summary(receipt: Mapping[str, Any]) -> dict[str, Any]:
    counts: dict[str, int] = {}
    for field in ("case_count", "known_bad_count", "control_count"):
        value = receipt.get(field)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(f"checked receipt {field} must be a non-negative integer")
        counts[field] = value
    terminals = _string_list(
        receipt.get("terminal_statuses"),
        "checked receipt terminal_statuses",
        allow_empty=False,
    )
    if (
        len(terminals) != len(set(terminals))
        or any(status not in TERMINAL_STATUSES for status in terminals)
    ):
        raise ValueError("checked receipt terminal statuses are invalid")
    return {
        "profile_id": _profile_id(receipt),
        "gate": receipt["gate"],
        "formal_family_count": _family_count(receipt),
        **counts,
        "terminal_statuses": terminals,
    }


def build_dashboard_projection(
    receipt_sources: Iterable[Mapping[str, Any]],
    *,
    declared_source_ids: Sequence[str],
    observed_at: str,
    snapshot_id: str,
    repository_root: str | Path | None = None,
) -> dict[str, Any]:
    sources = [dict(source) for source in receipt_sources]
    declared = list(declared_source_ids)
    if not declared or len(declared) != len(set(declared)):
        raise ValueError("declared source identities must be non-empty and unique")
    if not isinstance(observed_at, str) or not observed_at.endswith("Z"):
        raise ValueError("observed_at must be an explicit UTC timestamp")
    if not isinstance(snapshot_id, str) or not snapshot_id.strip():
        raise ValueError("snapshot_id must be a non-empty string")

    claimed = _normalize_receipt_sources(sources)
    observed_ids = [item["evidence_ref"]["source_id"] for item in claimed]
    if len(observed_ids) != len(set(observed_ids)):
        raise ValueError("duplicate canonical source identity")
    if set(observed_ids) != set(declared):
        raise ValueError("global projection requires the complete declared source set")
    commits = {item["evidence_ref"]["git_commit"] for item in claimed}
    if len(commits) != 1:
        raise ValueError("one static snapshot cannot silently mix git contexts")
    if repository_root is None:
        raise ValueError(
            "repository_root is required to bind receipt sources to exact Git evidence"
        )
    normalized = _bind_receipt_sources_to_git(sources, repository_root)

    profiles: list[dict[str, Any]] = []
    for item in normalized:
        receipt = item["receipt"]
        summary = _receipt_profile_summary(receipt)
        profile = {
            **summary,
            "field_semantics": "profile_checked_receipt_summary",
            "scope_type": "PROFILE",
            "scope_id": summary["profile_id"],
            "observed_at": observed_at,
            "evidence_ref": item["evidence_ref"],
        }
        profiles.append(profile)
    profiles.sort(key=lambda profile: profile["profile_id"])
    evidence_refs = [profile["evidence_ref"] for profile in profiles]

    quality_deltas = [
        {
            "profile_id": profile["profile_id"],
            "metric_id": "profile_gate_delta",
            "terminal_status": "NOT_EVALUABLE",
            "reason": "NO_BASELINE",
            "baseline_value": None,
            "current_value": None,
            "delta": None,
            "scope_type": "PROFILE",
            "scope_id": profile["profile_id"],
            "observed_at": observed_at,
            "evidence_ref": profile["evidence_ref"],
        }
        for profile in profiles
    ]

    projection = {
        "schema_version": QUALITY_PROJECTION_SCHEMA_VERSION,
        "projection_id": "B2-QA3-STATIC-QUALITY-PROJECTION-001",
        "authority": "DERIVED_READ_ONLY_PROJECTION",
        "source_snapshot": {
            "snapshot_id": snapshot_id,
            "git_commit": next(iter(commits)),
            "observed_at": observed_at,
            "single_snapshot_only": True,
        },
        "source_manifest": {
            "selection_predicate": "all approved checked B2 QA0 through QA3-A receipts in the declared snapshot",
            "declared_source_ids": sorted(declared),
            "included_source_ids": sorted(observed_ids),
            "excluded_source_ids": [],
            "source_count": len(declared),
            "included_count": len(observed_ids),
            "excluded_count": 0,
            "dedupe_identity": "CanonicalEvidenceRef.source_id",
            "completeness_status": "PASS",
            "evidence_refs": evidence_refs,
        },
        "profiles": profiles,
        "quality_deltas": quality_deltas,
        "regression_recurrence": {
            "terminal_status": "NOT_EVALUABLE",
            "reason": "NO_CANONICAL_RECURRENCE_SERIES",
            "series": [],
            "evidence_refs": evidence_refs,
        },
        "terminal_state_visibility": {
            "statuses": sorted({status for profile in profiles for status in profile["terminal_statuses"]}),
            "preserves_unknown": True,
            "preserves_not_evaluable": True,
            "preserves_error": True,
            "evidence_refs": evidence_refs,
        },
        "performance": {
            "terminal_status": "NOT_EVALUABLE",
            "reason": "NO_CANONICAL_PERFORMANCE_METRICS_IN_SELECTED_RECEIPTS",
            "metrics": [],
            "evidence_refs": evidence_refs,
        },
        "brand_adapters": {
            "status": "OPTIONAL_NOT_SELECTED",
            "claims_unlocked": [],
        },
        "limitations": [
            "The selected checked receipts are one snapshot, not a time series or model-version trend.",
            "No baseline means NOT_EVALUABLE / NO_BASELINE, never zero improvement.",
            "No live provider, paid service, private source body, or brand-specific adapter is represented.",
            "Deleting this projection does not delete or modify any canonical receipt or SQLite run.",
        ],
    }
    assert_public_safe(projection)
    projection["projection_fingerprint"] = sha256_json(projection)
    return projection


def verify_dashboard_projection(
    document: object,
    *,
    receipt_sources: Iterable[Mapping[str, Any]] | None = None,
    repository_root: str | Path | None = None,
) -> dict[str, Any]:
    projection = dict(_obj(document, "quality projection"))
    fingerprint = projection.pop("projection_fingerprint", None)
    required = {
        "schema_version",
        "projection_id",
        "authority",
        "source_snapshot",
        "source_manifest",
        "profiles",
        "quality_deltas",
        "regression_recurrence",
        "terminal_state_visibility",
        "performance",
        "brand_adapters",
        "limitations",
    }
    if set(projection) != required:
        raise ValueError("quality projection has an invalid top-level shape")
    if projection.get("schema_version") != QUALITY_PROJECTION_SCHEMA_VERSION:
        raise ValueError("unsupported quality projection schema")
    if projection.get("authority") != "DERIVED_READ_ONLY_PROJECTION":
        raise ValueError("dashboard cannot become a canonical authority")
    if not _is_sha256(fingerprint) or fingerprint != sha256_json(projection):
        raise ValueError("quality projection fingerprint does not reproduce")

    snapshot = _obj(projection.get("source_snapshot"), "source_snapshot")
    if set(snapshot) != {"snapshot_id", "git_commit", "observed_at", "single_snapshot_only"}:
        raise ValueError("source_snapshot has an invalid shape")
    _text(snapshot, "snapshot_id", "source_snapshot")
    if not _is_git_commit(snapshot.get("git_commit")):
        raise ValueError("source_snapshot git_commit must be a full commit SHA")
    if not isinstance(snapshot.get("observed_at"), str) or not snapshot["observed_at"].endswith("Z"):
        raise ValueError("source_snapshot observed_at must be explicit UTC")
    if snapshot.get("single_snapshot_only") is not True:
        raise ValueError("source_snapshot must remain a single snapshot")

    manifest = _obj(projection.get("source_manifest"), "source_manifest")
    manifest_fields = {
        "selection_predicate",
        "declared_source_ids",
        "included_source_ids",
        "excluded_source_ids",
        "source_count",
        "included_count",
        "excluded_count",
        "dedupe_identity",
        "completeness_status",
        "evidence_refs",
    }
    if set(manifest) != manifest_fields:
        raise ValueError("source_manifest has an invalid shape")
    _text(manifest, "selection_predicate", "source_manifest")
    declared = _string_list(manifest.get("declared_source_ids"), "declared_source_ids", allow_empty=False)
    included = _string_list(manifest.get("included_source_ids"), "included_source_ids", allow_empty=False)
    excluded = _string_list(manifest.get("excluded_source_ids"), "excluded_source_ids")
    if any(len(values) != len(set(values)) for values in (declared, included, excluded)):
        raise ValueError("projection source identities must be unique")
    if set(declared) != set(included) or excluded:
        raise ValueError("GREEN projection requires the complete declared source set")
    if (
        manifest.get("source_count") != len(declared)
        or manifest.get("included_count") != len(included)
        or manifest.get("excluded_count") != len(excluded)
        or manifest.get("dedupe_identity") != "CanonicalEvidenceRef.source_id"
        or manifest.get("completeness_status") != "PASS"
    ):
        raise ValueError("source_manifest counts or completeness semantics disagree")
    refs_value = manifest.get("evidence_refs")
    if not isinstance(refs_value, list) or not refs_value:
        raise ValueError("source_manifest evidence_refs must be non-empty")
    manifest_refs = [validate_evidence_ref(ref) for ref in refs_value]
    manifest_ref_ids = [ref["source_id"] for ref in manifest_refs]
    if len(manifest_ref_ids) != len(set(manifest_ref_ids)) or set(manifest_ref_ids) != set(included):
        raise ValueError("source_manifest evidence refs do not reproduce included identities")
    if any(ref["git_commit"] != snapshot["git_commit"] for ref in manifest_refs):
        raise ValueError("projection cannot mix canonical git contexts")
    root = repository_root or Path(__file__).resolve().parents[1]
    if receipt_sources is None:
        canonical_sources = _normalize_receipt_sources(
            _load_receipt_sources_at_git_commit(manifest_refs, root)
        )
    else:
        if repository_root is None:
            raise ValueError(
                "caller-supplied receipt sources require repository_root for exact Git binding"
            )
        canonical_sources = _bind_receipt_sources_to_git(receipt_sources, root)
    canonical_by_id = {
        item["evidence_ref"]["source_id"]: item for item in canonical_sources
    }
    if len(canonical_by_id) != len(canonical_sources):
        raise ValueError("canonical receipt source identities must be unique")
    if set(canonical_by_id) != set(included):
        raise ValueError("canonical receipt sources do not reproduce the declared set")
    manifest_refs_by_id = {ref["source_id"]: ref for ref in manifest_refs}
    if any(
        canonical_by_id[source_id]["evidence_ref"] != manifest_refs_by_id[source_id]
        for source_id in included
    ):
        raise ValueError("canonical receipt refs do not match declared path+commit evidence")

    profiles_value = projection.get("profiles")
    if not isinstance(profiles_value, list) or not profiles_value:
        raise ValueError("profiles must be a non-empty array")
    profile_fields = {
        "profile_id",
        "gate",
        "formal_family_count",
        "case_count",
        "known_bad_count",
        "control_count",
        "terminal_statuses",
        "field_semantics",
        "scope_type",
        "scope_id",
        "observed_at",
        "evidence_ref",
    }
    profiles: list[dict[str, Any]] = []
    for value in profiles_value:
        profile = dict(_obj(value, "profile"))
        if set(profile) != profile_fields:
            raise ValueError("profile has an invalid shape")
        profile_id = _text(profile, "profile_id", "profile")
        if (
            profile.get("gate") != "PASS"
            or profile.get("field_semantics") != "profile_checked_receipt_summary"
            or profile.get("scope_type") != "PROFILE"
            or profile.get("scope_id") != profile_id
            or profile.get("observed_at") != snapshot["observed_at"]
        ):
            raise ValueError("profile semantics, scope, or snapshot disagree")
        for count_field in ("formal_family_count", "case_count", "known_bad_count", "control_count"):
            count = profile.get(count_field)
            if not isinstance(count, int) or isinstance(count, bool) or count < 0:
                raise ValueError(f"profile {count_field} must be a non-negative integer")
        terminals = _string_list(profile.get("terminal_statuses"), "profile terminal_statuses")
        if len(terminals) != len(set(terminals)) or any(status not in TERMINAL_STATUSES for status in terminals):
            raise ValueError("profile terminal statuses are invalid")
        ref = validate_evidence_ref(profile.get("evidence_ref"))
        if ref["source_id"] not in included or ref["git_commit"] != snapshot["git_commit"]:
            raise ValueError("profile evidence ref is outside the declared snapshot")
        canonical_source = canonical_by_id[ref["source_id"]]
        if ref != canonical_source["evidence_ref"]:
            raise ValueError("profile evidence ref does not bind to canonical receipt")
        expected_summary = _receipt_profile_summary(canonical_source["receipt"])
        observed_summary = {
            key: profile[key]
            for key in (
                "profile_id",
                "gate",
                "formal_family_count",
                "case_count",
                "known_bad_count",
                "control_count",
                "terminal_statuses",
            )
        }
        if observed_summary != expected_summary:
            raise ValueError(
                "profile scalar/status summary does not rehydrate from canonical receipt"
            )
        profiles.append(profile)
    profile_ids = [profile["profile_id"] for profile in profiles]
    profile_ref_ids = [profile["evidence_ref"]["source_id"] for profile in profiles]
    if len(profile_ids) != len(set(profile_ids)) or set(profile_ref_ids) != set(included):
        raise ValueError("profiles must map one-to-one to declared receipt sources")

    deltas_value = projection.get("quality_deltas")
    if not isinstance(deltas_value, list) or len(deltas_value) != len(profiles):
        raise ValueError("quality_deltas must map one-to-one to profiles")
    delta_fields = {
        "profile_id",
        "metric_id",
        "terminal_status",
        "reason",
        "baseline_value",
        "current_value",
        "delta",
        "scope_type",
        "scope_id",
        "observed_at",
        "evidence_ref",
    }
    deltas: list[dict[str, Any]] = []
    profiles_by_id = {profile["profile_id"]: profile for profile in profiles}
    for value in deltas_value:
        delta = dict(_obj(value, "quality delta"))
        if set(delta) != delta_fields:
            raise ValueError("quality delta has an invalid shape")
        profile = profiles_by_id.get(delta.get("profile_id"))
        if profile is None:
            raise ValueError("quality delta references an unknown profile")
        if (
            delta.get("metric_id") != "profile_gate_delta"
            or delta.get("terminal_status") != "NOT_EVALUABLE"
            or delta.get("reason") != "NO_BASELINE"
            or any(delta.get(key) is not None for key in ("baseline_value", "current_value", "delta"))
            or delta.get("scope_type") != "PROFILE"
            or delta.get("scope_id") != profile["profile_id"]
            or delta.get("observed_at") != snapshot["observed_at"]
            or delta.get("evidence_ref") != profile["evidence_ref"]
        ):
            raise ValueError("quality delta invents a baseline, value, scope, or source")
        deltas.append(delta)
    if len({delta["profile_id"] for delta in deltas}) != len(profiles):
        raise ValueError("quality delta profile identities must be unique")

    expected_refs = [profile["evidence_ref"] for profile in profiles]
    recurrence = _obj(projection.get("regression_recurrence"), "regression_recurrence")
    if (
        set(recurrence) != {"terminal_status", "reason", "series", "evidence_refs"}
        or recurrence.get("terminal_status") != "NOT_EVALUABLE"
        or recurrence.get("reason") != "NO_CANONICAL_RECURRENCE_SERIES"
        or recurrence.get("series") != []
        or recurrence.get("evidence_refs") != expected_refs
    ):
        raise ValueError("single-snapshot recurrence must remain explicitly unavailable")

    visibility = _obj(projection.get("terminal_state_visibility"), "terminal_state_visibility")
    observed_terminals = sorted({status for profile in profiles for status in profile["terminal_statuses"]})
    if (
        set(visibility) != {
            "statuses",
            "preserves_unknown",
            "preserves_not_evaluable",
            "preserves_error",
            "evidence_refs",
        }
        or visibility.get("statuses") != observed_terminals
        or visibility.get("preserves_unknown") is not True
        or visibility.get("preserves_not_evaluable") is not True
        or visibility.get("preserves_error") is not True
        or visibility.get("evidence_refs") != expected_refs
    ):
        raise ValueError("terminal visibility does not reproduce canonical receipt terminals")

    performance = _obj(projection.get("performance"), "performance")
    if (
        set(performance) != {"terminal_status", "reason", "metrics", "evidence_refs"}
        or performance.get("terminal_status") != "NOT_EVALUABLE"
        or performance.get("reason") != "NO_CANONICAL_PERFORMANCE_METRICS_IN_SELECTED_RECEIPTS"
        or performance.get("metrics") != []
        or performance.get("evidence_refs") != expected_refs
    ):
        raise ValueError("performance must remain unavailable without canonical metrics")

    brand = _obj(projection.get("brand_adapters"), "brand_adapters")
    if set(brand) != {"status", "claims_unlocked"} or brand.get("status") != "OPTIONAL_NOT_SELECTED" or brand.get("claims_unlocked") != []:
        raise ValueError("brand-specific adapters are outside QA3 v0.1")
    _string_list(projection.get("limitations"), "limitations", allow_empty=False)
    projection["projection_fingerprint"] = fingerprint
    assert_public_safe(projection)
    return projection


def validate_metric_observation(document: object) -> dict[str, Any]:
    observation = dict(_obj(document, "metric observation"))
    required = {
        "observation_id",
        "comparable_key",
        "value",
        "terminal_status",
        "hard_invariant_pass",
        "provenance_state",
        "causal_attribution",
        "evidence_ref",
    }
    if set(observation) != required:
        raise ValueError("metric observation has an invalid shape")
    _text(observation, "observation_id", "metric observation")
    key = _obj(observation["comparable_key"], "comparable_key")
    if set(key) != set(COMPARABILITY_FIELDS):
        raise ValueError("comparable_key must freeze every comparison dimension")
    for field in COMPARABILITY_FIELDS:
        _text(key, field, "comparable_key")
    value = observation["value"]
    if value is not None:
        _number(value, "metric observation.value")
    if observation["terminal_status"] not in TERMINAL_STATUSES:
        raise ValueError("metric observation terminal status is unsupported")
    hard_invariant_pass = observation["hard_invariant_pass"]
    if hard_invariant_pass is not None and not isinstance(hard_invariant_pass, bool):
        raise ValueError("hard_invariant_pass must be boolean or null")
    if observation["terminal_status"] == "PASS" and hard_invariant_pass is not True:
        raise ValueError("PASS requires hard_invariant_pass=true")
    if observation["terminal_status"] == "FAIL" and hard_invariant_pass is not False:
        raise ValueError("FAIL requires hard_invariant_pass=false")
    if observation["provenance_state"] not in PROVENANCE_STATES:
        raise ValueError("metric provenance state is unsupported")
    if observation["causal_attribution"] not in PROVENANCE_STATES:
        raise ValueError("metric causal attribution is unsupported")
    validate_evidence_ref(observation["evidence_ref"])
    assert_public_safe(observation)
    return observation


def compute_quality_delta(current: object, baseline: object | None) -> dict[str, Any]:
    current_row = validate_metric_observation(current)
    current_hard_failure = (
        current_row["hard_invariant_pass"] is False
        or current_row["terminal_status"] == "FAIL"
    )
    if baseline is None:
        if current_hard_failure:
            return {
                "terminal_status": "FAIL",
                "reason": "HARD_INVARIANT_FAILURE",
                "baseline_value": None,
                "current_value": current_row["value"],
                "delta": None,
                "current_evidence_ref": current_row["evidence_ref"],
                "baseline_evidence_ref": None,
            }
        return {
            "terminal_status": "NOT_EVALUABLE",
            "reason": "NO_BASELINE",
            "baseline_value": None,
            "current_value": current_row["value"],
            "delta": None,
            "current_evidence_ref": current_row["evidence_ref"],
            "baseline_evidence_ref": None,
        }
    baseline_row = validate_metric_observation(baseline)
    statuses = {current_row["terminal_status"], baseline_row["terminal_status"]}
    hard_failure = (
        current_hard_failure
        or baseline_row["hard_invariant_pass"] is False
        or "FAIL" in statuses
    )
    if hard_failure:
        status, reason = "FAIL", "HARD_INVARIANT_FAILURE"
    elif "ERROR" in statuses:
        status, reason = "ERROR", "INFRASTRUCTURE_TERMINAL"
    elif "UNKNOWN" in statuses:
        status, reason = "UNKNOWN", "REQUIRED_EVIDENCE_UNRESOLVED"
    elif statuses & {"NOT_EVALUABLE", "BLOCKED"}:
        status, reason = "NOT_EVALUABLE", "INPUT_TERMINAL_NOT_COMPARABLE"
    elif current_row["comparable_key"] != baseline_row["comparable_key"]:
        status, reason = "FAIL", "NOT_COMPARABLE"
    elif current_row["value"] is None or baseline_row["value"] is None:
        status, reason = "UNKNOWN", "METRIC_VALUE_MISSING"
    else:
        status, reason = "PASS", "COMPARABLE"
    delta = (
        float(current_row["value"]) - float(baseline_row["value"])
        if status == "PASS" else None
    )
    return {
        "terminal_status": status,
        "reason": reason,
        "baseline_value": baseline_row["value"],
        "current_value": current_row["value"],
        "delta": delta,
        "current_evidence_ref": current_row["evidence_ref"],
        "baseline_evidence_ref": baseline_row["evidence_ref"],
    }


def load_sqlite_runs_read_only(store_path: str | Path) -> dict[str, Any]:
    path = Path(store_path)
    if not path.is_file():
        raise ValueError(f"experiment store does not exist: {path}")
    before = _sha256_bytes(path.read_bytes())
    try:
        connection = sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)
        connection.execute("PRAGMA query_only = ON")
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version != 1:
            raise ValueError(f"unsupported experiment store schema version {version}")
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """
            SELECT run_id, suite, case_suite_version, model, prompt_version,
                   git_commit, created_at_utc, latency_ms, token_cost,
                   baseline_accuracy, treatment_accuracy, regression_status,
                   result_json
            FROM experiment_runs
            ORDER BY created_at_utc, run_id
            """
        ).fetchall()
        connection.close()
    except sqlite3.DatabaseError as exc:
        raise ValueError(f"experiment store error: {exc}") from exc

    records: list[dict[str, Any]] = []
    for row in rows:
        record = dict(row)
        result = json.loads(str(record.pop("result_json")))
        if result.get("run_id") != record["run_id"]:
            raise ValueError("SQLite metadata and canonical result run identity disagree")
        canonical_record = {**record, "result": result}
        ref = validate_evidence_ref(
            {
                "kind": "SQLITE_RUN",
                "source_id": f"SQLITE_RUN:{record['run_id']}",
                "source_locator": f"experiment_runs/{record['run_id']}",
                "source_fingerprint": sha256_json(canonical_record),
                "git_commit": record["git_commit"],
                "scope": f"{record['suite']}:{record['case_suite_version']}",
            }
        )
        records.append(_verify_sqlite_run({**canonical_record, "evidence_ref": ref}))
    after = _sha256_bytes(path.read_bytes())
    if before != after:
        raise RuntimeError("read-only SQLite projection mutated canonical evidence")
    return {
        "schema_version": "b2-qa3-sqlite-read-only-projection/v1",
        "run_count": len(records),
        "declared_run_ids": [record["run_id"] for record in records],
        "unique_run_id_count": len({record["run_id"] for record in records}),
        "store_fingerprint_before": before,
        "store_fingerprint_after": after,
        "canonical_mutated": False,
        "runs": records,
    }


def _sqlite_terminal_semantics(
    record: Mapping[str, Any],
) -> tuple[str, bool | None]:
    column_status = record.get("regression_status")
    if not isinstance(column_status, str) or column_status not in TERMINAL_STATUSES:
        raise ValueError("SQLite regression_status is unsupported")
    result = _obj(record.get("result"), "SQLite canonical result")
    regression = _obj(result.get("regression"), "SQLite canonical result regression")
    result_status = regression.get("status")
    if result_status != column_status:
        raise ValueError("SQLite column and canonical result terminal statuses disagree")
    statuses = [column_status]
    integration = result.get("integration")
    if integration is not None:
        integration_status = _obj(
            integration, "SQLite canonical result integration"
        ).get("status")
        if integration_status not in TERMINAL_STATUSES:
            raise ValueError("SQLite integration terminal status is unsupported")
        statuses.append(str(integration_status))
    top_level_status = result.get("terminal_status")
    if top_level_status is not None:
        if top_level_status not in TERMINAL_STATUSES:
            raise ValueError("SQLite result terminal_status is unsupported")
        statuses.append(str(top_level_status))
    if "FAIL" in statuses:
        terminal = "FAIL"
    elif "ERROR" in statuses:
        terminal = "ERROR"
    elif "UNKNOWN" in statuses:
        terminal = "UNKNOWN"
    elif "BLOCKED" in statuses:
        terminal = "BLOCKED"
    elif "NOT_EVALUABLE" in statuses:
        terminal = "NOT_EVALUABLE"
    else:
        terminal = "PASS"
    if terminal == "FAIL":
        hard_invariant_pass: bool | None = False
    elif terminal == "PASS":
        hard_invariant_pass = True
    else:
        hard_invariant_pass = None
    return terminal, hard_invariant_pass


def _verify_sqlite_run(run: object) -> dict[str, Any]:
    record = dict(_obj(run, "SQLite run"))
    required = {
        "run_id",
        "suite",
        "case_suite_version",
        "model",
        "prompt_version",
        "git_commit",
        "created_at_utc",
        "latency_ms",
        "token_cost",
        "baseline_accuracy",
        "treatment_accuracy",
        "regression_status",
        "result",
        "evidence_ref",
    }
    if set(record) != required:
        raise ValueError("SQLite run has an invalid canonical shape")
    ref = validate_evidence_ref(record["evidence_ref"])
    run_id = _text(record, "run_id", "SQLite run")
    suite = _text(record, "suite", "SQLite run")
    case_suite_version = _text(record, "case_suite_version", "SQLite run")
    if (
        ref["source_id"] != f"SQLITE_RUN:{run_id}"
        or ref["source_locator"] != f"experiment_runs/{run_id}"
        or ref["git_commit"] != record["git_commit"]
        or ref["scope"] != f"{suite}:{case_suite_version}"
    ):
        raise ValueError("SQLite run evidence ref does not reproduce canonical identity")
    canonical_record = {
        key: value for key, value in record.items() if key != "evidence_ref"
    }
    if ref["source_fingerprint"] != sha256_json(canonical_record):
        raise ValueError("SQLite run evidence fingerprint does not reproduce")
    result = _obj(record["result"], "SQLite canonical result")
    if result.get("run_id") != run_id:
        raise ValueError("SQLite metadata and canonical result run identity disagree")
    for column, policy_name in (
        ("baseline_accuracy", "baseline"),
        ("treatment_accuracy", "treatment"),
    ):
        policy = _obj(result.get(policy_name), f"SQLite canonical result {policy_name}")
        result_accuracy = _number(
            policy.get("accuracy"),
            f"SQLite canonical result {policy_name}.accuracy",
        )
        column_accuracy = _number(record[column], f"SQLite run.{column}")
        if column_accuracy != result_accuracy:
            raise ValueError(
                f"SQLite {column} and canonical result {policy_name}.accuracy disagree"
            )
    _sqlite_terminal_semantics(record)
    return record


def sqlite_accuracy_delta(run: object) -> dict[str, Any]:
    record = _verify_sqlite_run(run)
    ref = record["evidence_ref"]
    terminal_status, hard_invariant_pass = _sqlite_terminal_semantics(record)
    key = {
        "profile": "CORE_REGRESSION",
        "suite_id": str(record["suite"]),
        "metric_id": "accuracy",
        "metric_version": "experiment-store/v1",
        "metric_definition": "correct cases divided by the declared case set",
        "case_set_fingerprint": str(record["case_suite_version"]),
        "terminal_semantics_version": "evaluation-result/v1",
        "aggregation_rule": "arithmetic_mean_over_declared_case_set",
        "scope_type": "RUN",
        "scope_id": str(record["run_id"]),
    }
    baseline = {
        "observation_id": f"{record['run_id']}:baseline_accuracy",
        "comparable_key": key,
        "value": record["baseline_accuracy"],
        "terminal_status": terminal_status,
        "hard_invariant_pass": hard_invariant_pass,
        "provenance_state": "VERIFIED",
        "causal_attribution": "UNKNOWN",
        "evidence_ref": ref,
    }
    current = {
        **baseline,
        "observation_id": f"{record['run_id']}:treatment_accuracy",
        "value": record["treatment_accuracy"],
    }
    return compute_quality_delta(current, baseline)


def validate_neutral_record(document: object) -> dict[str, Any]:
    record = dict(_obj(document, "neutral projection record"))
    required = {
        "schema_version",
        "record_id",
        "evidence_ref",
        "metric",
        "terminal_status",
        "hard_invariant_pass",
    }
    allowed = required | {"optional_metadata"}
    if set(record) - allowed or not required <= set(record):
        raise ValueError("neutral projection record has an invalid shape")
    if record["schema_version"] != NEUTRAL_RECORD_SCHEMA_VERSION:
        raise ValueError("unsupported neutral projection record schema")
    _text(record, "record_id", "neutral projection record")
    validate_evidence_ref(record["evidence_ref"])
    metric = _obj(record["metric"], "neutral projection metric")
    metric_fields = {
        "metric_id",
        "metric_version",
        "definition",
        "value",
        "unit",
        "scope_type",
        "scope_id",
        "observed_at",
        "provenance_state",
        "causal_attribution",
    }
    if set(metric) != metric_fields:
        raise ValueError("neutral projection metric has an invalid shape")
    for key in metric_fields - {"value"}:
        _text(metric, key, "neutral projection metric")
    if metric["value"] is not None:
        _number(metric["value"], "neutral projection metric.value")
    if metric["scope_type"] not in SCOPE_TYPES:
        raise ValueError("neutral projection metric scope is unsupported")
    for key in ("provenance_state", "causal_attribution"):
        if metric[key] not in PROVENANCE_STATES:
            raise ValueError(f"neutral projection metric {key} is unsupported")
    if record["terminal_status"] not in TERMINAL_STATUSES:
        raise ValueError("neutral projection terminal status is unsupported")
    if not isinstance(record["hard_invariant_pass"], bool):
        raise ValueError("neutral projection hard_invariant_pass must be boolean")
    if "optional_metadata" in record and not isinstance(record["optional_metadata"], Mapping):
        raise ValueError("optional_metadata must be an object")
    assert_public_safe(record)
    return record


def validate_adapter_representation(document: object) -> dict[str, Any]:
    adapter = dict(_obj(document, "adapter representation"))
    required = {
        "schema_version",
        "adapter_id",
        "adapter_record_id",
        "source_digest",
        "canonical_ref",
        "metric",
        "terminal_status",
        "hard_invariant_pass",
        "writeback_permitted",
        "limitations",
    }
    if set(adapter) != required:
        raise ValueError("adapter representation has an invalid shape")
    if adapter["schema_version"] != REFERENCE_ADAPTER_SCHEMA_VERSION:
        raise ValueError("unsupported reference adapter schema")
    if adapter.get("adapter_id") != "vendor-neutral-reference/v1":
        raise ValueError("unsupported reference adapter identity")
    _text(adapter, "adapter_record_id", "adapter representation")
    if not _is_sha256(adapter["source_digest"]):
        raise ValueError("adapter source_digest is invalid")
    validate_evidence_ref(adapter["canonical_ref"])
    if not isinstance(adapter["metric"], Mapping):
        raise ValueError("adapter metric must be an object")
    if adapter["terminal_status"] not in TERMINAL_STATUSES:
        raise ValueError("adapter terminal status is unsupported")
    if not isinstance(adapter["hard_invariant_pass"], bool):
        raise ValueError("adapter hard_invariant_pass must be boolean")
    if adapter["writeback_permitted"] is not False:
        raise ValueError("reference adapter must never permit canonical writeback")
    _string_list(adapter["limitations"], "adapter limitations")
    assert_public_safe(adapter)
    return adapter


def reference_adapter(
    canonical_record: object,
    *,
    available: bool = True,
    drop_optional_metadata: bool = False,
) -> dict[str, Any] | None:
    canonical = validate_neutral_record(canonical_record)
    if not available:
        return None
    source_digest = sha256_json(canonical)
    limitations: list[str] = []
    if drop_optional_metadata and "optional_metadata" in canonical:
        limitations.append("optional_metadata omitted by reference adapter")
    return {
        "schema_version": REFERENCE_ADAPTER_SCHEMA_VERSION,
        "adapter_id": "vendor-neutral-reference/v1",
        "adapter_record_id": "neutral:" + source_digest.removeprefix("sha256:")[:20],
        "source_digest": source_digest,
        "canonical_ref": json.loads(canonical_json(canonical["evidence_ref"])),
        "metric": json.loads(canonical_json(canonical["metric"])),
        "terminal_status": canonical["terminal_status"],
        "hard_invariant_pass": canonical["hard_invariant_pass"],
        "writeback_permitted": False,
        "limitations": limitations,
    }


def reconcile_adapter(
    canonical_record: object,
    adapter_representation: object | None,
    *,
    adapter_available: bool = True,
) -> dict[str, Any]:
    canonical = validate_neutral_record(canonical_record)
    before = sha256_json(canonical)
    if not adapter_available:
        after = sha256_json(canonical)
        return {
            "schema_version": RECONCILIATION_SCHEMA_VERSION,
            "status": "ERROR",
            "reason": "ADAPTER_UNAVAILABLE",
            "mismatches": [],
            "canonical_terminal_status": canonical["terminal_status"],
            "quality_verdict_unchanged": True,
            "canonical_fingerprint_before": before,
            "canonical_fingerprint_after": after,
            "canonical_mutated": before != after,
            "limitations": ["Adapter infrastructure was unavailable; canonical quality evidence is unchanged."],
        }

    mismatches: list[str] = []
    try:
        adapter = validate_adapter_representation(adapter_representation)
    except ValueError:
        adapter = None
        mismatches.append("adapter_schema")
    if adapter is not None:
        if adapter["source_digest"] != before:
            mismatches.append("source_digest")
        expected_alias = "neutral:" + before.removeprefix("sha256:")[:20]
        if adapter["adapter_record_id"] != expected_alias:
            mismatches.append("adapter_record_id")
        if adapter["canonical_ref"] != canonical["evidence_ref"]:
            mismatches.append("canonical_ref")
        canonical_metric = canonical["metric"]
        adapter_metric = adapter["metric"]
        for field in (
            "metric_id",
            "metric_version",
            "definition",
            "value",
            "unit",
            "scope_type",
            "scope_id",
            "observed_at",
            "provenance_state",
            "causal_attribution",
        ):
            if adapter_metric.get(field) != canonical_metric.get(field):
                mismatches.append(f"metric.{field}")
        if adapter["terminal_status"] != canonical["terminal_status"]:
            mismatches.append("terminal_status")
        if adapter["hard_invariant_pass"] != canonical["hard_invariant_pass"]:
            mismatches.append("hard_invariant_pass")
        if adapter["writeback_permitted"] is not False:
            mismatches.append("canonical_writeback")
        if "optional_metadata" in canonical and not adapter["limitations"]:
            mismatches.append("lossy_mapping_undisclosed")
    after = sha256_json(canonical)
    unique = sorted(set(mismatches))
    return {
        "schema_version": RECONCILIATION_SCHEMA_VERSION,
        "status": "FAIL" if unique else "PASS",
        "reason": "NOT_RECONCILED" if unique else "RECONCILED",
        "mismatches": unique,
        "canonical_terminal_status": canonical["terminal_status"],
        "quality_verdict_unchanged": True,
        "canonical_fingerprint_before": before,
        "canonical_fingerprint_after": after,
        "canonical_mutated": before != after,
        "limitations": list(adapter["limitations"]) if adapter is not None else [],
    }


def _mutate_path(document: dict[str, Any], path: str, operation: str, value: object = None) -> None:
    keys = path.split(".")
    current: dict[str, Any] = document
    for key in keys[:-1]:
        child = current.get(key)
        if not isinstance(child, dict):
            raise ValueError(f"mutation path {path!r} is invalid")
        current = child
    if operation == "DELETE":
        current.pop(keys[-1], None)
    elif operation == "SET":
        current[keys[-1]] = value
    else:
        raise ValueError(f"unsupported mutation operation {operation!r}")


def run_adapter_fixture(document: object) -> dict[str, Any]:
    fixture = dict(_obj(document, "adapter fixture"))
    required = {
        "schema_version",
        "case_id",
        "scenario",
        "privacy",
        "canonical_record",
        "mutations",
        "expected",
    }
    if set(fixture) != required or fixture["schema_version"] != "b2-qa3-adapter-fixture/v1":
        raise ValueError("adapter fixture has an invalid shape")
    if fixture["scenario"] not in ADAPTER_REQUIRED_SCENARIOS:
        raise ValueError("adapter fixture scenario is unsupported")
    if fixture["privacy"] != "PUBLIC_SAFE":
        raise ValueError("adapter fixture must be PUBLIC_SAFE")
    canonical = validate_neutral_record(fixture["canonical_record"])
    mutations = fixture["mutations"]
    if not isinstance(mutations, list):
        raise ValueError("adapter fixture mutations must be an array")
    expected = _obj(fixture["expected"], "adapter fixture expected")
    if set(expected) != {"status", "reason", "required_mismatches"}:
        raise ValueError("adapter fixture expected outcome has an invalid shape")
    if expected["status"] not in {"PASS", "FAIL", "ERROR"}:
        raise ValueError("adapter fixture expected status is unsupported")
    required_mismatches = _string_list(expected["required_mismatches"], "required_mismatches")

    unavailable = fixture["scenario"] == "ADAPTER_UNAVAILABLE"
    lossy = fixture["scenario"] == "LOSSY_OPTIONAL_EXPLICIT"
    adapter = reference_adapter(
        canonical,
        available=not unavailable,
        drop_optional_metadata=lossy,
    )
    if adapter is not None:
        adapter = json.loads(canonical_json(adapter))
        for index, mutation in enumerate(mutations):
            item = _obj(mutation, f"mutation[{index}]")
            if set(item) - {"path", "operation", "value"}:
                raise ValueError("adapter mutation has an invalid shape")
            _mutate_path(
                adapter,
                _text(item, "path", f"mutation[{index}]"),
                _text(item, "operation", f"mutation[{index}]"),
                item.get("value"),
            )
    reconciliation = reconcile_adapter(
        canonical,
        adapter,
        adapter_available=not unavailable,
    )
    outcome_match = (
        reconciliation["status"] == expected["status"]
        and reconciliation["reason"] == expected["reason"]
        and set(required_mismatches) <= set(reconciliation["mismatches"])
    )
    result = {
        "case_id": _text(fixture, "case_id", "adapter fixture"),
        "scenario": fixture["scenario"],
        "expected_status": expected["status"],
        "expected_reason": expected["reason"],
        "expected_required_mismatches": required_mismatches,
        "status": reconciliation["status"],
        "reason": reconciliation["reason"],
        "mismatches": reconciliation["mismatches"],
        "canonical_mutated": reconciliation["canonical_mutated"],
        "quality_verdict_unchanged": reconciliation["quality_verdict_unchanged"],
        "writeback_permitted": adapter["writeback_permitted"] if adapter is not None else False,
        "limitations": reconciliation["limitations"],
        "outcome_match": outcome_match,
        "canonical_fingerprint": reconciliation["canonical_fingerprint_before"],
        "adapter_representation_fingerprint": sha256_json(adapter) if adapter is not None else None,
    }
    assert_public_safe(result)
    return result


def build_adapter_receipt(results: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = sorted((dict(row) for row in results), key=lambda row: row["case_id"])
    scenarios = {row["scenario"] for row in rows}
    mismatch_rows = [row for row in rows if row["scenario"] in ADAPTER_MISMATCH_SCENARIOS]
    pass_rows = [row for row in rows if row["scenario"] in {"EXACT_ROUNDTRIP", "LOSSY_OPTIONAL_EXPLICIT"}]
    unavailable = [row for row in rows if row["scenario"] == "ADAPTER_UNAVAILABLE"]
    receipt = {
        "schema_version": ADAPTER_RECEIPT_SCHEMA_VERSION,
        "adapter_id": "vendor-neutral-reference/v1",
        "run_id": "B2-QA3-REFERENCE-ADAPTER-DETERMINISTIC-001",
        "scope": "FROZEN_DETERMINISTIC_VENDOR_NEUTRAL_ADAPTER_FIXTURE_SET",
        "case_count": len(rows),
        "unique_case_id_count": len({row["case_id"] for row in rows}),
        "scenario_count": len(scenarios),
        "observed_scenarios": sorted(scenarios),
        "exact_scenario_set": scenarios == ADAPTER_REQUIRED_SCENARIOS,
        "expected_outcome_match_rate": (
            sum(bool(row["outcome_match"]) for row in rows) / len(rows) if rows else None
        ),
        "mismatch_detection_rate": (
            sum(row["status"] == "FAIL" and row["reason"] == "NOT_RECONCILED" for row in mismatch_rows) / len(mismatch_rows)
            if mismatch_rows else None
        ),
        "roundtrip_pass_rate": (
            sum(row["status"] == "PASS" for row in pass_rows) / len(pass_rows)
            if pass_rows else None
        ),
        "canonical_mutation_rate": (
            sum(bool(row["canonical_mutated"]) for row in rows) / len(rows) if rows else None
        ),
        "writeback_permitted_rate": (
            sum(bool(row["writeback_permitted"]) for row in rows) / len(rows) if rows else None
        ),
        "unavailable_quality_failure_rate": (
            sum(not row["quality_verdict_unchanged"] for row in unavailable) / len(unavailable)
            if unavailable else None
        ),
        "loss_disclosure_rate": (
            sum(bool(row["limitations"]) for row in rows if row["scenario"] == "LOSSY_OPTIONAL_EXPLICIT")
            / sum(row["scenario"] == "LOSSY_OPTIONAL_EXPLICIT" for row in rows)
            if any(row["scenario"] == "LOSSY_OPTIONAL_EXPLICIT" for row in rows) else None
        ),
        "case_fingerprints": {row["case_id"]: sha256_json(row) for row in rows},
        "limitations": [
            "Vendor-neutral deterministic reference adapter only.",
            "No external account, credential, network call, paid service, or brand-specific SDK is used.",
            "Adapter infrastructure status never replaces the canonical evaluation verdict.",
        ],
    }
    receipt["gate_criteria"] = {
        "case_count": 9,
        "unique_case_id_count": 9,
        "scenario_count": 9,
        "observed_scenarios": sorted(ADAPTER_REQUIRED_SCENARIOS),
        "exact_scenario_set": True,
        "expected_outcome_match_rate": 1.0,
        "mismatch_detection_rate": 1.0,
        "roundtrip_pass_rate": 1.0,
        "canonical_mutation_rate": 0.0,
        "writeback_permitted_rate": 0.0,
        "unavailable_quality_failure_rate": 0.0,
        "loss_disclosure_rate": 1.0,
    }
    receipt["gate"] = (
        "PASS"
        if all(receipt.get(key) == value for key, value in receipt["gate_criteria"].items())
        else "FAIL"
    )
    receipt["receipt_fingerprint"] = sha256_json(receipt)
    return receipt


def build_checked_dashboard(
    root: str | Path,
    *,
    source_commit: str,
    observed_at: str,
) -> dict[str, Any]:
    root_path = Path(root)
    paths = (
        "results/b2/qa0-contract-validation.json",
        "results/b2/qa1-grounding-validation.json",
        "results/b2/qa1-tool-workflow-validation.json",
        "results/b2/qa2-robustness-validation.json",
        "results/b2/qa3-quality-delta-validation.json",
    )
    sources = _load_receipt_paths_at_git_commit(paths, source_commit, root_path)
    projection = build_dashboard_projection(
        sources,
        declared_source_ids=[f"B2_RECEIPT:{path}" for path in paths],
        observed_at=observed_at,
        snapshot_id=f"git:{source_commit}",
        repository_root=root_path,
    )
    return verify_dashboard_projection(projection, repository_root=root_path)


def render_dashboard_html(
    document: object,
    *,
    receipt_sources: Iterable[Mapping[str, Any]] | None = None,
    repository_root: str | Path | None = None,
) -> str:
    projection = verify_dashboard_projection(
        document,
        receipt_sources=receipt_sources,
        repository_root=repository_root,
    )
    escape = lambda value: html.escape(str(value), quote=True)
    profile_rows = []
    for profile in projection["profiles"]:
        ref = profile["evidence_ref"]
        terminals = ", ".join(profile["terminal_statuses"])
        profile_rows.append(
            "<tr>"
            f"<td><strong>{escape(profile['profile_id'])}</strong></td>"
            f"<td><span class=\"badge pass\">{escape(profile['gate'])}</span></td>"
            f"<td>{profile['formal_family_count']}</td>"
            f"<td>{profile['case_count']}</td>"
            f"<td>{profile['known_bad_count']} / {profile['control_count']}</td>"
            f"<td>{escape(terminals)}</td>"
            f"<td><code>{escape(ref['source_locator'])}</code><br><small>{escape(ref['source_fingerprint'])}</small></td>"
            "</tr>"
        )
    delta_rows = []
    for delta in projection["quality_deltas"]:
        delta_rows.append(
            "<tr>"
            f"<td>{escape(delta['profile_id'])}</td>"
            f"<td><span class=\"badge neutral\">{escape(delta['terminal_status'])}</span></td>"
            f"<td>{escape(delta['reason'])}</td>"
            "<td>—</td>"
            f"<td><code>{escape(delta['evidence_ref']['source_id'])}</code></td>"
            "</tr>"
        )
    manifest = projection["source_manifest"]
    terminal_states = ", ".join(projection["terminal_state_visibility"]["statuses"])
    limitations = "".join(f"<li>{escape(item)}</li>" for item in projection["limitations"])
    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>B2 QA3 Quality Evidence Dashboard</title>
<style>
:root{--ink:#172033;--muted:#5f6b7a;--line:#dce3ea;--panel:#f7f9fc;--accent:#3659d9;--good:#0a7a53;--neutral:#6b7280}
*{box-sizing:border-box}body{margin:0;background:#eef2f7;color:var(--ink);font:15px/1.5 Inter,ui-sans-serif,system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}
main{max-width:1180px;margin:32px auto;padding:0 22px 48px}.hero{background:linear-gradient(135deg,#172554,#3659d9);color:white;border-radius:18px;padding:30px;box-shadow:0 16px 40px #1e3a8a24}
h1{margin:0 0 8px;font-size:32px;letter-spacing:-.025em}.hero p{margin:5px 0;color:#dbe7ff}.grid{display:grid;grid-template-columns:repeat(3,1fr);gap:14px;margin:18px 0}.card,section{background:white;border:1px solid var(--line);border-radius:14px;padding:18px}.card strong{display:block;font-size:26px}.card span,small{color:var(--muted)}section{margin-top:16px;overflow:auto}h2{margin:0 0 12px;font-size:20px}table{width:100%;border-collapse:collapse;min-width:850px}th,td{text-align:left;vertical-align:top;padding:10px;border-bottom:1px solid var(--line)}th{font-size:12px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted)}code{font-size:12px;overflow-wrap:anywhere}.badge{display:inline-block;border-radius:999px;padding:3px 9px;font-size:12px;font-weight:700}.pass{background:#dcfce7;color:var(--good)}.neutral{background:#eef2f7;color:var(--neutral)}.notice{border-left:4px solid var(--accent);background:#eef4ff;padding:12px 14px;border-radius:8px}.footer{margin-top:18px;color:var(--muted);font-size:12px}@media(max-width:760px){.grid{grid-template-columns:1fr}h1{font-size:26px}}
</style>
</head>
<body><main>
<header class="hero"><h1>B2 QA3 Quality Evidence Dashboard</h1>
<p>Read-only, reproducible projection of fingerprinted evaluation receipts.</p>
<p><strong>Authority:</strong> derived projection only · <strong>Snapshot:</strong> """ + escape(projection["source_snapshot"]["snapshot_id"]) + """</p></header>
<div class="grid">
<div class="card"><strong>""" + str(manifest["included_count"]) + """</strong><span>canonical sources included</span></div>
<div class="card"><strong>""" + str(len(projection["profiles"])) + """</strong><span>checked QA profiles</span></div>
<div class="card"><strong>0</strong><span>brand adapters selected</span></div>
</div>
<section><h2>Evidence inventory</h2>
<p class="notice">Full declared set included: """ + str(manifest["included_count"]) + "/" + str(manifest["source_count"]) + """. Dedupe identity: <code>""" + escape(manifest["dedupe_identity"]) + """</code>. Projection does not write back to canonical evidence.</p>
<table><thead><tr><th>Profile</th><th>Gate</th><th>Families</th><th>Cases</th><th>Known-bad / control</th><th>Observed terminals</th><th>Canonical evidence</th></tr></thead><tbody>""" + "".join(profile_rows) + """</tbody></table></section>
<section><h2>Quality delta</h2>
<p>There is no compatible prior checked snapshot in the selected evidence set. The dashboard preserves this as <code>NOT_EVALUABLE / NO_BASELINE</code>; it does not display zero improvement or invent a trend.</p>
<table><thead><tr><th>Profile</th><th>Terminal</th><th>Reason</th><th>Delta</th><th>Evidence ref</th></tr></thead><tbody>""" + "".join(delta_rows) + """</tbody></table></section>
<section><h2>Terminal and scope visibility</h2>
<p>Observed receipt terminals: <strong>""" + escape(terminal_states) + """</strong>. The projection contract separately preserves PASS, FAIL, UNKNOWN, NOT_EVALUABLE, BLOCKED, and ERROR where present.</p>
<p>Performance: <span class="badge neutral">""" + escape(projection["performance"]["terminal_status"]) + """</span> """ + escape(projection["performance"]["reason"]) + """.</p>
<p>Recurrence: <span class="badge neutral">""" + escape(projection["regression_recurrence"]["terminal_status"]) + """</span> """ + escape(projection["regression_recurrence"]["reason"]) + """.</p></section>
<section><h2>Limits</h2><ul>""" + limitations + """</ul></section>
<div class="footer">Projection fingerprint: <code>""" + escape(projection["projection_fingerprint"]) + """</code><br>Source commit: <code>""" + escape(projection["source_snapshot"]["git_commit"]) + """</code> · Observed at: """ + escape(projection["source_snapshot"]["observed_at"]) + """</div>
</main></body></html>
"""
