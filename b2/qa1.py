"""Deterministic B2-QA1 Grounding and Tool/Agent evaluation profiles."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from .qa0 import CaseResult, TERMINAL_STATUSES, abstract_seed_digest, sha256_json, validate_public_seed

QA1_RECEIPT_SCHEMA_VERSION = "b2-qa1-receipt/v1"

PROFILE_FAMILIES = {
    "GROUNDING": {
        "entity-attribute-binding",
        "inventory-evidence-scope",
        "source-modality",
    },
    "TOOL_AGENT": {
        "connector-schema-retry",
        "capability-routing",
        "destructive-write-recovery",
    },
}

DETECTION_ORACLES = {
    "entity-attribute-binding": ("FAIL", {"entity_attribute_evidence_binding"}),
    "inventory-evidence-scope": ("FAIL", {"current_inventory_evidence_scope"}),
    "source-modality": ("FAIL", {"provenance_level_not_upgraded"}),
    "connector-schema-retry": ("ERROR", {"request_schema_valid"}),
    "capability-routing": ("FAIL", {"discovery_before_unavailability_claim"}),
    "destructive-write-recovery": ("FAIL", {"destructive_write_guard"}),
}

REQUIRED_INPUT_PATHS = {
    "entity-attribute-binding": (
        ("claim", "entity_id"), ("claim", "scope_id"), ("claim", "attribute"), ("claim", "value"),
        ("evidence", "entity_id"), ("evidence", "scope_id"), ("evidence", "attribute"), ("evidence", "value"),
    ),
    "inventory-evidence-scope": (("claim", "attribute"), ("claim", "value"), ("source", "surface_type")),
    "source-modality": (
        ("claim", "value"), ("claim", "provenance_level"),
        ("source", "value"), ("source", "provenance_level"),
    ),
    "connector-schema-retry": (
        ("allowed_keys",), ("request",), ("outcome", "status"), ("outcome", "committed"),
        ("readback", "performed"), ("readback", "state_unchanged"),
        ("retry", "performed"), ("retry", "side_effect_count"),
    ),
    "capability-routing": (
        ("registry_checked",), ("matching_action_attempted",), ("claim",),
        ("permission_state",), ("capability_state",),
    ),
    "destructive-write-recovery": tuple((key,) for key in (
        "live_target_bound", "revision_guard", "pilot_write", "neighbor_readback",
        "recovery_evidence", "side_effect_count",
    )),
}


@dataclass(frozen=True)
class QA1CaseResult(CaseResult):
    provenance_digest: str


def _has_path(data: Mapping[str, Any], path: tuple[str, ...]) -> bool:
    current: object = data
    for key in path:
        if not isinstance(current, Mapping) or key not in current or current[key] is None:
            return False
        current = current[key]
    return True


def _evidence_complete(data: Mapping[str, Any], family: str) -> bool:
    if not all(_has_path(data, path) for path in REQUIRED_INPUT_PATHS[family]):
        return False
    if family == "inventory-evidence-scope":
        source = data["source"]
        if source["surface_type"] in {"INVENTORY_LIST", "FILTERED_INVENTORY", "ACCOUNT_DASHBOARD"}:
            return _has_path(data, ("source", "current_count"))
    if family == "connector-schema-retry" and data["retry"]["performed"] is True:
        return _has_path(data, ("retry", "after_readback"))
    return True


def validate_profile_case(document: object, profile: str) -> dict[str, Any]:
    case = validate_public_seed(document)
    if profile not in PROFILE_FAMILIES:
        raise ValueError(f"unsupported QA1 profile: {profile}")
    if case["family_id"] not in PROFILE_FAMILIES[profile]:
        raise ValueError(f"family {case['family_id']} is not in profile {profile}")
    return case


def _grounding(data: Mapping[str, Any], family: str):
    if not _evidence_complete(data, family):
        return "UNKNOWN", False, ("evidence_complete",)
    if family == "entity-attribute-binding":
        claim, evidence = data.get("claim"), data.get("evidence")
        if not isinstance(claim, Mapping) or not isinstance(evidence, Mapping):
            return "UNKNOWN", False, ("evidence_complete",)
        failed = []
        if any(claim.get(k) != evidence.get(k) for k in ("entity_id", "scope_id", "attribute", "value")):
            failed.append("entity_attribute_evidence_binding")
    elif family == "inventory-evidence-scope":
        claim, source = data.get("claim"), data.get("source")
        if not isinstance(claim, Mapping) or not isinstance(source, Mapping):
            return "UNKNOWN", False, ("evidence_complete",)
        failed = []
        if source.get("surface_type") not in {"INVENTORY_LIST", "FILTERED_INVENTORY", "ACCOUNT_DASHBOARD"}:
            failed.append("current_inventory_evidence_scope")
        if source.get("current_count") != claim.get("value"):
            failed.append("claim_source_value_consistency")
    else:
        claim, source = data.get("claim"), data.get("source")
        if not isinstance(claim, Mapping) or not isinstance(source, Mapping):
            return "UNKNOWN", False, ("evidence_complete",)
        levels = {"USER_REPORTED": 1, "FIRST_PARTY": 2, "EXECUTION_SURFACE": 3}
        if claim.get("provenance_level") not in levels or source.get("provenance_level") not in levels:
            return "UNKNOWN", False, ("evidence_complete",)
        failed = []
        if levels[claim["provenance_level"]] > levels[source["provenance_level"]]:
            failed.append("provenance_level_not_upgraded")
        if claim.get("value") != source.get("value"):
            failed.append("claim_source_value_consistency")
    unique = tuple(sorted(set(failed)))
    return ("FAIL", False, unique) if unique else ("PASS", True, ())


def _tool_agent(data: Mapping[str, Any], family: str):
    if not _evidence_complete(data, family):
        return "UNKNOWN", False, ("evidence_complete",)
    if family == "connector-schema-retry":
        allowed, request = data.get("allowed_keys"), data.get("request")
        outcome, readback, retry = data.get("outcome"), data.get("readback"), data.get("retry")
        if not isinstance(allowed, list) or not all(isinstance(x, Mapping) for x in (request, outcome, readback, retry)):
            return "UNKNOWN", False, ("evidence_complete",)
        failed = []
        bad_keys = set(request) - set(allowed)
        if bad_keys:
            failed.append("request_schema_valid")
        if outcome.get("committed") is False and readback.get("state_unchanged") is not True:
            failed.append("rejected_mutation_state_unchanged")
        if retry.get("performed") and (readback.get("performed") is not True or retry.get("after_readback") is not True):
            failed.append("retry_requires_readback")
        if retry.get("side_effect_count") not in {0, 1}:
            failed.append("no_duplicate_side_effects")
        unique = tuple(sorted(set(failed)))
        if bad_keys or outcome.get("status") == "REJECTED":
            return "ERROR", False, unique or ("provider_or_schema_error",)
    elif family == "capability-routing":
        failed = []
        if data.get("claim") == "UNAVAILABLE" and not (data.get("registry_checked") and data.get("matching_action_attempted")):
            failed.append("discovery_before_unavailability_claim")
        if data.get("claim") != data.get("capability_state"):
            failed.append("permission_capability_separation")
    else:
        required = ("live_target_bound", "revision_guard", "pilot_write", "neighbor_readback", "recovery_evidence", "side_effect_count")
        failed = []
        if not all(data.get(k) is True for k in required[:-1]):
            failed.append("destructive_write_guard")
        if data.get("side_effect_count") != 1:
            failed.append("no_duplicate_side_effects")
    unique = tuple(sorted(set(failed)))
    return ("FAIL", False, unique) if unique else ("PASS", True, ())


def _detected(family: str, variant: str, status: str, failed: Iterable[str], complete: bool) -> bool:
    if variant == "CONTROL":
        return status == "PASS"
    if variant != "KNOWN_BAD" or not complete or status in {"UNKNOWN", "NOT_EVALUABLE", "BLOCKED"}:
        return False
    expected_status, targets = DETECTION_ORACLES[family]
    return status == expected_status and bool(set(failed) & targets)


def score_profile_case(document: object, profile: str) -> QA1CaseResult:
    case = validate_profile_case(document, profile)
    family = case["family_id"]
    status, hard_pass, failed = (_grounding(case["input"], family) if profile == "GROUNDING" else _tool_agent(case["input"], family))
    if status not in TERMINAL_STATUSES:
        raise AssertionError("scorer emitted an unsupported terminal status")
    complete = "evidence_complete" not in failed
    provenance_digest = case["provenance"].get("seed_digest", "")
    provenance_traceable = provenance_digest == abstract_seed_digest(family)
    return QA1CaseResult(
        case_id=case["case_id"], family_id=family, variant=case["variant"],
        terminal_status=status, hard_invariant_pass=hard_pass,
        detected=_detected(family, case["variant"], status, failed, complete),
        failed_invariants=failed, evidence_complete=complete,
        provenance_traceable=provenance_traceable,
        fixture_fingerprint=sha256_json(case),
        provenance_digest=provenance_digest,
    )


def build_profile_receipt(profile: str, results: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    if profile not in PROFILE_FAMILIES:
        raise ValueError(f"unsupported QA1 profile: {profile}")
    rows = sorted((dict(row) for row in results), key=lambda row: row["case_id"])
    known_bad = [r for r in rows if r["variant"] == "KNOWN_BAD"]
    controls = [r for r in rows if r["variant"] == "CONTROL"]
    expected_families = sorted(PROFILE_FAMILIES[profile])
    case_ids = [r["case_id"] for r in rows]
    family_composition = {
        family: {
            "case_count": sum(r["family_id"] == family for r in rows),
            "variants": sorted(r["variant"] for r in rows if r["family_id"] == family),
            "expected_seed_digest": abstract_seed_digest(family),
            "provenance_digests": sorted({r.get("provenance_digest", "") for r in rows if r["family_id"] == family}),
        }
        for family in sorted({r["family_id"] for r in rows})
    }
    exact_family_pairing = (
        sorted(family_composition) == expected_families
        and all(info["case_count"] == 2 and info["variants"] == ["CONTROL", "KNOWN_BAD"] for info in family_composition.values())
    )
    provenance_digest_match_rate = (
        sum(r.get("provenance_digest") == abstract_seed_digest(r["family_id"]) for r in rows) / len(rows)
        if rows else None
    )
    receipt = {
        "schema_version": QA1_RECEIPT_SCHEMA_VERSION,
        "profile": profile,
        "run_id": f"B2-QA1-{profile}-DETERMINISTIC-001",
        "runner": "python-unittest-compatible/deterministic",
        "scope": "FROZEN_DETERMINISTIC_SYNTHETIC_FIXTURE_SET",
        "case_count": len(rows), "known_bad_count": len(known_bad), "control_count": len(controls),
        "family_count": len(family_composition),
        "expected_families": expected_families,
        "observed_families": sorted(family_composition),
        "family_composition": family_composition,
        "unique_case_id_count": len(set(case_ids)),
        "exact_family_pairing": exact_family_pairing,
        "known_bad_detection_rate": sum(bool(r["detected"]) for r in known_bad) / len(known_bad) if known_bad else None,
        "control_false_reject_rate": sum(r["terminal_status"] != "PASS" for r in controls) / len(controls) if controls else None,
        "provenance_trace_rate": sum(bool(r["provenance_traceable"]) for r in rows) / len(rows) if rows else None,
        "provenance_digest_match_rate": provenance_digest_match_rate,
        "evidence_completeness_rate": sum(bool(r["evidence_complete"]) for r in rows) / len(rows) if rows else None,
        "terminal_statuses": sorted({r["terminal_status"] for r in rows}),
        "fixture_fingerprints": {r["case_id"]: r["fixture_fingerprint"] for r in rows},
        "limitations": ["Frozen synthetic deterministic cases only.", "No live model or provider performance is measured."],
    }
    receipt["gate_criteria"] = {
        "case_count": 6, "known_bad_count": 3, "control_count": 3,
        "family_count": 3, "observed_families": expected_families,
        "unique_case_id_count": 6, "exact_family_pairing": True,
        "known_bad_detection_rate": 1.0, "control_false_reject_rate": 0.0,
        "provenance_trace_rate": 1.0, "provenance_digest_match_rate": 1.0,
        "evidence_completeness_rate": 1.0,
    }
    receipt["gate"] = "PASS" if all(receipt[k] == v for k, v in receipt["gate_criteria"].items()) else "FAIL"
    receipt["receipt_fingerprint"] = sha256_json(receipt)
    return receipt
