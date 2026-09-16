"""ENG-B1-SC-V23-T4 offline instance-package validation."""

from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from search_cup.contracts import canonical_json, fingerprint
from search_cup.protocol_v23 import SearchSpecV2, verify_seal
from search_cup.v23_judgment import judge_view, validate_package, validate_pool
from search_cup.v23_t4_instance import BASELINE, INSTANCE_ID, build_bundle


class T4JudgmentInstanceTests(unittest.TestCase):
    def test_bundle_is_deterministic_and_sealed(self):
        first = build_bundle()
        second = build_bundle()
        self.assertEqual(canonical_json(first), canonical_json(second))
        verify_seal(first["manifest"])
        verify_seal(first["instance_bindings"])
        verify_seal(first["receipt"])
        self.assertEqual(BASELINE, first["manifest"]["baseline"])
        self.assertEqual(INSTANCE_ID, first["manifest"]["instance_id"])

    def test_selected_instance_is_synthetic_protocol_validation_not_benchmark(self):
        bundle = build_bundle()
        spec = SearchSpecV2.from_mapping(bundle["searchspec"])
        doc = spec.as_dict()
        self.assertEqual("JUDGMENT_ONLY", doc["track_id"])
        self.assertEqual("SYNTHETIC_PROTOCOL_VALIDATION", doc["task"]["task_class"])
        self.assertFalse(bundle["manifest"]["benchmark_claim"])
        self.assertFalse(bundle["receipt"]["real_world_candidate_claim"])
        self.assertEqual("SYNTHETIC", bundle["judgment_package"]["source_overlay"]["kind"])
        self.assertEqual(3, len(bundle["candidate_pool"]["candidates"]))

    def test_judgment_package_and_blind_view_are_exact(self):
        bundle = build_bundle()
        validate_pool(bundle["candidate_pool"])
        validate_package(bundle["judgment_package"])
        expected = json.loads(judge_view(bundle["judgment_package"]).decode("utf-8"))
        self.assertEqual(expected, bundle["blind_judge_view"])
        rendered = canonical_json(bundle["blind_judge_view"]).casefold()
        for token in (
            "t4-origin-a",
            "t4-origin-b",
            "t4-origin-c",
            "t4-pv1-sealed-submission-a",
            "t4-pv1-sealed-submission-b",
            "t4-pv1-sealed-submission-c",
        ):
            self.assertNotIn(token, rendered)
        self.assertEqual(
            bundle["manifest"]["blind_judge_view_sha256"],
            bundle["receipt"]["blind_judge_view_sha256"],
        )

    def test_required_t1_binding_map_is_frozen_and_complete(self):
        bundle = build_bundle()
        decisions = bundle["instance_bindings"]["decisions"]
        for name in ("D1", "D2", "D3", "D5", "D7"):
            self.assertEqual("FROZEN", decisions[name]["status"])
            self.assertIsNotNone(decisions[name]["artifact"])
            self.assertIsNotNone(decisions[name]["approval"])
        for name in ("D4", "D6", "D8"):
            self.assertEqual("NOT_APPLICABLE", decisions[name]["status"])
            self.assertIsNone(decisions[name]["artifact"])
            self.assertIsNone(decisions[name]["approval"])
        gate = bundle["receipt"]["execution_gate"]
        self.assertEqual([], gate["missing_decisions"])
        self.assertEqual(["T1_IMPLEMENTATION_ONLY"], gate["reason_codes"])

    def test_judgment_only_search_tools_retries_and_execution_are_zero(self):
        bundle = build_bundle()
        spec = bundle["searchspec"]
        resources = bundle["resources"]
        self.assertIsNone(spec["retriever"])
        self.assertEqual([], spec["overlay"]["allowed_tools"])
        for key in (
            "max_search_calls",
            "max_search_turns",
            "max_results_per_call",
            "max_follow_links",
            "automatic_retries",
        ):
            self.assertEqual(0, resources[key])
        receipt = bundle["receipt"]
        self.assertFalse(receipt["execution_allowed"])
        self.assertEqual(0, receipt["provider_calls"])
        self.assertEqual(0, receipt["search_calls"])
        self.assertEqual(0, receipt["judge_calls"])
        self.assertEqual(0, receipt["credit_consumption"])
        self.assertEqual(0, receipt["spend"]["value"])
        self.assertFalse(receipt["official_prompt_consumed"])
        self.assertFalse(receipt["hidden_registry_loaded"])

    def test_roster_is_exact_synthetic_not_connected_and_not_in_blind_view(self):
        bundle = build_bundle()
        roster = bundle["judge_roster"]
        self.assertEqual(
            ["t4-fixture-judge-a", "t4-fixture-judge-b"],
            [j["entrant_id"] for j in roster],
        )
        self.assertTrue(all(j["provider"] == "synthetic-not-connected" for j in roster))
        self.assertTrue(all(j["endpoint_mode"] == "NOT_CONNECTED" for j in roster))
        rendered = canonical_json(bundle["blind_judge_view"])
        self.assertNotIn("fixture-judge-a", rendered)
        self.assertNotIn("fixture-judge-b", rendered)
        self.assertEqual(fingerprint(roster), bundle["receipt"]["judge_roster_fingerprint"])

    def test_unknown_and_adjudication_rules_are_frozen_before_outputs(self):
        bundle = build_bundle()
        rubric = bundle["rubric"]
        self.assertEqual("PRESERVE", rubric["aggregation"]["unknown_policy"])
        self.assertTrue(rubric["aggregation"]["frozen_before_outputs"])
        self.assertEqual("PRESERVE_DISAGREEMENT", rubric["aggregation"]["tie_policy"])
        self.assertTrue(
            all(
                d["unknown_rule"] == "INSUFFICIENT_EVIDENCE_NOT_NEGATIVE"
                for d in rubric["dimensions"]
            )
        )
        adjudication = bundle["adjudication"]
        self.assertTrue(adjudication["append_only"])
        self.assertEqual("FROZEN_PACKET_ONLY", adjudication["evidence_policy"])

    def test_bundle_builder_does_not_require_network_or_environment_credentials(self):
        with patch("socket.socket", side_effect=AssertionError("network forbidden")), patch(
            "socket.create_connection", side_effect=AssertionError("network forbidden")
        ):
            bundle = build_bundle()
        self.assertFalse(bundle["receipt"]["execution_allowed"])


if __name__ == "__main__":
    unittest.main()
