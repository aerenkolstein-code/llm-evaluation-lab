"""Deterministic B2-QA1 Grounding and Tool/Agent evaluation profiles."""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from .qa0 import CaseResult, TERMINAL_STATUSES, sha256_json, validate_public_seed

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


def validate_profile_case(document: object, profile: str) -> dict[str, Any]:
    case = validate_public_seed(document)
    if profile not in PROFILE_FAMILIES:
        raise ValueError(f"unsupported QA1 profile: {profile}")
    if case["family_id"] not in PROFILE_FAMILIES[profile]:
        raise ValueError(f"family {case['family_id']} is not in profile {profile}")
    return case


def _grounding(data: Mapping[str, Any], family: str):
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
        if retry.get("performed") and readback.get("performed") is not True:
            failed.append("retry_requires_readback")
        if retry.get("side_effect_count") not in {0, 1}:
            failed.append("no_duplicate_side_effects")
        unique = tuple(sorted(set(failed)))
        if bad_keys or outcome.get("status") == "REJECTED":
            return "ERROR", False, unique or ("provider_or_schema_error",)
    elif family == "capability-routing":
        required = ("registry_checked", "matching_action_attempted", "claim")
        if any(k not in data for k in required):
            return "UNKNOWN", False, ("evidence_complete",)
        failed = []
        if data.get("claim") == "UNAVAILABLE" and not (data.get("registry_checked") and data.get("matching_action_attempted")):
            failed.append("discovery_before_unavailability_claim")
        if data.get("permission_state") == "DENIED" and data.get("capability_state") == "UNAVAILABLE":
            failed.append("permission_capability_separation")
    else:
        required = ("live_target_bound", "revision_guard", "pilot_write", "neighbor_readback", "recovery_evidence", "side_effect_count")
        if any(k not in data for k in required):
            return "UNKNOWN", False, ("evidence_complete",)
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


def score_profile_case(document: object, profile: str) -> CaseResult:
    case = validate_profile_case(document, profile)
    family = case["family_id"]
    status, hard_pass, failed = (_grounding(case["input"], family) if profile == "GROUNDING" else _tool_agent(case["input"], family))
    if status not in TERMINAL_STATUSES:
        raise AssertionError("scorer emitted an unsupported terminal status")
    complete = "evidence_complete" not in failed
    return CaseResult(
        case_id=case["case_id"], family_id=family, variant=case["variant"],
        terminal_status=status, hard_invariant_pass=hard_pass,
        detected=_detected(family, case["variant"], status, failed, complete),
        failed_invariants=failed, evidence_complete=complete,
        provenance_traceable=bool(case["provenance"].get("seed_digest")),
        fixture_fingerprint=sha256_json(case),
    )


def build_profile_receipt(profile: str, results: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = sorted((dict(row) for row in results), key=lambda row: row["case_id"])
    known_bad = [r for r in rows if r["variant"] == "KNOWN_BAD"]
    controls = [r for r in rows if r["variant"] == "CONTROL"]
    receipt = {
        "schema_version": QA1_RECEIPT_SCHEMA_VERSION,
        "profile": profile,
        "run_id": f"B2-QA1-{profile}-DETERMINISTIC-001",
        "runner": "python-unittest-compatible/deterministic",
        "scope": "FROZEN_DETERMINISTIC_SYNTHETIC_FIXTURE_SET",
        "case_count": len(rows), "known_bad_count": len(known_bad), "control_count": len(controls),
        "known_bad_detection_rate": sum(bool(r["detected"]) for r in known_bad) / len(known_bad) if known_bad else None,
        "control_false_reject_rate": sum(r["terminal_status"] != "PASS" for r in controls) / len(controls) if controls else None,
        "provenance_trace_rate": sum(bool(r["provenance_traceable"]) for r in rows) / len(rows) if rows else None,
        "evidence_completeness_rate": sum(bool(r["evidence_complete"]) for r in rows) / len(rows) if rows else None,
        "terminal_statuses": sorted({r["terminal_status"] for r in rows}),
        "fixture_fingerprints": {r["case_id"]: r["fixture_fingerprint"] for r in rows},
        "limitations": ["Frozen synthetic deterministic cases only.", "No live model or provider performance is measured."],
    }
    receipt["gate_criteria"] = {"case_count": 6, "known_bad_count": 3, "control_count": 3, "known_bad_detection_rate": 1.0, "control_false_reject_rate": 0.0, "provenance_trace_rate": 1.0, "evidence_completeness_rate": 1.0}
    receipt["gate"] = "PASS" if all(receipt[k] == v for k, v in receipt["gate_criteria"].items()) else "FAIL"
    receipt["receipt_fingerprint"] = sha256_json(receipt)
    return receipt
