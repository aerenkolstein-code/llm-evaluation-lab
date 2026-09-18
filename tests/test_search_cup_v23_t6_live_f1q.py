"""Offline candidate tests and explicit qualification harness; no live API/key.

The protocol module stays inert. Only this test/harness surface owns process
guards, read-only source verification and temporary artifact publication.
"""
from __future__ import annotations

import argparse
import ast
import contextlib
from dataclasses import asdict
import hashlib
import http.client
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
if __name__ == "__main__":
    # Script invocation must resolve the checked-out repository, not an installed
    # wheel or another package with the same name.
    sys.path.insert(0, str(ROOT))

from search_cup.contracts import SearchRequest, SearchResult, canonical_json, fingerprint
from search_cup.protocol_v23 import assert_content_safe, f1_eligibility
from search_cup.tools import BudgetedSearchProxy, SearchBackendError, SearchBudgetExceeded
from search_cup.v23_t6_live_brave_retriever import (
    API_VERSION, BACKEND_ID, CANDIDATE_ID, DEFAULT_CONFIG, PARAMETERS,
    BraveWebRawRetriever, WebRequest, WebResponse, validate_config,
)
from search_cup.v23_t6_live_f1q import (
    BASELINE_SHA, BASELINE_TREE, SCOPE, REQUEST_CONTRACT, RESULT_CONTRACT,
    build_descriptor, inspect_adapter, validate_doc_evidence,
)


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if type(value) is not dict:
        raise ValueError("INVALID_DOCUMENT")
    assert_content_safe(value)
    return value


class OfflineSandbox:
    """Deny socket creation/DNS and secret environment reads during qualification.

    Git checkout/setup and artifact upload are outside this sandbox and are not
    falsely counted as offline. Negative guard tests can record blocked attempts.
    """
    def __init__(self) -> None:
        self.counts = {"blocked_network_attempts": 0, "blocked_secret_reads": 0}
        self._stack = contextlib.ExitStack()

    def __enter__(self) -> "OfflineSandbox":
        def denied(*args, **kwargs):
            self.counts["blocked_network_attempts"] += 1
            raise RuntimeError("OFFLINE_NETWORK_FORBIDDEN")
        original = type(os.environ).__getitem__
        def guarded(env, key):
            upper = str(key).upper()
            if any(word in upper for word in ("TOKEN", "SECRET", "PASSWORD", "CREDENTIAL", "API_KEY", "APIKEY")):
                self.counts["blocked_secret_reads"] += 1
                raise RuntimeError("OFFLINE_SECRET_READ_FORBIDDEN")
            return original(env, key)
        for target in ("socket.socket", "socket.create_connection", "socket.getaddrinfo",
                       "urllib.request.urlopen", "urllib.request.OpenerDirector.open",
                       "http.client.HTTPConnection.connect", "http.client.HTTPSConnection.connect"):
            self._stack.enter_context(patch(target, side_effect=denied))
        self._stack.enter_context(patch.object(type(os.environ), "__getitem__", guarded))
        return self

    def __exit__(self, *exc) -> None:
        self._stack.close()


def _git(root: Path, *args: str) -> str:
    proc = subprocess.run(["git", *args], cwd=root, text=True, capture_output=True, check=False)
    if proc.returncode:
        raise ValueError("SOURCE_GIT_GUARD_FAILED")
    return proc.stdout.strip()


def source_guard(root: Path) -> dict:
    head = _git(root, "rev-parse", "HEAD")
    if _git(root, "rev-parse", BASELINE_SHA + "^{tree}") != BASELINE_TREE:
        raise ValueError("BASELINE_DRIFT")
    _git(root, "merge-base", "--is-ancestor", BASELINE_SHA, "HEAD")
    changes = _git(root, "diff", "--name-status", "--no-renames", BASELINE_SHA, "HEAD").splitlines()
    expected = sorted("A\t" + path for path in SCOPE)
    if sorted(changes) != expected:
        raise ValueError("SCOPE_AMENDMENT_REQUIRED")
    if _git(root, "status", "--porcelain", "--untracked-files=normal"):
        raise ValueError("DIRTY_QUALIFICATION_SOURCE")
    hashes = {}
    for path in SCOPE:
        p = root / path
        if not p.is_file() or p.is_symlink():
            raise ValueError("INVALID_SOURCE_FILE")
        hashes[path] = hashlib.sha256(p.read_bytes()).hexdigest()
    return {"base_sha": BASELINE_SHA, "base_tree": BASELINE_TREE, "head_sha": head,
            "head_tree": _git(root, "rev-parse", "HEAD^{tree}"), "changes": changes,
            "source_sha256": hashes, "scope_status": "PASS"}


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

    def test_r4_pure_module_preserves_existing_protocol_boundary(self):
        tree = ast.parse((ROOT / SCOPE[1]).read_text(encoding="utf-8"))
        forbidden = {"os", "socket", "subprocess", "requests", "httpx", "http", "urllib"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                self.assertFalse({a.name.split(".")[0] for a in node.names} & forbidden)
            elif isinstance(node, ast.ImportFrom):
                self.assertNotIn((node.module or "").split(".")[0], forbidden)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                self.assertNotIn(node.func.id, {"eval", "exec", "__import__", "open"})


class RecordingResult(unittest.TextTestResult):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.case_records = []
    def addSuccess(self, test):
        super().addSuccess(test)
        self.case_records.append({"id": test.id(), "status": "PASS"})
    def addFailure(self, test, err):
        super().addFailure(test, err)
        self.case_records.append({"id": test.id(), "status": "FAIL"})
    def addError(self, test, err):
        super().addError(test, err)
        self.case_records.append({"id": test.id(), "status": "ERROR"})
    def addSkip(self, test, reason):
        super().addSkip(test, reason)
        self.case_records.append({"id": test.id(), "status": "SKIP"})


def run_qualification(root: Path, output: Path) -> dict:
    root, output = root.resolve(), output.resolve()
    if output.exists() or root == output or root in output.parents:
        raise ValueError("FRESH_OUTPUT_OUTSIDE_REPOSITORY_REQUIRED")
    before = source_guard(root)
    config = load_json(root / SCOPE[2])
    documents = load_json(root / SCOPE[3])
    validate_config(config)
    validate_doc_evidence(documents)
    assessment = inspect_adapter((root / SCOPE[0]).read_text(encoding="utf-8"))
    stream = io.StringIO()
    # This explicit test harness owns I/O. The production qualification assembler
    # neither imports the harness nor dispatches tests or transports.
    with OfflineSandbox() as sandbox:
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(T6LiveF1QualificationTests)
        result = unittest.TextTestRunner(stream=stream, verbosity=2, resultclass=RecordingResult).run(suite)
    after = source_guard(root)
    if before != after:
        raise ValueError("SOURCE_CHANGED_DURING_QUALIFICATION")
    tests = {"tests_run": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
             "skipped": len(result.skipped), "cases": result.case_records}
    descriptor, matrix = build_descriptor(config, documents, before, tests, assessment)
    bounds = {"scope": "Qualification Python process only; platform GitHub checkout/setup/upload are control-plane operations.",
              "no_default_transport": True, "live_transport_qualification": "NOT_PERFORMED",
              "live_api_calls": 0, "provider_calls": 0, "model_calls": 0,
              "credential_reads": 0, "network_calls": 0, "search_credit_consumption": 0,
              "automatic_retries": 0, "spend": {"currency": "USD", "amount": 0},
              "t6_live_runs": 0, "official_prompt_consumed": False, "hidden_registry_loaded": False,
              "guard_observations": sandbox.counts}
    receipt = {"schema_id": "t6-live-f1q-receipt/v1", "work_order": "WO-ENG-B1-SC-V23-T6-LIVE-F1Q-01/v0.1",
               "candidate_id": CANDIDATE_ID, "qualification_result": matrix["qualification_result"],
               "source": before, "config_fingerprint": fingerprint(config),
               "candidate_fingerprint": fingerprint(descriptor), "test_summary": {k: v for k, v in tests.items() if k != "cases"},
               "r1_r8_status": {k: v["status"] for k, v in matrix["criteria"].items()},
               **bounds, "independent_qa": "PENDING", "publication": "NOT_AUTHORIZED",
               "parent_d6": "BLOCKED_NOT_F1_ELIGIBLE" if matrix["qualification_result"] != "F1_ELIGIBLE" else "AWAIT_INDEPENDENT_QA_AND_PUBLICATION", "live_execution_authorized": False}
    manifest = {"schema_id": "t6-live-f1q-artifact/v1", "candidate_id": CANDIDATE_ID,
                "source_sha": before["head_sha"], "source_tree": before["head_tree"], "api_version": API_VERSION,
                "evidence_scope": matrix["basis"], "docs_fingerprint": documents["canonical_fingerprint"]}
    payloads = {"manifest.json": manifest, "candidate-descriptor.json": descriptor, "config.json": config,
                "official-doc-evidence.json": documents, "source-evidence.json": {**before, "adapter_assessment": assessment},
                "r1-r8.json": matrix, "capability-boundary.json": bounds,
                "request-response-contract.json": {"request": REQUEST_CONTRACT, "result": RESULT_CONTRACT},
                "negative-tests.json": tests, "qualification-receipt.json": receipt}
    output.mkdir(parents=True, exist_ok=False)
    for name, payload in payloads.items():
        assert_content_safe(payload)
        (output / name).write_text(canonical_json(payload) + "\n", encoding="utf-8")
    (output / "focused-tests.log").write_text(stream.getvalue(), encoding="utf-8")
    lines = [hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name
             for path in sorted(output.iterdir()) if path.is_file()]
    (output / "MANIFEST.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return receipt


def qualification_main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        receipt = run_qualification(Path(__file__).resolve().parents[1], args.output)
    except (ValueError, OSError):
        print("T6_QUALIFICATION_STOP: source/evidence/output prerequisite failed", file=sys.stderr)
        return 2
    print("T6_QUALIFICATION_RECEIPT=" + canonical_json(receipt))
    return 0 if receipt["qualification_result"] == "F1_ELIGIBLE" else 1


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--qualify":
        raise SystemExit(qualification_main(sys.argv[2:]))
    unittest.main()
