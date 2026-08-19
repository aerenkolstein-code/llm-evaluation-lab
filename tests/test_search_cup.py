"""ENG-SC-01-P0 offline fairness and determinism gates."""

from __future__ import annotations

import dataclasses
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout

from search_cup.cli import main as search_cup_main
from search_cup.contracts import (
    CandidateCard,
    CompetitionSpec,
    FrozenSubmission,
    JudgeRegistrySnapshot,
    Lead,
    RegistryLeadAssessment,
    SearchResult,
    Submission,
    URLReadResult,
)
from search_cup.demo import (
    DEFAULT_CANDIDATE,
    DEFAULT_COMPETITION,
    build_offline_demo,
)
from search_cup.judge import HiddenRegistryGate, RegistryAccessDenied, judge_match
from search_cup.providers import (
    FailingFakeProvider,
    FakeProvider,
    LiveProviderNotImplemented,
    LockedLiveProvider,
)
from search_cup.runner import EntrantOutcome, MatchRun, run_match
from search_cup.search_pro import SearchProBackend, TransportResponse
from search_cup.tools import (
    BudgetedSearchProxy,
    EntrantTools,
    FakeSearchBackend,
    FakeURLReader,
    SearchBackendError,
    SearchBudgetExceeded,
)


def make_lead(url: str = "https://jobs.example.test/role") -> Lead:
    return Lead(
        company="Synthetic Employer",
        role="AI Evaluation Engineer",
        source_url=url,
        official_source=True,
        open_status="OPEN",
        remote_scope="Europe Remote",
        location_constraint="Spain eligible",
        employment_type="Contract",
        required_skills=("Python",),
        candidate_fit="Relevant public evidence.",
        mismatch_risks=(),
        portfolio_relevance="Evaluation repository.",
        confidence=0.9,
        next_action="Human review.",
        evidence_urls=(url,),
        claimed_novel=True,
    )


class ContractTests(unittest.TestCase):
    def test_candidate_fingerprint_is_order_independent(self) -> None:
        document = dict(CandidateCard.load(DEFAULT_CANDIDATE).as_dict())
        reversed_document = dict(reversed(tuple(document.items())))
        self.assertEqual(
            CandidateCard.from_mapping(document).fingerprint,
            CandidateCard.from_mapping(reversed_document).fingerprint,
        )

    def test_candidate_rejects_private_fields(self) -> None:
        document = dict(CandidateCard.load(DEFAULT_CANDIDATE).as_dict())
        document["health"] = {"condition": "private"}
        with self.assertRaisesRegex(ValueError, "private field"):
            CandidateCard.from_mapping(document)

    def test_candidate_uses_current_55_test_baseline(self) -> None:
        content = CandidateCard.load(DEFAULT_CANDIDATE).canonical_content
        self.assertIn("55/55", content)
        self.assertNotIn("51/51", content)

    def test_competition_freezes_four_exact_provider_identities(self) -> None:
        spec = CompetitionSpec.load(DEFAULT_COMPETITION)
        self.assertEqual(20, spec.max_search_calls)
        self.assertFalse(spec.official_match_authorized)
        self.assertEqual(
            {"OpenAI", "Gemini", "DeepSeek", "GLM"},
            {entrant.provider for entrant in spec.entrants},
        )
        self.assertTrue(all(entrant.exact_model_id for entrant in spec.entrants))

    def test_submission_rejects_apply_now_outside_ranked_leads(self) -> None:
        entrant = CompetitionSpec.load(DEFAULT_COMPETITION).entrants[0]
        with self.assertRaisesRegex(ValueError, "Apply-Now"):
            Submission(
                entrant=entrant,
                candidate_fingerprint="candidate",
                competition_fingerprint="competition",
                leads=(make_lead(),),
                apply_now_urls=("https://jobs.example.test/other",),
                search_strategy_summary="fixture",
                rejected_or_downgraded=(),
                uncertainties=(),
                search_calls=1,
            )

    def test_frozen_submission_detects_tampering(self) -> None:
        match, _, _ = build_offline_demo()
        frozen = match.frozen_outcomes[0].frozen_submission
        self.assertIsNotNone(frozen)
        assert frozen is not None
        frozen.thaw_verified()
        tampered = FrozenSubmission(
            entrant_id=frozen.entrant_id,
            canonical_content=frozen.canonical_content + " ",
            sha256=frozen.sha256,
        )
        with self.assertRaisesRegex(ValueError, "hash mismatch"):
            tampered.thaw_verified()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            frozen.sha256 = "replacement"  # type: ignore[misc]


class ToolBoundaryTests(unittest.TestCase):
    def test_call_21_is_physically_rejected(self) -> None:
        backend_calls: list[str] = []

        def backend(request):
            backend_calls.append(request.query)
            return ()

        proxy = BudgetedSearchProxy("entrant", 20, backend)
        for index in range(20):
            proxy.search(f"query {index}")
        with self.assertRaises(SearchBudgetExceeded):
            proxy.search("query 21")
        self.assertEqual(20, len(backend_calls))
        self.assertEqual(20, proxy.calls_used)

    def test_failed_backend_attempt_consumes_one_ticket(self) -> None:
        def fail(_):
            raise TimeoutError("offline injected failure")

        proxy = BudgetedSearchProxy("entrant", 20, fail)
        with self.assertRaises(TimeoutError):
            proxy.search("query")
        self.assertEqual(1, proxy.calls_used)
        self.assertEqual("FAILED", proxy.traces[0].status)
        self.assertEqual("TimeoutError", proxy.traces[0].error_type)

    def test_invalid_empty_query_is_a_failed_budget_event(self) -> None:
        backend_calls = 0

        def backend(_request):
            nonlocal backend_calls
            backend_calls += 1
            return ()

        proxy = BudgetedSearchProxy("entrant", 20, backend)
        with self.assertRaisesRegex(ValueError, "non-empty"):
            proxy.search("   ")
        self.assertEqual(0, backend_calls)
        self.assertEqual(1, proxy.calls_used)
        self.assertEqual("FAILED", proxy.traces[0].status)
        self.assertEqual("UNEXPECTED_BACKEND_ERROR", proxy.traces[0].error_code)

    def test_url_reader_returns_typed_not_found_without_fallback(self) -> None:
        result = FakeURLReader({}).read("https://example.test/missing")
        self.assertEqual("NOT_FOUND", result.status)

    def test_entrant_tool_surface_has_no_registry_access(self) -> None:
        tools = EntrantTools(
            BudgetedSearchProxy("entrant", 20, FakeSearchBackend({})),
            FakeURLReader({}),
        )
        self.assertFalse(hasattr(tools, "registry"))
        self.assertFalse(hasattr(tools, "judge_snapshot"))

    def test_search_pro_normalizes_real_contract_and_traces_identity(self) -> None:
        captured: dict[str, object] = {}

        def transport(endpoint, headers, payload, timeout):
            captured.update(
                endpoint=endpoint,
                headers=dict(headers),
                payload=dict(payload),
                timeout=timeout,
            )
            return TransportResponse(
                200,
                json.dumps(
                    {
                        "id": "backend-response-1",
                        "request_id": payload["request_id"],
                        "search_result": [
                            {
                                "title": " Example role ",
                                "link": "https://jobs.example.test/live-role",
                                "content": " Search snippet. ",
                                "media": "Example",
                            }
                        ],
                    }
                ).encode("utf-8"),
            )

        secret = "test-secret-must-not-enter-trace"
        proxy = BudgetedSearchProxy(
            "fake-entrant",
            20,
            SearchProBackend(secret, count=7, transport=transport),
        )
        results = proxy.search("AI evaluation remote Europe")
        self.assertEqual(
            (
                SearchResult(
                    title="Example role",
                    url="https://jobs.example.test/live-role",
                    snippet="Search snippet.",
                ),
            ),
            results,
        )
        payload = captured["payload"]
        self.assertIsInstance(payload, dict)
        assert isinstance(payload, dict)
        self.assertEqual("search_pro", payload["search_engine"])
        self.assertEqual(7, payload["count"])
        trace = proxy.traces[0]
        self.assertEqual(1, trace.call_number)
        self.assertEqual("zhipu-web-search/search_pro", trace.backend_id)
        self.assertEqual("backend-response-1", trace.backend_response_id)
        self.assertEqual(1, trace.result_count)
        self.assertEqual(0, trace.automatic_retries)
        self.assertNotIn(secret, json.dumps(dataclasses.asdict(trace)))

    def test_search_pro_http_failure_consumes_ticket_without_hidden_retry(self) -> None:
        transport_calls = 0

        def transport(_endpoint, _headers, payload, _timeout):
            nonlocal transport_calls
            transport_calls += 1
            return TransportResponse(
                429,
                json.dumps(
                    {
                        "request_id": payload["request_id"],
                        "error": {"code": "1302", "message": "rate limited"},
                    }
                ).encode("utf-8"),
            )

        proxy = BudgetedSearchProxy(
            "fake-entrant", 20, SearchProBackend("test-key", transport=transport)
        )
        with self.assertRaisesRegex(SearchBackendError, "1302"):
            proxy.search("query")
        self.assertEqual(1, transport_calls)
        self.assertEqual(1, proxy.calls_used)
        trace = proxy.traces[0]
        self.assertEqual("FAILED", trace.status)
        self.assertEqual("1302", trace.error_code)
        self.assertEqual(429, trace.http_status)
        self.assertTrue(trace.retryable)
        self.assertEqual(1, trace.backend_attempts)
        self.assertEqual(0, trace.automatic_retries)

    def test_search_pro_malformed_result_is_an_audited_failure(self) -> None:
        def transport(_endpoint, _headers, payload, _timeout):
            return TransportResponse(
                200,
                json.dumps(
                    {
                        "request_id": payload["request_id"],
                        "search_result": [{"title": "Missing link"}],
                    }
                ).encode("utf-8"),
            )

        proxy = BudgetedSearchProxy(
            "fake-entrant", 20, SearchProBackend("test-key", transport=transport)
        )
        with self.assertRaisesRegex(SearchBackendError, "missing title or link"):
            proxy.search("query")
        self.assertEqual(1, proxy.calls_used)
        self.assertEqual("INVALID_RESULT", proxy.traces[0].error_code)

    def test_search_pro_rejects_overlong_query_as_one_failed_budget_event(self) -> None:
        proxy = BudgetedSearchProxy(
            "fake-entrant", 20, SearchProBackend("test-key", transport=lambda *_: None)
        )
        with self.assertRaisesRegex(SearchBackendError, "70-character"):
            proxy.search("x" * 71)
        self.assertEqual(1, proxy.calls_used)
        self.assertEqual("INVALID_QUERY", proxy.traces[0].error_code)


class RunnerAndJudgeTests(unittest.TestCase):
    def test_four_entrant_offline_match_freezes_every_submission(self) -> None:
        match, _, _ = build_offline_demo()
        self.assertTrue(match.all_frozen)
        self.assertEqual(4, len(match.frozen_outcomes))
        self.assertEqual(0, len(match.failed_outcomes))
        self.assertEqual({1}, {len(outcome.traces) for outcome in match.outcomes})
        self.assertEqual(
            {match.candidate_fingerprint},
            {
                outcome.frozen_submission.thaw_verified().candidate_fingerprint
                for outcome in match.outcomes
                if outcome.frozen_submission is not None
            },
        )

    def test_one_provider_failure_preserves_other_frozen_evidence(self) -> None:
        candidate = CandidateCard.load(DEFAULT_CANDIDATE)
        spec = CompetitionSpec.load(DEFAULT_COMPETITION)
        lead = make_lead()
        providers = {
            entrant.entrant_id: FakeProvider((), (lead,), (lead.source_url,))
            for entrant in spec.entrants
        }
        providers[spec.entrants[1].entrant_id] = FailingFakeProvider()  # type: ignore[assignment]
        match = run_match(
            candidate,
            spec,
            providers,
            search_fixtures=lambda _: {},
            url_fixtures=lambda _: {},
        )
        self.assertEqual(3, len(match.frozen_outcomes))
        self.assertEqual(1, len(match.failed_outcomes))
        self.assertFalse(match.all_frozen)
        for outcome in match.frozen_outcomes:
            self.assertIsNotNone(outcome.frozen_submission)
            outcome.frozen_submission.thaw_verified()  # type: ignore[union-attr]

    def test_registry_refuses_access_before_execution_closes(self) -> None:
        match, snapshot, _ = build_offline_demo()
        open_match = MatchRun(
            competition_id=match.competition_id,
            candidate_fingerprint=match.candidate_fingerprint,
            competition_fingerprint=match.competition_fingerprint,
            expected_entrant_ids=match.expected_entrant_ids,
            outcomes=match.outcomes,
            entrant_execution_closed=False,
        )
        with self.assertRaisesRegex(RegistryAccessDenied, "still open"):
            HiddenRegistryGate.open(open_match, snapshot)

    def test_registry_refuses_partial_freeze(self) -> None:
        match, snapshot, _ = build_offline_demo()
        first = match.outcomes[0]
        partial = MatchRun(
            competition_id=match.competition_id,
            candidate_fingerprint=match.candidate_fingerprint,
            competition_fingerprint=match.competition_fingerprint,
            expected_entrant_ids=match.expected_entrant_ids,
            outcomes=(
                first,
                EntrantOutcome("missing", "FAILED", None, (), "Failure", "fixture"),
            ),
            entrant_execution_closed=True,
        )
        with self.assertRaisesRegex(RegistryAccessDenied, "must be frozen"):
            HiddenRegistryGate.open(partial, snapshot)

    def test_repeated_judging_is_byte_identical(self) -> None:
        match, snapshot, report = build_offline_demo()
        repeated = judge_match(match, snapshot)
        self.assertEqual(report.report_fingerprint, repeated.report_fingerprint)
        self.assertEqual(report.render_json(), repeated.render_json())
        self.assertEqual(report.render_markdown(), repeated.render_markdown())

    def test_registry_snapshot_hash_is_verified(self) -> None:
        match, snapshot, _ = build_offline_demo()
        tampered = dataclasses.replace(snapshot, fingerprint="0" * 64)
        with self.assertRaisesRegex(ValueError, "snapshot hash mismatch"):
            judge_match(match, tampered)

    def test_apply_now_errors_receive_double_penalty(self) -> None:
        match, snapshot, report = build_offline_demo()
        deepseek = next(
            score
            for score in report.scores
            if score.entrant_id == "deepseek-offline"
        )
        self.assertEqual(10.0, deepseek.penalties)
        self.assertIn("closed/stale", deepseek.judgments[0].reasons[0])

    def test_report_keeps_dimensions_and_exact_model_identity(self) -> None:
        _, _, report = build_offline_demo()
        document = json.loads(report.render_json())
        self.assertEqual(4, len(document["scores"]))
        self.assertTrue(
            all(
                item["exact_model_id"].startswith("fake-")
                for item in document["scores"]
            )
        )
        self.assertIn("search_efficiency", document["scores"][0])
        self.assertIn("behavior", document["scores"][0])


class CLIGateTests(unittest.TestCase):
    def test_preflight_reports_offline_lock(self) -> None:
        output = io.StringIO()
        with redirect_stdout(output):
            code = search_cup_main(["preflight"])
        self.assertEqual(0, code)
        result = json.loads(output.getvalue())
        self.assertEqual("OFFLINE_ONLY", result["mode"])
        self.assertFalse(result["official_match_authorized"])
        self.assertEqual(0, result["live_provider_adapters"])
        self.assertTrue(result["search_pro_backend_available"])
        self.assertTrue(result["live_search_requires_explicit_smoke_authorization"])

    def test_live_smoke_requires_manual_authorization_before_key_lookup(self) -> None:
        with self.assertRaisesRegex(ValueError, "authorize-live-search-smoke"):
            search_cup_main(["live-smoke", "--query", "non-official smoke"])

    def test_live_provider_is_explicitly_unimplemented(self) -> None:
        with self.assertRaisesRegex(LiveProviderNotImplemented, "outside ENG-SC-01-P0"):
            LockedLiveProvider("OpenAI").run()

    def test_p0_preflight_refuses_official_authorization(self) -> None:
        document = json.loads(DEFAULT_COMPETITION.read_text(encoding="utf-8"))
        document["official_match_authorized"] = True
        with tempfile.TemporaryDirectory() as directory:
            path = f"{directory}/authorized.json"
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(document, handle)
            with self.assertRaisesRegex(ValueError, "refuses"):
                search_cup_main(["preflight", "--competition", path])


if __name__ == "__main__":
    unittest.main()
