"""ENG-B1-SC-V23-T4: deterministic Judgment-only first-instance authoring.

This module creates a public-safe synthetic protocol-validation instance only.
It performs no provider/search/judge/network call and grants no execution authority.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
from .contracts import canonical_json, fingerprint
from .protocol_v23 import SearchSpecV2, assert_content_safe, instance_gate, reference, seal, validate_entrant
from .v23_accounting import measure
from .v23_judgment import judge_view, judgment_contract, judgment_package, pool_candidates, validate_package, validate_pool
from .v23_offline import fixture_ref, reseal_spec, synthetic_spec

INSTANCE_ID = "T4-JUDGMENT-PV-001"
WORK_ORDER = "ENG-B1-SC-V23-T4"
ISSUE_NUMBER = 56
BASELINE = "b3b3a07d18950cdde2a6ad1e42b45fcda494b039"


def _artifact_ref(artifact: dict, identity: str) -> dict:
    return reference(artifact, identity, "1")


def _approval_ref() -> dict:
    return reference(
        {
            "work_order": WORK_ORDER,
            "issue_number": ISSUE_NUMBER,
            "scope": "INSTANCE_AUTHORING_ONLY",
            "execution_authority": False,
        },
        "t4-issue-56-authoring-approval",
        "1",
    )


def _candidate_material() -> tuple[list[dict], dict, dict]:
    evidence_alpha = fixture_ref("t4-pv1-evidence-alpha")
    evidence_beta = fixture_ref("t4-pv1-evidence-beta")
    evidence_gamma = fixture_ref("t4-pv1-evidence-gamma")
    policy = {
        "id": "t4-pv1-dedupe-policy",
        "version": "1",
        "normalization": "NFKC_CASEFOLD_WHITESPACE_V1",
        "identity_fields": ["target"],
        "visible_fields": ["target", "description"],
        "collision_policy": "UNKNOWN_IDENTITY",
        "ordering": "CANDIDATE_ID_ASC",
    }
    items = [
        {
            "fields": {
                "target": "Synthetic Remote Evaluation Alpha",
                "description": "Synthetic listing with explicit remote eligibility, open application status, and a stated task rate.",
            },
            "object_fingerprint": fingerprint({"t4_synthetic_object": "alpha"}),
            "evidence": [evidence_alpha],
            "frozen_submission": fixture_ref("t4-pv1-sealed-submission-a"),
            "source_alias": "t4-origin-a",
        },
        {
            "fields": {
                "target": "Synthetic Onsite Beta",
                "description": "Synthetic listing whose frozen evidence explicitly requires on-site attendance.",
            },
            "object_fingerprint": fingerprint({"t4_synthetic_object": "beta"}),
            "evidence": [evidence_beta],
            "frozen_submission": fixture_ref("t4-pv1-sealed-submission-b"),
            "source_alias": "t4-origin-b",
        },
        {
            "fields": {
                "target": "Synthetic Ambiguous Gamma",
                "description": "Synthetic listing that mentions possible remote work but omits application status and compensation.",
            },
            "object_fingerprint": fingerprint({"t4_synthetic_object": "gamma"}),
            "evidence": [evidence_gamma],
            "frozen_submission": fixture_ref("t4-pv1-sealed-submission-c"),
            "source_alias": "t4-origin-c",
        },
    ]
    packet = {
        "id": "t4-pv1-evidence-packet",
        "version": "1",
        "entries": [
            {
                "reference": evidence_alpha,
                "excerpt": "Synthetic Alpha is remote-eligible, accepting applications, and states a task rate.",
                "captured_at": "2026-09-16T13:07:00+02:00",
                "locator": "urn:synthetic:t4-pv1:alpha",
                "corpus_fingerprint": None,
            },
            {
                "reference": evidence_beta,
                "excerpt": "Synthetic Beta requires attendance at the synthetic work site and does not permit remote work.",
                "captured_at": "2026-09-16T13:07:00+02:00",
                "locator": "urn:synthetic:t4-pv1:beta",
                "corpus_fingerprint": None,
            },
            {
                "reference": evidence_gamma,
                "excerpt": "Synthetic Gamma may allow remote work; application status and compensation are not stated.",
                "captured_at": "2026-09-16T13:07:00+02:00",
                "locator": "urn:synthetic:t4-pv1:gamma",
                "corpus_fingerprint": None,
            },
        ],
    }
    return items, policy, packet


def _rubric_and_adjudication() -> tuple[dict, dict]:
    rubric = {
        "id": "t4-pv1-rubric",
        "version": "1",
        "dimensions": [
            {
                "id": "remote_eligibility",
                "allowed_values": ["YES", "NO", "UNKNOWN"],
                "evidence_threshold": "Explicit frozen evidence that remote work is allowed or forbidden.",
                "unknown_rule": "INSUFFICIENT_EVIDENCE_NOT_NEGATIVE",
                "hard_constraint": True,
                "satisfying_values": ["YES"],
            },
            {
                "id": "actionability",
                "allowed_values": ["YES", "NO", "UNKNOWN"],
                "evidence_threshold": "Frozen evidence states an actionable application path/status and enough terms to act.",
                "unknown_rule": "INSUFFICIENT_EVIDENCE_NOT_NEGATIVE",
                "hard_constraint": True,
                "satisfying_values": ["YES"],
            },
        ],
        "confidence_allowed": True,
        "hard_constraints_first": True,
        "aggregation": {
            "method": "ALL_HARD_CONSTRAINTS_SATISFIED",
            "tie_policy": "PRESERVE_DISAGREEMENT",
            "unknown_policy": "PRESERVE",
            "frozen_before_outputs": True,
        },
    }
    adjudication = {
        "id": "t4-pv1-adjudication",
        "version": "1",
        "allowed": True,
        "triggers": [
            "DISAGREEMENT",
            "CRITICAL_UNKNOWN",
            "IDENTITY_COLLISION",
            "CONTRADICTION",
            "RUBRIC_EDGE",
        ],
        "thresholds": fixture_ref("t4-pv1-adjudication-thresholds"),
        "evidence_policy": "FROZEN_PACKET_ONLY",
        "append_only": True,
    }
    return rubric, adjudication


def _judge_roster() -> list[dict]:
    common = {
        "provider": "synthetic-not-connected",
        "resolution_status": "KNOWN",
        "identity_status": "AS_REQUESTED",
        "alias_evidence": None,
        "endpoint_mode": "NOT_CONNECTED",
    }
    roster = [
        {
            **common,
            "entrant_id": "t4-fixture-judge-a",
            "requested_model_id": "fixture-judge-a-v1",
            "resolved_model_id": "fixture-judge-a-v1",
            "config_fingerprint": fingerprint(
                {"instance": INSTANCE_ID, "judge": "a", "temperature": 0, "tools": []}
            ),
        },
        {
            **common,
            "entrant_id": "t4-fixture-judge-b",
            "requested_model_id": "fixture-judge-b-v1",
            "resolved_model_id": "fixture-judge-b-v1",
            "config_fingerprint": fingerprint(
                {"instance": INSTANCE_ID, "judge": "b", "temperature": 0, "tools": []}
            ),
        },
    ]
    for entrant in roster:
        validate_entrant(entrant)
    return roster


def _searchspec_and_package() -> tuple[SearchSpecV2, dict, dict]:
    items, policy, evidence_packet = _candidate_material()
    pool, provenance = pool_candidates(items, policy)
    validate_pool(pool)
    rubric, adjudication = _rubric_and_adjudication()

    doc = synthetic_spec("JUDGMENT_ONLY")
    doc["spec_id"] = "SEARCH-CUP-V23-T4-JUDGMENT-PV-001"
    doc["spec_version"] = "1"
    doc["created_at"] = "2026-09-16T13:07:00+02:00"
    doc["frozen_at"] = "2026-09-16T13:07:00+02:00"
    doc["task"] = {
        "task_id": INSTANCE_ID,
        "task_class": "SYNTHETIC_PROTOCOL_VALIDATION",
        "target": "synthetic remote-work opportunity candidate",
        "objective": "Judge each frozen synthetic candidate for remote eligibility and actionability using only frozen evidence.",
        "success_criteria": [
            "preserve insufficient evidence as UNKNOWN",
            "apply hard constraints before aggregation",
            "use no search or external tools",
        ],
        "unit_of_evaluation": "candidate",
        "output_cardinality": {"minimum": 3, "maximum": 3},
        "inclusion_criteria": ["public-safe synthetic candidate", "frozen evidence packet"],
        "exclusion_criteria": ["real-world candidate claim", "private source", "live lookup"],
        "evidence_requirements": ["frozen candidate-linked evidence only"],
        "unknown_semantics": "INSUFFICIENT_EVIDENCE_NOT_NEGATIVE",
        "stop_conditions": [
            "all frozen candidates receive one independent first-pass record per configured judge",
            "future resource ceiling reached",
            "typed terminal returned",
        ],
    }
    doc["scope"] = {
        "language_pool": ["en"],
        "geography_scope": {"included": ["synthetic-protocol-validation"], "excluded": []},
        "source_classes_allowed": ["SYNTHETIC"],
        "source_classes_excluded": ["PRIVATE", "LIVE"],
        "time_window": "2026-09-16-fixed-synthetic-fixture-v1",
        "freshness_rule": "frozen synthetic evidence only",
        "verification_sources_allowed": [],
        "verification_sources_excluded": ["LIVE", "EXTERNAL_TOOL"],
        "privacy_class": "PUBLIC_SAFE",
        "public_safe_only": True,
    }
    doc["resources"].update(
        max_search_calls=0,
        max_search_turns=0,
        max_results_per_call=0,
        max_follow_links=0,
        automatic_retries=0,
        timeout_per_call_ms=30000,
        max_total_runtime_ms=measure(120000, "ms"),
        token_ceiling=measure(6000, "tokens"),
        money_ceiling=measure(0, "USD"),
        resource_unit_definition="one future judge request per judge-candidate pair; no search or external tools",
        search_unit="NONE",
    )
    output_schema = fixture_ref("t4-pv1-judge-record-output")
    source_overlay = {
        "kind": "SYNTHETIC",
        "corpus": None,
        "reference_set": None,
        "capture_cutoff": None,
        "adjudication_time": None,
        "drift_policy": None,
    }
    resource_fingerprint = fingerprint(doc["resources"])
    core = judgment_contract(
        pool,
        evidence_packet,
        rubric,
        adjudication,
        output_schema=output_schema,
        resource_fingerprint=resource_fingerprint,
        source_overlay=source_overlay,
    )
    doc["output_contract"] = reference(output_schema, "t4-pv1-output-contract", "1")
    doc["judgment_contract"] = reference(core, "t4-pv1-judgment-contract", "1")
    doc["overlay"]["candidate_set"] = _artifact_ref(pool, "t4-pv1-candidate-set")
    doc["overlay"]["evidence_packet"] = _artifact_ref(evidence_packet, "t4-pv1-evidence-packet")
    doc["overlay"]["rubric"] = _artifact_ref(rubric, "t4-pv1-rubric")
    doc["overlay"]["output_schema"] = output_schema
    doc["overlay"]["adjudication_policy"] = _artifact_ref(adjudication, "t4-pv1-adjudication")
    doc["overlay"]["blind_transform"] = _artifact_ref(policy, "t4-pv1-blind-transform")
    doc["overlay"]["order_policy"] = _artifact_ref(core["order_policy"], "t4-pv1-order-policy")
    doc["overlay"]["aggregation_policy"] = _artifact_ref(rubric["aggregation"], "t4-pv1-aggregation")
    doc["overlay"]["allowed_tools"] = []
    doc["overlay"]["independent_first_pass"] = True

    spec = SearchSpecV2.from_mapping(reseal_spec(doc))
    package = judgment_package(
        pool,
        evidence_packet,
        rubric,
        adjudication,
        output_schema=output_schema,
        resource_fingerprint=fingerprint(spec.as_dict()["resources"]),
        source_overlay=source_overlay,
        spec=spec,
    )
    validate_package(package)
    return spec, package, provenance


def _binding_artifacts(spec: SearchSpecV2, judgment: dict, roster: list[dict]) -> tuple[dict, dict]:
    doc = spec.as_dict()
    artifacts = {
        "D1": {
            "schema_id": "search-instance/d1/v2",
            "spec_fingerprint": spec.fingerprint,
            "binding": "JUDGMENT_ONLY",
        },
        "D2": {
            "schema_id": "search-instance/d2/v2",
            "spec_fingerprint": spec.fingerprint,
            "binding": spec.fingerprint,
            "searchspec": doc,
        },
        "D3": {
            "schema_id": "search-instance/d3/v2",
            "spec_fingerprint": spec.fingerprint,
            "judgment_package": judgment,
        },
        "D5": {
            "schema_id": "search-instance/d5/v2",
            "spec_fingerprint": spec.fingerprint,
            "roster": roster,
        },
        "D7": {
            "schema_id": "search-instance/d7/v2",
            "spec_fingerprint": spec.fingerprint,
            "binding": fingerprint(doc["resources"]),
            "resources": doc["resources"],
        },
    }
    approval = _approval_ref()
    decisions = {}
    artifact_map = {}
    for name in ("D1", "D2", "D3", "D5", "D7"):
        ref = _artifact_ref(artifacts[name], f"{INSTANCE_ID.lower()}-{name.lower()}")
        artifact_map[ref["fingerprint"]] = artifacts[name]
        decisions[name] = {
            "status": "FROZEN",
            "artifact": ref,
            "approval": approval,
            "reason": "Frozen for T4 synthetic protocol-validation package authoring; execution remains separately gated.",
        }
    for name, reason in {
        "D4": "NOT_APPLICABLE: Judgment-only uses a synthetic judgment overlay, not a frozen corpus/index execution overlay.",
        "D6": "NOT_APPLICABLE: Judgment-only has no retriever; all search/follow-link/tool budgets are zero.",
        "D8": "NOT_APPLICABLE: first protocol-validation instance is F1 Judgment-only, not system/economic/ablation.",
    }.items():
        decisions[name] = {"status": "NOT_APPLICABLE", "artifact": None, "approval": None, "reason": reason}
    binding_package = seal(
        {
            "schema_id": "search-instance-bindings/v2",
            "spec_fingerprint": spec.fingerprint,
            "decisions": decisions,
        }
    )
    return binding_package, artifact_map


def build_bundle() -> dict:
    spec, judgment, provenance = _searchspec_and_package()
    roster = _judge_roster()
    bindings, artifact_map = _binding_artifacts(spec, judgment, roster)
    gate = instance_gate(spec, bindings, artifact_map)
    if gate["missing_decisions"]:
        raise ValueError("T4 binding package is incomplete")
    if gate["execution_allowed"] or gate["terminal_status"] != "BLOCKED":
        raise ValueError("T4 authoring must remain fail-closed")
    blind = judge_view(judgment)
    blind_sha256 = hashlib.sha256(blind).hexdigest()

    manifest = seal(
        {
            "schema_id": "search-t4-instance-manifest/v1",
            "instance_id": INSTANCE_ID,
            "work_order": WORK_ORDER,
            "issue_number": ISSUE_NUMBER,
            "baseline": BASELINE,
            "mode": "SYNTHETIC_PROTOCOL_VALIDATION",
            "benchmark_claim": False,
            "searchspec": _artifact_ref(spec.as_dict(), "t4-pv1-searchspec"),
            "candidate_pool": _artifact_ref(judgment["candidate_pool"], "t4-pv1-candidate-pool"),
            "judgment_package": _artifact_ref(judgment, "t4-pv1-judgment-package"),
            "provenance_ledger": _artifact_ref(provenance, "t4-pv1-provenance-ledger"),
            "judge_roster": _artifact_ref(roster, "t4-pv1-judge-roster"),
            "resources": _artifact_ref(spec.as_dict()["resources"], "t4-pv1-resources"),
            "instance_bindings": _artifact_ref(bindings, "t4-pv1-instance-bindings"),
            "blind_judge_view_sha256": blind_sha256,
            "execution_authority": False,
        }
    )
    receipt = seal(
        {
            "schema_id": "search-t4-instance-authoring-receipt/v1",
            "instance_id": INSTANCE_ID,
            "work_order": WORK_ORDER,
            "baseline": BASELINE,
            "manifest_fingerprint": manifest["canonical_fingerprint"],
            "searchspec_fingerprint": spec.fingerprint,
            "judgment_package_fingerprint": judgment["canonical_fingerprint"],
            "candidate_pool_fingerprint": judgment["candidate_pool"]["canonical_fingerprint"],
            "provenance_ledger_fingerprint": provenance["canonical_fingerprint"],
            "judge_roster_fingerprint": fingerprint(roster),
            "resource_fingerprint": fingerprint(spec.as_dict()["resources"]),
            "instance_bindings_fingerprint": bindings["canonical_fingerprint"],
            "blind_judge_view_sha256": blind_sha256,
            "execution_gate": gate,
            "execution_allowed": False,
            "provider_calls": 0,
            "search_calls": 0,
            "judge_calls": 0,
            "credit_consumption": 0,
            "spend": {"state": "KNOWN", "value": 0, "currency": "USD"},
            "official_prompt_consumed": False,
            "hidden_registry_loaded": False,
            "real_world_candidate_claim": False,
            "review_status": "AWAITING_BOARD_VERIFICATION",
        }
    )
    bundle = {
        "manifest": manifest,
        "searchspec": spec.as_dict(),
        "candidate_pool": judgment["candidate_pool"],
        "blind_judge_view": json.loads(blind.decode("utf-8")),
        "provenance_ledger": provenance,
        "evidence_packet": judgment["evidence_packet"],
        "rubric": judgment["rubric"],
        "adjudication": judgment["adjudication"],
        "judge_roster": roster,
        "resources": spec.as_dict()["resources"],
        "instance_bindings": bindings,
        "judgment_package": judgment,
        "receipt": receipt,
    }
    assert_content_safe(bundle)
    return bundle


def _write_bundle(output_dir: Path) -> None:
    bundle = build_bundle()
    output_dir.mkdir(parents=True, exist_ok=True)
    names = {
        "manifest": "manifest.json",
        "searchspec": "searchspec.json",
        "candidate_pool": "candidate-pool.json",
        "blind_judge_view": "blind-judge-view.json",
        "provenance_ledger": "provenance-ledger.json",
        "evidence_packet": "evidence-packet.json",
        "rubric": "rubric.json",
        "adjudication": "adjudication.json",
        "judge_roster": "judge-roster.json",
        "resources": "resource-envelope.json",
        "instance_bindings": "instance-bindings.json",
        "judgment_package": "judgment-package.json",
        "receipt": "receipt.json",
    }
    for key, filename in names.items():
        (output_dir / filename).write_text(
            json.dumps(bundle[key], ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    bundle_parser = sub.add_parser("bundle")
    bundle_parser.add_argument("--output-dir", required=True)
    sub.add_parser("receipt")
    args = parser.parse_args(argv)
    if args.command == "bundle":
        _write_bundle(Path(args.output_dir))
    else:
        print(json.dumps(build_bundle()["receipt"], ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
