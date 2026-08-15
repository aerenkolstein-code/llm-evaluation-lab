import asyncio
import hashlib
import json
import io
import sqlite3
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest.mock import patch

try:
    import fastapi  # noqa: F401
except ModuleNotFoundError:
    HAS_FASTAPI = False
else:
    HAS_FASTAPI = True

from evaluation_lab import (
    BUILTIN_MITIGATION_SPEC,
    BUILTIN_SUITE,
    CASES,
    DEFAULT_CASE_PATH,
    DEFAULT_MITIGATION_PATH,
    closure_guard_policy,
    confidence_only_baseline,
    constraint_gate_policy,
    create_app,
    evaluate_historical_policy,
    evaluate_policy,
    get_experiment_run,
    load_case_suite,
    load_historical_benchmark,
    load_mitigation_spec,
    list_experiment_runs,
    main,
    naive_any_done,
    persist_experiment_run,
    render_report,
    run_experiment,
    run_historical_benchmark,
    validate_mitigation_spec,
)


ROOT = Path(__file__).resolve().parents[1]
CHECKED_RESULT = ROOT / "results" / "EVAL-CASE-001.json"


def asgi_get(
    app: object, path: str, query_string: bytes = b""
) -> tuple[int, dict[str, object]]:
    """Exercise one GET request without adding an HTTP test dependency."""

    async def invoke() -> tuple[int, dict[str, object]]:
        messages: list[dict[str, object]] = []
        request_sent = False

        async def receive() -> dict[str, object]:
            nonlocal request_sent
            if request_sent:
                return {"type": "http.disconnect"}
            request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}

        async def send(message: dict[str, object]) -> None:
            messages.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0"},
            "http_version": "1.1",
            "method": "GET",
            "scheme": "http",
            "path": path,
            "raw_path": path.encode("utf-8"),
            "query_string": query_string,
            "headers": [(b"host", b"testserver")],
            "client": ("127.0.0.1", 12345),
            "server": ("127.0.0.1", 8000),
            "root_path": "",
        }
        await app(scope, receive, send)  # type: ignore[operator]
        start = next(item for item in messages if item["type"] == "http.response.start")
        body = b"".join(
            item.get("body", b"")  # type: ignore[arg-type]
            for item in messages
            if item["type"] == "http.response.body"
        )
        return int(start["status"]), json.loads(body)

    return asyncio.run(invoke())


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

    def test_historical_benchmark_has_declared_public_safe_scope(self) -> None:
        suite = load_historical_benchmark(DEFAULT_CASE_PATH)
        self.assertEqual(suite.benchmark_id, "HISTORICAL-FAILURE-BENCHMARK-v1")
        self.assertEqual(suite.privacy, "PUBLIC_SAFE")
        self.assertEqual(suite.source_observations, 89)
        self.assertEqual(suite.source_categories, 18)
        self.assertEqual(len(suite.mechanisms), 12)
        self.assertEqual(len(suite.cases), 24)

    def test_historical_mechanisms_have_minimal_pairs(self) -> None:
        suite = load_historical_benchmark(DEFAULT_CASE_PATH)
        pairs: dict[str, set[str]] = {}
        for case in suite.cases:
            pairs.setdefault(str(case["mechanism_id"]), set()).add(
                str(case["variant"])
            )
        self.assertEqual(set(pairs), {item["mechanism_id"] for item in suite.mechanisms})
        self.assertTrue(all(variants == {"TRAP", "CONTROL"} for variants in pairs.values()))

    def test_historical_baseline_reproduces_twelve_traps(self) -> None:
        suite = load_historical_benchmark(DEFAULT_CASE_PATH)
        result = evaluate_historical_policy(
            "baseline", confidence_only_baseline, suite.cases
        )
        self.assertEqual(result.accuracy, 0.5)
        self.assertEqual(result.false_accept_rate, 1.0)
        self.assertEqual(len(result.failures), 12)

    def test_uniform_constraint_gate_mitigates_without_case_rules(self) -> None:
        suite = load_historical_benchmark(DEFAULT_CASE_PATH)
        result = evaluate_historical_policy(
            "gate", constraint_gate_policy, suite.cases
        )
        self.assertEqual(result.accuracy, 1.0)
        self.assertEqual(result.false_accept_rate, 0.0)
        self.assertEqual(result.failures, ())
        unseen = {
            "mechanism_id": "UNSEEN",
            "surface_confidence": "HIGH",
            "evidence_state": "SUPPORTED",
            "constraints": ({"constraint_id": "new_gate", "status": "FAIL"},),
        }
        self.assertFalse(constraint_gate_policy(unseen))

    def test_historical_run_reports_no_per_observation_rules(self) -> None:
        result = run_historical_benchmark(
            load_historical_benchmark(DEFAULT_CASE_PATH)
        )
        self.assertEqual(result["regression"]["status"], "PASS")
        self.assertEqual(result["regression"]["known_bad_failures_detected"], 12)
        self.assertEqual(result["architecture"]["mechanism_specific_branches"], 0)
        self.assertEqual(result["architecture"]["per_observation_rules"], 0)

    def test_historical_fixture_contains_no_private_locator(self) -> None:
        text = DEFAULT_CASE_PATH.read_text(encoding="utf-8")
        for marker in ("drive.google.com", "docs.google.com", "PRIVATE CANDIDATE", "L0_"):
            self.assertNotIn(marker, text)

    def test_historical_cli_emits_json_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            json_output = Path(temporary) / "historical.json"
            markdown_output = Path(temporary) / "historical.md"
            self.assertEqual(
                main(
                    [
                        "--suite",
                        "historical",
                        "--cases",
                        str(DEFAULT_CASE_PATH),
                        "--output",
                        str(json_output),
                    ]
                ),
                0,
            )
            self.assertEqual(
                main(
                    [
                        "--suite",
                        "historical",
                        "--cases",
                        str(DEFAULT_CASE_PATH),
                        "--format",
                        "markdown",
                        "--output",
                        str(markdown_output),
                    ]
                ),
                0,
            )
            result = json.loads(json_output.read_text(encoding="utf-8"))
            self.assertEqual(result["fixture_count"], 24)
            self.assertIn(
                "| Confidence-only baseline | 50% | 100% | 12 |",
                markdown_output.read_text(encoding="utf-8"),
            )

    def test_sqlite_store_persists_complete_experiment_metadata(self) -> None:
        result = run_historical_benchmark(
            load_historical_benchmark(DEFAULT_CASE_PATH)
        )
        result["run_id"] = "RUN-STORE-001"
        with tempfile.TemporaryDirectory() as temporary:
            store = Path(temporary) / "runs.sqlite3"
            record = persist_experiment_run(
                store,
                result,
                suite="historical",
                model="deterministic-reference",
                prompt_version="hfb-v1",
                git_commit="abc123",
                latency_ms=12.5,
                token_cost=0.0,
                created_at_utc="2026-08-15T19:00:00Z",
            )
            self.assertEqual(record["run_id"], "RUN-STORE-001")
            self.assertEqual(record["case_suite_version"], "HISTORICAL-FAILURE-BENCHMARK-v1")
            self.assertEqual(record["treatment_accuracy"], 1.0)
            listed = list_experiment_runs(store, 1)
            self.assertEqual(listed, [record])
            with sqlite3.connect(store) as connection:
                version = connection.execute("PRAGMA user_version").fetchone()[0]
                payload = connection.execute(
                    "SELECT result_json FROM experiment_runs WHERE run_id = ?",
                    ("RUN-STORE-001",),
                ).fetchone()[0]
            self.assertEqual(version, 1)
            self.assertEqual(json.loads(payload)["fixture_count"], 24)

    def test_sqlite_store_is_immutable_by_run_id(self) -> None:
        result = run_historical_benchmark(
            load_historical_benchmark(DEFAULT_CASE_PATH)
        )
        result["run_id"] = "RUN-DUPLICATE"
        with tempfile.TemporaryDirectory() as temporary:
            store = Path(temporary) / "runs.sqlite3"
            kwargs = {
                "suite": "historical",
                "model": "deterministic-reference",
                "prompt_version": "hfb-v1",
                "git_commit": "abc123",
                "latency_ms": 1.0,
            }
            persist_experiment_run(store, result, **kwargs)
            with self.assertRaisesRegex(ValueError, "already exists"):
                persist_experiment_run(store, result, **kwargs)
            self.assertEqual(len(list_experiment_runs(store)), 1)

    def test_sqlite_store_accepts_runtime_closure_suite(self) -> None:
        result = run_experiment(load_case_suite(DEFAULT_CASE_PATH))
        result["run_id"] = "RUN-CLOSURE-001"
        with tempfile.TemporaryDirectory() as temporary:
            store = Path(temporary) / "runs.sqlite3"
            persist_experiment_run(
                store,
                result,
                suite="closure",
                model="companion-mind-closure-guard",
                prompt_version="none",
                git_commit="abc123",
                latency_ms=2.0,
            )
            row = list_experiment_runs(store, 1)[0]
            self.assertEqual(row["case_suite_version"], "EVAL-CASE-001")
            self.assertEqual(row["baseline_accuracy"], 0.2)
            self.assertEqual(row["treatment_accuracy"], 1.0)

    def _seed_api_store(self, store: Path, run_id: str = "RUN-API-001") -> None:
        result = run_historical_benchmark(
            load_historical_benchmark(DEFAULT_CASE_PATH)
        )
        result["run_id"] = run_id
        persist_experiment_run(
            store,
            result,
            suite="historical",
            model="deterministic-reference",
            prompt_version="hfb-v1",
            git_commit="abc123",
            latency_ms=3.5,
            created_at_utc="2026-08-15T20:00:00Z",
        )

    @unittest.skipUnless(HAS_FASTAPI, "FastAPI is not installed")
    def test_api_exposes_only_read_routes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = Path(temporary) / "runs.sqlite3"
            self._seed_api_store(store)
            app = create_app(store)
            methods = {
                method
                for route in app.routes
                for method in (getattr(route, "methods", None) or set())
            }
            self.assertTrue(methods)
            self.assertEqual(methods - {"GET", "HEAD"}, set())

    @unittest.skipUnless(HAS_FASTAPI, "FastAPI is not installed")
    def test_api_health_reports_read_only_schema(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = Path(temporary) / "runs.sqlite3"
            self._seed_api_store(store)
            status, body = asgi_get(create_app(store), "/healthz")
            self.assertEqual(status, 200)
            self.assertEqual(body["status"], "ok")
            self.assertTrue(body["read_only"])
            self.assertEqual(body["store_schema_version"], 1)

    @unittest.skipUnless(HAS_FASTAPI, "FastAPI is not installed")
    def test_api_lists_metadata_and_returns_canonical_detail(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = Path(temporary) / "runs.sqlite3"
            self._seed_api_store(store)
            app = create_app(store)
            list_status, rows = asgi_get(app, "/v1/runs", b"limit=1")
            self.assertEqual(list_status, 200)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["run_id"], "RUN-API-001")
            self.assertNotIn("result", rows[0])
            detail_status, detail = asgi_get(app, "/v1/runs/RUN-API-001")
            self.assertEqual(detail_status, 200)
            self.assertEqual(detail["run_id"], "RUN-API-001")
            self.assertEqual(detail["result"]["fixture_count"], 24)
            self.assertEqual(
                get_experiment_run(store, "RUN-API-001"), detail
            )

    @unittest.skipUnless(HAS_FASTAPI, "FastAPI is not installed")
    def test_api_returns_404_for_unknown_run(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = Path(temporary) / "runs.sqlite3"
            self._seed_api_store(store)
            status, body = asgi_get(create_app(store), "/v1/runs/UNKNOWN")
            self.assertEqual(status, 404)
            self.assertEqual(body["detail"], "experiment run not found")

    @unittest.skipUnless(HAS_FASTAPI, "FastAPI is not installed")
    def test_api_queries_do_not_mutate_the_sqlite_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = Path(temporary) / "runs.sqlite3"
            self._seed_api_store(store)
            before = hashlib.sha256(store.read_bytes()).hexdigest()
            app = create_app(store)
            asgi_get(app, "/healthz")
            asgi_get(app, "/v1/runs", b"limit=1")
            asgi_get(app, "/v1/runs/RUN-API-001")
            after = hashlib.sha256(store.read_bytes()).hexdigest()
            self.assertEqual(after, before)

    def test_cli_persists_lists_and_emits_structured_logs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            store = Path(temporary) / "runs.sqlite3"
            report = Path(temporary) / "run.json"
            listing = Path(temporary) / "runs.json"
            error = io.StringIO()
            with redirect_stderr(error):
                exit_code = main(
                    [
                        "--suite",
                        "historical",
                        "--cases",
                        str(DEFAULT_CASE_PATH),
                        "--store",
                        str(store),
                        "--run-id",
                        "RUN-CLI-001",
                        "--model",
                        "deterministic-reference",
                        "--prompt-version",
                        "hfb-v1",
                        "--git-commit",
                        "abc123",
                        "--log-json",
                        "--output",
                        str(report),
                    ]
                )
            self.assertEqual(exit_code, 0)
            events = [json.loads(line)["event"] for line in error.getvalue().splitlines()]
            self.assertEqual(events, ["run_started", "run_completed", "run_persisted"])
            persisted = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(persisted["run_id"], "RUN-CLI-001")
            self.assertEqual(persisted["experiment"]["git_commit"], "abc123")
            self.assertEqual(
                main(
                    [
                        "--store",
                        str(store),
                        "--list-runs",
                        "1",
                        "--output",
                        str(listing),
                    ]
                ),
                0,
            )
            rows = json.loads(listing.read_text(encoding="utf-8"))
            self.assertEqual(rows[0]["run_id"], "RUN-CLI-001")

    def test_cli_rejects_list_without_store(self) -> None:
        error = io.StringIO()
        with redirect_stderr(error):
            exit_code = main(["--list-runs", "1"])
        self.assertEqual(exit_code, 2)
        self.assertIn("requires --store", error.getvalue())

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
