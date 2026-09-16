"""Deterministic synthetic protocol probes, NOT a selected benchmark instance.

CLI: python -m search_cup.v23_offline [receipt|schema]
No provider, search, judge, credential lookup or official prompt is invoked.
"""

from __future__ import annotations

import argparse
import json

from .contracts import fingerprint
from .protocol_v23 import (
    PRINCIPAL, REQUIRED_CONTROLS, TRACK_CLAIM, SearchSpecV2, a0_resource_binding, assert_content_safe,
    control_bindings, instance_gate, reference, seal,
)
from .v23_accounting import ResourceLedger, measure
from .v23_judgment import judgment_contract, judgment_package, pool_candidates
from .v23_schema import SEARCHSPEC_SCHEMA, TRACKS


def fixture_ref(name: str) -> dict:
    return reference({"synthetic_fixture": name}, "synthetic-" + name)


def synthetic_spec(track: str = "JUDGMENT_ONLY") -> dict:
    """Numbers, task, roster and refs are test inputs, never D1-D8 decisions."""
    if track not in TRACKS:
        raise ValueError("unknown fixture track")
    judgment = track == "JUDGMENT_ONLY"
    mode = "F1" if track in ("JUDGMENT_ONLY", "E1_FROZEN", "E1_LIVE") else "F3" if track == "ECONOMIC_TRACK" else "F2"
    task = {"task_id": "synthetic-contract-probe", "task_class": "SYNTHETIC_NOT_BENCHMARK",
            "target": "synthetic information object", "objective": "validate protocol boundaries only",
            "success_criteria": ["contract validity, no execution"], "unit_of_evaluation": "synthetic contract",
            "output_cardinality": {"minimum": 0, "maximum": 2}, "inclusion_criteria": ["synthetic"],
            "exclusion_criteria": ["real inputs"], "evidence_requirements": ["frozen synthetic evidence"],
            "unknown_semantics": "INSUFFICIENT_EVIDENCE_NOT_NEGATIVE", "stop_conditions": ["return for review"]}
    scope = {"language_pool": ["en"], "geography_scope": {"included": ["synthetic"], "excluded": []},
             "source_classes_allowed": ["SYNTHETIC"], "source_classes_excluded": ["PRIVATE"],
             "time_window": "synthetic-fixed-window", "freshness_rule": "fixture capture time only",
             "verification_sources_allowed": [], "verification_sources_excluded": ["LIVE"],
             "privacy_class": "PUBLIC_SAFE", "public_safe_only": True}
    resource = {"schema_id": "search-resource/v2", "max_search_calls": 0 if judgment else 2,
                "max_search_turns": 0 if judgment else 2, "max_results_per_call": 0 if judgment else 2,
                "max_follow_links": 0 if judgment else 1, "automatic_retries": 0,
                "retry_policy": fixture_ref("no-auto-retries"), "manual_retry_policy": "NEW_BUDGETED_EVENT",
                "timeout_per_call_ms": 1000, "max_total_runtime_ms": measure(5000, "ms"),
                "token_ceiling": measure(100, "tokens"), "money_ceiling": measure(1, "USD"),
                "resource_unit_definition": "synthetic counter, not a real search credit",
                "search_unit": "NONE" if judgment else "RAW_BACKEND_ATTEMPT" if mode == "F1" else "INTEGRATED_STACK_INVOCATION",
                "failure_policy": "INFRASTRUCTURE_NOT_QUALITY", "exhaustion_policy": "STOP_NO_EXPANSION",
                "budget_rejection_policy": "NO_BACKEND_NO_TICKET"}
    retriever = None
    if not judgment:
        retriever = {"identity": fixture_ref("retriever"), "backend_id": "synthetic-not-connected",
                     "class": "RAW_RETRIEVER" if mode == "F1" else "INTEGRATED_SEARCH_STACK",
                     "config_fingerprint": fingerprint({"synthetic_config": 1}),
                     "request_schema": fixture_ref("request"), "result_schema": fixture_ref("result"),
                     "capabilities": ["RETRIEVAL"] if mode == "F1" else ["RETRIEVAL", "DECOMPOSITION"],
                     "qualification": None}
        if mode == "F1":
            retriever["qualification"] = {"backend_fingerprint": fingerprint({k: v for k, v in retriever.items() if k != "qualification"}),
                "criteria": {f"R{i}": {"status": "PASS", "evidence": [fixture_ref(f"r{i}-synthetic-proof")]} for i in range(1, 9)}}
    overlay = {"kind": "JUDGMENT", "candidate_set": fixture_ref("candidates"),
               "evidence_packet": fixture_ref("evidence"), "rubric": fixture_ref("rubric"),
               "output_schema": fixture_ref("judge-output"), "adjudication_policy": fixture_ref("adjudication"),
               "blind_transform": fixture_ref("blind-transform"), "order_policy": fixture_ref("ordering"),
               "aggregation_policy": fixture_ref("aggregation"), "allowed_tools": [], "independent_first_pass": True}
    if track == "E1_LIVE":
        overlay = {"kind": "LIVE", "window_policy": fixture_ref("window"), "backend": retriever["identity"],
                   "drift_policy": fixture_ref("drift"), "pooled_candidate_policy": fixture_ref("pool"),
                   "adjudication_timing": fixture_ref("timing"), "capture_policy": fixture_ref("capture"),
                   "exhaustive_reference": None}
    elif not judgment:
        overlay = {"kind": "FROZEN", "corpus": fixture_ref("corpus"), "collection_provenance": fixture_ref("collection"),
                   "public_safe": True, "index": fixture_ref("index"), "reference_set": fixture_ref("reference"),
                   "reproduction_procedure": fixture_ref("reproduction")}
    doc = {"schema_id": "searchspec/v2", "spec_id": "SYNTHETIC-PROTOCOL-PROBE-" + track,
           "spec_version": "test-1", "spec_status": "FROZEN", "architecture_authority": "SEARCH-CUP/v2.3",
           "created_at": "2026-09-16T00:00:00Z", "frozen_at": "2026-09-16T00:00:00Z",
           "track_id": track, "fairness_mode": mode, "task": task, "scope": scope,
           "a0": {"origin": "HUMAN_MODEL_CO_DESIGN", "scored": False, "frozen": True,
                  "task_fingerprint": fingerprint(task), "scope_fingerprint": fingerprint(scope),
                  "resource_fingerprint": fingerprint(resource), "task_hierarchy": ["synthetic"],
                  "stop_on_signal": ["contract checked"], "economic_success_criteria": []},
           "a1": {"owner": "NONE" if judgment else "ENTRANT" if mode == "F1" else "SEARCH_STACK",
                  "allowed": [] if judgment else ["QUERY_WORDING"] if mode == "F1" else ["DECOMPOSITION"],
                  "forbidden_mutations": ["TASK", "SCOPE", "BUDGET", "EVIDENCE", "UNKNOWN_RULE"]},
           "variable_control": {"principal": PRINCIPAL[track], "fixed": {},
                                "qualified_nuisance": ["synthetic live drift declaration"] if track == "E1_LIVE" else [],
                                "changed_capabilities": [], "fixed_capabilities": {}},
           "retriever": retriever, "resources": resource, "output_contract": fixture_ref("output"),
           "judgment_contract": fixture_ref("judgment"), "overlay": overlay,
           "system_disclosure": None, "economic_package": None,
           "claims": [TRACK_CLAIM[track]], "metrics": [{"metric_id": "synthetic-ratio", "numerator": "synthetic-positive-count",
             "denominator": "synthetic-observed-count", "population": fixture_ref("population"), "exclusion_rule": "typed states separate",
             "missingness": "PRESERVE_TYPED_STATES", "zero_denominator": "NOT_EVALUABLE"}],
           "privacy": {"public_safe_inputs_only": True, "credential_access": False,
                       "private_locator_access": False, "hidden_authority_access": False, "official_prompt_access": False}}
    if mode in ("F2", "F3"):
        doc["system_disclosure"] = {"components": [fixture_ref("system-component")], "capabilities": ["DECOMPOSITION"],
            "tool_classes": ["synthetic"], "retry_fallback_policy": fixture_ref("retry-fallback"),
            "human_intervention_policy": fixture_ref("human-policy"), "money_source": fixture_ref("money"),
            "time_source": fixture_ref("time"), "opaque_quantities": ["internal-stack-call-count"]}
    if mode == "F3":
        doc["economic_package"] = {"basis": "MONEY_AND_TIME", "definition": fixture_ref("real-resources"),
            "accounting_period": "synthetic-fixed-period", "currency": "USD", "billing_basis": "synthetic",
            "price_source": fixture_ref("price"), "tax_policy": "synthetic excluded", "exchange_policy": fixture_ref("exchange"),
            "rounding_policy": "synthetic exact", "free_credit_policy": "reported separately",
            "prepaid_credit_policy": "reported separately", "unused_credit_policy": "reported separately",
            "cost_basis": "BOTH", "time_kinds": ["MACHINE_ELAPSED", "OPERATOR_ACTIVE", "WAITING_QUEUE"]}
    return reseal_spec(doc)


def reseal_spec(doc: dict) -> dict:
    """Fixture authoring helper; not a mutation API for a running experiment."""
    for key in ("task", "scope"):
        doc["a0"][key + "_fingerprint"] = fingerprint(doc[key])
    doc["a0"]["resource_fingerprint"] = a0_resource_binding(doc)
    bindings = control_bindings(doc)
    doc["variable_control"]["fixed"] = {
        key: bindings.get(key, fixture_ref(key)["fingerprint"])
        for key in sorted(REQUIRED_CONTROLS[doc["track_id"]])}
    return seal(doc)


def synthetic_judgment_package() -> tuple[dict, dict]:
    evidence = fixture_ref("evidence-alpha")
    policy = {"id": "synthetic-pool-policy", "version": "1", "normalization": "NFKC_CASEFOLD_WHITESPACE_V1",
              "identity_fields": ["target"], "visible_fields": ["target", "description"],
              "collision_policy": "UNKNOWN_IDENTITY", "ordering": "CANDIDATE_ID_ASC"}
    items = [{"fields": {"target": "Synthetic Alpha", "description": "Public synthetic object"},
              "object_fingerprint": fingerprint({"synthetic_object": "alpha"}), "evidence": [evidence],
              "frozen_submission": fixture_ref("submission-source-a"), "source_alias": "sealed-origin-a"}]
    pool, provenance = pool_candidates(items, policy)
    packet = {"id": "synthetic-evidence", "version": "1", "entries": [{"reference": evidence,
        "excerpt": "Synthetic alpha satisfies the test predicate.", "captured_at": "2026-09-16T00:00:00Z",
        "locator": "urn:synthetic:alpha", "corpus_fingerprint": None}]}
    rubric = {"id": "synthetic-rubric", "version": "1", "dimensions": [{"id": "relevance",
        "allowed_values": ["YES", "NO"], "evidence_threshold": "synthetic explicit predicate",
        "unknown_rule": "INSUFFICIENT_EVIDENCE_NOT_NEGATIVE", "hard_constraint": True, "satisfying_values": ["YES"]}],
        "confidence_allowed": True, "hard_constraints_first": True,
        "aggregation": {"method": "synthetic-escalation", "tie_policy": "PRESERVE_DISAGREEMENT",
                        "unknown_policy": "PRESERVE", "frozen_before_outputs": True}}
    adjudication = {"id": "synthetic-adjudication", "version": "1", "allowed": True,
        "triggers": ["DISAGREEMENT", "CRITICAL_UNKNOWN"], "thresholds": fixture_ref("adjudication-threshold"),
        "evidence_policy": "FROZEN_PACKET_ONLY", "append_only": True}
    kwargs = {"output_schema": fixture_ref("judge-output"),
        "resource_fingerprint": fingerprint(synthetic_spec()["resources"]),
        "source_overlay": {"kind": "SYNTHETIC", "corpus": None, "reference_set": None,
                           "capture_cutoff": None, "adjudication_time": None, "drift_policy": None}}
    core = judgment_contract(pool, packet, rubric, adjudication, **kwargs)
    doc = synthetic_spec()
    doc["judgment_contract"] = {"id": "synthetic-judgment-contract", "version": "1", "fingerprint": fingerprint(core)}
    for key, value in (("candidate_set", pool), ("evidence_packet", packet), ("rubric", rubric),
                       ("adjudication_policy", adjudication), ("blind_transform", pool["policy"]),
                       ("order_policy", core["order_policy"]), ("aggregation_policy", rubric["aggregation"])):
        doc["overlay"][key]["fingerprint"] = fingerprint(value)
    package = judgment_package(pool, packet, rubric, adjudication,
                               spec=SearchSpecV2.from_mapping(reseal_spec(doc)), **kwargs)
    return package, provenance


def build_receipt() -> dict:
    specs = [SearchSpecV2.from_mapping(synthetic_spec(track)) for track in TRACKS]
    package, _ = synthetic_judgment_package()
    ledger = ResourceLedger(specs[3], "SYNTHETIC-NO-EXECUTION")
    resource = ledger.receipt(entrant_fingerprint=fixture_ref("no-entrant-selected")["fingerprint"],
        elapsed_ms=0, operator_ms=measure(0, "ms"), waiting_ms=measure(0, "ms"), outcomes={}, price_evidence=[])
    receipt = seal({"schema_id": "search-protocol-conformance/v2", "work_order": "ENG-B1-SC-V23-T1",
        "baseline": "6229e8d164831b8433c62b7d90820d4b0b4ce225",
        "mode": "SYNTHETIC_PROTOCOL_VALIDATION_ONLY", "protocol_schema_fingerprint": fingerprint(SEARCHSPEC_SCHEMA),
        "track_contracts": [{"track_id": s.as_dict()["track_id"], "spec_fingerprint": s.fingerprint,
                             "gate": instance_gate(s, None)} for s in specs],
        "synthetic_judgment_package_fingerprint": package["canonical_fingerprint"],
        "zero_event_resource_receipt": resource,
        "secret_exclusion": {"scanner": "public-safe-patterns/v1", "status": "PASS"},
        "live_provider_calls": 0, "live_search_calls": 0, "judge_calls": 0, "credit_consumption": 0,
        "official_prompt_consumed": False, "hidden_registry_loaded": False,
        "instance_selected": False, "execution_allowed": False, "review_status": "AWAITING_BOARD_VERIFICATION"})
    assert_content_safe(receipt)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("receipt", "schema"), nargs="?", default="receipt")
    args = parser.parse_args(argv)
    result = SEARCHSPEC_SCHEMA if args.command == "schema" else build_receipt()
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
