import unittest

from evaluation_lab import (
    CASES,
    closure_guard_policy,
    evaluate_policy,
    naive_any_done,
    run_experiment,
)


class EvaluationHarnessTest(unittest.TestCase):
    def test_fixture_has_invariant_and_sensitive_cases(self) -> None:
        expected = [bool(case["expected_close"]) for case in CASES]
        self.assertIn(False, expected)
        self.assertIn(True, expected)

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
        result = run_experiment()
        self.assertEqual(result["regression"]["status"], "PASS")
        self.assertEqual(result["regression"]["known_bad_failures_detected"], 4)
        self.assertEqual(result["regression"]["guard_failures"], 0)


if __name__ == "__main__":
    unittest.main()

