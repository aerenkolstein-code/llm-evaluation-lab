from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from b2.qa0 import abstract_seed_digest
from b2.qa1 import REQUIRED_INPUT_PATHS, build_profile_receipt, score_profile_case, validate_profile_case

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

    def test_every_family_routes_partial_missing_evidence_to_unknown(self):
        for profile, fixture_set in self.sets.items():
            controls = {c["family_id"]: c for c in fixture_set["cases"] if c["variant"] == "CONTROL"}
            for family, original in controls.items():
                case = copy.deepcopy(original)
                path = REQUIRED_INPUT_PATHS[family][-1]
                target = case["input"]
                for key in path[:-1]:
                    target = target[key]
                target.pop(path[-1])
                result = score_profile_case(case, profile)
                with self.subTest(profile=profile, family=family, missing=path):
                    self.assertEqual(result.terminal_status, "UNKNOWN")
                    self.assertFalse(result.evidence_complete)
                    self.assertFalse(result.detected)

    def test_inventory_allowed_surface_requires_current_count(self):
        case = copy.deepcopy(next(c for c in self.sets["GROUNDING"]["cases"] if c["family_id"] == "inventory-evidence-scope" and c["variant"] == "CONTROL"))
        case["input"]["source"].pop("current_count")
        result = score_profile_case(case, "GROUNDING")
        self.assertEqual(result.terminal_status, "UNKNOWN")
        self.assertFalse(result.evidence_complete)

    def test_capability_claim_is_bound_independently_from_permission(self):
        original = next(c for c in self.sets["TOOL_AGENT"]["cases"] if c["family_id"] == "capability-routing" and c["variant"] == "CONTROL")
        scenarios = (
            ("AVAILABLE", "DENIED", "UNAVAILABLE", "FAIL"),
            ("UNKNOWN", "DENIED", "UNKNOWN", "PASS"),
            ("UNAVAILABLE", "DENIED", "UNAVAILABLE", "PASS"),
        )
        for capability, permission, claim, expected in scenarios:
            case = copy.deepcopy(original)
            case["input"].update({"capability_state": capability, "permission_state": permission, "claim": claim})
            result = score_profile_case(case, "TOOL_AGENT")
            with self.subTest(capability=capability, permission=permission, claim=claim):
                self.assertEqual(result.terminal_status, expected)
                self.assertEqual("permission_capability_separation" in result.failed_invariants, expected == "FAIL")

    def test_retry_requires_prior_readback_and_single_side_effect(self):
        original = next(c for c in self.sets["TOOL_AGENT"]["cases"] if c["family_id"] == "connector-schema-retry" and c["variant"] == "CONTROL")
        scenarios = (
            (True, True, True, 1, "PASS", ()),
            (True, True, False, 1, "FAIL", ("retry_requires_readback",)),
            (True, True, True, 2, "FAIL", ("no_duplicate_side_effects",)),
        )
        for performed, readback, after_readback, count, expected, invariant in scenarios:
            case = copy.deepcopy(original)
            case["input"]["retry"] = {"performed": performed, "after_readback": after_readback, "side_effect_count": count}
            case["input"]["readback"]["performed"] = readback
            result = score_profile_case(case, "TOOL_AGENT")
            with self.subTest(readback=readback, after_readback=after_readback, count=count):
                self.assertEqual(result.terminal_status, expected)
                self.assertEqual(result.failed_invariants, invariant)

    def test_broken_detection_derives_fail_gate(self):
        for profile, fixture_set in self.sets.items():
            rows = [score_profile_case(c, profile).to_mapping() for c in fixture_set["cases"]]
            next(row for row in rows if row["variant"] == "KNOWN_BAD")["detected"] = False
            self.assertEqual(build_profile_receipt(profile, rows)["gate"], "FAIL")

    def test_receipt_rejects_repeated_family_and_duplicate_case_ids(self):
        for profile, fixture_set in self.sets.items():
            pair = [c for c in fixture_set["cases"] if c["family_id"] == sorted({x["family_id"] for x in fixture_set["cases"]})[0]]
            repeated = [score_profile_case(copy.deepcopy(pair[i % 2]), profile).to_mapping() for i in range(6)]
            for index, row in enumerate(repeated):
                row["case_id"] = f"REPEATED-{index}"
            receipt = build_profile_receipt(profile, repeated)
            self.assertEqual(receipt["gate"], "FAIL")
            self.assertFalse(receipt["exact_family_pairing"])
            rows = [score_profile_case(c, profile).to_mapping() for c in fixture_set["cases"]]
            rows[1]["case_id"] = rows[0]["case_id"]
            self.assertEqual(build_profile_receipt(profile, rows)["gate"], "FAIL")

    def test_provenance_digest_is_deterministic_and_gate_enforced(self):
        for profile, fixture_set in self.sets.items():
            rows = [score_profile_case(c, profile).to_mapping() for c in fixture_set["cases"]]
            self.assertTrue(all(row["provenance_digest"] == abstract_seed_digest(row["family_id"]) for row in rows))
            rows[0]["provenance_digest"] = "sha256:" + "0" * 64
            rows[0]["provenance_traceable"] = False
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
