"""ENG-B1-SC-V23-T1: deterministic positive, adversarial and no-I/O proofs."""

from __future__ import annotations

import ast
import copy
import dataclasses
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import unittest
from unittest.mock import patch

from search_cup.contracts import canonical_json, fingerprint
from search_cup.protocol_v23 import (
    SearchSpecV2, assert_content_safe, compare_controls, f1_eligibility,
    instance_gate, metric_ratio, seal, validate_output, verify_seal,
)
from search_cup.v23_accounting import ResourceLedger, measure, validate_resource_receipt
from search_cup.v23_judgment import (
    JudgmentJournal, integrity_gate, judge_view, judgment_package, pool_candidates, validate_record,
    validate_package,
)
from search_cup.v23_offline import (
    build_receipt, fixture_ref, main, reseal_spec, synthetic_judgment_package, synthetic_spec,
)
from search_cup.v23_schema import ABLATION_CAPABILITIES, SEARCHSPEC_SCHEMA, TERMINALS, TRACKS

ROOT = Path(__file__).resolve().parents[1]


def spec(track="E1_FROZEN"):
    return SearchSpecV2.from_mapping(synthetic_spec(track))


def event(identity="event-1", *, status="SUCCEEDED", kind="SEARCH", turn=1, retry_kind="NONE", retry_of=None):
    return {"event_id": identity, "kind": kind,
            "unit": {"SEARCH": "RAW_BACKEND_ATTEMPT", "VERIFY": "VERIFICATION", "MODEL": "MODEL_REQUEST"}[kind],
            "status": status, "crossed_boundary": status != "REJECTED", "turn": turn,
            "result_count": 0, "elapsed_ms": 10, "tokens": measure(0, "tokens"), "money": measure(0, "USD"),
            "retry_kind": retry_kind, "retry_of": retry_of,
            "failure_class": {"SUCCEEDED": "NONE", "FAILED": "INFRASTRUCTURE", "REJECTED": "BUDGET"}[status],
            "request_fingerprint": fixture_ref(identity), "result_fingerprints": []}


def receipt(ledger, *, elapsed_ms=20, price_evidence=None):
    return ledger.receipt(entrant_fingerprint=fixture_ref("entrant")["fingerprint"], elapsed_ms=elapsed_ms,
                          operator_ms=measure(0, "ms"), waiting_ms=measure(0, "ms"), outcomes={},
                          price_evidence=price_evidence or [])


def record(package, alias="judge-a", state="ACCEPT"):
    candidate = package["candidate_pool"]["candidates"][0]
    return seal({"record_id": "record-" + alias, "run_id": "synthetic-judgment-records", "candidate_id": candidate["candidate_id"],
        "judge_identity": {"entrant_id": alias, "provider": "synthetic", "requested_model_id": "fixture-model",
                           "resolved_model_id": "fixture-model", "resolution_status": "KNOWN", "identity_status": "AS_REQUESTED",
                           "alias_evidence": None, "endpoint_mode": "NOT_CONNECTED", "config_fingerprint": fixture_ref("judge-config")["fingerprint"]},
        "judge_alias": alias, "package_fingerprint": package["canonical_fingerprint"],
        "rubric_fingerprint": fingerprint(package["rubric"]), "state": state,
        "dimensions": [{"id": "relevance", "value": "UNKNOWN" if state == "UNKNOWN" else "YES"}],
        "confidence": None, "evidence_used": candidate["evidence"], "reason_codes": ["SYNTHETIC"],
        "failure_class": {"ACCEPT": "NONE", "REJECT": "NONE", "UNKNOWN": "INSUFFICIENT_EVIDENCE",
                          "NOT_EVALUABLE": "INFRASTRUCTURE", "ERROR": "INFRASTRUCTURE", "BLOCKED": "POLICY"}[state],
        "committed_at": "2026-09-16T00:00:01Z", "observed_peer_records": []})


def pool_inputs():
    policy = {"id": "synthetic-dedupe", "version": "1", "normalization": "NFKC_CASEFOLD_WHITESPACE_V1",
              "identity_fields": ["target"], "visible_fields": ["target", "description"],
              "collision_policy": "UNKNOWN_IDENTITY", "ordering": "CANDIDATE_ID_ASC"}
    one = {"fields": {"target": "Alpha", "description": "synthetic public object"},
           "object_fingerprint": fingerprint({"object": "alpha"}), "evidence": [fixture_ref("evidence-1")],
           "frozen_submission": fixture_ref("sealed-submission-a"), "source_alias": "private-source-label-a"}
    two = copy.deepcopy(one)
    two["fields"]["target"] = "  ALPHA  "
    two["evidence"] = [fixture_ref("evidence-2")]
    two["source_alias"] = "private-source-label-b"
    two["frozen_submission"] = fixture_ref("sealed-submission-b")
    return [one, two], policy


class SearchSpecTests(unittest.TestCase):
    def test_all_eight_tracks_are_structurally_valid_but_execution_blocked(self):
        for track in TRACKS:
            with self.subTest(track=track):
                model = spec(track)
                gate = instance_gate(model, None)
                self.assertEqual("BLOCKED", gate["terminal_status"])
                self.assertFalse(gate["execution_allowed"])
                self.assertIn("T1_IMPLEMENTATION_ONLY", gate["reason_codes"])

    def test_schema_is_versioned_closed_and_matches_runtime_export(self):
        self.assertEqual("searchspec/v2", SEARCHSPEC_SCHEMA["properties"]["schema_id"]["const"])
        exported = ROOT / "schemas" / "searchspec_v2.schema.json"
        self.assertEqual(SEARCHSPEC_SCHEMA, json.loads(exported.read_text()))

    def test_canonical_fingerprint_ignores_mapping_order_only(self):
        doc = synthetic_spec()
        other = dict(reversed(list(doc.items())))
        self.assertEqual(spec("JUDGMENT_ONLY").fingerprint, SearchSpecV2.from_mapping(other).fingerprint)
        other["task"]["objective"] = "different task"
        self.assertNotEqual(doc["canonical_fingerprint"], seal(other)["canonical_fingerprint"])
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            SearchSpecV2.from_mapping(other)

    def test_nested_mutation_cannot_change_frozen_object(self):
        model = spec()
        exported = model.as_dict()
        exported["resources"]["max_search_calls"] = 999
        self.assertEqual(2, model.as_dict()["resources"]["max_search_calls"])
        with self.assertRaises(dataclasses.FrozenInstanceError):
            model.canonical_content = "{}"

    def test_direct_constructor_also_validates(self):
        with self.assertRaises(ValueError):
            SearchSpecV2("{}")
        with self.assertRaises(ValueError):
            SearchSpecV2(" " + canonical_json(synthetic_spec()))

    def test_missing_mandatory_fields_all_rejected(self):
        for key in SEARCHSPEC_SCHEMA["required"]:
            doc = synthetic_spec()
            del doc[key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                SearchSpecV2.from_mapping(doc)

    def test_invalid_json_and_bool_as_integer_rejected(self):
        for value in (True, -1, 1.1, float("nan"), float("inf"), "2"):
            doc = synthetic_spec("E1_FROZEN")
            doc["resources"]["max_search_calls"] = value
            with self.subTest(value=str(value)), self.assertRaises(ValueError):
                SearchSpecV2.from_mapping(reseal_spec(doc))
        for value in ({1: "bad"}, {"bad": {1, 2}}, {"bad": (1, 2)}):
            with self.assertRaises(ValueError):
                seal(value)

    def test_unknown_fields_and_legacy_competition_are_not_v2_authority(self):
        doc = synthetic_spec()
        doc["official_match_authorized"] = True
        with self.assertRaises(ValueError):
            SearchSpecV2.from_mapping(seal(doc))
        old = json.loads((ROOT / "competitions/search-cup-02.offline.json").read_text())
        with self.assertRaises(ValueError):
            SearchSpecV2.from_mapping(seal(old))

    def test_one_run_one_track_no_array_alias_or_unknown(self):
        for value in (list(TRACKS[:2]), "E1", "JUDGMENT_AND_VERIFICATION", ""):
            doc = synthetic_spec()
            doc["track_id"] = value
            with self.subTest(value=value), self.assertRaises(ValueError):
                SearchSpecV2.from_mapping(seal(doc))

    def test_frozen_time_and_cardinality_are_validated(self):
        for field, value in (("frozen_at", None), ("created_at", "undated"), ("frozen_at", "2026-01-01T00:00:00")):
            doc = synthetic_spec()
            doc[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                SearchSpecV2.from_mapping(seal(doc))
        doc = synthetic_spec()
        doc["task"]["output_cardinality"]["minimum"] = 3
        with self.assertRaises(ValueError):
            SearchSpecV2.from_mapping(reseal_spec(doc))

    def test_version_and_run_identity_must_both_change(self):
        old = spec()
        doc = old.as_dict()
        doc["task"]["objective"] = "new synthetic objective"
        new = SearchSpecV2.from_mapping(reseal_spec(doc))
        with self.assertRaises(ValueError):
            old.require_successor(new, "run-a", "run-b")
        doc["spec_version"] = "test-2"
        new = SearchSpecV2.from_mapping(reseal_spec(doc))
        with self.assertRaises(ValueError):
            old.require_successor(new, "run-a", "run-a")
        old.require_successor(new, "run-a", "run-b")

    def test_a0_scope_and_resource_bindings_cannot_be_stale(self):
        for key in ("task_fingerprint", "scope_fingerprint", "resource_fingerprint"):
            doc = synthetic_spec()
            doc["a0"][key] = "0" * 64
            with self.subTest(key=key), self.assertRaises(ValueError):
                SearchSpecV2.from_mapping(seal(doc))

    def test_a0_never_scored_and_a1_no_hidden_planning(self):
        doc = synthetic_spec("E1_FROZEN")
        doc["a0"]["scored"] = True
        with self.assertRaises(ValueError):
            SearchSpecV2.from_mapping(reseal_spec(doc))
        for owner, allowed in (("SEARCH_STACK", ["QUERY_WORDING"]), ("ENTRANT", ["DECOMPOSITION"]), ("NONE", [])):
            doc = synthetic_spec("E1_FROZEN")
            doc["a1"].update(owner=owner, allowed=allowed)
            with self.subTest(owner=owner), self.assertRaises(ValueError):
                SearchSpecV2.from_mapping(reseal_spec(doc))

    def test_neutrality_every_r_requires_pass_and_evidence(self):
        for i in range(1, 9):
            for state in ("FAIL", "UNKNOWN", "PASS_WITHOUT_EVIDENCE"):
                doc = synthetic_spec("E1_FROZEN")
                criterion = doc["retriever"]["qualification"]["criteria"][f"R{i}"]
                criterion.update(status=state if state != "PASS_WITHOUT_EVIDENCE" else "PASS",
                                 evidence=[] if state == "PASS_WITHOUT_EVIDENCE" else criterion["evidence"])
                with self.subTest(i=i, state=state), self.assertRaises(ValueError):
                    SearchSpecV2.from_mapping(reseal_spec(doc))

    def test_search_pro_not_neutral_by_name_or_history(self):
        doc = synthetic_spec("E1_FROZEN")
        doc["retriever"]["backend_id"] = "zhipu-web-search/search_pro"
        doc["retriever"]["qualification"] = None
        self.assertEqual("NOT_F1_ELIGIBLE_BY_DEFAULT", f1_eligibility(doc["retriever"]))
        with self.assertRaises(ValueError):
            SearchSpecV2.from_mapping(reseal_spec(doc))

    def test_stale_qualification_and_hidden_capability_fail(self):
        for key, value in (("config_fingerprint", "0" * 64), ("capabilities", ["RETRIEVAL", "SYNTHESIS"]), ("class", "INTEGRATED_SEARCH_STACK")):
            doc = synthetic_spec("E1_FROZEN")
            doc["retriever"][key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                SearchSpecV2.from_mapping(reseal_spec(doc))

    def test_judgment_forbids_search_turn_results_followlinks_and_tools(self):
        for key in ("max_search_calls", "max_search_turns", "max_results_per_call", "max_follow_links"):
            doc = synthetic_spec()
            doc["resources"][key] = 1
            with self.subTest(key=key), self.assertRaises(ValueError):
                SearchSpecV2.from_mapping(reseal_spec(doc))
        doc = synthetic_spec()
        doc["overlay"]["allowed_tools"] = ["search"]
        with self.assertRaises(ValueError):
            SearchSpecV2.from_mapping(reseal_spec(doc))

    def test_live_frozen_overlays_and_absolute_recall_not_interchangeable(self):
        doc = synthetic_spec("E1_LIVE")
        doc["overlay"] = synthetic_spec("E1_FROZEN")["overlay"]
        with self.assertRaises(ValueError):
            SearchSpecV2.from_mapping(reseal_spec(doc))
        doc = synthetic_spec("E1_LIVE")
        doc["claims"].append("ABSOLUTE_RECALL")
        with self.assertRaises(ValueError):
            SearchSpecV2.from_mapping(reseal_spec(doc))
        doc["overlay"]["exhaustive_reference"] = fixture_ref("exhaustive-reference")
        SearchSpecV2.from_mapping(reseal_spec(doc))

    def test_no_e2_model_attribution_or_universal_champion(self):
        for claim in ("EXECUTION_ON_FROZEN_ENVIRONMENT", "UNIVERSAL_CHAMPION", "OBSERVED_ECONOMIC_EFFICIENCY"):
            doc = synthetic_spec("E2_RETRIEVER")
            doc["claims"] = [claim]
            with self.subTest(claim=claim), self.assertRaises(ValueError):
                SearchSpecV2.from_mapping(reseal_spec(doc))

    def test_f1_f2_f3_mapping_cannot_be_relabelled(self):
        for track, mode in (("E1_FROZEN", "F2"), ("GLM_SEARCH_STACK", "F1"), ("ECONOMIC_TRACK", "F1")):
            doc = synthetic_spec(track)
            doc["fairness_mode"] = mode
            with self.subTest(track=track), self.assertRaises(ValueError):
                SearchSpecV2.from_mapping(reseal_spec(doc))

    def test_f2_native_stack_and_internal_call_counts_can_differ(self):
        first = spec("SYSTEM_PLAYOFF")
        second = first.as_dict()
        second["resources"]["max_search_calls"] = 12
        second["resources"]["money_ceiling"] = measure(3, "USD")
        second["system_disclosure"]["components"] = [fixture_ref("different-system")]
        second["retriever"]["identity"] = fixture_ref("different-stack")
        compare_controls([first, SearchSpecV2.from_mapping(reseal_spec(second))])

    def test_ablation_exactly_one_capability(self):
        doc = synthetic_spec("E2_RETRIEVER")
        doc["fairness_mode"] = "ABLATION"
        doc["variable_control"].update(principal="ONE_CAPABILITY", changed_capabilities=["RANKING"])
        doc["variable_control"]["fixed_capabilities"] = {key: fixture_ref(key)["fingerprint"] for key in ABLATION_CAPABILITIES if key != "RANKING"}
        doc["claims"].append("SINGLE_CAPABILITY_EFFECT")
        SearchSpecV2.from_mapping(reseal_spec(doc))
        for changes in ([], ["RANKING", "SYNTHESIS"]):
            doc["variable_control"]["changed_capabilities"] = changes
            with self.assertRaises(ValueError):
                SearchSpecV2.from_mapping(reseal_spec(doc))

    def test_fixed_model_control_and_f1_equality_required(self):
        doc = synthetic_spec("E2_RETRIEVER")
        del doc["variable_control"]["fixed"]["control_model"]
        with self.assertRaises(ValueError):
            SearchSpecV2.from_mapping(seal(doc))
        first = spec()
        compare_controls([first, first])
        changed = first.as_dict()
        changed["resources"]["max_search_calls"] = 3
        with self.assertRaises(ValueError):
            compare_controls([first, SearchSpecV2.from_mapping(reseal_spec(changed))])
        with self.assertRaises(ValueError):
            compare_controls([first, spec("E1_LIVE")])

    def test_f3_price_time_normalization_is_required(self):
        for key in synthetic_spec("ECONOMIC_TRACK")["economic_package"]:
            doc = synthetic_spec("ECONOMIC_TRACK")
            del doc["economic_package"][key]
            with self.subTest(key=key), self.assertRaises(ValueError):
                SearchSpecV2.from_mapping(reseal_spec(doc))

    def test_claim_population_scope_changes_identity(self):
        before = spec()
        doc = before.as_dict()
        doc["scope"]["language_pool"].append("es")
        after = SearchSpecV2.from_mapping(reseal_spec(doc))
        self.assertNotEqual(before.fingerprint, after.fingerprint)
        with self.assertRaises(ValueError):
            compare_controls([before, after])


class InstanceAndEvidenceTests(unittest.TestCase):
    def test_fully_materialized_synthetic_instance_still_cannot_execute(self):
        package, _ = synthetic_judgment_package()
        model = SearchSpecV2.from_mapping(package["searchspec"])
        doc = model.as_dict()
        roster = [{"entrant_id": "synthetic-judge", "provider": "synthetic", "requested_model_id": "fixture",
                   "resolved_model_id": None, "resolution_status": "UNKNOWN", "endpoint_mode": "NOT_CONNECTED",
                   "identity_status": "UNRESOLVED", "alias_evidence": None,
                   "config_fingerprint": fixture_ref("judge-config")["fingerprint"]}]
        payloads = {"D1": {"binding": doc["track_id"]}, "D2": {"binding": model.fingerprint, "searchspec": doc},
                    "D3": {"judgment_package": package}, "D5": {"roster": roster},
                    "D7": {"binding": fingerprint(doc["resources"]), "resources": doc["resources"]}}
        artifacts, decisions = {}, {}
        for index in range(1, 9):
            name = f"D{index}"
            if name in payloads:
                artifact = {"schema_id": f"search-instance/{name.lower()}/v2", "spec_fingerprint": model.fingerprint, **payloads[name]}
                digest = fingerprint(artifact)
                artifacts[digest] = artifact
                decisions[name] = {"status": "FROZEN", "artifact": {"id": "synthetic-" + name, "version": "1", "fingerprint": digest},
                                   "approval": fixture_ref("synthetic-untrusted-approval"), "reason": "synthetic structural input only"}
            else:
                decisions[name] = {"status": "NOT_APPLICABLE", "artifact": None, "approval": None, "reason": "not needed for synthetic track"}
        bindings = seal({"schema_id": "search-instance-bindings/v2", "spec_fingerprint": model.fingerprint, "decisions": decisions})
        result = instance_gate(model, bindings, artifacts)
        self.assertEqual([], result["missing_decisions"])
        self.assertEqual(["T1_IMPLEMENTATION_ONLY"], result["reason_codes"])
        self.assertFalse(result["execution_allowed"])
        # Re-hashing a wrong resource body cannot satisfy D7.
        bad = {"schema_id": "search-instance/d7/v2", "spec_fingerprint": model.fingerprint,
               "binding": fingerprint(doc["resources"]), "resources": {**doc["resources"], "max_search_calls": 999}}
        digest = fingerprint(bad)
        artifacts[digest] = bad
        bindings["decisions"]["D7"]["artifact"]["fingerprint"] = digest
        with self.assertRaises(ValueError):
            instance_gate(model, seal(bindings), artifacts)

    def test_track_specific_missing_decisions(self):
        cases = {"JUDGMENT_ONLY": {"D1", "D2", "D3", "D5", "D7"},
                 "E1_FROZEN": {"D1", "D2", "D4", "D5", "D6", "D7"},
                 "E1_LIVE": {"D1", "D2", "D5", "D6", "D7"},
                 "ECONOMIC_TRACK": {"D1", "D2", "D4", "D5", "D7", "D8"}}
        for track, expected in cases.items():
            self.assertEqual(expected, set(instance_gate(spec(track), None)["missing_decisions"]))

    def test_unverified_frozen_labels_do_not_resolve_artifacts_or_unlock(self):
        model = spec("JUDGMENT_ONLY")
        package = seal({"schema_id": "search-instance-bindings/v2", "spec_fingerprint": model.fingerprint,
            "decisions": {f"D{i}": {"status": "FROZEN", "artifact": fixture_ref(f"d{i}"),
                "approval": fixture_ref("unverified-approval"), "reason": "synthetic unverified assertion"} for i in range(1, 9)}})
        gate = instance_gate(model, package)
        self.assertFalse(gate["execution_allowed"])
        self.assertTrue(gate["missing_decisions"])

    def test_instance_mismatch_and_extra_authorize_boolean_rejected(self):
        model = spec()
        package = seal({"schema_id": "search-instance-bindings/v2", "spec_fingerprint": "0" * 64,
            "decisions": {f"D{i}": {"status": "DEFERRED", "artifact": None, "approval": None, "reason": "not frozen"} for i in range(1, 9)}})
        with self.assertRaises(ValueError):
            instance_gate(model, package)
        package["spec_fingerprint"] = model.fingerprint
        package["execution_authorized"] = True
        with self.assertRaises(ValueError):
            instance_gate(model, seal(package))

    def test_metric_unknown_not_negative_and_zero_not_zero_percent(self):
        definition = synthetic_spec()["metrics"][0]
        self.assertEqual("UNKNOWN", metric_ratio(measure(None, "items"), measure(5, "items"), definition)["terminal_status"])
        empty = metric_ratio(measure(0, "items"), measure(0, "items"), definition)
        self.assertEqual("NOT_EVALUABLE", empty["terminal_status"])
        self.assertIsNone(empty["value"])
        self.assertEqual(0.5, metric_ratio(measure(1, "items"), measure(2, "items"), definition)["value"])
        for terminal in TERMINALS:
            self.assertIn(terminal, ("PASS", "FAIL", "UNKNOWN", "BLOCKED", "NOT_EVALUABLE", "ERROR"))

    def test_content_safe_scan_rejects_keys_values_encoding_without_echo(self):
        samples = [{"apiKey": "synthetic"}, {"nested": {"health": "synthetic"}},
                   {"x": "https://" + "docs.google.com/document/d/private"},
                   {"x": "https%3A%2F%2Fdrive.google.com%2Fprivate"},
                   {"x": "sk-" + "X" * 24}, {"x": "Bearer " + "X" * 16},
                   {"x": "-----BEGIN " + "PRIVATE KEY-----"}]
        for sample in samples:
            with self.subTest(sample=list(sample)), self.assertRaises(ValueError) as failure:
                assert_content_safe(sample)
            self.assertNotIn("private", str(failure.exception).split(" ")[-1] if "locator" not in str(failure.exception) else "")

    def test_measure_known_unknown_and_not_applicable_are_not_interchangeable(self):
        with self.assertRaises(ValueError):
            measure(0, "tokens", state="UNKNOWN")
        with self.assertRaises(ValueError):
            measure(None, "tokens", state="KNOWN")
        doc = synthetic_spec()
        doc["resources"]["token_ceiling"] = measure(10, "USD")
        with self.assertRaises(ValueError):
            SearchSpecV2.from_mapping(reseal_spec(doc))

    def test_output_seal_and_resource_binding_typed_failure(self):
        model = spec()
        resources = receipt(ResourceLedger(model, "run-output"))
        doc = model.as_dict()
        output = seal({"schema_id": "search-output/v2", "run_id": "run-output", "spec_id": doc["spec_id"],
            "spec_version": doc["spec_version"], "spec_fingerprint": model.fingerprint,
            "architecture_authority": "SEARCH-CUP/v2.3", "track_id": doc["track_id"], "fairness_mode": "F1",
            "entrant": {"entrant_id": "synthetic-entrant", "provider": "synthetic", "requested_model_id": "synthetic-requested",
                        "resolved_model_id": None, "resolution_status": "UNKNOWN", "endpoint_mode": "NOT_CONNECTED",
                        "identity_status": "UNRESOLVED", "alias_evidence": None,
                        "config_fingerprint": fixture_ref("config")["fingerprint"]},
            "environment": fixture_ref("environment"), "retriever_fingerprint": fingerprint(doc["retriever"]),
            "resource_receipt_fingerprint": resources["canonical_fingerprint"], "query_call_provenance": [],
            "result_provenance": [], "submission_fingerprint": fixture_ref("submission")["fingerprint"],
            "terminal_status": "NOT_EVALUABLE", "failure_class": "INFRASTRUCTURE", "confidence": None,
            "unknown_reasons": [], "quality_score": None, "secret_exclusion": {"scanner": "public-safe-patterns/v1", "status": "PASS"},
            "official_prompt_consumed": False, "hidden_registry_loaded": False, "judge_invoked": False})
        resources["entrant_fingerprint"] = fingerprint(output["entrant"])
        resources = seal(resources)
        output["resource_receipt_fingerprint"] = resources["canonical_fingerprint"]
        output = seal(output)
        validate_output(output, model, resources)
        for key, value in (("terminal_status", "FAIL"), ("quality_score", 0), ("judge_invoked", True), ("spec_version", "other")):
            changed = copy.deepcopy(output)
            changed[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_output(seal(changed), model, resources)


class AccountingTests(unittest.TestCase):
    def test_rehashed_receipt_cannot_hide_attempt_failure_or_budget_overrun(self):
        model = spec()
        original = receipt(ResourceLedger(model, "run-failed").append(event(status="FAILED")))
        validate_resource_receipt(original, model)
        for key, value in (("search_attempted", 0), ("terminal_status", "PASS"), ("search_failed", 0),
                           ("resource_contract_fingerprint", "0" * 64)):
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_resource_receipt(seal({**original, key: value}), model)

    def test_failed_backend_attempt_spends_exactly_one_ticket_and_not_quality(self):
        ledger = ResourceLedger(spec(), "run-accounting").append(event(status="FAILED"))
        result = receipt(ledger)
        self.assertEqual(1, result["search_attempted"])
        self.assertEqual(1, result["search_remaining"])
        self.assertEqual(1, result["search_failed"])
        self.assertEqual("NOT_EVALUABLE", result["terminal_status"])
        self.assertIsNone(result["quality_score"])

    def test_pre_boundary_rejection_spends_no_ticket(self):
        ledger = ResourceLedger(spec(), "run-accounting")
        ledger = ledger.append(event()).append(event("event-2", turn=2))
        ledger = ledger.append(event("event-3", status="REJECTED", turn=3))
        result = receipt(ledger)
        self.assertEqual(2, result["search_attempted"])
        self.assertEqual(0, result["search_remaining"])
        self.assertEqual("BLOCKED", result["terminal_status"])
        self.assertEqual(3, len(result["events"]))

    def test_actual_overrun_is_retained_not_silently_dropped(self):
        ledger = ResourceLedger(spec(), "run-accounting")
        for i in range(3):
            ledger = ledger.append(event(f"event-{i}", turn=i + 1))
        result = receipt(ledger)
        self.assertEqual(3, result["search_attempted"])
        self.assertIn("SEARCH_CALLS_EXCEEDED", result["reason_codes"])
        self.assertIn("SEARCH_TURNS_EXCEEDED", result["reason_codes"])

    def test_append_is_immutable_and_duplicate_event_rejected(self):
        ledger = ResourceLedger(spec(), "run-accounting")
        next_ledger = ledger.append(event())
        self.assertEqual([], ledger.events)
        self.assertEqual(1, len(next_ledger.events))
        with self.assertRaises(ValueError):
            next_ledger.append(event())
        with self.assertRaises(dataclasses.FrozenInstanceError):
            next_ledger.events_json = "[]"

    def test_manual_retry_new_event_and_default_auto_retry_forbidden(self):
        ledger = ResourceLedger(spec(), "run-accounting").append(event(status="FAILED"))
        manual = ledger.append(event("retry-manual", turn=2, retry_kind="MANUAL", retry_of="event-1"))
        self.assertEqual(2, receipt(manual)["search_attempted"])
        self.assertEqual(1, receipt(manual)["manual_retries"])
        with self.assertRaises(ValueError):
            ledger.append(event("retry-auto", turn=2, retry_kind="AUTOMATIC", retry_of="event-1"))

    def test_explicit_auto_retry_policy_chain_cannot_reset_budget(self):
        doc = synthetic_spec("E1_FROZEN")
        doc["resources"]["automatic_retries"] = 1
        ledger = ResourceLedger(SearchSpecV2.from_mapping(reseal_spec(doc)), "run-retry")
        ledger = ledger.append(event(status="FAILED"))
        ledger = ledger.append(event("retry", status="FAILED", turn=2, retry_kind="AUTOMATIC", retry_of="event-1"))
        with self.assertRaises(ValueError):
            ledger.append(event("retry-again", turn=3, retry_kind="AUTOMATIC", retry_of="retry"))

    def test_unknown_spend_not_zero_and_paid_failure_preserved(self):
        failed = event(status="FAILED")
        failed["money"] = measure(0.25, "USD")
        ledger = ResourceLedger(spec(), "run-cost").append(failed)
        result = receipt(ledger)
        self.assertEqual(0.25, result["money"]["value"])
        self.assertEqual(["event-1"], result["paid_failed_attempts"])
        unknown = event("unknown", turn=2)
        unknown["money"] = measure(None, "USD")
        result = receipt(ledger.append(unknown))
        self.assertEqual("UNKNOWN", result["money"]["state"])
        self.assertIsNone(result["money"]["value"])
        self.assertIn("MONEY_COMPLIANCE_UNKNOWN", result["reason_codes"])

    def test_turns_results_verification_timeout_token_money_runtime_caps(self):
        tests = [("results", "RESULT_LIMIT_EXCEEDED"), ("follow", "FOLLOW_LINKS_EXCEEDED"),
                 ("timeout", "CALL_TIMEOUT_EXCEEDED"), ("tokens", "TOKENS_EXCEEDED"),
                 ("money", "MONEY_EXCEEDED"), ("runtime", "RUNTIME_EXCEEDED")]
        for name, reason in tests:
            ledger = ResourceLedger(spec(), "run-caps")
            e = event()
            if name == "results":
                e["result_count"] = 3
                e["result_fingerprints"] = [fixture_ref(f"result-{i}") for i in range(3)]
            elif name == "timeout":
                e["elapsed_ms"] = 1001
            elif name == "tokens":
                e["tokens"] = measure(101, "tokens")
            elif name == "money":
                e["money"] = measure(1.1, "USD")
            ledger = ledger.append(e)
            if name == "follow":
                ledger = ledger.append(event("verify-1", kind="VERIFY", turn=0)).append(event("verify-2", kind="VERIFY", turn=0))
            result = receipt(ledger, elapsed_ms=6000 if name == "runtime" else 1001 if name == "timeout" else 20)
            with self.subTest(name=name):
                self.assertIn(reason, result["reason_codes"])

    def test_cannot_disguise_units_or_search_as_model_request(self):
        e = event()
        e["unit"] = "INTEGRATED_STACK_INVOCATION"
        with self.assertRaises(ValueError):
            ResourceLedger(spec(), "run-units").append(e)
        for kind in ("SEARCH", "VERIFY"):
            with self.assertRaises(ValueError):
                ResourceLedger(spec("JUDGMENT_ONLY"), "run-zero").append(event(kind=kind, turn=0 if kind == "VERIFY" else 1))

    def test_f3_observed_cost_requires_price_source(self):
        e = event()
        e["unit"] = "INTEGRATED_STACK_INVOCATION"
        ledger = ResourceLedger(spec("ECONOMIC_TRACK"), "run-economic").append(e)
        self.assertIn("PRICE_EVIDENCE_MISSING", receipt(ledger)["reason_codes"])
        self.assertNotIn("PRICE_EVIDENCE_MISSING", receipt(ledger, price_evidence=[fixture_ref("price-source")])["reason_codes"])


class JudgmentTests(unittest.TestCase):
    def test_resealed_package_cannot_add_tools_provenance_or_mutate_rubric(self):
        package, _ = synthetic_judgment_package()
        validate_package(package)
        for key, value in (("allowed_tools", ["search"]), ("provider", "source-model"),
                           ("order_policy", "PROVIDER_ORDER"), ("independent_first_pass", False)):
            changed = seal({**package, key: value})
            with self.subTest(key=key), self.assertRaises(ValueError):
                judge_view(changed)
        changed = copy.deepcopy(package)
        changed["rubric"]["dimensions"][0]["evidence_threshold"] = "different"
        with self.assertRaises(ValueError):
            judge_view(seal(changed))

    def test_pool_deterministic_dedupe_preserves_all_evidence_and_sealed_lineage(self):
        items, policy = pool_inputs()
        pool, hidden = pool_candidates(items, policy)
        self.assertEqual((pool, hidden), pool_candidates(list(reversed(items)), policy))
        self.assertEqual(1, len(pool["candidates"]))
        self.assertEqual(2, len(pool["candidates"][0]["evidence"]))
        self.assertEqual(2, len(hidden["entries"][0]["sources"]))
        self.assertNotIn(items[0]["source_alias"], canonical_json(pool))
        self.assertNotIn("sealed-submission", canonical_json(pool))

    def test_candidate_identity_independent_of_source_and_order(self):
        items, policy = pool_inputs()
        a, _ = pool_candidates(items[:1], policy)
        items[0]["source_alias"] = "another-sealed-origin"
        items[0]["frozen_submission"] = fixture_ref("other-sealed-submission")
        b, _ = pool_candidates(items[:1], policy)
        self.assertEqual(a, b)

    def test_ambiguous_identity_not_automatically_merged(self):
        items, policy = pool_inputs()
        items[1]["object_fingerprint"] = "0" * 64
        pool, _ = pool_candidates(items, policy)
        self.assertEqual([], pool["candidates"])
        self.assertEqual("UNKNOWN_IDENTITY", pool["collisions"][0]["terminal_status"])

    def test_same_object_hash_different_material_fields_still_collision(self):
        items, policy = pool_inputs()
        items[1]["fields"]["description"] = "different object facts"
        pool, _ = pool_candidates(items, policy)
        self.assertEqual([], pool["candidates"])

    def test_blind_allowlist_rejects_metadata_and_embedded_source_signal(self):
        items, policy = pool_inputs()
        items[0]["fields"]["provider"] = "source"
        with self.assertRaises(ValueError):
            pool_candidates(items, policy)
        items, policy = pool_inputs()
        items[0]["fields"]["description"] = items[0]["source_alias"]
        with self.assertRaises(ValueError):
            pool_candidates(items[:1], policy)

    def test_all_judge_views_identical_and_have_no_tools_or_ledger(self):
        package, ledger = synthetic_judgment_package()
        self.assertEqual(judge_view(package), judge_view(copy.deepcopy(package)))
        self.assertEqual([], package["allowed_tools"])
        self.assertNotIn("sealed-origin-a", judge_view(package).decode())
        self.assertNotIn("sources", package)
        self.assertTrue(ledger["entries"])

    def test_record_all_typed_states_preserved_no_quality_imputation(self):
        package, _ = synthetic_judgment_package()
        for state in ("ACCEPT", "REJECT", "UNKNOWN", "NOT_EVALUABLE", "ERROR", "BLOCKED"):
            with self.subTest(state=state):
                validate_record(record(package, state=state), package)

    def test_unknown_hard_constraint_cannot_be_forced_to_reject(self):
        package, _ = synthetic_judgment_package()
        result = record(package, state="UNKNOWN")
        result.update(state="REJECT", failure_class="NONE")
        with self.assertRaises(ValueError):
            validate_record(seal(result), package)

    def test_hard_constraint_failure_cannot_be_soft_accepted(self):
        package, _ = synthetic_judgment_package()
        result = record(package)
        result["dimensions"][0]["value"] = "NO"
        with self.assertRaises(ValueError):
            validate_record(seal(result), package)

    def test_foreign_candidate_evidence_rubric_and_peer_output_rejected(self):
        package, _ = synthetic_judgment_package()
        for key, value in (("candidate_id", "not-in-pool"), ("evidence_used", [fixture_ref("new-live-evidence")]),
                           ("rubric_fingerprint", "0" * 64), ("observed_peer_records", ["peer"])):
            result = record(package)
            result[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_record(seal(result), package)

    def test_no_first_pass_overwrite_or_out_of_roster_judge(self):
        package, _ = synthetic_judgment_package()
        journal = JudgmentJournal(canonical_json(package), ("judge-a", "judge-b"))
        journal = journal.append({"kind": "FIRST_PASS", "record": record(package)})
        with self.assertRaises(ValueError):
            journal.append({"kind": "FIRST_PASS", "record": record(package, state="REJECT")})
        with self.assertRaises(ValueError):
            journal.append({"kind": "FIRST_PASS", "record": record(package, "outsider")})

    def test_human_override_appends_and_keeps_all_machine_records(self):
        package, _ = synthetic_judgment_package()
        journal = JudgmentJournal(canonical_json(package), ("judge-a", "judge-b"))
        a, b = record(package), record(package, "judge-b", "REJECT")
        journal = journal.append({"kind": "FIRST_PASS", "record": a})
        override = {"kind": "HUMAN_OVERRIDE", "candidate_id": a["candidate_id"],
            "prior_machine_fingerprints": [a["canonical_fingerprint"], b["canonical_fingerprint"]],
            "adjudicator_alias": "synthetic-human", "decision": "UNKNOWN", "trigger": "DISAGREEMENT",
            "reason_code": "SYNTHETIC_DISAGREEMENT", "evidence_used": a["evidence_used"],
            "timestamp": "2026-09-16T00:00:02Z", "previous_journal_fingerprint": fingerprint(json.loads(journal.entries_json))}
        with self.assertRaises(ValueError):
            journal.append(seal(override))
        journal = journal.append({"kind": "FIRST_PASS", "record": b})
        override["previous_journal_fingerprint"] = fingerprint(json.loads(journal.entries_json))
        next_journal = journal.append(seal(override))
        self.assertEqual(2, len(json.loads(journal.entries_json)))
        self.assertEqual([a, b], [e["record"] for e in json.loads(next_journal.entries_json)[:2]])
        for key, value in (("evidence_used", [fixture_ref("new-evidence")]), ("trigger", "RUBRIC_EDGE"),
                           ("prior_machine_fingerprints", [a["canonical_fingerprint"]]), ("previous_journal_fingerprint", "0" * 64)):
            changed = {**override, key: value}
            with self.subTest(key=key), self.assertRaises(ValueError):
                journal.append(seal(changed))

    def test_j1_j10_all_of_integrity_including_unknown_and_missing_evidence(self):
        checks = {f"J{i}": {"status": "PASS", "evidence": [fixture_ref(f"j{i}")]} for i in range(1, 11)}
        self.assertEqual("PASS", integrity_gate(checks))
        for key in checks:
            for state in ("FAIL", "UNKNOWN"):
                changed = copy.deepcopy(checks)
                changed[key]["status"] = state
                self.assertEqual("NOT_EVALUABLE", integrity_gate(changed))
            changed = copy.deepcopy(checks)
            changed[key]["evidence"] = []
            self.assertEqual("NOT_EVALUABLE", integrity_gate(changed))

    def test_package_evidence_and_overlay_boundaries(self):
        package, _ = synthetic_judgment_package()
        packet = copy.deepcopy(package["evidence_packet"])
        packet["entries"] = []
        with self.assertRaises(ValueError):
            judgment_package(package["candidate_pool"], packet, package["rubric"], package["adjudication"],
                output_schema=package["output_schema"], resource_fingerprint=package["resource_fingerprint"],
                source_overlay=package["source_overlay"], spec=SearchSpecV2.from_mapping(package["searchspec"]))
        overlay = {"kind": "FROZEN", "corpus": fixture_ref("corpus"), "reference_set": fixture_ref("reference"),
                   "capture_cutoff": None, "adjudication_time": None, "drift_policy": None}
        with self.assertRaises(ValueError):
            judgment_package(package["candidate_pool"], package["evidence_packet"], package["rubric"], package["adjudication"],
                output_schema=package["output_schema"], resource_fingerprint=package["resource_fingerprint"],
                source_overlay=overlay, spec=SearchSpecV2.from_mapping(package["searchspec"]))


class OfflineBoundaryTests(unittest.TestCase):
    def test_published_schema_and_receipt_exclude_secrets_private_locators(self):
        for path in (ROOT / "schemas/searchspec_v2.schema.json", ROOT / "results/search-cup/v23-protocol-offline.json"):
            assert_content_safe(json.loads(path.read_text()))

    def test_receipt_reproducible_and_no_network_credential_or_legacy_execution(self):
        with patch("socket.create_connection", side_effect=AssertionError("network forbidden")), \
             patch("socket.socket.connect", side_effect=AssertionError("network forbidden")), \
             patch("os.getenv", side_effect=AssertionError("credential lookup forbidden")), \
             patch("search_cup.runner.run_match", side_effect=AssertionError("legacy execution forbidden")), \
             patch("search_cup.judge.judge_match", side_effect=AssertionError("judge forbidden")), \
             patch("search_cup.search_pro.run_live_smoke", side_effect=AssertionError("live forbidden")):
            one, two = build_receipt(), build_receipt()
        self.assertEqual(one, two)
        verify_seal(one)
        self.assertEqual(0, one["live_provider_calls"] + one["live_search_calls"] + one["judge_calls"] + one["credit_consumption"])
        self.assertFalse(one["official_prompt_consumed"] or one["hidden_registry_loaded"] or one["instance_selected"])
        self.assertEqual("AWAITING_BOARD_VERIFICATION", one["review_status"])

    def test_published_receipt_is_reproducible(self):
        published = json.loads((ROOT / "results/search-cup/v23-protocol-offline.json").read_text())
        self.assertEqual(build_receipt(), published)

    def test_cli_only_schema_receipt_no_authorization_switch(self):
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(0, main(["receipt"]))
        self.assertEqual(build_receipt(), json.loads(output.getvalue()))
        with patch("sys.stderr", new=io.StringIO()), self.assertRaises(SystemExit):
            main(["run"])

    def test_new_modules_have_no_transport_environment_runner_or_judge_invocation(self):
        for path in [ROOT / "search_cup/protocol_v23.py", *sorted((ROOT / "search_cup").glob("v23_*.py"))]:
            tree = ast.parse(path.read_text())
            # User-approved JE1 scope amendment: only this executor needs local
            # fsync/atomic writes and fixed read-only Git/source-context probes.
            # Transport and provider bans still apply, including to JE1.
            is_je1 = path.name == "v23_t4_je1.py"
            forbidden = {"socket", "requests", "httpx", "os", "subprocess"}
            if is_je1:
                forbidden -= {"os", "subprocess"}
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    self.assertFalse({a.name.split(".")[0] for a in node.names} & forbidden)
                if isinstance(node, ast.ImportFrom):
                    self.assertNotIn(node.module, ("runner", "judge", "providers", "search_pro", "urllib.request"))
                    if is_je1:
                        self.assertNotIn((node.module or "").split(".")[0], forbidden)
                if is_je1 and isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                    if node.value.id == "os":
                        self.assertIn(node.attr, {"environ", "open", "O_RDONLY", "O_DIRECTORY", "fsync", "close", "replace"})
                    if node.value.id == "subprocess":
                        self.assertEqual("run", node.attr)


if __name__ == "__main__":
    unittest.main()
