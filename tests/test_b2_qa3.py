from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from b2.qa0 import abstract_seed_digest, sha256_json
from b2.qa3 import (
    ADAPTER_REQUIRED_SCENARIOS,
    COMPARABILITY_FIELDS,
    PROJECTION_FAMILIES,
    SEED_LINEAGE,
    build_adapter_receipt,
    build_checked_dashboard,
    build_dashboard_projection,
    build_qa3_receipt,
    compute_quality_delta,
    load_sqlite_runs_read_only,
    receipt_evidence_ref,
    reconcile_adapter,
    reference_adapter,
    render_dashboard_html,
    run_adapter_fixture,
    score_qa3_case,
    sqlite_accuracy_delta,
    validate_adapter_representation,
    validate_evidence_ref,
    validate_metric_observation,
    validate_neutral_record,
    validate_qa3_case,
    verify_checked_receipt,
    verify_dashboard_projection,
)
from evaluation_lab import persist_experiment_run


ROOT = Path(__file__).resolve().parents[1]
PROJECTION_FIXTURES = (
    ROOT / "cases/b2/public-safe/projection/qa3-projection-fixtures.json"
)
ADAPTER_FIXTURES = (
    ROOT / "cases/b2/public-safe/adapters/qa3-reference-adapter-fixtures.json"
)
PROJECTION_RECEIPT = ROOT / "results/b2/qa3-quality-delta-validation.json"
ADAPTER_RECEIPT = ROOT / "results/b2/qa3-adapter-validation.json"
DASHBOARD_JSON = ROOT / "reports/b2/qa3-quality-delta.json"
DASHBOARD_HTML = ROOT / "reports/b2/qa3-quality-delta.html"
SOURCE_COMMIT = "c" * 40


def refingerprint(document: dict, field: str) -> dict:
    changed = copy.deepcopy(document)
    changed.pop(field, None)
    changed[field] = sha256_json(changed)
    return changed


class B2QA3Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.projection_set = json.loads(
            PROJECTION_FIXTURES.read_text(encoding="utf-8")
        )
        cls.adapter_set = json.loads(ADAPTER_FIXTURES.read_text(encoding="utf-8"))
        cls.projection_rows = [
            score_qa3_case(case).to_mapping()
            for case in cls.projection_set["cases"]
        ]
        cls.adapter_rows = [
            run_adapter_fixture(case) for case in cls.adapter_set["cases"]
        ]

    def _receipt_sources(self):
        paths = (
            "results/b2/qa0-contract-validation.json",
            "results/b2/qa1-grounding-validation.json",
            "results/b2/qa1-tool-workflow-validation.json",
            "results/b2/qa2-robustness-validation.json",
        )
        sources = [
            {
                "path": path,
                "git_commit": SOURCE_COMMIT,
                "receipt": json.loads((ROOT / path).read_text(encoding="utf-8")),
            }
            for path in paths
        ]
        qa3_path = "results/b2/qa3-quality-delta-validation.json"
        sources.append(
            {
                "path": qa3_path,
                "git_commit": SOURCE_COMMIT,
                "receipt": build_qa3_receipt(self.projection_rows),
            }
        )
        declared = [f"B2_RECEIPT:{source['path']}" for source in sources]
        return sources, declared

    @staticmethod
    def _evidence_ref(kind="B2_RECEIPT"):
        if kind == "B2_RECEIPT":
            source_id = "B2_RECEIPT:results/b2/synthetic-receipt.json"
            locator = "results/b2/synthetic-receipt.json"
        else:
            source_id = "SQLITE_RUN:synthetic-run-001"
            locator = "experiment_runs/synthetic-run-001"
        return {
            "kind": kind,
            "source_id": source_id,
            "source_locator": locator,
            "source_fingerprint": "sha256:" + "1" * 64,
            "git_commit": SOURCE_COMMIT,
            "scope": "SYNTHETIC_SCOPE",
        }

    def _observation(self, **changes):
        key = {
            "profile": "SYNTHETIC_PROFILE",
            "suite_id": "synthetic-suite",
            "metric_id": "synthetic_accuracy",
            "metric_version": "v1",
            "metric_definition": "correct cases divided by declared cases",
            "case_set_fingerprint": "sha256:" + "2" * 64,
            "terminal_semantics_version": "v1",
            "aggregation_rule": "arithmetic_mean_over_declared_case_set",
            "scope_type": "PROFILE",
            "scope_id": "synthetic-profile",
        }
        row = {
            "observation_id": "synthetic-observation-current",
            "comparable_key": key,
            "value": 0.75,
            "terminal_status": "PASS",
            "hard_invariant_pass": True,
            "provenance_state": "VERIFIED",
            "causal_attribution": "UNKNOWN",
            "evidence_ref": self._evidence_ref(),
        }
        row.update(changes)
        return row

    def _dashboard(self):
        sources, declared = self._receipt_sources()
        return build_dashboard_projection(
            sources,
            declared_source_ids=declared,
            observed_at="2026-09-03T00:00:00Z",
            snapshot_id=f"git:{SOURCE_COMMIT}",
        )

    def test_exact_seed_lineage_and_matched_family_set(self):
        families = {}
        self.assertEqual(6, len(self.projection_set["cases"]))
        for case in self.projection_set["cases"]:
            validate_qa3_case(case)
            families.setdefault(case["family_id"], set()).add(case["variant"])
            self.assertEqual(SEED_LINEAGE[case["family_id"]], case["seed_lineage"])
            self.assertEqual(
                abstract_seed_digest(case["family_id"]),
                case["provenance"]["seed_digest"],
            )
        self.assertEqual(PROJECTION_FAMILIES, set(families))
        self.assertTrue(all(pair == {"KNOWN_BAD", "CONTROL"} for pair in families.values()))

    def test_projection_fixture_oracles_and_controls(self):
        for case in self.projection_set["cases"]:
            result = score_qa3_case(case)
            with self.subTest(case=result.case_id):
                self.assertEqual(case["expected"]["terminal_status"], result.terminal_status)
                self.assertEqual(case["expected"]["hard_invariant_pass"], result.hard_invariant_pass)
                self.assertEqual(case["expected"]["detected"], result.detected)
                self.assertEqual(case["expected"]["failed_invariants"], list(result.failed_invariants))

    def test_missing_required_projection_evidence_routes_unknown(self):
        for original in self.projection_set["cases"]:
            case = copy.deepcopy(original)
            case["input"].pop(next(iter(case["input"])))
            result = score_qa3_case(case)
            with self.subTest(case=result.case_id):
                self.assertEqual("UNKNOWN", result.terminal_status)
                self.assertFalse(result.hard_invariant_pass)
                self.assertFalse(result.detected)

    def test_sampled_subset_cannot_claim_global_completeness(self):
        case = copy.deepcopy(next(
            item for item in self.projection_set["cases"]
            if item["family_id"] == "full-set-projection-completeness"
            and item["variant"] == "CONTROL"
        ))
        case["input"]["sampled_source_ids"] = ["run-a"]
        case["input"]["projected_source_ids"] = ["run-a"]
        result = score_qa3_case(case)
        self.assertEqual("FAIL", result.terminal_status)
        self.assertIn("sample_not_global_evidence", result.failed_invariants)
        self.assertIn("declared_source_set_complete", result.failed_invariants)

    def test_duplicate_missing_and_ambiguous_source_identity_fail_closed(self):
        original = next(
            item for item in self.projection_set["cases"]
            if item["family_id"] == "full-set-projection-completeness"
            and item["variant"] == "CONTROL"
        )
        mutations = (
            ("declared_source_ids", ["run-a", "run-a"], "unique_source_identity"),
            ("available_source_ids", ["run-a", "run-b"], "declared_source_set_complete"),
            ("source_identities_unambiguous", False, "source_identity_unambiguous"),
        )
        for field, value, invariant in mutations:
            case = copy.deepcopy(original)
            case["input"][field] = value
            result = score_qa3_case(case)
            with self.subTest(field=field):
                self.assertEqual("FAIL", result.terminal_status)
                self.assertIn(invariant, result.failed_invariants)

    def test_metric_value_does_not_upgrade_unknown_attribution(self):
        original = next(
            item for item in self.projection_set["cases"]
            if item["family_id"] == "metric-attribution-provenance-separation"
            and item["variant"] == "CONTROL"
        )
        self.assertEqual("PASS", score_qa3_case(original).terminal_status)
        case = copy.deepcopy(original)
        case["input"].update({"attribution_state": "VERIFIED", "causal_narrative": True})
        result = score_qa3_case(case)
        self.assertEqual("FAIL", result.terminal_status)
        self.assertIn("metric_value_provenance_separated", result.failed_invariants)
        self.assertIn("causal_attribution_evidenced", result.failed_invariants)

    def test_field_semantics_scope_and_observation_source_are_explicit(self):
        original = next(
            item for item in self.projection_set["cases"]
            if item["family_id"] == "dashboard-field-semantics-scope-lock"
            and item["variant"] == "CONTROL"
        )
        for field in ("field_semantics", "scope_type", "scope_id", "observed_at", "source_ref"):
            case = copy.deepcopy(original)
            case["input"].pop(field)
            with self.subTest(field=field):
                self.assertEqual("UNKNOWN", score_qa3_case(case).terminal_status)

    def test_personal_global_and_current_history_scopes_do_not_coerce(self):
        original = next(
            item for item in self.projection_set["cases"]
            if item["family_id"] == "dashboard-field-semantics-scope-lock"
            and item["variant"] == "CONTROL"
        )
        for scope in ("PERSONAL_CURRENT", "PERSONAL_HISTORY", "GLOBAL_HISTORY"):
            case = copy.deepcopy(original)
            case["input"]["scope_type"] = scope
            case["input"]["scope_id"] = f"synthetic-{scope.lower()}"
            result = score_qa3_case(case)
            with self.subTest(scope=scope):
                self.assertEqual("FAIL", result.terminal_status)
                self.assertIn("field_scope_preserved", result.failed_invariants)

    def test_qa3_receipt_is_deterministic_checked_and_fail_closed(self):
        first = build_qa3_receipt(self.projection_rows)
        second = build_qa3_receipt(self.projection_rows)
        self.assertEqual(first, second)
        self.assertEqual("PASS", first["gate"])
        self.assertEqual(3, first["family_count"])
        self.assertEqual(1.0, first["known_bad_detection_rate"])
        self.assertEqual(0.0, first["control_false_reject_rate"])
        self.assertEqual(first, verify_checked_receipt(first))
        failed = copy.deepcopy(self.projection_rows)
        failed[0]["detected"] = False
        self.assertEqual("FAIL", build_qa3_receipt(failed)["gate"])

    def test_checked_receipt_fingerprint_tampering_is_rejected(self):
        receipt = build_qa3_receipt(self.projection_rows)
        receipt["case_count"] = 999
        with self.assertRaisesRegex(ValueError, "fingerprint"):
            verify_checked_receipt(receipt)

    def test_canonical_evidence_ref_is_typed_and_bounded(self):
        for kind in ("B2_RECEIPT", "SQLITE_RUN"):
            ref = self._evidence_ref(kind)
            self.assertEqual(ref, validate_evidence_ref(ref))
        invalid = self._evidence_ref()
        invalid["git_commit"] = "short"
        with self.assertRaises(ValueError):
            validate_evidence_ref(invalid)
        receipt = build_qa3_receipt(self.projection_rows)
        with self.assertRaises(ValueError):
            receipt_evidence_ref("../outside.json", receipt, SOURCE_COMMIT)

    def test_dashboard_requires_complete_unique_single_snapshot_sources(self):
        sources, declared = self._receipt_sources()
        with self.assertRaisesRegex(ValueError, "complete declared source set"):
            build_dashboard_projection(
                sources[:-1],
                declared_source_ids=declared,
                observed_at="2026-09-03T00:00:00Z",
                snapshot_id="synthetic",
            )
        duplicate = sources + [copy.deepcopy(sources[0])]
        with self.assertRaisesRegex(ValueError, "duplicate"):
            build_dashboard_projection(
                duplicate,
                declared_source_ids=declared,
                observed_at="2026-09-03T00:00:00Z",
                snapshot_id="synthetic",
            )
        mixed = copy.deepcopy(sources)
        mixed[-1]["git_commit"] = "d" * 40
        with self.assertRaisesRegex(ValueError, "mix git contexts"):
            build_dashboard_projection(
                mixed,
                declared_source_ids=declared,
                observed_at="2026-09-03T00:00:00Z",
                snapshot_id="synthetic",
            )

    def test_dashboard_profiles_and_scalars_retain_canonical_refs(self):
        dashboard = verify_dashboard_projection(self._dashboard())
        manifest_ids = set(dashboard["source_manifest"]["included_source_ids"])
        self.assertEqual(5, dashboard["source_manifest"]["source_count"])
        self.assertEqual(manifest_ids, {
            profile["evidence_ref"]["source_id"] for profile in dashboard["profiles"]
        })
        for profile, delta in zip(dashboard["profiles"], dashboard["quality_deltas"]):
            self.assertEqual(profile["evidence_ref"], delta["evidence_ref"])
            self.assertEqual("NOT_EVALUABLE", delta["terminal_status"])
            self.assertEqual("NO_BASELINE", delta["reason"])
            self.assertIsNone(delta["delta"])

    def test_dashboard_semantic_tampering_fails_even_after_refingerprint(self):
        dashboard = self._dashboard()
        mutations = []
        partial = copy.deepcopy(dashboard)
        partial["source_manifest"]["included_source_ids"].pop()
        partial["source_manifest"]["excluded_source_ids"].append(
            partial["source_manifest"]["declared_source_ids"][-1]
        )
        partial["source_manifest"]["included_count"] -= 1
        partial["source_manifest"]["excluded_count"] = 1
        mutations.append(partial)
        trend = copy.deepcopy(dashboard)
        trend["regression_recurrence"]["terminal_status"] = "PASS"
        trend["regression_recurrence"]["series"] = [0.0]
        mutations.append(trend)
        invented_delta = copy.deepcopy(dashboard)
        invented_delta["quality_deltas"][0].update(
            {"terminal_status": "PASS", "reason": "COMPARABLE", "delta": 0.0}
        )
        mutations.append(invented_delta)
        second_authority = copy.deepcopy(dashboard)
        second_authority["authority"] = "CANONICAL"
        mutations.append(second_authority)
        for mutation in mutations:
            with self.subTest(mutation=mutations.index(mutation)), self.assertRaises(ValueError):
                verify_dashboard_projection(refingerprint(mutation, "projection_fingerprint"))

    def test_metric_observation_freezes_every_comparability_dimension(self):
        row = self._observation()
        self.assertEqual(set(COMPARABILITY_FIELDS), set(row["comparable_key"]))
        validate_metric_observation(row)
        for field in COMPARABILITY_FIELDS:
            broken = copy.deepcopy(row)
            broken["comparable_key"].pop(field)
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_metric_observation(broken)

    def test_no_baseline_is_not_evaluable_and_never_zero_delta(self):
        delta = compute_quality_delta(self._observation(), None)
        self.assertEqual("NOT_EVALUABLE", delta["terminal_status"])
        self.assertEqual("NO_BASELINE", delta["reason"])
        self.assertIsNone(delta["baseline_value"])
        self.assertIsNone(delta["delta"])

    def test_quality_delta_computes_only_for_compatible_records(self):
        baseline = self._observation(
            observation_id="synthetic-observation-baseline", value=0.5
        )
        current = self._observation(value=0.75)
        delta = compute_quality_delta(current, baseline)
        self.assertEqual("PASS", delta["terminal_status"])
        self.assertEqual(0.25, delta["delta"])
        for field in COMPARABILITY_FIELDS:
            incompatible = copy.deepcopy(baseline)
            incompatible["comparable_key"][field] += "-different"
            with self.subTest(field=field):
                result = compute_quality_delta(current, incompatible)
                self.assertEqual("FAIL", result["terminal_status"])
                self.assertEqual("NOT_COMPARABLE", result["reason"])
                self.assertIsNone(result["delta"])

    def test_unknown_error_and_hard_failure_are_not_averaged_away(self):
        baseline = self._observation(
            observation_id="synthetic-observation-baseline", value=0.5
        )
        scenarios = (
            ({"terminal_status": "UNKNOWN"}, "UNKNOWN", "REQUIRED_EVIDENCE_UNRESOLVED"),
            ({"terminal_status": "ERROR"}, "ERROR", "INFRASTRUCTURE_TERMINAL"),
            ({"terminal_status": "FAIL", "hard_invariant_pass": False}, "FAIL", "HARD_INVARIANT_FAILURE"),
        )
        for changes, status, reason in scenarios:
            current = self._observation(**changes)
            result = compute_quality_delta(current, baseline)
            with self.subTest(status=status):
                self.assertEqual(status, result["terminal_status"])
                self.assertEqual(reason, result["reason"])
                self.assertIsNone(result["delta"])

    def test_sqlite_projection_reads_all_runs_without_mutation(self):
        result = {
            "run_id": "RUN-QA3-SYNTHETIC-001",
            "case_id": "SYNTHETIC-CASE-SET-v1",
            "baseline": {"accuracy": 0.25},
            "treatment": {"accuracy": 0.75},
            "regression": {"status": "PASS"},
        }
        with tempfile.TemporaryDirectory() as temporary:
            store = Path(temporary) / "runs.sqlite3"
            persist_experiment_run(
                store,
                result,
                suite="historical",
                model="deterministic-reference",
                prompt_version="synthetic-v1",
                git_commit=SOURCE_COMMIT,
                latency_ms=3.0,
                token_cost=0.0,
                created_at_utc="2026-09-03T00:00:00Z",
            )
            before = store.read_bytes()
            projection = load_sqlite_runs_read_only(store)
            after = store.read_bytes()
        self.assertEqual(before, after)
        self.assertFalse(projection["canonical_mutated"])
        self.assertEqual(1, projection["run_count"])
        self.assertEqual(projection["store_fingerprint_before"], projection["store_fingerprint_after"])
        self.assertEqual("SQLITE_RUN:RUN-QA3-SYNTHETIC-001", projection["runs"][0]["evidence_ref"]["source_id"])
        delta = sqlite_accuracy_delta(projection["runs"][0])
        self.assertEqual("PASS", delta["terminal_status"])
        self.assertEqual(0.5, delta["delta"])

    def test_adapter_fixture_set_is_exact_and_all_outcomes_match(self):
        scenarios = {row["scenario"] for row in self.adapter_rows}
        self.assertEqual(ADAPTER_REQUIRED_SCENARIOS, scenarios)
        self.assertEqual(9, len(self.adapter_rows))
        self.assertTrue(all(row["outcome_match"] for row in self.adapter_rows))
        receipt = build_adapter_receipt(self.adapter_rows)
        self.assertEqual("PASS", receipt["gate"])
        self.assertEqual(1.0, receipt["mismatch_detection_rate"])
        self.assertEqual(0.0, receipt["canonical_mutation_rate"])
        self.assertEqual(0.0, receipt["writeback_permitted_rate"])

    def test_reference_adapter_preserves_canonical_identity_and_truth(self):
        canonical = copy.deepcopy(self.adapter_set["cases"][0]["canonical_record"])
        before = sha256_json(canonical)
        adapter = reference_adapter(canonical)
        self.assertIsNotNone(adapter)
        validate_neutral_record(canonical)
        validate_adapter_representation(adapter)
        self.assertEqual(canonical["evidence_ref"], adapter["canonical_ref"])
        self.assertEqual(before, adapter["source_digest"])
        self.assertTrue(adapter["adapter_record_id"].startswith("neutral:"))
        self.assertFalse(adapter["writeback_permitted"])
        self.assertEqual(before, sha256_json(canonical))
        self.assertEqual("PASS", reconcile_adapter(canonical, adapter)["status"])

    def test_adapter_mismatch_matrix_fails_not_reconciled(self):
        mismatch_scenarios = {
            "DIGEST_MISMATCH",
            "METRIC_SEMANTICS_MISMATCH",
            "TERMINAL_MISMATCH",
            "SCOPE_MISMATCH",
            "VALUE_MISMATCH",
            "SILENT_CRITICAL_DROP",
        }
        rows = [row for row in self.adapter_rows if row["scenario"] in mismatch_scenarios]
        self.assertEqual(mismatch_scenarios, {row["scenario"] for row in rows})
        for row in rows:
            with self.subTest(scenario=row["scenario"]):
                self.assertEqual("FAIL", row["status"])
                self.assertEqual("NOT_RECONCILED", row["reason"])
                self.assertTrue(row["mismatches"])
                self.assertTrue(row["quality_verdict_unchanged"])
                self.assertFalse(row["canonical_mutated"])

    def test_adapter_unavailable_is_infrastructure_error_only(self):
        row = next(row for row in self.adapter_rows if row["scenario"] == "ADAPTER_UNAVAILABLE")
        self.assertEqual("ERROR", row["status"])
        self.assertEqual("ADAPTER_UNAVAILABLE", row["reason"])
        self.assertTrue(row["quality_verdict_unchanged"])
        self.assertFalse(row["canonical_mutated"])
        self.assertTrue(row["limitations"])

    def test_lossy_optional_mapping_is_disclosed_and_critical_drop_fails(self):
        lossy = next(row for row in self.adapter_rows if row["scenario"] == "LOSSY_OPTIONAL_EXPLICIT")
        silent = next(row for row in self.adapter_rows if row["scenario"] == "SILENT_CRITICAL_DROP")
        self.assertEqual("PASS", lossy["status"])
        self.assertIn("optional_metadata omitted by reference adapter", lossy["limitations"])
        self.assertEqual("FAIL", silent["status"])
        self.assertIn("metric.provenance_state", silent["mismatches"])

    def test_malformed_or_second_authority_adapter_fails_closed(self):
        canonical = copy.deepcopy(self.adapter_set["cases"][0]["canonical_record"])
        adapter = reference_adapter(canonical)
        adapter["writeback_permitted"] = True
        result = reconcile_adapter(canonical, adapter)
        self.assertEqual("FAIL", result["status"])
        self.assertIn("adapter_schema", result["mismatches"])
        adapter = reference_adapter(canonical)
        adapter["adapter_record_id"] = "external-authority-id"
        result = reconcile_adapter(canonical, adapter)
        self.assertEqual("FAIL", result["status"])
        self.assertIn("adapter_record_id", result["mismatches"])

    def test_checked_receipt_files_rebuild_exactly(self):
        expected_projection = build_qa3_receipt(self.projection_rows)
        expected_adapter = build_adapter_receipt(self.adapter_rows)
        self.assertEqual(expected_projection, json.loads(PROJECTION_RECEIPT.read_text(encoding="utf-8")))
        self.assertEqual(expected_adapter, json.loads(ADAPTER_RECEIPT.read_text(encoding="utf-8")))

    def test_schemas_parse_and_freeze_authority_terminal_and_refs(self):
        projection_schema = json.loads(
            (ROOT / "schemas/quality_delta_projection.schema.json").read_text(encoding="utf-8")
        )
        adapter_schema = json.loads(
            (ROOT / "schemas/external_eval_adapter.schema.json").read_text(encoding="utf-8")
        )
        self.assertEqual("https://json-schema.org/draft/2020-12/schema", projection_schema["$schema"])
        self.assertEqual("DERIVED_READ_ONLY_PROJECTION", projection_schema["properties"]["authority"]["const"])
        self.assertEqual("NOT_EVALUABLE", projection_schema["$defs"]["delta"]["properties"]["terminal_status"]["const"])
        self.assertEqual({"B2_RECEIPT", "SQLITE_RUN"}, set(projection_schema["$defs"]["evidenceRef"]["properties"]["kind"]["enum"]))
        adapter_definition = adapter_schema["$defs"]["adapterRepresentation"]
        self.assertFalse(adapter_definition["properties"]["writeback_permitted"]["const"])

    def test_static_dashboard_report_rebuilds_byte_exactly(self):
        checked = json.loads(DASHBOARD_JSON.read_text(encoding="utf-8"))
        source_commit = checked["source_snapshot"]["git_commit"]
        observed_at = checked["source_snapshot"]["observed_at"]
        rebuilt = build_checked_dashboard(
            ROOT, source_commit=source_commit, observed_at=observed_at
        )
        self.assertEqual(checked, rebuilt)
        self.assertEqual(
            DASHBOARD_HTML.read_text(encoding="utf-8"),
            render_dashboard_html(rebuilt),
        )
        self.assertEqual("OPTIONAL_NOT_SELECTED", checked["brand_adapters"]["status"])
        self.assertEqual([], checked["brand_adapters"]["claims_unlocked"])


if __name__ == "__main__":
    unittest.main()
