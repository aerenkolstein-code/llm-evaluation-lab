from __future__ import annotations

import copy
import unittest
from pathlib import Path

from b2.qa0 import (
    TERMINAL_STATUSES,
    assert_public_safe,
    build_qa0_receipt,
    detection_oracle,
    load_json,
    score_case,
    sha256_json,
    validate_bug_case,
    validate_error_mechanism,
    validate_metric_registry,
    validate_public_seed,
)

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "cases" / "b2" / "public-safe"
RESULTS = ROOT / "results" / "b2"


class B2QA0Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_set = load_json(PUBLIC / "qa0-fixtures.json")
        cls.mechanism_set = load_json(PUBLIC / "mechanisms.json")
        cls.metric_registry = load_json(PUBLIC / "metric-registry.json")
        cls.bugcase_set = load_json(RESULTS / "bugcases.json")
        cls.receipt = load_json(RESULTS / "qa0-contract-validation.json")

    def test_terminal_semantics_are_explicit_and_distinct(self):
        self.assertEqual(
            TERMINAL_STATUSES,
            ("PASS", "FAIL", "NOT_EVALUABLE", "BLOCKED", "ERROR", "UNKNOWN"),
        )
        self.assertEqual(len(set(TERMINAL_STATUSES)), 6)

    def test_four_matched_pairs_validate(self):
        cases = self.fixture_set["cases"]
        self.assertEqual(len(cases), 8)
        families = {}
        for case in cases:
            validate_public_seed(case)
            families.setdefault(case["family_id"], set()).add(case["variant"])
        self.assertEqual(
            set(families),
            {
                "entity-attribute-binding",
                "connector-schema",
                "integrity-completeness",
                "evidence-scope",
            },
        )
        self.assertTrue(all(v == {"KNOWN_BAD", "CONTROL"} for v in families.values()))

    def test_mechanisms_keep_observation_and_hypothesis_separate(self):
        mechanisms = self.mechanism_set["mechanisms"]
        self.assertEqual(len(mechanisms), 4)
        for mechanism in mechanisms:
            doc = validate_error_mechanism(mechanism)
            self.assertNotEqual(doc["observed_phenomenon"], doc["mechanism_hypothesis"])

    def test_metric_registry_validates(self):
        doc = validate_metric_registry(self.metric_registry)
        kinds = {m["metric_id"]: m["kind"] for m in doc["metrics"]}
        self.assertEqual(kinds["hard_invariant_pass"], "HARD")
        self.assertEqual(kinds["mutation_validity"], "PLACEHOLDER")

    def test_bugcases_validate(self):
        bugs = self.bugcase_set["bug_cases"]
        self.assertEqual(len(bugs), 4)
        for bug in bugs:
            validate_bug_case(bug)

    def test_private_locator_and_exact_error_id_are_rejected(self):
        sample = copy.deepcopy(self.fixture_set["cases"][0])
        sample["limitations"] = ["https://" + "drive." + "google.com/example"]
        with self.assertRaises(ValueError):
            assert_public_safe(sample)
        sample = copy.deepcopy(self.fixture_set["cases"][0])
        sample["limitations"] = ["private mapping " + "ERR-" + "9999"]
        with self.assertRaises(ValueError):
            validate_public_seed(sample)

    def test_expected_verdicts_match_scorers(self):
        for case in self.fixture_set["cases"]:
            result = score_case(case)
            with self.subTest(case_id=case["case_id"]):
                self.assertEqual(result.terminal_status, case["expected"]["terminal_status"])
                self.assertEqual(
                    result.hard_invariant_pass,
                    case["expected"]["hard_invariant_pass"],
                )
                self.assertEqual(result.detected, case["expected"]["detected"])
                self.assertEqual(
                    list(result.failed_invariants),
                    sorted(case["expected"]["failed_invariants"]),
                )

    def test_frozen_gate_and_rerun_are_deterministic(self):
        first = [score_case(case).to_mapping() for case in self.fixture_set["cases"]]
        second = [score_case(case).to_mapping() for case in self.fixture_set["cases"]]
        self.assertEqual(first, second)
        computed = build_qa0_receipt(first)
        self.assertEqual(computed, build_qa0_receipt(second))
        self.assertEqual(computed["known_bad_detection_rate"], 1.0)
        self.assertEqual(computed["control_false_reject_rate"], 0.0)
        self.assertEqual(computed["provenance_trace_rate"], 1.0)
        self.assertEqual(computed["evidence_completeness_rate"], 1.0)
        self.assertEqual(computed["gate"], "PASS")

    def test_missing_or_blocked_outcomes_never_detect_known_bad(self):
        for status in ("UNKNOWN", "NOT_EVALUABLE", "BLOCKED"):
            with self.subTest(status=status):
                self.assertFalse(
                    detection_oracle(
                        family_id="entity-attribute-binding",
                        variant="KNOWN_BAD",
                        terminal_status=status,
                        failed_invariants=("entity_attribute_evidence_binding",),
                        evidence_complete=status != "UNKNOWN",
                    )
                )

    def test_error_detection_is_limited_to_typed_connector_target(self):
        self.assertFalse(
            detection_oracle(
                family_id="entity-attribute-binding",
                variant="KNOWN_BAD",
                terminal_status="ERROR",
                failed_invariants=("entity_attribute_evidence_binding",),
                evidence_complete=True,
            )
        )
        self.assertFalse(
            detection_oracle(
                family_id="connector-schema",
                variant="KNOWN_BAD",
                terminal_status="ERROR",
                failed_invariants=("unrelated_infrastructure_error",),
                evidence_complete=True,
            )
        )
        self.assertTrue(
            detection_oracle(
                family_id="connector-schema",
                variant="KNOWN_BAD",
                terminal_status="ERROR",
                failed_invariants=("request_schema_valid",),
                evidence_complete=True,
            )
        )

    def test_deliberately_failing_input_derives_fail_gate(self):
        results = [score_case(case).to_mapping() for case in self.fixture_set["cases"]]
        passing_receipt = build_qa0_receipt(results)
        broken = copy.deepcopy(results)
        known_bad = next(row for row in broken if row["variant"] == "KNOWN_BAD")
        known_bad["detected"] = False
        receipt = build_qa0_receipt(broken)
        self.assertLess(receipt["known_bad_detection_rate"], 1.0)
        self.assertEqual(receipt["gate"], "FAIL")
        self.assertNotEqual(
            receipt["receipt_fingerprint"], passing_receipt["receipt_fingerprint"]
        )

    def test_checked_in_receipt_matches_frozen_set(self):
        results = [score_case(case).to_mapping() for case in self.fixture_set["cases"]]
        computed = build_qa0_receipt(results)
        self.assertEqual(self.receipt, computed)
        self.assertEqual(computed["gate"], "PASS")
        payload = {
            key: value
            for key, value in self.receipt.items()
            if key != "receipt_fingerprint"
        }
        self.assertEqual(self.receipt["receipt_fingerprint"], sha256_json(payload))

    def test_connector_failure_is_infrastructure_error_not_model_fail(self):
        case = next(
            c
            for c in self.fixture_set["cases"]
            if c["case_id"] == "B2-QA0-CS-KB-001"
        )
        result = score_case(case)
        self.assertEqual(result.terminal_status, "ERROR")
        self.assertNotEqual(result.terminal_status, "FAIL")


if __name__ == "__main__":
    unittest.main()
