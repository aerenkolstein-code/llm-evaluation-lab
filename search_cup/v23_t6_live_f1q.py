"""Pure T6 documentary qualification assembly, with no orchestration I/O.

Runtime client behavior lives in the candidate adapter. Test execution, network
denial, read-only Git probes and evidence publication belong to the separately
reviewed offline test harness, not the protocol module. Public documentation and
passed client tests do not establish opaque provider internals.
"""
from __future__ import annotations

import ast

from .contracts import fingerprint
from .protocol_v23 import f1_eligibility
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
