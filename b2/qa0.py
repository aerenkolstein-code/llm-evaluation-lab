"""B2 QA0: deterministic public-safe Errorbook-derived evaluation foundation.

The public repository contains only mechanism-preserving synthetic reconstructions.
Exact private Error IDs, source bodies, and private locators are intentionally absent.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping

TERMINAL_STATUSES = (
    "PASS",
    "FAIL",
    "NOT_EVALUABLE",
    "BLOCKED",
    "ERROR",
    "UNKNOWN",
)
PUBLIC_SAFE = "PUBLIC_SAFE"
PUBLIC_SEED_SCHEMA_VERSION = "b2-public-seed/v1"
ERROR_MECHANISM_SCHEMA_VERSION = "error-mechanism/v1"
BUG_CASE_SCHEMA_VERSION = "bug-case/v1"
METRIC_REGISTRY_SCHEMA_VERSION = "metric-registry/v1"
QA0_RECEIPT_SCHEMA_VERSION = "b2-qa0-receipt/v1"

# A known-bad fixture is detected only when its family's frozen oracle observes
# the intended failure mechanism.  Missing/blocked outcomes are never evidence
# of detection.  ERROR is intentionally accepted only for connector-schema,
# where a typed schema/infrastructure rejection is itself the target outcome.
KNOWN_BAD_DETECTION_ORACLES = {
    "entity-attribute-binding": {
        "terminal_status": "FAIL",
        "target_invariants": {"entity_attribute_evidence_binding"},
    },
    "connector-schema": {
        "terminal_status": "ERROR",
        "target_invariants": {"request_schema_valid", "provider_or_schema_error"},
    },
    "integrity-completeness": {
        "terminal_status": "FAIL",
        "target_invariants": {
            "event_order_monotonic",
            "global_pass_requires_full_set_scan",
            "terminal_envelope_complete",
            "unique_event_ids",
        },
    },
    "evidence-scope": {
        "terminal_status": "FAIL",
        "target_invariants": {
            "claim_source_value_consistency",
            "current_inventory_cross_surface_consistency",
            "current_inventory_evidence_scope",
        },
    },
}

QA0_HARD_GATE_CRITERIA = {
    "case_count": 8,
    "known_bad_count": 4,
    "control_count": 4,
    "known_bad_detection_rate": 1.0,
    "control_false_reject_rate": 0.0,
    "provenance_trace_rate": 1.0,
    "evidence_completeness_rate": 1.0,
}


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    family_id: str
    variant: str
    terminal_status: str
    hard_invariant_pass: bool
    detected: bool
    failed_invariants: tuple[str, ...]
    evidence_complete: bool
    provenance_traceable: bool
    fixture_fingerprint: str

    def to_mapping(self) -> dict[str, Any]:
        return asdict(self)


def canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sha256_json(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def abstract_seed_digest(family_id: str, transform_version: str = "v1") -> str:
    payload = f"b2-public-safe|{family_id}|{transform_version}".encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def load_json(path: str | Path) -> object:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _obj(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _text(document: Mapping[str, Any], key: str, label: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}.{key} must be a non-empty string")
    return value.strip()


def _string_list(
    document: Mapping[str, Any], key: str, label: str, *, allow_empty: bool = False
) -> list[str]:
    value = document.get(key)
    if not isinstance(value, list) or (not value and not allow_empty):
        requirement = "an array" if allow_empty else "a non-empty array"
        raise ValueError(f"{label}.{key} must be {requirement}")
    normalized: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{label}.{key}[{index}] must be a non-empty string")
        normalized.append(item.strip())
    return normalized


def _scan_strings(value: object) -> Iterable[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for key, item in value.items():
            yield str(key)
            yield from _scan_strings(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _scan_strings(item)


def _looks_like_private_locator(value: str) -> bool:
    lowered = value.lower()
    # Split literals keep the scanner itself from looking like a leaked locator.
    forbidden_fragments = (
        "docs." + "google.com/",
        "drive." + "google.com/",
        "mail." + "google.com/",
        "session_" + "raw",
        "raw_" + "file_id",
        "o" + "auth",
        "api_" + "key",
        "authorization:" + " bearer",
    )
    return any(fragment in lowered for fragment in forbidden_fragments)


def assert_public_safe(document: object) -> None:
    for text in _scan_strings(document):
        if _looks_like_private_locator(text):
            raise ValueError(
                f"public-safe contract contains forbidden locator/secret marker: {text!r}"
            )
        if re.search(r"\bERR-\d{4,}\b", text):
            raise ValueError("public-safe artifact must not expose exact private Error_ID")


def validate_public_seed(document: object, label: str = "<public-seed>") -> dict[str, Any]:
    doc = _obj(document, label)
    if _text(doc, "schema_version", label) != PUBLIC_SEED_SCHEMA_VERSION:
        raise ValueError(f"{label}: unsupported schema_version")
    family_id = _text(doc, "family_id", label)
    case_id = _text(doc, "case_id", label)
    variant = _text(doc, "variant", label)
    if variant not in {"KNOWN_BAD", "CONTROL"}:
        raise ValueError(f"{label}.variant must be KNOWN_BAD or CONTROL")
    capability_profile = _text(doc, "capability_profile", label)
    if _text(doc, "privacy", label) != PUBLIC_SAFE:
        raise ValueError(f"{label}.privacy must be PUBLIC_SAFE")

    provenance = _obj(doc.get("provenance"), f"{label}.provenance")
    if _text(provenance, "kind", f"{label}.provenance") != "ABSTRACT_PUBLIC_SEED_DIGEST":
        raise ValueError(f"{label}.provenance.kind must be ABSTRACT_PUBLIC_SEED_DIGEST")
    digest = _text(provenance, "seed_digest", f"{label}.provenance")
    if not digest.startswith("sha256:") or len(digest) != 71:
        raise ValueError(f"{label}.provenance.seed_digest must be sha256:<64hex>")
    if (
        _text(provenance, "transformation", f"{label}.provenance")
        != "mechanism-preserving synthetic reconstruction"
    ):
        raise ValueError(f"{label}: unsupported transformation")

    input_value = _obj(doc.get("input"), f"{label}.input")
    expected = _obj(doc.get("expected"), f"{label}.expected")
    terminal_status = _text(expected, "terminal_status", f"{label}.expected")
    if terminal_status not in TERMINAL_STATUSES:
        raise ValueError(f"{label}: unsupported expected terminal status")
    if not isinstance(expected.get("hard_invariant_pass"), bool):
        raise ValueError(f"{label}.expected.hard_invariant_pass must be boolean")
    if not isinstance(expected.get("detected"), bool):
        raise ValueError(f"{label}.expected.detected must be boolean")
    _string_list(expected, "failed_invariants", f"{label}.expected", allow_empty=True)
    limitations = doc.get("limitations", [])
    if not isinstance(limitations, list):
        raise ValueError(f"{label}.limitations must be an array")
    assert_public_safe(doc)
    return {
        "schema_version": PUBLIC_SEED_SCHEMA_VERSION,
        "family_id": family_id,
        "case_id": case_id,
        "variant": variant,
        "capability_profile": capability_profile,
        "privacy": PUBLIC_SAFE,
        "provenance": dict(provenance),
        "input": dict(input_value),
        "expected": dict(expected),
        "limitations": list(limitations),
    }


def validate_error_mechanism(
    document: object, label: str = "<error-mechanism>"
) -> dict[str, Any]:
    doc = _obj(document, label)
    if _text(doc, "schema_version", label) != ERROR_MECHANISM_SCHEMA_VERSION:
        raise ValueError(f"{label}: unsupported schema_version")
    for key in (
        "mechanism_id",
        "seed_status",
        "private_seed_digest",
        "error_class",
        "observed_phenomenon",
        "mechanism_hypothesis",
        "mechanism_status",
        "falsifier",
        "capability_profile",
        "severity",
        "public_safe_transform",
        "privacy_class",
    ):
        _text(doc, key, label)
    for key in (
        "alternative_causes",
        "expected_invariants",
        "forbidden_outcomes",
        "mutation_axes",
    ):
        _string_list(doc, key, label, allow_empty=True)
    if doc["mechanism_status"] not in {"OBSERVED_ONLY", "HYPOTHESIS", "UNKNOWN"}:
        raise ValueError(f"{label}.mechanism_status unsupported")
    assert_public_safe(doc)
    return dict(doc)


def validate_bug_case(document: object, label: str = "<bug-case>") -> dict[str, Any]:
    doc = _obj(document, label)
    if _text(doc, "schema_version", label) != BUG_CASE_SCHEMA_VERSION:
        raise ValueError(f"{label}: unsupported schema_version")
    for key in (
        "bug_id",
        "run_id",
        "family_id",
        "case_id",
        "capability_profile",
        "phenomenon",
        "mechanism_hypothesis",
        "mechanism_status",
        "severity",
        "impact",
        "reproduction",
        "regression_ref",
        "terminal_status",
        "privacy",
    ):
        _text(doc, key, label)
    if doc["terminal_status"] not in TERMINAL_STATUSES:
        raise ValueError(f"{label}: unsupported terminal_status")
    _obj(doc.get("environment"), f"{label}.environment")
    _obj(doc.get("expected"), f"{label}.expected")
    _obj(doc.get("actual"), f"{label}.actual")
    for key in (
        "failed_invariants",
        "alternative_causes",
        "evidence_refs",
        "limitations",
    ):
        _string_list(doc, key, label, allow_empty=True)
    _text(doc, "falsifier", label)
    assert_public_safe(doc)
    return dict(doc)


def validate_metric_registry(
    document: object, label: str = "<metric-registry>"
) -> dict[str, Any]:
    doc = _obj(document, label)
    if _text(doc, "schema_version", label) != METRIC_REGISTRY_SCHEMA_VERSION:
        raise ValueError(f"{label}: unsupported schema_version")
    metrics = doc.get("metrics")
    if not isinstance(metrics, list) or not metrics:
        raise ValueError(f"{label}.metrics must be a non-empty array")
    seen: set[str] = set()
    for index, raw in enumerate(metrics):
        metric = _obj(raw, f"{label}.metrics[{index}]")
        metric_id = _text(metric, "metric_id", label)
        if metric_id in seen:
            raise ValueError(f"{label}: duplicate metric_id {metric_id}")
        seen.add(metric_id)
        for key in (
            "definition",
            "task_scope",
            "scorer",
            "directionality",
            "threshold",
            "kind",
            "missing_data_semantics",
            "aggregation",
            "version",
            "provenance",
        ):
            _text(metric, key, label)
        if metric["kind"] not in {"HARD", "SOFT", "PLACEHOLDER"}:
            raise ValueError(f"{label}: unsupported metric kind")
    assert_public_safe(doc)
    return dict(doc)


def _entity_attribute_binding(
    data: Mapping[str, Any],
) -> tuple[str, bool, tuple[str, ...]]:
    claims = data.get("claims")
    if not isinstance(claims, list) or not claims:
        return "UNKNOWN", False, ("evidence_complete",)
    failed: list[str] = []
    for claim in claims:
        if not isinstance(claim, Mapping):
            failed.append("evidence_complete")
            continue
        evidence = claim.get("evidence")
        if not isinstance(evidence, Mapping):
            failed.append("evidence_complete")
            continue
        if any(
            claim.get(key) != evidence.get(key)
            for key in ("entity_id", "scope_id", "attribute")
        ):
            failed.append("entity_attribute_evidence_binding")
    unique = tuple(sorted(set(failed)))
    if "evidence_complete" in unique:
        return "UNKNOWN", False, unique
    return ("FAIL", False, unique) if unique else ("PASS", True, ())


def _connector_schema(data: Mapping[str, Any]) -> tuple[str, bool, tuple[str, ...]]:
    allowed = data.get("allowed_request_keys")
    request = data.get("request")
    outcome = data.get("provider_outcome")
    readback = data.get("target_readback")
    retry = data.get("retry")
    if (
        not isinstance(allowed, list)
        or not isinstance(request, Mapping)
        or not isinstance(outcome, Mapping)
        or not isinstance(readback, Mapping)
        or not isinstance(retry, Mapping)
    ):
        return "UNKNOWN", False, ("evidence_complete",)

    failed: list[str] = []
    unknown_keys = sorted(set(request) - set(allowed))
    if unknown_keys:
        failed.append("request_schema_valid")

    status = outcome.get("http_status")
    if not isinstance(status, int):
        failed.append("evidence_complete")
    elif status >= 400:
        if outcome.get("committed") is not False or readback.get("state_unchanged") is not True:
            failed.append("provider_rejection_requires_no_mutation")

    if retry.get("performed") is True and readback.get("performed") is not True:
        failed.append("retry_requires_target_readback")
    if retry.get("side_effect_count") not in {0, 1}:
        failed.append("no_duplicate_side_effects")

    unique = tuple(sorted(set(failed)))
    if "evidence_complete" in unique:
        return "UNKNOWN", False, unique
    if unknown_keys or (isinstance(status, int) and status >= 400):
        return "ERROR", False, unique or ("provider_or_schema_error",)
    return ("FAIL", False, unique) if unique else ("PASS", True, ())


def _integrity_completeness(
    data: Mapping[str, Any],
) -> tuple[str, bool, tuple[str, ...]]:
    if data.get("audit_scope") != "GLOBAL":
        return "UNKNOWN", False, ("evidence_complete",)
    events = data.get("events")
    if not isinstance(events, list) or not events:
        return "UNKNOWN", False, ("evidence_complete",)

    failed: list[str] = []
    if data.get("checked_scope") != "FULL":
        failed.append("global_pass_requires_full_set_scan")

    ids: list[str] = []
    ordinals: list[int] = []
    for event in events:
        if not isinstance(event, Mapping):
            failed.append("evidence_complete")
            continue
        event_id = event.get("event_id")
        ordinal = event.get("ordinal")
        if (
            not isinstance(event_id, str)
            or not event_id
            or not isinstance(ordinal, int)
        ):
            failed.append("evidence_complete")
            continue
        ids.append(event_id)
        ordinals.append(ordinal)
        if event.get("terminal_fields_complete") is not True:
            failed.append("terminal_envelope_complete")

    if len(ids) != len(set(ids)):
        failed.append("unique_event_ids")
    if ordinals != sorted(ordinals) or len(ordinals) != len(set(ordinals)):
        failed.append("event_order_monotonic")

    unique = tuple(sorted(set(failed)))
    if "evidence_complete" in unique:
        return "UNKNOWN", False, unique
    return ("FAIL", False, unique) if unique else ("PASS", True, ())


def _evidence_scope(data: Mapping[str, Any]) -> tuple[str, bool, tuple[str, ...]]:
    claim = data.get("claim")
    sources = data.get("sources")
    if (
        not isinstance(claim, Mapping)
        or not isinstance(sources, list)
        or not sources
        or claim.get("attribute") != "current_count"
        or not isinstance(claim.get("value"), int)
    ):
        return "UNKNOWN", False, ("evidence_complete",)

    source_id = claim.get("source_id")
    source = next(
        (
            item
            for item in sources
            if isinstance(item, Mapping) and item.get("source_id") == source_id
        ),
        None,
    )
    if not isinstance(source, Mapping):
        return "UNKNOWN", False, ("evidence_complete",)

    allowed_surfaces = {
        "INVENTORY_LIST",
        "FILTERED_INVENTORY",
        "ACCOUNT_DASHBOARD",
    }
    failed: list[str] = []
    if source.get("surface_type") not in allowed_surfaces:
        failed.append("current_inventory_evidence_scope")
    if source.get("current_count") != claim.get("value"):
        failed.append("claim_source_value_consistency")

    scoped_counts = [
        item.get("current_count")
        for item in sources
        if isinstance(item, Mapping)
        and item.get("surface_type") in allowed_surfaces
        and isinstance(item.get("current_count"), int)
    ]
    if scoped_counts and any(count != claim.get("value") for count in scoped_counts):
        failed.append("current_inventory_cross_surface_consistency")

    unique = tuple(sorted(set(failed)))
    return ("FAIL", False, unique) if unique else ("PASS", True, ())


_SCORERS = {
    "entity-attribute-binding": _entity_attribute_binding,
    "connector-schema": _connector_schema,
    "integrity-completeness": _integrity_completeness,
    "evidence-scope": _evidence_scope,
}


def detection_oracle(
    *,
    family_id: str,
    variant: str,
    terminal_status: str,
    failed_invariants: Iterable[str],
    evidence_complete: bool,
) -> bool:
    """Apply the frozen per-family detection contract to one result."""
    if variant == "CONTROL":
        return terminal_status == "PASS"
    if variant != "KNOWN_BAD" or not evidence_complete:
        return False
    oracle = KNOWN_BAD_DETECTION_ORACLES.get(family_id)
    if oracle is None or terminal_status != oracle["terminal_status"]:
        return False
    return bool(set(failed_invariants) & oracle["target_invariants"])


def score_case(document: object) -> CaseResult:
    case = validate_public_seed(document)
    scorer = _SCORERS.get(case["family_id"])
    if scorer is None:
        terminal_status, hard_pass, failed = (
            "NOT_EVALUABLE",
            False,
            ("unsupported_family",),
        )
    else:
        terminal_status, hard_pass, failed = scorer(case["input"])

    variant = case["variant"]
    evidence_complete = "evidence_complete" not in failed
    detected = detection_oracle(
        family_id=case["family_id"],
        variant=variant,
        terminal_status=terminal_status,
        failed_invariants=failed,
        evidence_complete=evidence_complete,
    )
    return CaseResult(
        case_id=case["case_id"],
        family_id=case["family_id"],
        variant=variant,
        terminal_status=terminal_status,
        hard_invariant_pass=hard_pass,
        detected=detected,
        failed_invariants=failed,
        evidence_complete=evidence_complete,
        provenance_traceable=bool(case["provenance"].get("seed_digest"))
        and case["provenance"].get("kind") == "ABSTRACT_PUBLIC_SEED_DIGEST",
        fixture_fingerprint=sha256_json(case),
    )


def build_qa0_receipt(results: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = [dict(item) for item in results]
    rows.sort(key=lambda item: item["case_id"])
    known_bad = [row for row in rows if row["variant"] == "KNOWN_BAD"]
    controls = [row for row in rows if row["variant"] == "CONTROL"]

    receipt = {
        "schema_version": QA0_RECEIPT_SCHEMA_VERSION,
        "run_id": "B2-QA0-DETERMINISTIC-001",
        "runner": "python-unittest-compatible/deterministic",
        "scope": "FROZEN_DETERMINISTIC_QA0_FIXTURE_SET",
        "case_count": len(rows),
        "cases": [row["case_id"] for row in rows],
        "known_bad_count": len(known_bad),
        "control_count": len(controls),
        "known_bad_detection_rate": (
            sum(bool(row["detected"]) for row in known_bad) / len(known_bad)
            if known_bad
            else None
        ),
        "control_false_reject_rate": (
            sum(row["terminal_status"] != "PASS" for row in controls) / len(controls)
            if controls
            else None
        ),
        "provenance_trace_rate": (
            sum(bool(row["provenance_traceable"]) for row in rows) / len(rows)
            if rows
            else None
        ),
        "evidence_completeness_rate": (
            sum(bool(row["evidence_complete"]) for row in rows) / len(rows)
            if rows
            else None
        ),
        "terminal_statuses": sorted({row["terminal_status"] for row in rows}),
        "fixture_fingerprints": {
            row["case_id"]: row["fixture_fingerprint"] for row in rows
        },
        "limitations": [
            "Metrics apply only to the frozen deterministic QA0 fixture set.",
            "No live model/provider performance is measured.",
            "Mechanism hypotheses are not causal circuit findings.",
        ],
    }
    receipt["gate_criteria"] = dict(QA0_HARD_GATE_CRITERIA)
    receipt["gate"] = (
        "PASS"
        if all(receipt[key] == expected for key, expected in QA0_HARD_GATE_CRITERIA.items())
        else "FAIL"
    )
    receipt["receipt_fingerprint"] = sha256_json(receipt)
    return receipt
