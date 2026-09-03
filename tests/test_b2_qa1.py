from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from b2.qa1 import build_profile_receipt, score_profile_case, validate_profile_case

ROOT = Path(__file__).resolve().parents[1]
GROUNDING = ROOT / "cases/b2/public-safe/grounding/qa1-grounding-fixtures.json"
TOOL = ROOT / "cases/b2/public-safe/tool-workflow/qa1-tool-workflow-fixtures.json"


class B2QA1Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sets = {
            "GROUNDING": json.loads(GROUNDING.read_text(encoding="utf-8")),
            "TOOL_AGENT": json.loads(TOOL.read_text(encoding="utf-8")),
        }

    def test_three_matched_families_per_profile(self):
        for profile, fixture_set in self.sets.items():
            families = {}
            self.assertEqual(len(fixture_set["cases"]), 6)
            for case in fixture_set["cases"]:
                validate_profile_case(case, profile)
                families.setdefault(case["family_id"], set()).add(case["variant"])
            self.assertEqual(len(families), 3)
            self.assertTrue(all(v == {"KNOWN_BAD", "CONTROL"} for v in families.values()))

    def test_frozen_expected_results(self):
        for profile, fixture_set in self.sets.items():
            for case in fixture_set["cases"]:
                result = score_profile_case(case, profile)
                with self.subTest(profile=profile, case=result.case_id):
                    self.assertEqual(result.terminal_status, case["expected"]["terminal_status"])
                    self.assertEqual(result.hard_invariant_pass, case["expected"]["hard_invariant_pass"])
                    self.assertEqual(result.detected, case["expected"]["detected"])
                    self.assertEqual(list(result.failed_invariants), sorted(case["expected"]["failed_invariants"]))

    def test_profile_receipts_derive_pass_and_are_deterministic(self):
        for profile, fixture_set in self.sets.items():
            rows = [score_profile_case(c, profile).to_mapping() for c in fixture_set["cases"]]
            first = build_profile_receipt(profile, rows)
            second = build_profile_receipt(profile, rows)
            self.assertEqual(first, second)
            self.assertEqual(first["gate"], "PASS")
            self.assertEqual(first["known_bad_detection_rate"], 1.0)
            self.assertEqual(first["control_false_reject_rate"], 0.0)

    def test_unknown_and_blocked_do_not_satisfy_known_bad_oracle(self):
        for profile, fixture_set in self.sets.items():
            case = copy.deepcopy(next(c for c in fixture_set["cases"] if c["variant"] == "KNOWN_BAD"))
            case["input"] = {}
            result = score_profile_case(case, profile)
            self.assertEqual(result.terminal_status, "UNKNOWN")
            self.assertFalse(result.detected)

    def test_broken_detection_derives_fail_gate(self):
        for profile, fixture_set in self.sets.items():
            rows = [score_profile_case(c, profile).to_mapping() for c in fixture_set["cases"]]
            next(row for row in rows if row["variant"] == "KNOWN_BAD")["detected"] = False
            self.assertEqual(build_profile_receipt(profile, rows)["gate"], "FAIL")

    def test_schema_documents_parse_and_keep_profile_boundaries(self):
        for name in ("grounding_eval.schema.json", "tool_trace.schema.json"):
            doc = json.loads((ROOT / "schemas" / name).read_text(encoding="utf-8"))
            self.assertEqual(doc["$schema"], "https://json-schema.org/draft/2020-12/schema")
            self.assertIn("family_id", doc["properties"])

    def test_checked_receipts_equal_computed_receipts(self):
        paths = {
            "GROUNDING": ROOT / "results/b2/qa1-grounding-validation.json",
            "TOOL_AGENT": ROOT / "results/b2/qa1-tool-workflow-validation.json",
        }
        for profile, fixture_set in self.sets.items():
            rows = [score_profile_case(c, profile).to_mapping() for c in fixture_set["cases"]]
            checked = json.loads(paths[profile].read_text(encoding="utf-8"))
            self.assertEqual(checked, build_profile_receipt(profile, rows))


if __name__ == "__main__":
    unittest.main()
