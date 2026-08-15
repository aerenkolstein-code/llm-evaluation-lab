import json
import io
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

from evaluation_lab import (
    BUILTIN_MITIGATION_SPEC,
    BUILTIN_SUITE,
    CASES,
    DEFAULT_CASE_PATH,
    DEFAULT_MITIGATION_PATH,
    closure_guard_policy,
    evaluate_policy,
    load_case_suite,
    load_mitigation_spec,
    main,
    naive_any_done,
    render_report,
    run_experiment,
    validate_mitigation_spec,
)


ROOT = Path(__file__).resolve().parents[1]
CHECKED_RESULT = ROOT / "results" / "EVAL-CASE-001.json"


class EvaluationHarnessTest(unittest.TestCase):
    def test_fixture_has_invariant_and_sensitive_cases(self) -> None:
        expected = [bool(case["expected_close"]) for case in CASES]
        self.assertIn(False, expected)
        self.assertIn(True, expected)

    def test_case_card_loads_and_matches_packaged_fallback(self) -> None:
        suite = load_case_suite(DEFAULT_CASE_PATH)
        self.assertEqual(suite.case_id, "EVAL-CASE-001")
        self.assertEqual(suite.privacy, "PUBLIC_SAFE")
        self.assertEqual(suite.cases, BUILTIN_SUITE.cases)

    def test_mitigation_document_loads_and_matches_packaged_fallback(self) -> None:
        spec = load_mitigation_spec(DEFAULT_MITIGATION_PATH)
        self.assertEqual(spec, validate_mitigation_spec(BUILTIN_MITIGATION_SPEC))
        self.assertEqual(spec["schema_version"], "mitigation-spec/v1")

    def test_mitigation_validation_rejects_unsupported_guard(self) -> None:
        spec = json.loads(json.dumps(BUILTIN_MITIGATION_SPEC))
        spec["runtime"]["guard_type"] = "arbitrary_code"
        with self.assertRaisesRegex(ValueError, "unsupported guard_type"):
            validate_mitigation_spec(spec)

    def test_mitigation_validation_rejects_status_overlap(self) -> None:
        spec = json.loads(json.dumps(BUILTIN_MITIGATION_SPEC))
        spec["runtime"]["blocking_statuses"].append("DONE")
        with self.assertRaisesRegex(ValueError, "overlap"):
            validate_mitigation_spec(spec)

    def test_loader_rejects_duplicate_variant_ids(self) -> None:
        document = {
            "case_id": "EVAL-CASE-BAD",
            "title": "Invalid duplicate fixture",
            "run_id": "EVAL-RUN-BAD",
            "mitigation_id": "MIT-BAD",
            "safeguard_id": "GUARD-BAD",
            "privacy": "PUBLIC_SAFE",
            "inputs": [
                {
                    "variant_id": "duplicate",
                    "children": [{"child_id": "a", "status": "DONE"}],
                    "expected_close": True,
                },
                {
                    "variant_id": "duplicate",
                    "children": [{"child_id": "b", "status": "OPEN"}],
                    "expected_close": False,
                },
            ],
        }
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "invalid.json"
            path.write_text(json.dumps(document), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate variant_id"):
                load_case_suite(path)

    def test_baseline_reproduces_the_failure(self) -> None:
        result = evaluate_policy("baseline", naive_any_done)
        self.assertEqual(result.accuracy, 0.2)
        self.assertEqual(result.premature_closure_rate, 1.0)
        self.assertEqual(len(result.failures), 4)

    def test_treatment_mitigates_without_blocking_valid_closure(self) -> None:
        result = evaluate_policy("guard", closure_guard_policy)
        self.assertEqual(result.accuracy, 1.0)
        self.assertEqual(result.premature_closure_rate, 0.0)
        self.assertEqual(result.failures, ())

    def test_regression_run_detects_known_bad_recurrence(self) -> None:
        result = run_experiment(load_case_suite(DEFAULT_CASE_PATH))
        self.assertEqual(result["regression"]["status"], "PASS")
        self.assertEqual(result["regression"]["known_bad_failures_detected"], 4)
        self.assertEqual(result["regression"]["guard_failures"], 0)
        self.assertEqual(result["integration"]["status"], "PASS")
        self.assertEqual(
            result["integration"]["runtime"],
            "companion_mind.runtime.ClosureGuard",
        )
        self.assertEqual(len(result["integration"]["spec_fingerprint"]), 64)

    def test_json_report_matches_checked_result(self) -> None:
        result = run_experiment(load_case_suite(DEFAULT_CASE_PATH))
        generated = json.loads(render_report(result, "json"))
        expected = json.loads(CHECKED_RESULT.read_text(encoding="utf-8"))
        self.assertEqual(generated, expected)

    def test_markdown_report_contains_metrics_and_regression_status(self) -> None:
        result = run_experiment(load_case_suite(DEFAULT_CASE_PATH))
        report = render_report(result, "markdown")
        self.assertIn("| Baseline | 20% | 100% | 4 |", report)
        self.assertIn("| Closure Guard | 100% | 0% | 0 |", report)
        self.assertIn("**PASS**", report)

    def test_cli_writes_an_atomic_markdown_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "reports" / "evaluation.md"
            mitigation = Path(temporary) / "reports" / "mitigation.json"
            exit_code = main(
                [
                    "--cases",
                    str(DEFAULT_CASE_PATH),
                    "--format",
                    "markdown",
                    "--output",
                    str(output),
                    "--emit-mitigation",
                    str(mitigation),
                ]
            )
            self.assertEqual(exit_code, 0)
            self.assertTrue(output.is_file())
            self.assertIn("EVAL-CASE-001", output.read_text(encoding="utf-8"))
            emitted = json.loads(mitigation.read_text(encoding="utf-8"))
            self.assertEqual(emitted, load_mitigation_spec(DEFAULT_MITIGATION_PATH))

    def test_runtime_rejects_spec_case_identity_mismatch(self) -> None:
        spec = json.loads(json.dumps(BUILTIN_MITIGATION_SPEC))
        spec["regression_cases"] = ["EVAL-CASE-999"]
        with self.assertRaisesRegex(ValueError, "not registered"):
            run_experiment(BUILTIN_SUITE, spec)

    def test_cli_returns_2_for_invalid_input(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            invalid = Path(temporary) / "invalid.json"
            invalid.write_text("{}", encoding="utf-8")
            error = io.StringIO()
            with redirect_stderr(error):
                exit_code = main(["--cases", str(invalid)])
            self.assertEqual(exit_code, 2)
            self.assertIn("must be a non-empty string", error.getvalue())

    def test_cli_returns_1_when_regression_gate_fails(self) -> None:
        failed_result = run_experiment(BUILTIN_SUITE)
        failed_result["regression"]["status"] = "FAIL"
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "failed.json"
            with patch("evaluation_lab.run_experiment", return_value=failed_result):
                exit_code = main(["--output", str(output)])
            self.assertEqual(exit_code, 1)
            self.assertTrue(output.is_file())


if __name__ == "__main__":
    unittest.main()
