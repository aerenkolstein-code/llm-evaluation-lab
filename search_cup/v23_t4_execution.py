"""JE0: freeze offline fixture semantics and a future plan; never run judgments.

Only ``bundle`` and ``receipt`` are CLI commands. The pure decision transform is
exercised with synthetic test-only records by tests, not by the authoring path.
No parent T4/SP3 object is changed and no execution authority is granted.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .contracts import canonical_json, fingerprint
from .protocol_v23 import assert_content_safe, seal, verify_seal
from .v23_judgment import validate_package, validate_record
from .v23_t4_instance import build_bundle as build_parent

WORK_ORDER = "WO-ENG-B1-SC-V23-T4-JE0 v0.1"
BASELINE = "82fcbe64027d94e0b5115d2ef412000c004c32e2"
BASELINE_TREE = "1321e37917e69472586517628aa18e4c5e97e074"
EXECUTION_ID = "T4-JUDGMENT-PV-001-EXEC-V1"
MODE = "OFFLINE_FIXTURE_PROTOCOL_VALIDATION"
ALIASES = ("t4-fixture-judge-a", "t4-fixture-judge-b")

# SHA-256 of complete canonical objects (including any embedded seal). These
# constants are pinned from the unchanged accepted PR58 source, not caller input.
PARENT_HASHES = {
    "manifest": "8117cb43b29d31daf44de140c62881f574cf9a324e7cf35f8e220a4d5d6669f9",
    "judgment_package": "3e9d81c5ddee6b73697afe21d9754300be2f5f88e9b5c7cbca7bed58808233f4",
    "candidate_pool": "a0132c0b147d7e247533a05c6750a5252f4b4d0c6e97cc2099c97303085225f4",
    "searchspec": "2d45b631a5ded75210c15176fa325c76bafe373e526f6deb6890d69a2ab8a491",
    "evidence_packet": "bf48b10ad285afdb78e42248509f9c4975a4339ee53d731e2a898278b2935f0e",
    "rubric": "cfce4f09a316a9da83fc9841ca8f65c8dad5a756288306f7f8747e0ea6ed94ea",
    "adjudication": "ea4d2bf832f7ad218881b4f5f7c917f40bfabfca1ffe7c67e263ebf4291c69d8",
    "judge_roster": "d3a47eb0f01a3a816ecfb14a626a16586bc500ed14160f33469f0d83f5591a76",
    "instance_bindings": "32b5f76fd98deb417c2a79975ad0767269b1ee7300368c63f21f71701beb7a7b",
    "blind_judge_view": "3e9d81c5ddee6b73697afe21d9754300be2f5f88e9b5c7cbca7bed58808233f4",
    "resources": "5c437d04de0b462c40bce32be9c057537176ea73c1b7ed2d24719af6d8421552",
}

LINEAGE = {
    "repository": "aerenkolstein-code/llm-evaluation-lab",
    "accepted_pr": 58,
    "reviewed_head": "4ff845a2b15166175c0eb01d03a2ebe770f6ba2e",
    "publication_commit": BASELINE,
    "publication_tree": BASELINE_TREE,
    "artifact_name": "search-cup-v23-t4-judgment-pv-001-4ff845a2b15166175c0eb01d03a2ebe770f6ba2e",
    "artifact_id": 10448455537,
    "artifact_digest": "sha256:cde541471a561353c3419086db467c560c5f59a3be4dc612cecb125e84eaf4be",
}

J_PLANS = (
    ("Candidate set unchanged", ["parent-binding.json", "blind-input.json", "future:first-pass-journal"]),
    ("Equal rubric, evidence and candidate ordering", ["blind-input.json", "first-pass-plan.json", "future:input-delivery-digests"]),
    ("Blind input contains no source labels or roster", ["blind-input.json", "future:leakage-audit"]),
    ("Zero search, live retrieval, follow links and external tools", ["receipt.json", "future:resource-receipt"]),
    ("Six independent first passes committed before synthesis", ["first-pass-plan.json", "future:append-only-journal"]),
    ("UNKNOWN, REJECT and non-evaluable states remain distinct", ["fixture-profiles.json", "future:typed-record-validation"]),
    ("Overrides preserve all machine records and chain hashes", ["blind-input.json", "future:append-only-journal"]),
    ("Aggregation is frozen before outputs", ["blind-input.json", "execution-binding.json", "future:start-pin"]),
    ("Provenance ledger never delivered to judges", ["first-pass-plan.json", "future:input-delivery-audit"]),
    ("Parent, profiles, roster and binding unchanged since start", ["execution-binding.json", "fixture-profiles.json", "future:start-and-end-pins"]),
)


def _accepted_parent() -> dict:
    parent = build_parent()
    for key, expected in PARENT_HASHES.items():
        if fingerprint(parent[key]) != expected:
            raise ValueError("accepted T4 parent drift; a new work order is required")
    validate_package(parent["blind_judge_view"])
    return parent


def _profiles(blind: dict) -> dict:
    # Explicit lookup semantics for these three frozen synthetic examples only.
    # Beta's application terms are absent: under the accepted SP3 validator a
    # hard UNKNOWN precludes REJECT too. Do not invent an actionability=NO fact.
    values = {
        "synthetic remote evaluation alpha": ("YES", "YES", "ACCEPT", "EXPLICIT_REMOTE_AND_ACTIONABLE"),
        "synthetic onsite beta": ("NO", "UNKNOWN", "UNKNOWN", "ONSITE_EXPLICIT_ACTIONABILITY_UNRESOLVED"),
        "synthetic ambiguous gamma": ("UNKNOWN", "UNKNOWN", "UNKNOWN", "REMOTE_AND_TERMS_UNRESOLVED"),
    }
    profiles = {}
    for alias, positive, unknown in ((ALIASES[0], 0.95, 0.5), (ALIASES[1], 0.9, 0.25)):
        cases = []
        for candidate in blind["candidate_pool"]["candidates"]:
            remote, actionable, state, reason = values[candidate["fields"]["target"]]
            cases.append({
                "candidate_id": candidate["candidate_id"],
                "candidate_fingerprint": fingerprint(candidate),
                "decision_fields": {
                    "state": state,
                    "dimensions": [{"id": "remote_eligibility", "value": remote},
                                   {"id": "actionability", "value": actionable}],
                    "confidence": positive if state == "ACCEPT" else unknown,
                    "evidence_used": candidate["evidence"],
                    "reason_codes": [reason],
                    "failure_class": "NONE" if state == "ACCEPT" else "INSUFFICIENT_EVIDENCE",
                    "observed_peer_records": [],
                },
            })
        profiles[alias] = seal({
            "schema_id": "t4-fixture-behavior/v1",
            "profile_id": alias + "-semantics-v1",
            "algorithm": "EXACT_FROZEN_BLIND_LOOKUP_HARD_UNKNOWN_FIRST_V1",
            "blind_input_sha256": fingerprint(blind),
            "input_policy": "FROZEN_BLIND_PACKAGE_ONLY_NO_PEER_INPUT",
            "unknown_policy": "PRESERVE_HARD_UNKNOWN_BEFORE_QUALITY_DECISION",
            "confidence_meaning": "FIXED_SYNTHETIC_TEST_VALUE_NOT_EMPIRICAL_CALIBRATION",
            "semantic_cases": cases,
        })
    return profiles


def fixture_decision(blind_bytes: bytes, profile: dict, candidate_id: str) -> dict:
    """Pure frozen mapping, with no I/O, environment, peer or journal handle.

    This returns decision fields, not a committed FIRST_PASS record. JE0 calls
    it only in unit tests. Formal replay requires the separate JE1 work order.
    """
    blind = json.loads(blind_bytes)
    if blind_bytes != canonical_json(blind).encode("utf-8"):
        raise ValueError("blind input must use canonical bytes")
    if fingerprint(blind) != PARENT_HASHES["blind_judge_view"]:
        raise ValueError("unfrozen blind input")
    verify_seal(profile)
    if profile not in _profiles(blind).values():
        raise ValueError("unfrozen fixture semantics")
    case = next((c for c in profile["semantic_cases"] if c["candidate_id"] == candidate_id), None)
    if case is None:
        raise ValueError("unfrozen candidate")
    return json.loads(canonical_json(case["decision_fields"]))


def _assemble(parent: dict) -> dict:
    blind = parent["blind_judge_view"]
    parent_binding = seal({
        "schema_id": "t4-je0-parent-binding/v1",
        "instance_id": "T4-JUDGMENT-PV-001",
        "lineage": LINEAGE,
        "full_object_sha256": PARENT_HASHES,
        "parent_package_fingerprint": parent["judgment_package"]["canonical_fingerprint"],
        "parent_manifest_fingerprint": parent["manifest"]["canonical_fingerprint"],
    })
    profiles = _profiles(blind)
    roster = [{**identity, "config_fingerprint": fingerprint({
        "parent_identity": identity,
        "execution_id": EXECUTION_ID,
        "behavior_profile": profiles[identity["entrant_id"]]["canonical_fingerprint"],
    })} for identity in parent["judge_roster"]]
    integrity_plan = seal({
        "schema_id": "t4-je0-integrity-plan/v1",
        "checks": {f"J{i}": {"requirement": requirement, "required_evidence": evidence,
                               "run_status": "NOT_RUN"}
                   for i, (requirement, evidence) in enumerate(J_PLANS, 1)},
        "pass_rule": "ALL_J1_J10_PASS_WITH_NONEMPTY_EVIDENCE",
        "failed_hard_gate_result": "NOT_EVALUABLE",
        "missing_evidence_result": "NOT_EVALUABLE",
    })
    # The full successor fingerprint is the future run namespace. Profile or
    # parent mutation therefore cannot retain the same run identity.
    binding = seal({
        "schema_id": "t4-je0-execution-binding/v1",
        "execution_id": EXECUTION_ID,
        "version": "1",
        "work_order": WORK_ORDER,
        "mode": MODE,
        "parent_binding_fingerprint": parent_binding["canonical_fingerprint"],
        "parent_package_fingerprint": parent_binding["parent_package_fingerprint"],
        "blind_input_sha256": fingerprint(blind),
        "fixture_profile_fingerprints": {k: v["canonical_fingerprint"] for k, v in profiles.items()},
        "execution_roster_fingerprint": fingerprint(roster),
        "integrity_plan_fingerprint": integrity_plan["canonical_fingerprint"],
        "aggregation_fingerprint": fingerprint(blind["rubric"]["aggregation"]),
        "adjudication_fingerprint": fingerprint(blind["adjudication"]),
        "order_policy": "CANDIDATE_ID_ASC",
        "schedule_policy": "JUDGE_ALIAS_ASC_THEN_CANDIDATE_ID_ASC",
        "first_pass_count": 6,
        "run_namespace_policy": "EXECUTION_ID_COLON_FULL_BINDING_SHA256_COLON_JE1_001",
        "execution_allowed": False,
        "formal_execution_performed": False,
        "authority_required": "INDEPENDENT_ACCEPTANCE_AND_SEPARATE_JE1_WORK_ORDER",
        "claims": "SYNTHETIC_NOT_BENCHMARK_NO_MODEL_QUALITY_OR_LEADERBOARD",
    })
    run_id = EXECUTION_ID + ":" + binding["canonical_fingerprint"] + ":JE1-001"
    planned = [{
        "kind": "FIRST_PASS", "run_id": run_id,
        "record_id": run_id + ":" + alias + ":" + candidate["candidate_id"],
        "judge_alias": alias, "candidate_id": candidate["candidate_id"],
        "blind_input_sha256": fingerprint(blind), "observed_peer_records": [],
        "evidence_policy": "SUBSET_OF_CANDIDATE_FROZEN_EVIDENCE",
        "input_delivery": "CANONICAL_BLIND_INPUT_BYTES_ONLY",
        "status": "PLANNED_NOT_EXECUTED",
    } for alias in ALIASES for candidate in blind["candidate_pool"]["candidates"]]
    plan = seal({
        "schema_id": "t4-je0-first-pass-plan/v1", "run_id": run_id,
        "execution_binding_fingerprint": binding["canonical_fingerprint"],
        "judges": list(ALIASES), "planned_first_pass_count": 6,
        "planned_records": planned, "human_override_barrier": "ALL_SIX_FIRST_PASSES_COMMITTED",
        "first_pass_overwrite": "FORBIDDEN", "adjudication": "APPEND_ONLY_FROZEN_PACKET_ONLY",
        "formal_record_count": 0,
    })
    receipt = seal({
        "schema_id": "t4-je0-readiness-receipt/v1", "work_order": WORK_ORDER,
        "execution_id": EXECUTION_ID, "mode": MODE,
        "execution_binding_fingerprint": binding["canonical_fingerprint"],
        "parent_binding_fingerprint": parent_binding["canonical_fingerprint"],
        "first_pass_plan_fingerprint": plan["canonical_fingerprint"],
        "execution_allowed": False, "formal_execution_performed": False,
        "formal_record_count": 0, "fixture_decision_calls_on_authoring_path": 0,
        "provider_calls": 0, "search_calls": 0, "judge_network_calls": 0,
        "network_calls": 0, "follow_links": 0, "automatic_retries": 0,
        "external_tools": [], "credential_reads": 0, "credit_consumption": 0,
        "spend": {"value": 0, "currency": "USD"},
        "official_prompt_consumed": False, "hidden_registry_loaded": False,
        "real_world_candidate_claim": False, "benchmark_claim": False,
        "model_quality_claim": False, "leaderboard_claim": False,
        "counter_scope": "JE0_AUTHORING_PATH_ONLY_NOT_GIT_OR_CI_TRANSPORT",
        "post_run_integrity": "NOT_RUN", "review_status": "AWAITING_INDEPENDENT_BOARD_VERIFICATION",
    })
    return {"parent_binding": parent_binding, "blind_input": blind,
            "fixture_profiles": profiles, "execution_roster": roster,
            "execution_binding": binding, "first_pass_plan": plan,
            "integrity_plan": integrity_plan, "receipt": receipt}


def build_bundle() -> dict:
    """Deterministic authoring only. No fixture_decision call or record commit."""
    bundle = _assemble(_accepted_parent())
    assert_content_safe(bundle)
    return bundle


def validate_bundle(bundle: dict, *, expected_fingerprint: str) -> None:
    """Check against an independently retained review pin, not a supplied seal."""
    assert_content_safe(bundle)
    expected = build_bundle()
    if expected["execution_binding"]["canonical_fingerprint"] != expected_fingerprint:
        raise ValueError("execution binding differs from the retained review pin")
    if canonical_json(bundle) != canonical_json(expected):
        raise ValueError("frozen execution bundle was changed or extended")


def validate_planned_record(record: dict, bundle: dict, *, expected_fingerprint: str) -> None:
    """Pure validation of supplied records; does not produce or commit them."""
    validate_bundle(bundle, expected_fingerprint=expected_fingerprint)
    validate_record(record, bundle["blind_input"])
    plan = bundle["first_pass_plan"]
    planned = next((p for p in plan["planned_records"]
                    if (p["judge_alias"], p["candidate_id"]) ==
                    (record["judge_alias"], record["candidate_id"])), None)
    if planned is None or any(record[k] != planned[k] for k in ("run_id", "record_id")):
        raise ValueError("record is outside frozen six-record plan")
    identity = next(i for i in bundle["execution_roster"] if i["entrant_id"] == record["judge_alias"])
    if record["judge_identity"] != identity:
        raise ValueError("record identity/profile does not match successor roster")
    profile = bundle["fixture_profiles"][record["judge_alias"]]
    case = next(c for c in profile["semantic_cases"] if c["candidate_id"] == record["candidate_id"])
    if any(record[k] != v for k, v in case["decision_fields"].items()):
        raise ValueError("record does not implement frozen fixture semantics")


FILENAMES = {
    "parent_binding": "parent-binding.json", "blind_input": "blind-input.json",
    "fixture_profiles": "fixture-profiles.json", "execution_roster": "execution-roster.json",
    "execution_binding": "execution-binding.json", "first_pass_plan": "first-pass-plan.json",
    "integrity_plan": "integrity-plan.json", "receipt": "receipt.json",
}


def write_bundle(output_dir: Path) -> None:
    bundle = build_bundle()
    # A used directory could retain judgments from another stage. Fail closed.
    output_dir.mkdir(parents=True, exist_ok=False)
    for key, filename in FILENAMES.items():
        (output_dir / filename).write_bytes(canonical_json(bundle[key]).encode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("bundle")
    command.add_argument("--output-dir", type=Path, required=True)
    sub.add_parser("receipt")
    args = parser.parse_args(argv)
    if args.command == "bundle":
        write_bundle(args.output_dir)
    else:
        print(canonical_json(build_bundle()["receipt"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
