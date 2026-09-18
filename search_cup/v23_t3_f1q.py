"""T3 F1 qualification authoring: inspect pinned public source, never execute it."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import re

from .contracts import canonical_json, fingerprint
from .protocol_v23 import assert_content_safe, f1_eligibility, seal, verify_seal

WORK_ORDER = "WO-ENG-B1-SC-V23-T3-F1Q-01 v0.1"
BASELINE_SHA = "6c1b664a2264a021dc9ebca26514eca130ceaaec"
BASELINE_TREE = "2fcc3b0f2bf641d01ab8a90ab6b771be4e5c7434"
REPO_URL = "https://github.com/aerenkolstein-code/llm-evaluation-lab"
CLAIMS = "F1_RETRIEVER_QUALIFICATION_ONLY"
CRITERIA = {
    "R1": "Query transparency",
    "R2": "No hidden entrant-specific planning",
    "R3": "No entrant-specific hidden rerank",
    "R4": "Reproducible interface",
    "R5": "Normalized result contract",
    "R6": "Same capability envelope",
    "R7": "No hidden paid/intelligent stack inside F1 resource unit",
    "R8": "Traceability",
}
SOURCE_PINS = {
    "search_cup/contracts.py": "e08fea09a5e66694079425648642ba7ad14076c977b19fc1a5771ee9b4bac184",
    "search_cup/tools.py": "6bf6b34c651ca100c317f151a028ecf75d5ccdf53747df5c9152e900fa611af4",
    "search_cup/search_pro.py": "fddafa96bcb1c9694c32706c2f985fc0abc6cb484e457cf9b3dd65180aaeaab9",
    "tests/test_search_cup.py": "ce2100210f1fe6c9dbbf511638e95358b2f6a466f4b88ae29eb0bd1fddefea8c",
    "search_cup/protocol_v23.py": "50b6927bd1bc22ba42a40857f5e71658eae38aae0cc7d38fad5fa1b49396127b",
    "search_cup/v23_schema.py": "8c34ffca7bb64a8c9c4ad0985290f4b41e9fb62baef6ec66066cd0e2a2af0fef",
    "search_cup/v23_t4_instance.py": "a60de48ee7467922b0f0a19d78594fd0785ae427cef75bf7d938880f619f7ad6",
    "search_cup/v23_t4_execution.py": "fbcdcd8b24d087bf9a26785773151fb8c23dd28a4107364d0c1d49a4ec71ea75",
    "search_cup/v23_t4_je1.py": "7be87d913a6aba9f4af6587820f71751d88b8f2f10c75e5b5caa8e005c9efb63",
}
DISCOVERY_PATHS = ("search_cup/search_pro.py", "search_cup/tools.py")
FILENAMES = {
    "descriptor": "candidate-descriptor.json",
    "qualification": "r1-r8-qualification.json",
    "evidence": "evidence-manifest.json",
    "receipt": "qualification-receipt.json",
    "resources": "resource-zero-receipt.json",
}


def source_identity(sha=BASELINE_SHA, tree=BASELINE_TREE):
    if sha != BASELINE_SHA or tree != BASELINE_TREE:
        raise ValueError("SOURCE_BASELINE_MISMATCH")
    return {"sha": sha, "tree": tree}


def load_sources(root=None, *, expected_sha=BASELINE_SHA, expected_tree=BASELINE_TREE):
    """Read a closed public-source allowlist. No Git/process/environment access."""
    source_identity(expected_sha, expected_tree)
    root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    sources = {}
    for path, expected in SOURCE_PINS.items():
        data = (root / path).read_bytes()
        if hashlib.sha256(data).hexdigest() != expected:
            raise ValueError("SOURCE_CONTENT_MISMATCH")
        sources[path] = data.decode("utf-8")
    return sources


def _node(source, name):
    parts = name.split(".")
    nodes = ast.parse(source).body
    for part in parts:
        found = next((n for n in nodes if isinstance(n, (ast.ClassDef, ast.FunctionDef)) and n.name == part), None)
        if found is None:
            raise ValueError("SOURCE_SYMBOL_MISSING")
        nodes = found.body
    return found


def discover_candidates(sources):
    """Inventory concrete typed backend callables; no preferred backend rule.

    Both production and fake implementations on the frozen backend surface
    count. A proxy, transport helper or URL reader is not a SearchRequest backend.
    This returns implementation identities, not a selected configuration.
    """
    candidates = []
    for path in sorted(sources):
        if path not in DISCOVERY_PATHS:
            continue
        source = sources[path]
        for item in ast.parse(source).body:
            call = next((n for n in item.body if isinstance(n, ast.FunctionDef) and n.name == "__call__"), None) if isinstance(item, ast.ClassDef) else item
            if not isinstance(call, ast.FunctionDef):
                continue
            if not any(isinstance(a.annotation, ast.Name) and a.annotation.id == "SearchRequest"
                       for a in call.args.args):
                continue
            symbol = item.name + ".__call__" if isinstance(item, ast.ClassDef) else item.name
            node_source = ast.get_source_segment(source, item)
            candidates.append(seal({
                "candidate_id": path.removesuffix(".py").replace("/", ".") + ":" + item.name,
                "implementation_path": path, "symbol": symbol,
                "source": source_identity(), "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
                "implementation_sha256": hashlib.sha256(node_source.encode()).hexdigest(),
                "line_start": item.lineno, "line_end": item.end_lineno,
                "discovery_basis": "CONCRETE_CALLABLE_WITH_SEARCHREQUEST_PARAMETER",
                "selection_status": "DISCOVERED_NOT_SELECTED",
            }))
    return sorted(candidates, key=lambda c: c["candidate_id"])


def select_candidate(candidates):
    identities = [c["candidate_id"] for c in candidates]
    if len(identities) != len(set(identities)):
        raise ValueError("DUPLICATE_CANDIDATE_IDENTITY")
    if not candidates:
        return None, "NO_CANDIDATE"
    if len(candidates) != 1:
        return None, "CANDIDATE_AMBIGUOUS"
    verify_seal(candidates[0])
    return candidates[0], "UNIQUE_CANDIDATE"


def _ref(value, identity):
    return {"id": identity, "version": "1", "fingerprint": fingerprint(value)}


def freeze_candidate(candidate, sources):
    """Called only after unique discovery; source defaults are not a live instance."""
    path = candidate["implementation_path"]
    symbol = candidate["symbol"]
    if path == "search_cup/search_pro.py" and symbol == "SearchProBackend.__call__":
        config = {
            "backend_id": "zhipu-web-search/search_pro", "count_default": 10,
            "count_range": [1, 50], "timeout_seconds_default": 30.0,
            "endpoint_default": "https://open.bigmodel.cn/api/paas/v4/web_search",
            "transport_default": "search_cup.search_pro._default_transport",
            "search_intent": False, "search_recency_filter": "noLimit", "content_size": "medium",
            "upstream_implementation": "UNKNOWN", "observation": "SOURCE_DEFAULTS_NOT_INSTANTIATED",
            "frozen_instance": False,
        }
        # Conservative frozen protocol disposition, not a claim that API source
        # alone reveals provider internals. No raw-neutrality relabel is offered.
        kind = "INTEGRATED_SEARCH_STACK"
        class_basis = "FROZEN_PROTOCOL_SEARCH_STACK_DISPOSITION_NOT_PROVEN_F1_NEUTRAL"
    elif path == "search_cup/tools.py" and symbol == "FakeSearchBackend.__call__":
        config = {
            "backend_id": "fake-search-pro-offline", "results_by_query": "UNBOUND_CALLER_PARAMETER",
            "result_limit": "NO_EXPLICIT_LIMIT", "observation": "SOURCE_TEMPLATE_NOT_FROZEN_CORPUS",
            "frozen_instance": False,
        }
        kind = "RAW_RETRIEVER"
        class_basis = "LOCAL_LITERAL_QUERY_LOOKUP_ONLY_NOT_A_QUALIFIED_FROZEN_CORPUS"
    else:
        raise ValueError("UNSUPPORTED_CANDIDATE_DESCRIPTOR")
    return seal({
        "candidate_id": candidate["candidate_id"], "retriever_class": kind, "class_basis": class_basis,
        "implementation": candidate, "source": source_identity(),
        "search_proxy": {"path": "search_cup/tools.py", "symbol": "BudgetedSearchProxy.search",
                         "source_sha256": SOURCE_PINS["search_cup/tools.py"]},
        "request_schema": _ref({"path": "search_cup/contracts.py", "symbol": "SearchRequest",
                                "source_sha256": SOURCE_PINS["search_cup/contracts.py"]}, "current-main-searchrequest"),
        "result_schema": _ref({"path": "search_cup/contracts.py", "symbols": ["SearchResult", "SearchTrace"],
                               "source_sha256": SOURCE_PINS["search_cup/contracts.py"]}, "current-main-result-trace"),
        "normalization_identity": {"source_sha256": SOURCE_PINS[path], "symbol": symbol,
                                   "boundary_sha256": SOURCE_PINS["search_cup/tools.py"]},
        "config": config, "config_fingerprint": fingerprint(config),
        "retry_fallback_policy": {"local_automatic_retries": 0, "local_fallback": "NONE",
                                  "upstream_policy": "UNKNOWN" if kind == "INTEGRATED_SEARCH_STACK" else "NOT_APPLICABLE"},
        "capability_declaration": {"local": ["RETRIEVAL"], "upstream": "UNKNOWN" if kind == "INTEGRATED_SEARCH_STACK" else "NONE",
                                   "equalized_entrant_configuration": "NOT_FROZEN"},
        "default_eligibility": "NOT_YET_F1_ELIGIBLE_BY_DEFAULT",
    })


def make_evidence(identity, kind, locator, source, proposition, limitation, *, excerpt="", history_only=False):
    return seal({"evidence_id": identity, "source_kind": kind, "locator": locator,
                 "source_identity": source, "supported_proposition": proposition,
                 "scope_limitation": limitation, "excerpt": excerpt,
                 "observed_frozen": "FROZEN_OFFLINE_INSPECTION", "history_only": history_only})


def validate_evidence(item):
    verify_seal(item)
    required = {"evidence_id", "source_kind", "locator", "source_identity", "supported_proposition",
                "scope_limitation", "excerpt", "observed_frozen", "history_only", "canonical_fingerprint"}
    if set(item) != required or item["source_kind"] not in {
            "REPO_SOURCE", "REPO_TEST", "OFFICIAL_PUBLIC_DOC", "GENERATED_OFFLINE_RECEIPT"}:
        raise ValueError("EVIDENCE_SCHEMA_INVALID")
    for key in ("evidence_id", "locator", "supported_proposition", "scope_limitation"):
        if not isinstance(item[key], str) or not item[key].strip():
            raise ValueError("EVIDENCE_FIELD_MISSING")
    if item["observed_frozen"] != "FROZEN_OFFLINE_INSPECTION" or type(item["history_only"]) is not bool:
        raise ValueError("EVIDENCE_NOT_FROZEN")
    identity = item["source_identity"]
    if not isinstance(identity, dict) or not re.fullmatch(r"[0-9a-f]{64}", identity.get("content_sha256", "")):
        raise ValueError("EVIDENCE_IDENTITY_MISSING")
    if item["source_kind"] in {"REPO_SOURCE", "REPO_TEST"}:
        if identity.get("sha") != BASELINE_SHA or identity.get("tree") != BASELINE_TREE:
            raise ValueError("EVIDENCE_SOURCE_MISMATCH")
        if not item["locator"].startswith(REPO_URL + "/blob/" + BASELINE_SHA + "/"):
            raise ValueError("EVIDENCE_LOCATOR_MISMATCH")
    if item["source_kind"] == "OFFICIAL_PUBLIC_DOC":
        if not item["locator"].startswith("https://") or not item["excerpt"].strip():
            raise ValueError("PUBLIC_DOC_NOT_FROZEN")


def criterion_gate(candidate, checks, evidence):
    """All-of metadata gate; semantic support still requires independent review.

    The publisher uses only its frozen assessment, never caller-supplied PASS
    assertions. Synthetic tests of this gate do not qualify a real retriever.
    """
    if set(checks) != set(CRITERIA):
        raise ValueError("EXACTLY_R1_R8_REQUIRED")
    for item in evidence:
        validate_evidence(item)
    by_id = {e["evidence_id"]: e for e in evidence}
    if len(by_id) != len(evidence):
        raise ValueError("DUPLICATE_EVIDENCE")
    typed = {}
    unsupported = False
    for key, check in checks.items():
        if set(check) != {"status", "evidence_ids"} or check["status"] not in {"PASS", "FAIL", "UNKNOWN"}:
            raise ValueError("CRITERION_SCHEMA_INVALID")
        ids = check["evidence_ids"]
        if not isinstance(ids, list) or len(ids) != len(set(ids)) or any(i not in by_id for i in ids):
            raise ValueError("CRITERION_EVIDENCE_INVALID")
        active = [by_id[i] for i in ids if not by_id[i]["history_only"]]
        unsupported |= check["status"] == "PASS" and not active
        typed[key] = {"status": check["status"], "evidence": [_ref(e, e["evidence_id"]) for e in active]}
    if candidate is None:
        return "NOT_EVALUABLE"
    verify_seal(candidate)
    if candidate["source"] != source_identity() or candidate["config_fingerprint"] != fingerprint(candidate["config"]):
        raise ValueError("CANDIDATE_BINDING_INVALID")
    implementation = candidate["implementation"]
    verify_seal(implementation)
    if implementation["source"] != source_identity() or implementation["source_sha256"] != SOURCE_PINS.get(implementation["implementation_path"]):
        raise ValueError("CANDIDATE_SOURCE_INVALID")
    if implementation["symbol"] == "SearchProBackend.__call__" and candidate["retriever_class"] != "INTEGRATED_SEARCH_STACK":
        raise ValueError("INTEGRATED_CANDIDATE_RELABEL_FORBIDDEN")
    retriever = {
        "identity": _ref(candidate, candidate["candidate_id"]), "backend_id": candidate["config"]["backend_id"],
        "class": candidate["retriever_class"], "config_fingerprint": candidate["config_fingerprint"],
        "request_schema": candidate["request_schema"], "result_schema": candidate["result_schema"],
        "capabilities": candidate["capability_declaration"]["local"], "qualification": None,
    }
    retriever["qualification"] = {"backend_fingerprint": fingerprint({k: v for k, v in retriever.items() if k != "qualification"}),
                                  "criteria": typed}
    # This WO freezes no separately approved non-RAW neutral class.
    if (unsupported or candidate["retriever_class"] != "RAW_RETRIEVER"
            or candidate["config"].get("frozen_instance") is not True
            or candidate["capability_declaration"]["equalized_entrant_configuration"] != "FROZEN_IDENTICAL"):
        return "NOT_F1_ELIGIBLE"
    return f1_eligibility(retriever)


def _source_evidence(sources, identity, path, symbol, proposition, limitation):
    node = _node(sources[path], symbol)
    # Only the declaration line is exported; source content stays in the repo.
    excerpt = sources[path].splitlines()[node.lineno - 1].strip()
    return make_evidence(identity, "REPO_TEST" if path.startswith("tests/") else "REPO_SOURCE",
                         f"{REPO_URL}/blob/{BASELINE_SHA}/{path}#L{node.lineno}-L{node.end_lineno}",
                         {**source_identity(), "content_sha256": SOURCE_PINS[path]}, proposition, limitation, excerpt=excerpt)


def resource_zero_receipt():
    return seal({"formal_retriever_execution_performed": False,
                 **dict.fromkeys(("provider_calls", "search_calls", "network_search_calls", "follow_links",
                                  "automatic_retries", "credential_reads", "credit_consumption", "model_calls",
                                  "entrant_runs", "e1_frozen_runs", "e1_live_runs"), 0),
                 "spend": {"currency": "USD", "value": 0},
                 "official_prompt_consumed": False, "hidden_registry_loaded": False,
                 "operation": "PINNED_PUBLIC_SOURCE_INSPECTION_ONLY", "claims_ceiling": CLAIMS})


def build_bundle(*, root=None, expected_sha=BASELINE_SHA, expected_tree=BASELINE_TREE):
    sources = load_sources(root, expected_sha=expected_sha, expected_tree=expected_tree)
    candidates = discover_candidates(sources)
    chosen, reason = select_candidate(candidates)
    selected = freeze_candidate(chosen, sources) if chosen else None
    evidence = []
    for i, candidate in enumerate(candidates, 1):
        evidence.append(_source_evidence(sources, f"E-CANDIDATE-{i}", candidate["implementation_path"],
            candidate["symbol"].split(".")[0],
            "A concrete current-main backend exposes a SearchRequest callable: " + candidate["candidate_id"],
            "Implementation presence proves neither a selected instance/configuration nor F1 eligibility."))
    evidence += [
        _source_evidence(sources, "E-BOUNDARY", "search_cup/tools.py", "BudgetedSearchProxy",
                         "The shared proxy has normalized success/failure traces and a SearchRequest boundary.",
                         "Source contract only; no candidate call was made, and no entrant configuration was frozen."),
        _source_evidence(sources, "E-CONTRACT", "search_cup/contracts.py", "SearchResult",
                         "SearchResult declares the shared title/url/snippet result schema.",
                         "A schema does not establish upstream neutrality or equalized provenance/configuration."),
        _source_evidence(sources, "E-TEST-SOURCE", "tests/test_search_cup.py", "ToolBoundaryTests.test_search_pro_normalizes_real_contract_and_traces_identity",
                         "The existing test source checks normalization using an injected synthetic transport.",
                         "Test source inspected only; historical P1 success is not a v2.3 R1-R8 qualification."),
    ]
    discovery = {"candidate_ids": [c["candidate_id"] for c in candidates], "reason_code": reason,
                 "selection_rule": "EXACTLY_ONE_NO_PREFERENCE", "evidence_surface": list(DISCOVERY_PATHS),
                 "source": source_identity(), "source_pins": SOURCE_PINS}
    evidence.append(make_evidence("E-DISCOVERY", "GENERATED_OFFLINE_RECEIPT", "candidate-descriptor.json#discovery",
                                 {"content_sha256": fingerprint(discovery)},
                                 "Frozen discovery found " + str(len(candidates)) + " distinct backend implementations; " + reason + ".",
                                 "No choice by product name, history, convenience or eligibility class. No search executed."))
    descriptor = seal({"schema_id": "t3-f1q-candidate-discovery/v1", "source": source_identity(),
                       "discovery": discovery, "implementations": candidates,
                       "selected_candidate": selected,
                       "candidate_fingerprint": selected["canonical_fingerprint"] if selected else None})
    # Without unique selection, UNKNOWN is a NOT_ASSESSED placeholder, not a
    # judgment on either implementation. Even a unique implementation needs
    # evidence of a frozen instance/config and full upstream neutrality.
    checks = {r: {"status": "UNKNOWN", "evidence_ids": ["E-DISCOVERY", "E-BOUNDARY"]} for r in CRITERIA}
    qualification = seal({"schema_id": "t3-f1q-r1-r8/v1", "source": source_identity(),
                          "candidate_fingerprint": descriptor["candidate_fingerprint"],
                          "assessment_state": "NOT_ASSESSED_NO_UNIQUE_CANDIDATE" if selected is None else "INSUFFICIENT_INSTANCE_EVIDENCE",
                          "criteria": checks, "criterion_names": CRITERIA,
                          "reason_codes": [reason] if selected is None else ["INSTANCE_AND_NEUTRALITY_NOT_PROVEN"],
                          "qualification_result": criterion_gate(selected, checks, evidence)})
    manifest = seal({"schema_id": "t3-f1q-evidence/v1", "source": source_identity(), "entries": evidence,
                     "source_pins": SOURCE_PINS, "external_public_docs_collected": [],
                     "historical_live_receipts_used": [], "selection_authority": "NONE_DECLARED_IN_WORK_ORDER"})
    components = {"descriptor": descriptor, "qualification": qualification, "evidence": manifest,
                  "resources": resource_zero_receipt()}
    package_id = fingerprint({"source": source_identity(), "components": {k: v["canonical_fingerprint"] for k, v in components.items()}})
    receipt = seal({"work_order": WORK_ORDER, "source": source_identity(), "package_fingerprint": package_id,
                    "package_fingerprint_basis": "BASELINE_AND_FOUR_COMPONENT_SEALS",
                    "package_conformance": "PASS", "independent_acceptance": "PENDING",
                    "retriever_qualification": qualification["qualification_result"],
                    "qualification_result": qualification["qualification_result"],
                    "reason_codes": qualification["reason_codes"], "candidate_count": len(candidates),
                    "candidate_id": selected["candidate_id"] if selected else None,
                    "candidate_fingerprint": descriptor["candidate_fingerprint"],
                    "r1_r8": {r: check["status"] for r, check in checks.items()},
                    "evidence_fingerprints": {e["evidence_id"]: e["canonical_fingerprint"] for e in evidence},
                    "resource_receipt_fingerprint": components["resources"]["canonical_fingerprint"],
                    "t5_execution_authorized": False, "live_execution_authorized": False,
                    "claims_ceiling": CLAIMS})
    return {**components, "receipt": receipt}


def validate_bundle(bundle, *, root=None, expected_sha=BASELINE_SHA, expected_tree=BASELINE_TREE):
    for value in bundle.values():
        verify_seal(value)
    if canonical_json(bundle) != canonical_json(build_bundle(root=root, expected_sha=expected_sha, expected_tree=expected_tree)):
        raise ValueError("QUALIFICATION_PACKAGE_MUTATED")


def write_bundle(output_dir, **kwargs):
    bundle = build_bundle(**kwargs)
    validate_bundle(bundle, **kwargs)
    root = Path(output_dir)
    root.mkdir(parents=False, exist_ok=False)
    for key, name in FILENAMES.items():
        (root / name).write_text(canonical_json(bundle[key]), encoding="utf-8")
    manifest = "".join(hashlib.sha256(p.read_bytes()).hexdigest() + "  " + p.name + "\n" for p in sorted(root.iterdir()))
    (root / "MANIFEST.sha256").write_text(manifest, encoding="utf-8")
    return bundle["receipt"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("receipt", "bundle"))
    parser.add_argument("--expected-source-sha", required=True)
    parser.add_argument("--expected-source-tree", required=True)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    kwargs = {"expected_sha": args.expected_source_sha, "expected_tree": args.expected_source_tree}
    if args.command == "bundle":
        if args.output_dir is None:
            parser.error("bundle requires --output-dir")
        receipt = write_bundle(args.output_dir, **kwargs)
    else:
        if args.output_dir is not None:
            parser.error("receipt does not write a directory")
        receipt = build_bundle(**kwargs)["receipt"]
    print(canonical_json(receipt))
    # Negative/ambiguous retriever qualification is a valid conforming package.
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
