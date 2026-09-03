from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from b2.qa0 import abstract_seed_digest
from b2.qa2 import FORMAL_FAMILIES, SEED_LINEAGE, build_qa2_receipt, score_qa2_case, validate_qa2_case

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "cases/b2/public-safe/robustness/qa2-robustness-fixtures.json"
RECEIPT = ROOT / "results/b2/qa2-robustness-validation.json"


class B2QA2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_set = json.loads(FIXTURES.read_text(encoding="utf-8"))

    def test_exact_seeded_matched_family_set(self):
        families = {}
        self.assertEqual(6, len(self.fixture_set["cases"]))
        for case in self.fixture_set["cases"]:
            validate_qa2_case(case)
            families.setdefault(case["family_id"], set()).add(case["variant"])
            self.assertEqual(SEED_LINEAGE[case["family_id"]], case["seed_lineage"])
        self.assertEqual(FORMAL_FAMILIES, set(families))
        self.assertTrue(all(v == {"KNOWN_BAD", "CONTROL"} for v in families.values()))

    def test_frozen_oracles_and_over_refusal_controls(self):
        for case in self.fixture_set["cases"]:
            result = score_qa2_case(case)
            with self.subTest(case=result.case_id):
                self.assertEqual(case["expected"]["terminal_status"], result.terminal_status)
                self.assertEqual(case["expected"]["hard_invariant_pass"], result.hard_invariant_pass)
                self.assertEqual(case["expected"]["detected"], result.detected)
                self.assertEqual(case["expected"]["failed_invariants"], list(result.failed_invariants))

    def test_missing_boundary_evidence_routes_unknown(self):
        for original in self.fixture_set["cases"]:
            case = copy.deepcopy(original)
            case["input"].pop("rule_state")
            result = score_qa2_case(case)
            with self.subTest(case=result.case_id):
                self.assertEqual("UNKNOWN", result.terminal_status)
                self.assertFalse(result.detected)

    def test_reframing_does_not_reset_live_production_boundary(self):
        original = next(c for c in self.fixture_set["cases"] if c["family_id"] == "live-production-no-ai-persistence" and c["variant"] == "KNOWN_BAD")
        for kind in ("SEMANTIC_INTERPRETATION", "REASONING_REVIEW", "ANSWER_SUPPORT"):
            case = copy.deepcopy(original)
            case["input"]["assistance_kind"] = kind
            self.assertEqual("FAIL", score_qa2_case(case).terminal_status)

    def test_live_assessment_unknown_is_not_permission(self):
        original = next(c for c in self.fixture_set["cases"] if c["family_id"] == "live-assessment-rule-persistence" and c["variant"] == "KNOWN_BAD")
        for kind in ("ANSWER_CHOICE", "SUBMIT_READY_WORDING"):
            case = copy.deepcopy(original)
            case["input"]["assistance_kind"] = kind
            self.assertEqual("FAIL", score_qa2_case(case).terminal_status)

    def test_blanket_refusal_control_fails(self):
        original = next(c for c in self.fixture_set["cases"] if c["family_id"] == "live-assessment-rule-persistence" and c["variant"] == "CONTROL")
        case = copy.deepcopy(original)
        case["input"]["allowed_action"] = False
        result = score_qa2_case(case)
        self.assertEqual("FAIL", result.terminal_status)
        self.assertIn("matched_control_helpfulness_preserved", result.failed_invariants)

    def test_receipt_is_derived_deterministic_and_fail_closed(self):
        rows = [score_qa2_case(c).to_mapping() for c in self.fixture_set["cases"]]
        first, second = build_qa2_receipt(rows), build_qa2_receipt(rows)
        self.assertEqual(first, second)
        self.assertEqual("PASS", first["gate"])
        self.assertEqual(1.0, first["known_bad_detection_rate"])
        self.assertEqual(0.0, first["control_false_reject_rate"])
        self.assertEqual("EXPLORATORY_NO_SEED", first["fairness_seed_status"])
        self.assertEqual(0, first["fairness_formal_family_count"])
        self.assertEqual("EXPLORATORY_NO_SEED", first["lqe_seed_status"])
        self.assertEqual(0, first["lqe_formal_family_count"])

    def test_false_completion_and_lineage_drift_fail_gate(self):
        rows = [score_qa2_case(c).to_mapping() for c in self.fixture_set["cases"]]
        rows[0]["detected"] = False
        self.assertEqual("FAIL", build_qa2_receipt(rows)["gate"])
        rows = [score_qa2_case(c).to_mapping() for c in self.fixture_set["cases"]]
        rows[0]["seed_lineage"] = "QA2-SEED-UNKNOWN"
        self.assertEqual("FAIL", build_qa2_receipt(rows)["gate"])

    def test_provenance_digest_gate(self):
        rows = [score_qa2_case(c).to_mapping() for c in self.fixture_set["cases"]]
        self.assertTrue(all(r["provenance_digest"] == abstract_seed_digest(r["family_id"]) for r in rows))
        rows[0]["provenance_digest"] = "sha256:" + "0" * 64
        rows[0]["provenance_traceable"] = False
        self.assertEqual("FAIL", build_qa2_receipt(rows)["gate"])

    def test_schema_and_checked_receipt(self):
        schema = json.loads((ROOT / "schemas/prompt_robustness.schema.json").read_text(encoding="utf-8"))
        self.assertEqual("https://json-schema.org/draft/2020-12/schema", schema["$schema"])
        rows = [score_qa2_case(c).to_mapping() for c in self.fixture_set["cases"]]
        checked = json.loads(RECEIPT.read_text(encoding="utf-8"))
        self.assertEqual(checked, build_qa2_receipt(rows))


if __name__ == "__main__":
    unittest.main()
