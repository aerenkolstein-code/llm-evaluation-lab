"""Offline, evidence-bound T6 qualification. This is not a live runner.

Documentary eligibility is separate from independent acceptance, publication,
transport integration and live compatibility. All are reported separately.
"""
from __future__ import annotations

import argparse
import ast
import contextlib
from dataclasses import dataclass
import hashlib
import http.client
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import unittest
from unittest.mock import patch
import urllib.request

from .contracts import canonical_json, fingerprint
from .protocol_v23 import assert_content_safe, f1_eligibility
from .v23_t6_live_brave_retriever import API_VERSION, BACKEND_ID, CANDIDATE_ID, validate_config

BASELINE_SHA = "72932d41c862753d489ef2d2e1c6a2619f34a2d9"
BASELINE_TREE = "05c0953bfe67f9d684160a79ef7c9307dcd2a3a4"
SCOPE = (
    "search_cup/v23_t6_live_brave_retriever.py",
    "search_cup/v23_t6_live_f1q.py",
    "configs/search-cup-v23-t6-live-brave-raw-v1.json",
    "fixtures/search-cup/v23-t6-live-brave-public-doc-evidence.json",
    "tests/test_search_cup_v23_t6_live_f1q.py",
    "docs/search-cup-v23-t6-live-f1q.md",
    ".github/workflows/t6-live-f1-retriever-qualification.yml",
)
DOC_PIN = "3cc49d22414614d9bacc857a70021a4b24f72ee83bec3389b3378bf9e937b38d"
DOC_URLS = {
    "BRAVE-WEB-CONTRACT": "https://api-dashboard.search.brave.com/api-reference/web/search/get",
    "BRAVE-VERSIONING": "https://api-dashboard.search.brave.com/documentation/guides/versioning",
    "BRAVE-WEB-CHANGELOG": "https://api-dashboard.search.brave.com/app/documentation/web-search",
}
REQUEST_CONTRACT = {
    "schema_id": "t6-brave-web-request/v1", "method": "GET",
    "version_header": "Api-Version", "api_version": API_VERSION,
    "query_transform": "URL_ENCODING_ONLY", "attempts_per_valid_call": 1,
    "retry_policy": "NONE", "credential_lookup": False,
    "transport": "EXPLICITLY_INJECTED_NO_DEFAULT",
    "deadline": "15000ms supplied to transport; physical enforcement requires later transport qualification",
}
RESULT_CONTRACT = {
    "schema_id": "t6-brave-web-result/v1", "fields": ["title", "url", "snippet"],
    "mapping": "web.results title/url/description only; preserve sequence",
    "limit": 10, "extra_results": "REJECT_NOT_TRUNCATE",
    "unsafe_or_altered": "TYPED_NON_COMPARABLE_NO_SCORED_RESULT",
    "body_fingerprint": "Only after content-safety validation; unavailable on unsafe or failed responses",
}
R_TEST_PREFIXES = {
    "R1": ("test_r1_",), "R2": ("test_r2_",), "R3": ("test_r3_",),
    "R4": ("test_r4_",), "R5": ("test_r5_",), "R6": ("test_r6_",),
    "R7": ("test_r7_",), "R8": ("test_r8_",),
}


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if type(value) is not dict:
        raise ValueError("INVALID_DOCUMENT")
    assert_content_safe(value)
    return value


def validate_doc_evidence(document: dict) -> None:
    content = {k: v for k, v in document.items() if k != "canonical_fingerprint"}
    if (document.get("canonical_fingerprint") != fingerprint(content)
            or document.get("canonical_fingerprint") != DOC_PIN):
        raise ValueError("DOC_EVIDENCE_DRIFT")
    records = document.get("records", [])
    if len(records) != 3 or {r.get("id") for r in records} != set(DOC_URLS):
        raise ValueError("DOC_RECORD_SET")
    for row in records:
        bare = {k: v for k, v in row.items() if k != "record_fingerprint"}
        if row.get("record_fingerprint") != fingerprint(bare) or row.get("url") != DOC_URLS[row["id"]]:
            raise ValueError("DOC_RECORD_DRIFT")
        if not row.get("propositions"):
            raise ValueError("DOC_EVIDENCE_EMPTY")
    version_rows = [r for r in records if r["id"] in {"BRAVE-VERSIONING", "BRAVE-WEB-CHANGELOG"}]
    if document.get("api_version") != API_VERSION or any(r.get("api_version") != API_VERSION for r in version_rows):
        raise ValueError("API_VERSION_UNPROVEN")


def inspect_adapter(source: str) -> dict:
    """Evidence about client source only, not opaque provider internals."""
    tree = ast.parse(source)
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(n.name for n in node.names)
        elif isinstance(node, ast.ImportFrom):
            imports.append("." * node.level + (node.module or ""))
    banned = {"os", "subprocess", "socket", "requests", "httpx", "http.client", "urllib.request"}
    forbidden = sorted(i for i in imports if any(i == b or i.startswith(b + ".") for b in banned))
    methods = [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "__call__"]
    if len(methods) != 1:
        raise ValueError("ADAPTER_CALL_SURFACE_DRIFT")
    transport_calls = [n for n in ast.walk(methods[0]) if isinstance(n, ast.Call)
                       and isinstance(n.func, ast.Attribute) and n.func.attr == "_transport"]
    return {"forbidden_imports": forbidden, "transport_call_sites": len(transport_calls),
            "no_default_transport": "transport: Transport | None = None" in source,
            "client_source_status": "PASS" if not forbidden and len(transport_calls) == 1
            and "transport: Transport | None = None" in source else "FAIL"}


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


def ref(identity: str, document: dict) -> dict:
    return {"id": identity, "version": "1", "fingerprint": fingerprint(document)}


def build_descriptor(config: dict, documents: dict, source: dict,
                     tests: dict, assessment: dict) -> tuple[dict, dict]:
    validate_config(config)
    validate_doc_evidence(documents)
    identity = {"identity": ref(CANDIDATE_ID, {"adapter_sha256": source["source_sha256"][SCOPE[0]],
                                              "api_version": API_VERSION}),
                "backend_id": BACKEND_ID, "class": "RAW_RETRIEVER",
                "config_fingerprint": fingerprint(config),
                "request_schema": ref("t6-brave-web-request", REQUEST_CONTRACT),
                "result_schema": ref("t6-brave-web-result", RESULT_CONTRACT),
                "capabilities": ["RETRIEVAL", "RANKING"]}
    checks = {}
    for key, prefixes in R_TEST_PREFIXES.items():
        relevant = [r for r in tests["cases"] if any(r["id"].split(".")[-1].startswith(p) for p in prefixes)]
        status = "PASS" if relevant and all(r["status"] == "PASS" for r in relevant) else "UNKNOWN"
        if tests["failures"] or tests["errors"] or tests["skipped"] or assessment["client_source_status"] != "PASS":
            status = "FAIL"
        doc_rows = [r for r in documents["records"] if key in r["criteria"]]
        if not doc_rows:
            status = "UNKNOWN"
        # Source/mocks prove the client, not opaque provider internals. An
        # unresolved external capability obligation must not become a PASS
        # merely because the focused suite is green.
        external = documents.get("external_capability_attestations", {}).get(key)
        if external is not None and external.get("status") != "PASS":
            status = "FAIL" if external.get("status") == "FAIL" else "UNKNOWN"
        checks[key] = {"status": status, "evidence": [
            ref("t6-" + key + "-test-evidence", {"cases": relevant}),
            ref("t6-source-evidence", source), ref("t6-client-source-assessment", assessment),
            ref("t6-" + key + "-official-doc-evidence", {"records": doc_rows}),
        ]}
    descriptor = {**identity, "qualification": {"backend_fingerprint": fingerprint(identity), "criteria": checks}}
    verdict = f1_eligibility(descriptor)
    return descriptor, {"qualification_result": verdict, "criteria": checks,
                        "basis": "DOCUMENTED_INTERFACE_PLUS_INSPECTED_CLIENT_AND_OFFLINE_MOCKS",
                        "live_behavior_verified": False,
                        "external_capability_attestations": documents.get("external_capability_attestations", {}),
                        "independent_qa": "PENDING", "server_internals_verified": False}


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
    spec = importlib.util.spec_from_file_location("_t6_f1q_test", root / SCOPE[4])
    if spec is None or spec.loader is None:
        raise ValueError("TEST_MODULE_MISSING")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    stream = io.StringIO()
    with OfflineSandbox() as sandbox:
        spec.loader.exec_module(module)
        suite = unittest.defaultTestLoader.loadTestsFromModule(module)
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        receipt = run_qualification(Path(__file__).resolve().parents[1], args.output)
    except (ValueError, OSError):
        print("T6_QUALIFICATION_STOP: source/evidence/output prerequisite failed", file=sys.stderr)
        return 2
    print("T6_QUALIFICATION_RECEIPT=" + canonical_json(receipt))
    return 0 if receipt["qualification_result"] == "F1_ELIGIBLE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
