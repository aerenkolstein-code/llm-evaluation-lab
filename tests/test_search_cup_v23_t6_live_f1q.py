"""Offline tests. All responses are synthetic; no live API/key is involved."""
from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import socket
import unittest
from urllib.parse import parse_qs, urlsplit

from search_cup.contracts import SearchRequest, SearchResult, canonical_json, fingerprint
from search_cup.protocol_v23 import f1_eligibility
from search_cup.tools import BudgetedSearchProxy, SearchBackendError, SearchBudgetExceeded
from search_cup.v23_t6_live_brave_retriever import (
    API_VERSION, BACKEND_ID, DEFAULT_CONFIG, PARAMETERS, BraveWebRawRetriever, WebRequest, WebResponse,
)
from search_cup.v23_t6_live_f1q import (
    SCOPE, OfflineSandbox, build_descriptor, inspect_adapter, load_json, validate_doc_evidence,
)

ROOT = Path(__file__).resolve().parents[1]


def response(query="remote work", count=2):
    return {"type": "search", "query": {"original": query, "spellcheck_off": True, "should_fallback": False},
            "web": {"results": [{"title": f"Title {i}", "url": f"https://example.org/item/{i}",
                                   "description": f"Evidence {i}"} for i in range(count)]}}


class FakeTransport:
    def __init__(self, document=None, status=200, body=None, failure=None):
        self.document = document if document is not None else response()
        self.status, self.body, self.failure = status, body, failure
        self.calls = []

    def __call__(self, request):
        self.calls.append(request)
        if self.failure is not None:
            raise self.failure
        return WebResponse(self.status, self.body if self.body is not None else canonical_json(self.document).encode())


class T6LiveF1QualificationTests(unittest.TestCase):
    def request(self, query="remote work", entrant="fixture-a", number=1, identity="local-call-1"):
        return SearchRequest(entrant_id=entrant, query=query, call_number=number, request_id=identity)

    def assert_rejected(self, document=None, code=None, **kwargs):
        transport = FakeTransport(document=document, **kwargs)
        adapter = BraveWebRawRetriever(transport)
        with self.assertRaises(SearchBackendError) as raised:
            adapter(self.request())
        if code is not None:
            self.assertEqual(raised.exception.error_code, code)
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(adapter.receipts[-1]["result_count"], 0)
        return adapter, raised.exception

    def test_r1_query_bytes_preserved_by_encoding(self):
        query = "  Python + remote café & applications?  "
        transport = FakeTransport(document=response(query))
        adapter = BraveWebRawRetriever(transport)
        adapter(self.request(query))
        params = parse_qs(urlsplit(transport.calls[0].url).query)
        self.assertEqual(params["q"], [query])
        self.assertEqual(adapter.receipts[0]["query"], query)

    def test_r1_spellcheck_and_filter_explicit(self):
        wire = BraveWebRawRetriever().build_request(self.request())
        params = parse_qs(urlsplit(wire.url).query)
        self.assertEqual(params["spellcheck"], ["false"])
        self.assertEqual(params["result_filter"], ["web"])
        self.assertEqual(set(params), {"q", *PARAMETERS})

    def test_r1_original_mismatch_rejected(self):
        doc = response("rewritten")
        self.assert_rejected(doc, "NON_COMPARABLE_QUERY_ORIGINAL")

    def test_r1_altered_query_rejected_and_recorded(self):
        doc = response()
        doc["query"]["altered"] = "expanded words"
        adapter, _ = self.assert_rejected(doc, "NON_COMPARABLE_QUERY_ALTERED")
        self.assertEqual(adapter.receipts[0]["query_state"]["altered"], "expanded words")

    def test_r1_spellcheck_contradiction_rejected(self):
        doc = response()
        doc["query"]["spellcheck_off"] = False
        self.assert_rejected(doc, "NON_COMPARABLE_SPELLCHECK")

    def test_r1_backend_fallback_rejected_and_recorded(self):
        doc = response()
        doc["query"]["should_fallback"] = True
        adapter, _ = self.assert_rejected(doc, "NON_COMPARABLE_BACKEND_FALLBACK")
        self.assertTrue(adapter.receipts[0]["query_state"]["should_fallback"])

    def test_r1_malformed_fallback_not_coerced(self):
        for value in (0, 1, "false", [], {}):
            with self.subTest(kind=type(value).__name__):
                doc = response()
                doc["query"]["should_fallback"] = value
                self.assert_rejected(doc, "INVALID_QUERY_STATE")

    def test_r1_invalid_request_no_backend(self):
        transport = FakeTransport()
        adapter = BraveWebRawRetriever(transport)
        for request in (None, self.request("x" * 401), self.request(number=True)):
            with self.subTest(kind=type(request).__name__):
                with self.assertRaises(SearchBackendError):
                    adapter(request)
        self.assertEqual(transport.calls, [])

    def test_r2_one_request_one_transport_attempt(self):
        transport = FakeTransport()
        adapter = BraveWebRawRetriever(transport)
        adapter(self.request())
        self.assertEqual(len(transport.calls), 1)
        self.assertEqual(adapter.receipts[0]["backend_attempts"], 1)
        self.assertEqual(adapter.receipts[0]["automatic_retries"], 0)

    def test_r2_timeout_no_retry(self):
        adapter, error = self.assert_rejected(code="NETWORK_TIMEOUT", failure=TimeoutError("private transport details"))
        self.assertTrue(error.retryable)
        self.assertEqual(adapter.receipts[0]["automatic_retries"], 0)

    def test_r2_no_default_transport_or_key(self):
        with OfflineSandbox():
            adapter = BraveWebRawRetriever()
            with self.assertRaises(SearchBackendError) as raised:
                adapter(self.request())
        self.assertEqual(raised.exception.error_code, "LIVE_TRANSPORT_NOT_CONFIGURED")
        self.assertEqual(adapter.receipts[0]["backend_attempts"], 0)

    def test_r3_order_not_locally_reranked(self):
        doc = response(count=3)
        doc["web"]["results"].reverse()
        normalized = BraveWebRawRetriever(FakeTransport(doc))(self.request()).results
        self.assertEqual([r.title for r in normalized], ["Title 2", "Title 1", "Title 0"])

    def test_r3_entrant_identity_never_upstream(self):
        adapter = BraveWebRawRetriever()
        a = adapter.build_request(self.request(entrant="a", identity="one"))
        b = adapter.build_request(self.request(entrant="b", identity="two"))
        self.assertEqual(a, b)
        self.assertNotIn("entrant", parse_qs(urlsplit(a.url).query))

    def test_r3_goggles_or_rerank_signal_rejected(self):
        for key in ("goggles", "goggles_id", "rerank"):
            with self.subTest(key=key):
                doc = response()
                doc[key] = "non-frozen-control"
                self.assert_rejected(doc, "NON_COMPARABLE_ENHANCEMENT")

    def test_r4_config_closed_and_typed(self):
        mutations = {"count": 11, "api_version": "latest", "spellcheck": 0,
                     "endpoint": "https://example.org/other", "timeout_per_call_ms": 0,
                     "extra_property": True}
        for key, value in mutations.items():
            with self.subTest(key=key):
                bad = dict(DEFAULT_CONFIG)
                bad[key] = value
                with self.assertRaises(ValueError):
                    BraveWebRawRetriever(config=bad)

    def test_r4_version_header_and_timeout_frozen(self):
        wire = BraveWebRawRetriever().build_request(self.request())
        self.assertEqual(dict(wire.headers)["Api-Version"], "2023-01-01")
        self.assertEqual(API_VERSION, "2023-01-01")
        self.assertEqual(wire.timeout_ms, 15000)
        self.assertEqual(wire.method, "GET")
        self.assertNotIn("X-Subscription-Token", dict(wire.headers))

    def test_r4_file_config_matches_code(self):
        config = load_json(ROOT / SCOPE[2])
        self.assertEqual(canonical_json(config), canonical_json(dict(DEFAULT_CONFIG)))
        self.assertEqual(fingerprint(config), BraveWebRawRetriever().config_fingerprint)

    def test_r4_official_version_evidence_pinned(self):
        document = load_json(ROOT / SCOPE[3])
        validate_doc_evidence(document)
        ids = {r["id"]: r for r in document["records"]}
        self.assertEqual(ids["BRAVE-VERSIONING"]["api_version"], API_VERSION)
        self.assertEqual(ids["BRAVE-WEB-CHANGELOG"]["api_version"], API_VERSION)
        self.assertEqual(document["live_api_verification"], "NOT_PERFORMED")

    def test_r4_evidence_mutation_even_rehashed_rejected(self):
        doc = load_json(ROOT / SCOPE[3])
        doc["api_version"] = "unproven-date"
        doc["canonical_fingerprint"] = fingerprint({k: v for k, v in doc.items() if k != "canonical_fingerprint"})
        with self.assertRaises(ValueError):
            validate_doc_evidence(doc)

    def test_r4_source_has_no_network_key_module(self):
        source = (ROOT / SCOPE[0]).read_text()
        self.assertEqual(inspect_adapter(source)["client_source_status"], "PASS")
        self.assertEqual(inspect_adapter("import socket\n" + source.replace("from __future__ import annotations", ""))["client_source_status"], "FAIL")

    def test_r5_field_mapping_and_optional_description(self):
        doc = response()
        del doc["web"]["results"][0]["description"]
        result = BraveWebRawRetriever(FakeTransport(doc))(self.request()).results
        self.assertEqual(result[0], SearchResult("Title 0", "https://example.org/item/0", ""))
        self.assertEqual(result[1].snippet, "Evidence 1")

    def test_r5_non_web_categories_never_normalized(self):
        doc = response()
        doc["news"] = {"results": [{"title": "Do not return", "url": "https://example.org/news"}]}
        result = BraveWebRawRetriever(FakeTransport(doc))(self.request()).results
        self.assertEqual(len(result), 2)
        self.assertTrue(all("item" in r.url for r in result))

    def test_r5_empty_or_fewer_results_valid(self):
        for count in (0, 1, 10):
            with self.subTest(count=count):
                result = BraveWebRawRetriever(FakeTransport(response(count=count)))(self.request())
                self.assertEqual(len(result.results), count)

    def test_r5_over_limit_fails_not_truncates(self):
        self.assert_rejected(response(count=11), "RESULT_LIMIT_EXCEEDED")

    def test_r5_missing_web_or_invalid_result_rejected(self):
        doc = response()
        del doc["web"]
        self.assert_rejected(doc, "MISSING_WEB_RESULTS")
        for key, value in (("title", ""), ("url", "file:///private"), ("url", "https://name:pass@example.org/"), ("description", 2)):
            with self.subTest(key=key):
                doc = response()
                doc["web"]["results"][0][key] = value
                self.assert_rejected(doc, "UNSAFE_RESPONSE" if value == "file:///private" else "INVALID_RESULT")

    def test_r5_invalid_duplicate_nonfinite_json(self):
        for body in (b"{", b"\xff", b'{"web":{},"web":{}}', b'{"value":NaN}'):
            with self.subTest(body_kind=body[:1]):
                self.assert_rejected(body=body, code="INVALID_JSON")

    def test_r5_body_size_bounded(self):
        self.assert_rejected(body=b" " * (int(DEFAULT_CONFIG["max_response_bytes"]) + 1), code="INVALID_OR_OVERSIZE_BODY")

    def test_r6_budget_proxy_denies_fifth(self):
        transport = FakeTransport()
        proxy = BudgetedSearchProxy("a", 4, BraveWebRawRetriever(transport))
        for _ in range(4):
            proxy.search("remote work")
        with self.assertRaises(SearchBudgetExceeded):
            proxy.search("remote work")
        self.assertEqual(len(transport.calls), 4)
        self.assertEqual(proxy.calls_used, 4)

    def test_r6_failed_call_consumes_ticket_once(self):
        transport = FakeTransport(status=429)
        proxy = BudgetedSearchProxy("a", 1, BraveWebRawRetriever(transport))
        with self.assertRaises(SearchBackendError):
            proxy.search("remote work")
        with self.assertRaises(SearchBudgetExceeded):
            proxy.search("remote work")
        self.assertEqual(proxy.calls_used, 1)
        self.assertEqual(len(transport.calls), 1)

    def test_r6_shared_adapter_same_capability_envelope(self):
        transport = FakeTransport()
        adapter = BraveWebRawRetriever(transport)
        a, b = BudgetedSearchProxy("a", 4, adapter), BudgetedSearchProxy("b", 4, adapter)
        self.assertEqual(a.search("remote work"), b.search("remote work"))
        self.assertEqual(transport.calls[0], transport.calls[1])
        with self.assertRaises(TypeError):
            adapter.config["count"] = 1

    def test_r7_enhancements_disabled_or_absent(self):
        wire = BraveWebRawRetriever().build_request(self.request())
        params = parse_qs(urlsplit(wire.url).query)
        for key in ("summary", "extra_snippets", "enable_rich_callback", "include_fetch_metadata", "operators"):
            self.assertEqual(params[key], ["false"])
        for key in ("goggles", "freshness", "summarizer"):
            self.assertNotIn(key, params)
        self.assertEqual(urlsplit(wire.url).path, "/res/v1/web/search")

    def test_r7_enhanced_top_level_or_result_rejected(self):
        for key in ("summary", "summarizer", "rich"):
            with self.subTest(key=key):
                doc = response()
                doc[key] = {"available": True}
                self.assert_rejected(doc, "NON_COMPARABLE_ENHANCEMENT")
        doc = response()
        doc["web"]["results"][0]["extra_snippets"] = ["Extra"]
        self.assert_rejected(doc, "NON_COMPARABLE_ENHANCEMENT")

    def test_r7_offline_guard_blocks_network_and_secret_reads(self):
        with OfflineSandbox() as guard:
            with self.assertRaises(RuntimeError):
                socket.getaddrinfo("example.org", 443)
            with self.assertRaises(RuntimeError):
                socket.socket()
            with self.assertRaises(RuntimeError):
                os.environ.get("BRAVE_API_KEY")
        self.assertEqual(guard.counts["blocked_network_attempts"], 2)
        self.assertEqual(guard.counts["blocked_secret_reads"], 1)

    def test_r8_success_trace_and_hashes(self):
        transport = FakeTransport()
        adapter = BraveWebRawRetriever(transport)
        result = adapter(self.request())
        trace = adapter.receipts[0]
        required = {"request_id", "query", "call_number", "started_at_utc", "duration_ms", "backend_id",
                    "config_fingerprint", "http_status", "result_count", "error_code", "retryable",
                    "response_body_sha256", "normalized_result_fingerprint", "query_state"}
        self.assertTrue(required <= set(trace))
        self.assertEqual(trace["response_body_sha256"], hashlib.sha256(canonical_json(transport.document).encode()).hexdigest())
        self.assertEqual(trace["normalized_result_fingerprint"], fingerprint([asdict(r) for r in result.results]))
        self.assertEqual(trace["http_status"], 200)
        self.assertEqual(trace["backend_id"], BACKEND_ID)
        self.assertEqual(trace["request_id"], "local-call-1")

    def test_r8_http_errors_are_typed_no_retry(self):
        for status, code in ((400, "HTTP_ERROR"), (401, "HTTP_ERROR"), (429, "RATE_LIMIT"), (503, "HTTP_SERVER_ERROR")):
            with self.subTest(status=status):
                adapter, error = self.assert_rejected(status=status, code=code)
                self.assertEqual(error.http_status, status)
                self.assertEqual(adapter.receipts[0]["http_status"], status)

    def test_r8_transport_exception_not_leaked(self):
        sentinel = "SYNTHETIC_SECRET_VALUE_NOT_A_REAL_KEY"
        adapter, error = self.assert_rejected(failure=RuntimeError(sentinel), code="TRANSPORT_ERROR")
        self.assertNotIn(sentinel, str(error))
        self.assertNotIn(sentinel, canonical_json(adapter.receipts))
        self.assertTrue(error.__suppress_context__)

    def test_r8_unsafe_body_not_saved_or_hashed(self):
        doc = response()
        doc["credentials"] = "SYNTHETIC_SECRET_VALUE_NOT_A_REAL_KEY"
        adapter, error = self.assert_rejected(doc, "UNSAFE_RESPONSE")
        self.assertIsNone(adapter.receipts[0]["response_body_sha256"])
        self.assertNotIn("SYNTHETIC_SECRET", canonical_json(adapter.receipts))

    def test_r8_unsafe_request_identity_not_echoed(self):
        sentinel = "Bearer " + "x" * 20
        adapter = BraveWebRawRetriever(FakeTransport())
        with self.assertRaises(SearchBackendError) as caught:
            adapter(self.request(identity=sentinel))
        self.assertNotIn(sentinel, str(caught.exception))
        self.assertNotEqual(caught.exception.request_id, sentinel)
        self.assertEqual(adapter.receipts, ())

    def test_r8_receipt_copies_cannot_rewrite_history(self):
        adapter = BraveWebRawRetriever(FakeTransport())
        adapter(self.request())
        detached = adapter.receipts[0]
        detached["http_status"] = 500
        self.assertEqual(adapter.receipts[0]["http_status"], 200)

    def test_qualification_all_of_and_fingerprint_binding(self):
        config, evidence = load_json(ROOT / SCOPE[2]), load_json(ROOT / SCOPE[3])
        source = {"source_sha256": {SCOPE[0]: "a" * 64}}
        assessment = {"client_source_status": "PASS"}
        cases = [{"id": f"fixture.test_r{i}_unit_probe", "status": "PASS"} for i in range(1, 9)]
        tests = {"cases": cases, "failures": 0, "errors": 0, "skipped": 0}
        descriptor, matrix = build_descriptor(config, evidence, source, tests, assessment)
        self.assertEqual(matrix["qualification_result"], "NOT_F1_ELIGIBLE")
        self.assertEqual(matrix["criteria"]["R2"]["status"], "UNKNOWN")
        self.assertEqual(matrix["criteria"]["R7"]["status"], "UNKNOWN")
        # Synthetic predicate test only: never written as actual qualification.
        logical_fixture = json.loads(canonical_json(descriptor))
        for check in logical_fixture["qualification"]["criteria"].values():
            check["status"] = "PASS"
        self.assertEqual(f1_eligibility(logical_fixture), "F1_ELIGIBLE")
        for key in descriptor["qualification"]["criteria"]:
            for status in ("FAIL", "UNKNOWN"):
                changed = json.loads(canonical_json(logical_fixture))
                changed["qualification"]["criteria"][key]["status"] = status
                self.assertEqual(f1_eligibility(changed), "NOT_F1_ELIGIBLE")
        changed = json.loads(canonical_json(logical_fixture))
        changed["config_fingerprint"] = "b" * 64
        self.assertEqual(f1_eligibility(changed), "NOT_F1_ELIGIBLE")

    def test_qualification_missing_test_evidence_stays_unknown(self):
        config, evidence = load_json(ROOT / SCOPE[2]), load_json(ROOT / SCOPE[3])
        source = {"source_sha256": {SCOPE[0]: "a" * 64}}
        tests = {"cases": [], "failures": 0, "errors": 0, "skipped": 0}
        _, matrix = build_descriptor(config, evidence, source, tests, {"client_source_status": "PASS"})
        self.assertEqual(matrix["qualification_result"], "NOT_F1_ELIGIBLE")
        self.assertTrue(all(c["status"] == "UNKNOWN" for c in matrix["criteria"].values()))


if __name__ == "__main__":
    unittest.main()
