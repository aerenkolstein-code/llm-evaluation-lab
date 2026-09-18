"""Exact-candidate offline R1-R8 method evidence; independent acceptance stays pending."""
from __future__ import annotations

import argparse
import ast
from contextlib import ExitStack, contextmanager
from dataclasses import asdict, FrozenInstanceError
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
from types import SimpleNamespace
import unicodedata
from unittest.mock import patch

from .contracts import SearchRequest, SearchResult, canonical_json, fingerprint
from .protocol_v23 import f1_eligibility, seal, verify_seal
from .tools import BudgetedSearchProxy, SearchBackendError, SearchBackendResponse
from . import v23_frozen_retriever as nfr

WORK_ORDER = "WO-ENG-B1-SC-V23-T3-F1Q-R2-01 v0.1"
BASELINE_SHA = "34e147f26b582486474b4d4b29eae7494add2d4b"
BASELINE_TREE = "311b541fddf212060476a3f994581e06c71d98f0"
MODULE_PATH = "search_cup/v23_t3_f1q_r2.py"
TARGET_PATH = "configs/search-cup-v23-t3-f1q-r2-target.json"
TARGET_JSON_FINGERPRINT = "951cf7639c7be67d0645f62a2e9f487a83ffe4c344f9234fb44f0740f3c38ca5"
DESCRIPTOR_FINGERPRINT = "6715a759a36dd3039dbf36bb15636eb683e107caec3953c68adb8e92c93d4281"
ACCEPTED_NFR_PACKAGE = "ca6e7eb45499d3ab55cea7ecc16124bb05a09a11f4a13740d6b93b4ffcd7dd2f"
CODE_SHA256 = "0f87af3639d760c3dfad427f8d72f53f553a9c768d3f7b29d5b32cc8def95729"
REPO = "https://github.com/aerenkolstein-code/llm-evaluation-lab"
SOURCE_PINS = {
    nfr.CODE_PATH: CODE_SHA256,
    **nfr.INPUT_PINS,
    **{path: nfr.RETAINED_PINS[path] for path in (
        "search_cup/contracts.py", "search_cup/tools.py", "search_cup/protocol_v23.py", "search_cup/v23_schema.py")},
}
APPROVED_PATHS = tuple(sorted((MODULE_PATH, TARGET_PATH,
    "tests/test_search_cup_v23_t3_f1q_r2.py", "docs/search-cup-v23-t3-f1q-r2.md",
    ".github/workflows/t3-f1-retriever-qualification-r2-offline.yml")))
PAYLOADS = {
    "target": "target-descriptor.json", "qualification": "r1-r8-qualification.json",
    "evidence": "evidence-manifest.json", "runtime": "runtime-probe-receipt.json",
    "resources": "resource-zero-receipt.json", "receipt": "qualification-receipt.json",
}
CRITERIA = {
    "R1": "Original query is observable; only declared deterministic lexical normalization occurs.",
    "R2": "No entrant-specific planning, cross-query memory, decomposition or synthesis exists.",
    "R3": "One integer multiset-overlap score and score-desc/doc_id-asc ordering serve all entrants.",
    "R4": "Exact descriptor, Unicode runtime, source, config and versioned interfaces are reproducible.",
    "R5": "Typed SearchBackendResponse/SearchResult preserve document fields and request/backend identity.",
    "R6": "The identical immutable candidate/config/corpus and capability envelope serve all entrants.",
    "R7": "The qualification path contains no external, paid, intelligent, credential or fallback operation.",
    "R8": "Success and injected failure expose original query, call/request, timing, count and terminal provenance.",
}
EVIDENCE_IDS = {
    "R1": ["E_IMPL", "E_PROXY", "E_QUERY"],
    "R2": ["E_IMPL", "E_ENTRANTS", "E_IMMUTABLE"],
    "R3": ["E_IMPL", "E_CONFIG", "E_RANKING"],
    "R4": ["E_TARGET", "E_CONFIG", "E_SCHEMAS", "E_REPRODUCIBILITY"],
    "R5": ["E_IMPL", "E_SCHEMAS", "E_PROXY", "E_TYPED"],
    "R6": ["E_IMPL", "E_ENTRANTS", "E_IMMUTABLE", "E_CONFIG"],
    "R7": ["E_IMPL", "E_GUARD", "E_RESOURCES"],
    "R8": ["E_TARGET", "E_SCHEMAS", "E_PROXY", "E_SUCCESS", "E_FAILURE", "E_RESOURCES"],
}
ZERO_FIELDS = ("live_search_calls", "provider_calls", "model_calls", "network_calls", "credential_reads",
    "credit_consumption", "automatic_retries", "fallback_calls", "subprocess_calls", "e1_frozen_runs",
    "e1_live_runs", "t5_runs", "official_benchmark_runs")
GUARDED_TARGETS = (
    "socket.socket", "socket.create_connection", "socket.getaddrinfo", "urllib.request.urlopen",
    "http.client.HTTPConnection.request", "http.client.HTTPSConnection.request",
    "subprocess.Popen", "subprocess.run", "subprocess.call", "subprocess.check_call", "subprocess.check_output",
    "search_cup.search_pro.SearchProBackend.__init__", "search_cup.search_pro.SearchProBackend.__call__",
    "search_cup.search_pro.SearchProBackend.from_env", "search_cup.search_pro._default_transport",
    "search_cup.search_pro.run_live_smoke", "search_cup.runner.run_match", "search_cup.judge.judge_match",
    "search_cup.tools.FakeSearchBackend.__call__", "os.getenv",
)
ENTRANTS = ("fixture-ascii-A", "研究者/乙", "vendor-shaped/model-shaped", "0007 local entrant")
TRANSPARENT_QUERY = "  ＡＬＰＨＡ, alpha!!!  "
TOP_TEN = tuple(f"lex-{i:02}" for i in range(1, 11))
# These are algorithm-conformance expectations over the published fixture, not relevance labels.
CASES = tuple((f"entrant-{i}", TRANSPARENT_QUERY, entrant, TOP_TEN, "alpha alpha", 6, 3)
              for i, entrant in enumerate(ENTRANTS, 1)) + (
    ("nfkc", "ＣＡＦÉ!!!", ENTRANTS[0], ("lex-20",), "café", 0, 0),
    ("chinese", "数据目录", ENTRANTS[0], ("lex-20",), "数据目录", 0, 0),
    ("short", "猫 ab", ENTRANTS[0], ("lex-21",), "猫 ab", 0, 0),
    ("punctuation", "!!!", ENTRANTS[0], (), "", 0, 0),
    ("zero-score", "zzzzzz", ENTRANTS[0], (), "zzzzzz", 0, 0),
    ("repeat", TRANSPARENT_QUERY, ENTRANTS[0], TOP_TEN, "alpha alpha", 6, 3),
    ("multiset-cap", "alpha alpha alpha alpha", ENTRANTS[0], TOP_TEN, "alpha alpha alpha alpha", 9, 3),
    ("title-index", "record", ENTRANTS[0], TOP_TEN, "record", 4, 4),
)
TIMING_MODE = "CONTROLLED_SYNTHETIC_CLOCK_NOT_WALL_TIME_OR_PERFORMANCE"
LIMITATION = ("Exact pinned code/config and 14-document synthetic fixture only; source review complements finite probes. "
              "No production corpus, model-quality, universal retrieval-quality or execution-authority conclusion.")


class TargetIdentityMismatch(ValueError):
    def __init__(self, reason):
        self.reason = reason
        super().__init__("TARGET_IDENTITY_MISMATCH: " + reason)


class ExternalOperationBlocked(RuntimeError):
    pass


def baseline(sha=BASELINE_SHA, tree=BASELINE_TREE):
    if (sha, tree) != (BASELINE_SHA, BASELINE_TREE):
        raise ValueError("BASELINE_DRIFT")
    return {"sha": sha, "tree": tree}


def boundary():
    return {"independent_acceptance": "PENDING", "formal_f1_status": "PENDING_INDEPENDENT_ACCEPTANCE",
            "claims_ceiling": "F1_RETRIEVER_QUALIFICATION_ONLY", "t5_execution_authorized": False,
            "e1_execution_authorized": False, "live_execution_authorized": False}


def runtime_identity():
    return {"python_major_minor": f"{sys.version_info.major}.{sys.version_info.minor}",
            "unicode_data_version": unicodedata.unidata_version}


@contextmanager
def external_guard():
    """Fail closed at known transport/execution seams; not a hostile-code sandbox.

    Exact source pins and AST inspection close the call graph. Patching does not
    read environment values or invoke any blocked function. Package imports may
    load legacy definitions through search_cup.__init__; no legacy call is allowed.
    """
    attempts = []
    def deny(name):
        def blocked(*args, **kwargs):
            attempts.append(name)
            raise ExternalOperationBlocked("EXTERNAL_OPERATION_BLOCKED: " + name)
        return blocked
    class NoEnvironment:
        get = __getitem__ = __iter__ = __len__ = __contains__ = deny("environment_lookup")
        keys = values = items = copy = get
    with ExitStack() as stack:
        for target in GUARDED_TARGETS:
            stack.enter_context(patch(target, side_effect=deny(target)))
        stack.enter_context(patch("os.environ", NoEnvironment()))
        yield attempts


def resolve_target(root=None, *, expected_sha=BASELINE_SHA, expected_tree=BASELINE_TREE):
    """Read only the seven approved sources plus this method and target JSON."""
    baseline(expected_sha, expected_tree)
    if runtime_identity() != {"python_major_minor": "3.11", "unicode_data_version": "14.0.0"}:
        raise TargetIdentityMismatch("RUNTIME")
    root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    target_bytes = (root / TARGET_PATH).read_bytes()
    target = json.loads(target_bytes)
    if fingerprint(target) != TARGET_JSON_FINGERPRINT:
        raise TargetIdentityMismatch("TARGET_JSON")
    sources = {}
    for path, digest in SOURCE_PINS.items():
        data = (root / path).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise TargetIdentityMismatch("SOURCE_CONTENT")
        sources[path] = data.decode("utf-8")
    if (root / nfr.CODE_PATH).read_bytes() != Path(nfr.__file__).resolve().read_bytes():
        raise TargetIdentityMismatch("LOADED_IMPLEMENTATION")
    method_bytes = (root / MODULE_PATH).read_bytes()
    if method_bytes != Path(__file__).resolve().read_bytes():
        raise TargetIdentityMismatch("LOADED_METHOD")
    config = nfr.FrozenConfig(json.loads(sources[nfr.CONFIG_PATH]))
    fixture = json.loads(sources[nfr.FIXTURE_PATH])
    corpus = nfr.FrozenCorpus(fixture["documents"], expected_fingerprint=nfr.TEST_CORPUS_FINGERPRINT)
    header = {k: v for k, v in fixture.items() if k != "documents"}
    # Pure reconstruction of the published descriptor/package identity. This is
    # NOT an NFR conformance run, and its historical eight calls are not claimed here.
    published = nfr._assemble(config, corpus, CODE_SHA256, header, nfr.expected_observations(), 8)
    descriptor = published["candidate"]
    if descriptor["canonical_fingerprint"] != DESCRIPTOR_FINGERPRINT:
        raise TargetIdentityMismatch("DESCRIPTOR")
    if published["conformance"]["package_fingerprint"] != ACCEPTED_NFR_PACKAGE:
        raise TargetIdentityMismatch("NFR_PACKAGE")
    return {"target": target, "target_bytes_sha256": hashlib.sha256(target_bytes).hexdigest(),
            "method_sha256": hashlib.sha256(method_bytes).hexdigest(), "sources": sources,
            "config": config, "corpus": corpus, "descriptor": descriptor, "fixture_header": header}


def _node(source, symbol):
    nodes = ast.parse(source).body
    for name in symbol.split("."):
        node = next(n for n in nodes if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name == name)
        nodes = node.body
    return node


def source_observations(ctx):
    source = ctx["sources"][nfr.CODE_PATH]
    call = _node(source, "FrozenLexicalRetriever.__call__")
    candidate = _node(source, "FrozenLexicalRetriever")
    proxy = _node(ctx["sources"]["search_cup/tools.py"], "BudgetedSearchProxy.search")
    imports = sorted({(n.module or "") if isinstance(n, ast.ImportFrom) else a.name
                      for n in ast.walk(ast.parse(source)) if isinstance(n, (ast.Import, ast.ImportFrom))
                      for a in n.names})
    request_attrs = sorted({n.attr for n in ast.walk(candidate) if isinstance(n, ast.Attribute)
                            and isinstance(n.value, ast.Name) and n.value.id == "request"})
    call_names = [ast.unparse(n.func) for n in ast.walk(call) if isinstance(n, ast.Call)]
    writes = [ast.unparse(n) for n in ast.walk(call) if isinstance(n, (ast.Attribute, ast.Subscript))
              and isinstance(n.ctx, ast.Store)]
    fragments = {}
    for symbol in ("normalize", "character_units", "overlap", "FrozenLexicalRetriever.__init__",
                   "FrozenLexicalRetriever.__call__", "FrozenCorpus", "FrozenConfig", "CorpusDocument"):
        node = _node(source, symbol)
        fragments[symbol] = {"lines": [node.lineno, node.end_lineno],
                             "ast_fingerprint": fingerprint(ast.dump(node, include_attributes=False)),
                             "source_excerpt": ast.get_source_segment(source, node)}
    forbidden = {"os", "subprocess", "socket", "requests", "httpx", "search_pro", "runner", "judge", "providers"}
    expected_score = "sum(min(count, right_counts.get(unit, 0)) for unit, count in left)"
    checks = {
        "query_and_identity_only": request_attrs == ["query", "request_id"],
        "one_score_path": call_names.count("overlap") == 1 and ast.dump(_node(source, "overlap").body[-1].value)
                          == ast.dump(ast.parse(expected_score, mode="eval").body),
        "one_order_path": call_names.count("sorted") == 1 and "key=lambda row: (-row[0], row[1].doc_id)" in ast.unparse(call),
        "declared_limit_and_mapping": "[:10]" in ast.unparse(call) and "snippet=d.text[:240]" in ast.unparse(call),
        "no_state_writes_during_call": not writes,
        "no_external_candidate_imports": not any(m.split(".")[0] in forbidden for m in imports),
        "single_proxy_attempt_no_loop": sum(isinstance(n, ast.Call) and ast.unparse(n.func) == "self._backend"
                                            for n in ast.walk(proxy)) == 1 and not any(
                                                isinstance(n, (ast.For, ast.While)) for n in ast.walk(proxy)),
    }
    return {"imports": imports, "request_attributes": request_attrs, "retrieval_call_names": call_names,
            "state_writes": writes, "fragments": fragments, "checks": checks,
            "proxy_source_lines": [proxy.lineno, proxy.end_lineno],
            "proxy_ast_fingerprint": fingerprint(ast.dump(proxy, include_attributes=False))}


def _clock_time(i):
    return datetime(2000, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=i)


def _request_id(i):
    return "sc-" + f"{i:032x}"


def _state(candidate):
    return fingerprint({"corpus": candidate.corpus.canonical_content, "config": candidate.config.canonical_content,
                        "index": [(d.as_dict(), units) for d, units in candidate._index]})


def _golden_scores(case, corpus):
    name, _, _, _, _, first, rest = case
    return {d.doc_id: (first if d.doc_id == "lex-01" else rest if d.doc_id in
                       {f"lex-{i:02}" for i in range(2, 13)} else
                       2 if name in {"nfkc", "chinese"} and d.doc_id == "lex-20" else
                       3 if name == "short" and d.doc_id == "lex-21" else 0) for d in corpus.documents}


def _golden_trace(i, query, entrant, count, *, failed=False):
    return {"entrant_id": entrant, "call_number": 1, "query": query,
            "status": "FAILED" if failed else "SUCCEEDED", "result_count": count,
            "error_type": "SearchBackendError" if failed else None,
            "error_code": "INJECTED_LOCAL_FAILURE" if failed else None,
            "error_message": "controlled local fixture failure" if failed else None,
            "backend_id": nfr.BACKEND_ID, "backend_request_id": _request_id(i), "backend_response_id": None,
            "http_status": None if failed else 200, "retryable": failed,
            "backend_attempts": 1, "automatic_retries": 0,
            "started_at_utc": _clock_time(i).isoformat(), "duration_ms": 7.0}


def expected_probe_pass(ctx):
    """Independent, hand-specified golden observations; never labeled as a runtime execution."""
    corpus = ctx["corpus"]
    by_id = {d.doc_id: d for d in corpus.documents}
    observations = []
    for i, case in enumerate(CASES, 1):
        name, query, entrant, ids, normalized, _, _ = case
        results = [{"title": by_id[k].title, "url": by_id[k].url, "snippet": by_id[k].text[:240]} for k in ids]
        observations.append({"case_id": name, "request": asdict(SearchRequest(entrant, query, 1, _request_id(i))),
            "normalized_query": normalized, "scores": _golden_scores(case, corpus),
            "ordered_doc_ids": list(ids), "response": {"results": results, "backend_id": nfr.BACKEND_ID,
                "request_id": _request_id(i), "response_id": None},
            "typed_response": True, "typed_results": True, "same_candidate_config_corpus": True,
            "proxy_trace": _golden_trace(i, query, entrant, len(ids))})
    candidate = nfr.FrozenLexicalRetriever(corpus, ctx["config"])
    return seal({"observations": observations,
        "failure_trace": _golden_trace(len(CASES) + 1, "local failure probe", ENTRANTS[0], 0, failed=True),
        "candidate_state_before": _state(candidate), "candidate_state_after": _state(candidate),
        "frozen_assignment_rejections": 5, "qualification_fixture_retriever_calls": len(CASES),
        "qualification_proxy_calls": len(CASES) + 1, "qualification_injected_failure_calls": 1,
        "timing_mode": TIMING_MODE, "request_identity_mode": "CONTROLLED_FIXTURE_SEQUENCE"})


def run_probe_pass(ctx):
    candidate = nfr.FrozenLexicalRetriever(ctx["corpus"], ctx["config"])
    initial_state = _state(candidate)
    observations, requests, responses = [], [], []
    counts = {"retriever": 0, "proxy": 0, "failure": 0}
    by_url = {d.url: d.doc_id for d in ctx["corpus"].documents}
    class RecordingBoundary:
        backend_id = nfr.BACKEND_ID
        def __call__(self, request):
            counts["retriever"] += 1
            requests.append(request)
            response = candidate(request)
            responses.append(response)
            return response
    class InjectedFailure:
        backend_id = nfr.BACKEND_ID
        def __call__(self, request):
            counts["failure"] += 1
            raise SearchBackendError("controlled local fixture failure", backend_id=self.backend_id,
                request_id=request.request_id, error_code="INJECTED_LOCAL_FAILURE", retryable=True)
    wall = SimpleNamespace(now=lambda tz: _clock_time(counts["proxy"]))
    ticks = iter(t for i in range(1, len(CASES) + 2) for t in (float(i), i + 0.007))
    with patch("search_cup.tools.datetime", wall), \
         patch("search_cup.tools.perf_counter", side_effect=lambda: next(ticks)), \
         patch("search_cup.tools.uuid4", side_effect=lambda: SimpleNamespace(hex=f"{counts['proxy']:032x}")):
        for case in CASES:
            name, query, entrant, *_ = case
            proxy = BudgetedSearchProxy(entrant, 1, RecordingBoundary())
            counts["proxy"] += 1
            result = proxy.search(query)
            response, request = responses[-1], requests[-1]
            observations.append({"case_id": name, "request": asdict(request),
                "normalized_query": nfr.normalize(query),
                "scores": {d.doc_id: nfr.overlap(nfr.character_units(query), units) for d, units in candidate._index},
                "ordered_doc_ids": [by_url[r.url] for r in result], "response": json.loads(canonical_json(asdict(response))),
                "typed_response": type(response) is SearchBackendResponse,
                "typed_results": all(type(r) is SearchResult for r in result),
                "same_candidate_config_corpus": candidate.corpus is ctx["corpus"] and candidate.config is ctx["config"],
                "proxy_trace": asdict(proxy.traces[0])})
        proxy = BudgetedSearchProxy(ENTRANTS[0], 1, InjectedFailure())
        counts["proxy"] += 1
        try:
            proxy.search("local failure probe")
        except SearchBackendError:
            pass
        else:
            raise ValueError("INJECTED_FAILURE_NOT_OBSERVED")
    rejections = 0
    for obj, attr, value in ((candidate, "corpus", None), (candidate, "_index", ()),
            (ctx["corpus"], "documents", ()), (ctx["config"], "canonical_content", "{}"),
            (ctx["corpus"].documents[0], "text", "changed")):
        try:
            setattr(obj, attr, value)
        except FrozenInstanceError:
            rejections += 1
    return seal({"observations": observations, "failure_trace": asdict(proxy.traces[0]),
        "candidate_state_before": initial_state, "candidate_state_after": _state(candidate),
        "frozen_assignment_rejections": rejections, "qualification_fixture_retriever_calls": counts["retriever"],
        "qualification_proxy_calls": counts["proxy"], "qualification_injected_failure_calls": counts["failure"],
        "timing_mode": TIMING_MODE, "request_identity_mode": "CONTROLLED_FIXTURE_SEQUENCE"})


def make_evidence(eid, kind, locator, identity, proposition, observation, *, limitation=LIMITATION):
    return seal({"evidence_id": eid, "source_kind": kind, "source_locator": locator,
        "source_identity": identity, "supported_proposition": proposition, "scope_limitation": limitation,
        "observation_status": "FROZEN", "history_only": False, "observation": observation})


def validate_evidence(item):
    verify_seal(item)
    if set(item) != {"evidence_id", "source_kind", "source_locator", "source_identity", "supported_proposition",
                    "scope_limitation", "observation_status", "history_only", "observation", "canonical_fingerprint"}:
        raise ValueError("EVIDENCE_SCHEMA_INVALID")
    for k in ("evidence_id", "source_locator", "supported_proposition", "scope_limitation"):
        if type(item[k]) is not str or not item[k].strip():
            raise ValueError("EVIDENCE_FIELD_MISSING")
    if item["source_kind"] not in {"REPO_SOURCE", "LOCAL_RUNTIME", "METHOD_RECEIPT", "TARGET_RESOLUTION"}:
        raise ValueError("EVIDENCE_KIND_INVALID")
    if item["observation_status"] != "FROZEN" or type(item["history_only"]) is not bool:
        raise ValueError("EVIDENCE_NOT_FROZEN")
    identity = item["source_identity"]
    if type(identity) is not dict or identity.get("source_baseline") != baseline() or not re.fullmatch(
            r"[0-9a-f]{64}", identity.get("content_fingerprint", "")):
        raise ValueError("EVIDENCE_IDENTITY_MISSING")


def criterion_gate(criteria, evidence):
    """Validate evidence references then call the unchanged protocol RETRIEVER gate.

    This metadata function is not an independent semantic acceptance decision.
    validate_bundle additionally binds every exported observation to this method.
    """
    if set(criteria) != set(CRITERIA):
        raise ValueError("EXACTLY_R1_R8_REQUIRED")
    by_id = {}
    for item in evidence:
        validate_evidence(item)
        if item["evidence_id"] in by_id:
            raise ValueError("DUPLICATE_EVIDENCE")
        by_id[item["evidence_id"]] = item
    checks = {}
    for key, item in criteria.items():
        if set(item) != {"status", "evidence_ids", "proposition", "limitation"} or item["status"] not in {"PASS", "FAIL", "UNKNOWN"}:
            raise ValueError("CRITERION_SCHEMA_INVALID")
        if any(type(item[k]) is not str or not item[k].strip() for k in ("proposition", "limitation")):
            raise ValueError("CRITERION_SEMANTICS_MISSING")
        ids = item["evidence_ids"]
        if (type(ids) is not list or not ids or any(type(i) is not str for i in ids)
                or len(set(ids)) != len(ids) or any(i not in by_id for i in ids)):
            raise ValueError("CRITERION_EVIDENCE_INVALID")
        active = [by_id[i] for i in ids if not by_id[i]["history_only"]]
        if item["status"] == "PASS" and not active:
            raise ValueError("PASS_REQUIRES_ACTIVE_EVIDENCE")
        checks[key] = {"status": item["status"], "evidence": [
            {"id": e["evidence_id"], "version": "1", "fingerprint": e["canonical_fingerprint"]} for e in active]}
    schema = lambda symbol, path: {"id": symbol, "version": "pinned-source/v1",
                                  "fingerprint": fingerprint({"symbol": symbol, "path": path, "sha256": SOURCE_PINS[path]})}
    retriever = {"identity": {"id": nfr.CANDIDATE_ID, "version": "1", "fingerprint": DESCRIPTOR_FINGERPRINT},
        "backend_id": nfr.BACKEND_ID, "class": "RAW_RETRIEVER", "config_fingerprint": nfr.CONFIG_FINGERPRINT,
        "request_schema": schema("SearchRequest", "search_cup/contracts.py"),
        "result_schema": {"id": "SearchBackendResponse+SearchResult", "version": "pinned-source/v1",
                          "fingerprint": fingerprint({"response": schema("SearchBackendResponse", "search_cup/tools.py"),
                                                       "result": schema("SearchResult", "search_cup/contracts.py")})},
        "capabilities": ["RETRIEVAL", "RANKING"], "qualification": None}
    retriever["qualification"] = {"backend_fingerprint": fingerprint({k: v for k, v in retriever.items() if k != "qualification"}),
                                  "criteria": checks}
    return f1_eligibility(retriever), retriever


def resource_receipt(executed):
    calls = len(CASES) * 2 if executed else 0
    return seal({"work_order": WORK_ORDER, "source_baseline": baseline(),
        "accounting_scope": "ONE_QUALIFICATION_BUILD_TWO_IDENTICAL_PROBE_PASSES" if executed else "IDENTITY_REJECTED_NO_PROBES",
        "qualification_fixture_retriever_calls": calls, "qualification_proxy_calls": calls + (2 if executed else 0),
        "qualification_injected_failure_calls": 2 if executed else 0, **dict.fromkeys(ZERO_FIELDS, 0),
        "spend": {"currency": "USD", "value": 0}, "hidden_registry_loaded": False,
        "official_prompt_consumed": False, "production_corpus_loaded": False, "reference_set_loaded": False,
        "ci_provenance_git_subprocesses": "INFRASTRUCTURE_ONLY_SEPARATELY_COUNTED_IN_CI_SOURCE",
        "guarded_targets": list(GUARDED_TARGETS) + ["os.environ"], "blocked_external_attempts": 0, **boundary()})


def assemble(ctx, observation, analysis, *, mismatch=None):
    exact = mismatch is None
    resources = resource_receipt(exact)
    target = seal({"schema_id": "search-cup-v23-t3-f1q-r2-target-descriptor/v1", "work_order": WORK_ORDER,
        "source_baseline": baseline(), "resolution": "EXACT_MATCH" if exact else "NOT_EVALUABLE",
        "reason_code": None if exact else "TARGET_IDENTITY_MISMATCH", "mismatch_component": mismatch,
        "runtime_observed": runtime_identity(), "expected_descriptor_fingerprint": DESCRIPTOR_FINGERPRINT,
        "expected_target_json_fingerprint": TARGET_JSON_FINGERPRINT,
        "selected_target": ctx["target"] if exact else None,
        "target_bytes_sha256": ctx["target_bytes_sha256"] if exact else None,
        "published_candidate_descriptor": ctx["descriptor"] if exact else None,
        "method_content_sha256": ctx["method_sha256"] if exact else hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "selection_authority": WORK_ORDER, "prior_nfr_identity_only_not_qualification_proof": True, **boundary()})
    runtime = seal({"schema_id": "search-cup-v23-t3-f1q-r2-probes/v1", "target_fingerprint": target["canonical_fingerprint"],
        "probe_status": "EXECUTED" if exact else "NOT_RUN", "pass_count": 2 if exact else 0,
        "pass_receipts": [observation, observation] if exact else [],
        "byte_identical_passes": True if exact else None, "timing_mode": TIMING_MODE,
        "historical_nfr_conformance_executed": False, **boundary()})
    identity = lambda value: {"source_baseline": baseline(), "content_fingerprint": fingerprint(value),
                              "candidate_descriptor_fingerprint": DESCRIPTOR_FINGERPRINT,
                              "unicode_data_version_required": "14.0.0"}
    evidence = [make_evidence("E_TARGET", "TARGET_RESOLUTION", "target-descriptor.json",
        identity(target), "Exact descriptor/runtime/selector identity must match before assessment.", target)]
    if exact:
        def src(eid, path, proposition, obs):
            return make_evidence(eid, "REPO_SOURCE", f"{REPO}/blob/{BASELINE_SHA}/{path}",
                {**identity(obs), "source_path": path, "content_sha256": SOURCE_PINS[path]}, proposition, obs)
        evidence += [src("E_IMPL", nfr.CODE_PATH, "Closed source/AST shows the sole lexical call graph.", analysis),
            src("E_CONFIG", nfr.CONFIG_PATH, "Exact shared algorithm, limit, normalization and capability config.",
                json.loads(ctx["config"].canonical_content)),
            src("E_SCHEMAS", "search_cup/contracts.py", "Request/result dataclasses and response boundary are pinned.",
                {"request_symbol": "SearchRequest", "result_symbol": "SearchResult", "response_symbol": "SearchBackendResponse",
                 "response_source_sha256": SOURCE_PINS["search_cup/tools.py"], "schema_validator_sha256": SOURCE_PINS["search_cup/v23_schema.py"]}),
            src("E_PROXY", "search_cup/tools.py", "One backend attempt per call with typed terminal trace and no retry.",
                {"lines": analysis["proxy_source_lines"], "ast_fingerprint": analysis["proxy_ast_fingerprint"],
                 "single_attempt_no_loop": analysis["checks"]["single_proxy_attempt_no_loop"]})]
        observations = observation["observations"]
        for eid, proposition, obs in (
            ("E_QUERY", CRITERIA["R1"], [{"request": o["request"], "normalized_query": o["normalized_query"],
                "trace_query": o["proxy_trace"]["query"]} for o in observations]),
            ("E_ENTRANTS", CRITERIA["R2"] + " " + CRITERIA["R6"], observations[:4] + [observations[9]]),
            ("E_RANKING", CRITERIA["R3"], [{"case_id": o["case_id"], "scores": o["scores"],
                "ordered_doc_ids": o["ordered_doc_ids"]} for o in observations]),
            ("E_TYPED", CRITERIA["R5"], [{"request": o["request"], "response": o["response"],
                "typed_response": o["typed_response"], "typed_results": o["typed_results"]} for o in observations]),
            ("E_SUCCESS", CRITERIA["R8"], {"trace": observations[0]["proxy_trace"], "timing_mode": TIMING_MODE}),
            ("E_FAILURE", CRITERIA["R8"], {"trace": observation["failure_trace"], "timing_mode": TIMING_MODE,
                "injected_failure_calls_per_pass": 1, "candidate_calls_for_failure": 0}),
            ("E_IMMUTABLE", CRITERIA["R6"], {k: observation[k] for k in
                ("candidate_state_before", "candidate_state_after", "frozen_assignment_rejections")}),
            ("E_GUARD", CRITERIA["R7"], {"targets": resources["guarded_targets"], "blocked_attempts": 0,
                "source_has_no_external_imports": analysis["checks"]["no_external_candidate_imports"],
                "scope": "QUALIFICATION_PATH_NOT_CI_INFRASTRUCTURE_NOT_HOSTILE_CODE_SANDBOX"}),
            ("E_RESOURCES", CRITERIA["R7"], resources),
            ("E_REPRODUCIBILITY", CRITERIA["R4"], {"pass_fingerprints": [observation["canonical_fingerprint"]] * 2,
                "byte_identical": True, "deterministic_assembly": "CANONICAL_CONTENT_NO_WALL_CLOCK_ENTROPY",
                "qualification_method_sha256": ctx["method_sha256"], "target_json_fingerprint": TARGET_JSON_FINGERPRINT}),
        ):
            evidence.append(make_evidence(eid, "LOCAL_RUNTIME" if eid not in {"E_GUARD", "E_RESOURCES", "E_REPRODUCIBILITY"}
                else "METHOD_RECEIPT", "runtime-probe-receipt.json" if eid != "E_RESOURCES" else "resource-zero-receipt.json",
                identity(obs), proposition, obs))
    evidence_payload = seal({"schema_id": "search-cup-v23-t3-f1q-r2-evidence/v1", "items": evidence,
                             "target_fingerprint": target["canonical_fingerprint"]})
    criteria = {key: {"status": "PASS" if exact else "UNKNOWN", "evidence_ids": EVIDENCE_IDS[key] if exact else ["E_TARGET"],
                      "proposition": value, "limitation": LIMITATION + (" Timing uses an injected test clock." if key == "R8" else "")}
                for key, value in CRITERIA.items()}
    gate_result, retriever = criterion_gate(criteria, evidence)
    method_result = gate_result if exact else "NOT_EVALUABLE"
    qualification = seal({"schema_id": "search-cup-v23-t3-f1q-r2-qualification/v1",
        "criterion_assessment_performed": exact, "criteria": criteria, "protocol_retriever": retriever,
        "protocol_gate_result": gate_result, "method_qualification_result": method_result,
        "target_fingerprint": target["canonical_fingerprint"], "evidence_fingerprint": evidence_payload["canonical_fingerprint"],
        **boundary()})
    bundle = {"target": target, "qualification": qualification, "evidence": evidence_payload,
              "runtime": runtime, "resources": resources}
    receipt = seal({"schema_id": "search-cup-v23-t3-f1q-r2-receipt/v1", "work_order": WORK_ORDER,
        "source_baseline": baseline(), "package_conformance": "PASS", "target_resolution": target["resolution"],
        "reason_code": target["reason_code"], "method_qualification_result": method_result,
        "protocol_gate_result": gate_result, "protocol_gate_consistency": "PASS",
        "package_fingerprint": fingerprint({key: value["canonical_fingerprint"] for key, value in bundle.items()}),
        "candidate_descriptor_fingerprint": DESCRIPTOR_FINGERPRINT,
        "normalization_runtime": runtime_identity(), "code_content_sha256": CODE_SHA256,
        "config_fingerprint": nfr.CONFIG_FINGERPRINT, "synthetic_fixture_corpus_fingerprint": nfr.TEST_CORPUS_FINGERPRINT,
        "identity_fields_are_expected_only_when_not_evaluable": True,
        "resource_receipt_fingerprint": resources["canonical_fingerprint"], **boundary()})
    return {**bundle, "receipt": receipt}


def build_bundle(**kwargs):
    with external_guard() as attempts:
        try:
            ctx = resolve_target(**kwargs)
        except TargetIdentityMismatch as exc:
            return assemble(None, None, None, mismatch=exc.reason)
        analysis = source_observations(ctx)
        if not all(analysis["checks"].values()):
            raise ValueError("SOURCE_PROOF_FAILED")
        one, two = run_probe_pass(ctx), run_probe_pass(ctx)
        if canonical_json(one) != canonical_json(two) or canonical_json(one) != canonical_json(expected_probe_pass(ctx)):
            raise ValueError("PROBE_CONFORMANCE_OR_REPRODUCIBILITY_FAILED")
        if attempts:
            raise ExternalOperationBlocked("BLOCKED_ATTEMPT_OBSERVED")
        result = assemble(ctx, one, analysis)
        if result != assemble(ctx, two, analysis):
            raise ValueError("PACKAGE_ASSEMBLY_NOT_DETERMINISTIC")
        return result


def validate_bundle(bundle, **kwargs):
    """Source/golden replay validation with ZERO retriever/proxy/failure calls."""
    if type(bundle) is not dict or set(bundle) != set(PAYLOADS):
        raise ValueError("PACKAGE_SHAPE_MISMATCH")
    for payload in bundle.values():
        verify_seal(payload)
    with external_guard():
        try:
            ctx = resolve_target(**kwargs)
        except TargetIdentityMismatch as exc:
            expected = assemble(None, None, None, mismatch=exc.reason)
        else:
            analysis = source_observations(ctx)
            if not all(analysis["checks"].values()):
                raise ValueError("SOURCE_PROOF_FAILED")
            expected = assemble(ctx, expected_probe_pass(ctx), analysis)
        if canonical_json(bundle) != canonical_json(expected):
            raise ValueError("QUALIFICATION_PACKAGE_MUTATED")
    q = bundle["qualification"]
    if f1_eligibility(q["protocol_retriever"]) != q["protocol_gate_result"]:
        raise ValueError("PROTOCOL_GATE_INCONSISTENT")


def write_bundle(output_dir, **kwargs):
    output = Path(output_dir)
    if output.exists():
        raise FileExistsError("OUTPUT_DIRECTORY_ALREADY_EXISTS")
    bundle = build_bundle(**kwargs)
    validate_bundle(bundle, **kwargs)
    output.mkdir(parents=False, exist_ok=False)
    for key, name in PAYLOADS.items():
        (output / name).write_text(canonical_json(bundle[key]), encoding="utf-8")
    manifest = "".join(hashlib.sha256(p.read_bytes()).hexdigest() + "  " + p.name + "\n" for p in sorted(output.iterdir()))
    (output / "MANIFEST.sha256").write_text(manifest, encoding="utf-8")
    return bundle["receipt"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("receipt", "bundle", "validate"))
    parser.add_argument("--expected-source-sha", required=True)
    parser.add_argument("--expected-source-tree", required=True)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    kwargs = {"expected_sha": args.expected_source_sha, "expected_tree": args.expected_source_tree}
    if args.command == "receipt":
        if args.output_dir is not None:
            parser.error("receipt does not take --output-dir")
        result = build_bundle(**kwargs)["receipt"]
    else:
        if args.output_dir is None:
            parser.error("bundle/validate requires --output-dir")
        if args.command == "bundle":
            result = write_bundle(args.output_dir, **kwargs)
        else:
            bundle = {key: json.loads((args.output_dir / name).read_text(encoding="utf-8")) for key, name in PAYLOADS.items()}
            validate_bundle(bundle, **kwargs)
            result = bundle["receipt"]
    print(canonical_json(result))
    return 0 if result["target_resolution"] == "EXACT_MATCH" else 2


if __name__ == "__main__":
    raise SystemExit(main())
