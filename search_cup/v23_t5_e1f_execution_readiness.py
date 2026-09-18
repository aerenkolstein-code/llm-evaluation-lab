"""EX0 freezes inert replay semantics and schemas; it never runs an entrant or query."""
from __future__ import annotations

import argparse
from contextlib import contextmanager, ExitStack
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from .contracts import SearchResult, canonical_json, fingerprint
from .protocol_v23 import SearchSpecV2, f1_eligibility, instance_gate, seal, verify_seal
from . import v23_t5_e1f_instance as parent

WORK_ORDER = "WO-ENG-B1-SC-V23-T5-E1F-EX0 v0.1"
BASELINE_SHA = "a583f6042dbfd78d251434141cdbf9b86cb910a9"
BASELINE_TREE = "669c6cb0785aaa5cead04d0b009c14f70a7d98af"
EXECUTION_ID = "T5-E1FROZEN-PV-001-EXEC-V1"
MODE = "OFFLINE_SYNTHETIC_E1_FROZEN_PROTOCOL_VALIDATION"
CLAIMS_CEILING = "E1_FROZEN_SYNTHETIC_PROTOCOL_VALIDATION_ONLY"
MODULE_PATH = "search_cup/v23_t5_e1f_execution_readiness.py"
APPROVED_PATHS = tuple(sorted((MODULE_PATH, "tests/test_search_cup_v23_t5_e1f_execution_readiness.py",
    "docs/search-cup-v23-t5-e1f-execution-readiness.md", ".github/workflows/t5-e1f-execution-readiness-offline.yml")))
ALIASES = ("t5-fixture-agent-a", "t5-fixture-agent-b")
RUN_SUFFIX = "E1F-001"
RUN_TEMPLATE = EXECUTION_ID + ":<execution-binding-fingerprint>:" + RUN_SUFFIX
PARENT_PINS = {
    "spec_fingerprint": "e459d11a6edfa580c2ccf0e77f498bd0c77ee89e7e2e05aba05d31052e786c21",
    "corpus_fingerprint": "71f1cca4e52d236bcdf948424b56a2710f364bdbf87d6351c68864c04a178a8d",
    "reference_set_fingerprint": "ae1329842c1bb5b9c7d0162801f5fb8f19fde1284bcae75497f3d29459f2e9d6",
    "index_fingerprint": "f8093933ffed0c3859cae0728551d125a89fa88be5fa094a77e4b30fb01d5b6f",
    "environment_fingerprint": "8a6ab28820bc5b323d697cdc02c072c4834463d136f8863dd2345568acc3b269",
    "entrant_roster_fingerprint": "e25840c866cac4ed6211aa2019fb9f1b63078ad7d5d5107f8f13a31706a9b04c",
    "retriever_binding_fingerprint": "08fc5b00045b234870d298e7cd90c998282f6642b566222799d75b6b341512ca",
    "retriever_descriptor_fingerprint": "6715a759a36dd3039dbf36bb15636eb683e107caec3953c68adb8e92c93d4281",
    "resource_envelope_fingerprint": "dae100dd614394359960ee2a5699f7ebf086ca72abefcca4b841857abe573f46",
    "reproduction_procedure_fingerprint": "2e5a3ceffa93ff8d6268f0cc2b981394159ff482639e88ec68425d01995a6bf2",
    "package_fingerprint": "dd4742c12343b602a1f755093cc7267b442fae2fa5cbb96570f7a5107bd227bf",
    "canonical_fingerprint": "eac316a162a46561f0856dc881b229cca94b930e184ffa0c35efd58ea3973b20",
}
SOURCE_PINS = {
    "search_cup/v23_t5_e1f_instance.py": "5d23c49c5d62e3355174fba7a4a754bfae41a0bd30e49c7fb5d979a29b541714",
    "configs/search-cup-v23-t5-e1f-pv-001.json": "94c09ba8a7920388a810ac6226094aa5b166872013fb5d6c8a8a9b0385f85f8a",
    "fixtures/search-cup/v23-t5-e1f-pv-001-corpus.json": "54e11e155af2f1e974b65094878dd3ea76c23bd9b2f08fae8fc1d32d47af688a",
    "fixtures/search-cup/v23-t5-e1f-pv-001-reference.json": "b565bc4637db99d09f6b6ae37eb75bd74ec76bc853101087bcc61ef9ed6e9d46",
    "search_cup/runner.py": "5e4ae73acaecc3c380c0dad98553b80bd176d5234cdf509b0e4fe7a18fb1356a",
    "search_cup/judge.py": "1a5fb49429ba58c6db5f7971725af6bae2ef09d6f5d52b7ad52e2d68cf21af68",
    "search_cup/providers.py": "94fa8c926a62b8bc0a5aa035c4a0416fea21b9a4572c16ebdd821ced61631e43",
    "search_cup/search_pro.py": "fddafa96bcb1c9694c32706c2f985fc0abc6cb484e457cf9b3dd65180aaeaab9",
    ".github/workflows/test.yml": "b90300655ed9ae7ff7b909969c9986e42b9dab4f444ad3237113b7747b2a4b4d",
}
PAYLOADS = {"parent": "parent-binding.json", "binding": "execution-binding.json",
    "profile_a": "fixture-profile-a.json", "profile_b": "fixture-profile-b.json",
    "policy": "shared-decision-policy.json", "queries": "query-plan.json", "run": "future-run-plan.json",
    "environment": "environment-recheck.json", "resources": "resource-plan.json",
    "integrity": "integrity-plan.json", "receipt": "readiness-receipt.json"}
COMPONENTS = tuple(k for k in PAYLOADS if k not in {"binding", "receipt"})
ZERO_FIELDS = ("entrant_calls", "retriever_query_calls", "proxy_calls", "provider_calls", "model_calls",
    "live_search_calls", "e1_frozen_runs", "e1_live_runs", "judge_calls", "follow_links", "automatic_retries",
    "credential_reads", "credit_consumption", "network_calls", "fallback_calls", "formal_run_output_count",
    "fixture_decision_calls_on_authoring_path")
FIXTURE_GUARDS = ("search_cup.providers.FakeProvider.run", "search_cup.providers.EntrantProvider.run")
# Immutable literals transcribed from WO sections 7-9. No corpus/reference lookup.
PHRASES = (
    ("remote", ("Remote work is permitted.", "Working from home is allowed.", "Fully remote work is available.",
        "Location-independent work is permitted.", "Telecommuting is allowed.", "Home-based work is allowed."),
       ("remote work is forbidden", "Working from home is not allowed.", "on-site-only", "Remote work is not permitted.",
        "Telecommuting is forbidden.", "home-based work is not allowed")),
    ("python_required", ("Python is required.", "Proficiency in Python is mandatory.", "Applicants must use Python.",
        "Python is an essential requirement.", "Python is a required skill.", "Python proficiency is necessary."),
       ("Python is optional, not required.", "never mandatory", "need not know Python", "not an essential requirement",
        "Python is not required", "Python proficiency is optional.")),
    ("applications_open", ("Applications are open.", "accepting applications now", "Recruitment is currently open.",
        "Application submissions are welcome.", "Applications are currently accepted.", "Recruiting is open."),
       ("Applications are closed.", "not accepting applications", "Recruitment has ended", "application window is shut")),
)
QUERY_PROFILES = (
    (ALIASES[0], "BROAD_DECOMPOSED_QUERY_V1", ("remote work", "python required", "applications open", "remote python applications open")),
    (ALIASES[1], "SYNONYM_SWEEP_QUERY_V1", ("working from home python mandatory accepting applications",
        "fully remote python recruitment open", "telecommuting python required applications accepted", "home-based python recruiting open")),
)
FORMAL_FILES = ("preflight.json", "run-start.json", "entrant-a-output.json", "entrant-b-output.json",
    "query-provenance.jsonl", "result-provenance.jsonl", "resource-receipts.json", "hidden-reference-barrier-audit.json",
    "adjudication.json", "metrics.json", "integrity-checks.json", "run-end.json", "post-run-receipt.json", "MANIFEST.sha256")


def baseline(sha=BASELINE_SHA, tree=BASELINE_TREE):
    if (sha, tree) != (BASELINE_SHA, BASELINE_TREE):
        raise ValueError("BASELINE_DRIFT")
    return {"sha": sha, "tree": tree}


def scope_gate(changes):
    """Validate the actual Git name-status rows supplied by dedicated CI, without Git I/O."""
    if type(changes) is not list or sorted(changes) != ["A\t" + p for p in APPROVED_PATHS]:
        raise ValueError("SCOPE_AMENDMENT_REQUIRED")
    return {"added_paths": list(APPROVED_PATHS), "modified_paths": []}


def boundary():
    return {"execution_allowed": False, "formal_execution_allowed": False, "formal_execution_performed": False,
        "formal_e1_execution_performed": False, "reference_labels_exposed_to_fixture": False,
        "official_prompt_consumed": False, "hidden_registry_loaded": False, "benchmark_claim": False,
        "model_quality_claim": False, "live_web_claim": False, "claims_ceiling": CLAIMS_CEILING,
        "independent_acceptance": "PENDING", "merge_authorized": False, "successor_execution_authorized": False}


def _sealed(kind, **fields):
    return seal({"schema_id": "t5-e1f-ex0-" + kind + "/v1", **fields})


def decision_policy():
    return _sealed("visible-decision-policy", policy_id="T5-E1F-VISIBLE-LITERAL-V1", version="1",
        input_type="SearchResult", input_fields=["title", "url", "snippet"],
        matching="CASE_SENSITIVE_LITERAL_SUBSTRING_WITHIN_EACH_FIELD; NO_NORMALIZATION_OR_CROSS_FIELD_MATCH",
        predicates={name: {"true_phrases": list(yes), "false_phrases": list(no)} for name, yes, no in PHRASES},
        truth_table={"positive_only": "TRUE", "negative_only": "FALSE", "neither": "UNKNOWN",
                     "both": "UNKNOWN/CONTRADICTORY_VISIBLE_EVIDENCE"},
        final_rule=["TRUE/TRUE/TRUE => RETURN_AS_MATCH", "any FALSE => DO_NOT_RETURN", "otherwise UNKNOWN / DO_NOT_RETURN"],
        missing_evidence="PRESERVE_UNKNOWN", external_reads="FORBIDDEN", peer_state_access="FORBIDDEN",
        reference_material_access="FORBIDDEN", pure_transform=True, result_is_formal_submission=False)


def visible_decision(result: SearchResult):
    """Pure per-record transform of three strings; no profile, peer, label or I/O handle.

    This returns ephemeral decision fields, never a submission or committed run
    record. EX0 uses it only with synthetic unit-test SearchResult objects.
    """
    if type(result) is not SearchResult or any(type(v) is not str for v in (result.title, result.url, result.snippet)):
        raise ValueError("EXACT_VISIBLE_SEARCHRESULT_REQUIRED")
    fields = (result.title, result.url, result.snippet)
    states = {}
    for name, yes, no in PHRASES:
        positives = [phrase for phrase in yes if any(phrase in value for value in fields)]
        negatives = [phrase for phrase in no if any(phrase in value for value in fields)]
        contradictory = bool(positives and negatives)
        value = "UNKNOWN" if contradictory or not (positives or negatives) else "TRUE" if positives else "FALSE"
        reason = "CONTRADICTORY_VISIBLE_EVIDENCE" if contradictory else "INSUFFICIENT_VISIBLE_EVIDENCE" if value == "UNKNOWN" else "EXPLICIT_VISIBLE_PHRASE"
        states[name] = {"state": value, "reason_code": reason, "positive_matches": positives, "negative_matches": negatives}
    values = [item["state"] for item in states.values()]
    decision = "RETURN_AS_MATCH" if all(v == "TRUE" for v in values) else "DO_NOT_RETURN"
    terminal = "FALSE" if "FALSE" in values else "UNKNOWN" if "UNKNOWN" in values else "TRUE"
    return {"predicates": states, "decision": decision, "truth_state": terminal}


@contextmanager
def authoring_guard():
    with parent.authoring_guard() as attempts, ExitStack() as stack:
        decision_attempts = []
        def deny(*args, **kwargs):
            decision_attempts.append("FIXTURE_DECISION_ON_AUTHORING_PATH")
            raise RuntimeError("EX0_AUTHORING_ONLY")
        for target in (__name__ + ".visible_decision", *FIXTURE_GUARDS):
            stack.enter_context(patch(target, side_effect=deny))
        yield {"parent_guard": attempts, "fixture_decision": decision_attempts}


def validate_parent(bundle):
    if type(bundle) is not dict or set(bundle) != set(parent.PAYLOADS):
        raise ValueError("PARENT_PACKAGE_SHAPE_MISMATCH")
    for value in bundle.values():
        verify_seal(value)
    if any(bundle["receipt"].get(key) != value for key, value in PARENT_PINS.items()):
        raise ValueError("PARENT_IDENTITY_DRIFT")
    actual = fingerprint({parent.PAYLOADS[k]: v["canonical_fingerprint"] for k, v in bundle.items() if k != "receipt"})
    if actual != PARENT_PINS["package_fingerprint"]:
        raise ValueError("PARENT_PACKAGE_DRIFT")
    if bundle["receipt"]["instance_id"] != "T5-E1FROZEN-PV-001":
        raise ValueError("PARENT_INSTANCE_DRIFT")
    spec = SearchSpecV2.from_mapping(bundle["searchspec"])
    gate = instance_gate(spec, bundle["bindings"], bundle["manifest"]["artifacts"])
    if (gate != bundle["receipt"]["instance_gate"] or gate["missing_decisions"] or gate["execution_allowed"]
            or gate["reason_codes"] != ["T1_IMPLEMENTATION_ONLY"] or f1_eligibility(spec.as_dict()["retriever"]) != "F1_ELIGIBLE"):
        raise ValueError("PARENT_GATE_OR_RETRIEVER_DRIFT")


def _resolve_parent(root=None, *, expected_sha=BASELINE_SHA, expected_tree=BASELINE_TREE):
    baseline(expected_sha, expected_tree)
    if parent.qualification.runtime_identity() != {"python_major_minor": "3.11", "unicode_data_version": "14.0.0"}:
        raise ValueError("RUNTIME_MISMATCH")
    root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    for name, digest in SOURCE_PINS.items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest:
            raise ValueError("RETAINED_SOURCE_MUTATED")
    method = (root / MODULE_PATH).read_bytes()
    if method != Path(__file__).resolve().read_bytes():
        raise ValueError("LOADED_METHOD_MISMATCH")
    # Deliberate offline author-side verification, never a fixture input delivery.
    accepted = parent.build_bundle(root=root)
    validate_parent(accepted)
    return accepted, hashlib.sha256(method).hexdigest()


def _profile(alias, name, queries, identity, policy):
    return _sealed("fixture-profile", entrant_id=alias, profile_id=name, version="1",
        program_class="DETERMINISTIC_LOCAL_FIXTURE_NOT_MODEL", parent_identity=identity,
        decision_implementation=__name__ + ":visible_decision", decision_policy_fingerprint=policy["canonical_fingerprint"],
        query_schedule=[{"query_number": i, "query": query} for i, query in enumerate(queries, 1)],
        all_queries_frozen_before_start=True, query_adaptation="NONE", input_fields=["title", "url", "snippet"],
        context_policy="OWN_ENTRANT_VISIBLE_TASK_CONTEXT_AND_OWN_SEARCHRESULTS_ONLY",
        union_policy="DEDUPLICATE_BY_EXACT_FROZEN_URL_DOC_ID_KEEP_FIRST_QUERY_THEN_RANK",
        reference_material_access="FORBIDDEN", peer_state_access="FORBIDDEN", external_reads="FORBIDDEN",
        api_endpoint=None, credential_access="FORBIDDEN", formal_invocations=0)


def _closed(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def _future_schemas(accepted):
    """Data contracts for later implementation, never generated formal outputs."""
    h = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
    text = {"type": "string", "minLength": 1}
    count = {"type": "integer", "minimum": 0}
    run_id = {"type": "string", "pattern": "^" + EXECUTION_ID + ":[0-9a-f]{64}:E1F-001$"}
    terminal = {"enum": ["PASS", "FAIL", "UNKNOWN", "BLOCKED", "NOT_EVALUABLE", "ERROR"]}
    alias = {"enum": list(ALIASES)}
    frozen_pins = _closed({name: h for name in (
        *["parent_" + key for key in PARENT_PINS], "execution_binding", "profile_a", "profile_b",
        "decision_policy", "query_plan", "resource_plan", "environment_recheck", "future_run_plan", "integrity_plan")})
    external_counts = _closed({name: count for name in ("provider_calls", "model_calls", "live_search_calls",
        "network_calls", "credential_reads", "follow_links", "fallback_calls", "judge_calls", "credit_consumption")})
    ref = _closed({"path": text, "file_sha256": h, "record_fingerprint": h})
    checks = _closed({f"I{i}": _closed({"status": terminal,
        "actual_run_evidence": {"type": "array", "items": ref, "minItems": 1}, "run_id": run_id}) for i in range(1, 11)})
    receipt = _closed({"entrant_id": alias, "run_id": run_id, "execution_binding_fingerprint": h,
        "proxy_instance_id": text, "query_attempts": {"type": "integer", "minimum": 0, "maximum": 4},
        "search_turns": {"type": "integer", "minimum": 0, "maximum": 4}, "results_per_call_limit": {"const": 10},
        "automatic_retries": {"const": 0}, "follow_links": {"const": 0}, "fallback_calls": {"const": 0},
        "provider_calls": {"const": 0}, "model_calls": {"const": 0}, "elapsed_ms": {"type": "number", "minimum": 0},
        "token_count": count, "token_accounting_basis": text, "spend_usd": {"const": 0},
        "terminal_status": terminal, "canonical_fingerprint": h})
    identity = {"run_id": run_id, "execution_binding_fingerprint": h, "parent_package_fingerprint": {"const": PARENT_PINS["package_fingerprint"]}}
    seal_field = {"canonical_fingerprint": h}
    submission = _closed({**identity, "entrant_id": alias, "submission": accepted["output"]["json_schema"],
                          "resource_receipt": receipt, **seal_field})
    query = _closed({**identity, "entrant_id": alias, "query_number": {"type": "integer", "minimum": 1, "maximum": 4},
        "query": text, "call_id": text, "request_id": text, "backend_id": {"const": parent.nfr.BACKEND_ID},
        "backend_attempts": {"type": "integer", "minimum": 0, "maximum": 1},
        "started_at_utc": text, "duration_ms": {"type": "number", "minimum": 0}, "terminal_status": terminal,
        "error_code": {"type": ["string", "null"]}, **seal_field})
    result = _closed({**identity, "entrant_id": alias, "call_id": text, "request_id": text,
        "backend_id": {"const": parent.nfr.BACKEND_ID},
        "rank": {"type": "integer", "minimum": 1, "maximum": 10}, "doc_id": text,
        "visible_result": _closed({"title": text, "url": text, "snippet": {"type": "string"}}), **seal_field})
    commit = _closed({"entrant_id": alias, "run_id": run_id, "submission_fingerprint": h, "output_file": text,
        "output_sha256": h, "commit_sequence": {"type": "integer", "minimum": 1},
        "file_fsync": {"const": True}, "directory_fsync": {"const": True}, "journal_record_fingerprint": h})
    schemas = {
        "preflight.json": _closed({**identity, "main_sha": text, "main_tree": text, "authority_receipt_id": text,
            "runtime": _closed({"python_major_minor": {"const": "3.11"}, "unicode_data_version": {"const": "14.0.0"}}),
            "retained_pins": frozen_pins, "terminal_status": terminal, **seal_field}),
        "run-start.json": _closed({**identity, "state": {"const": "STARTED"}, "started_at": text,
            "frozen_pins": frozen_pins, **seal_field}),
        "entrant-a-output.json": {**submission, "properties": {**submission["properties"], "entrant_id": {"const": ALIASES[0]}}},
        "entrant-b-output.json": {**submission, "properties": {**submission["properties"], "entrant_id": {"const": ALIASES[1]}}},
        "query-provenance.jsonl": query, "result-provenance.jsonl": result,
        "resource-receipts.json": _closed({**identity, "receipts": {"type": "array", "items": receipt, "minItems": 2, "maxItems": 2}, **seal_field}),
        "hidden-reference-barrier-audit.json": _closed({**identity,
            "submission_commits": {"type": "array", "items": commit, "minItems": 2, "maxItems": 2},
            "reference_load_sequence": {"type": "integer", "minimum": 3}, "reference_set_fingerprint": {"const": PARENT_PINS["reference_set_fingerprint"]},
            "reference_labels_exposed_to_fixture": {"const": False}, "cross_entrant_access_count": {"const": 0}, **seal_field}),
        "adjudication.json": _closed({**identity, "reference_set_fingerprint": {"const": PARENT_PINS["reference_set_fingerprint"]},
            "barrier_audit_fingerprint": h, "entrant_decisions": {"type": "array", "minItems": 2, "maxItems": 2,
                "items": _closed({"entrant_id": alias, "submission_fingerprint": h, "labels": {"type": "array", "items":
                    _closed({"doc_id": text, "label": {"enum": ["RELEVANT", "NOT_RELEVANT", "UNKNOWN"]}})}})}, **seal_field}),
        "metrics.json": _closed({**identity, "adjudication_fingerprint": h, "integrity_fingerprint": h,
            "entrant_metrics": {"type": "array", "minItems": 2, "maxItems": 2, "items": _closed({"entrant_id": alias,
                "values": {"type": "array", "minItems": 3, "maxItems": 3, "items": _closed({
                    "metric_id": {"enum": ["Recall@Budget", "Precision@K", "UNKNOWN_RETURN_COUNT"]}, "terminal_status": terminal,
                    "numerator": count, "denominator": count, "value": {"type": ["number", "null"]}})}})}, **seal_field}),
        "integrity-checks.json": _closed({**identity, "checks": checks, "comparable_status": {"enum": ["PASS", "NOT_EVALUABLE"]}, **seal_field}),
        "run-end.json": _closed({**identity, "state": {"enum": ["COMPLETED", "PARTIAL", "ERROR", "BLOCKED"]}, "ended_at": text,
            "start_fingerprint": h, "frozen_pins": frozen_pins, "terminal_status": terminal, **seal_field}),
        "post-run-receipt.json": _closed({**identity, "run_end_fingerprint": h, "integrity_fingerprint": h,
            "formal_execution_performed": {"type": "boolean"}, "comparable_status": {"enum": ["PASS", "NOT_EVALUABLE"]},
            "external_counts": external_counts, "spend_usd": {"type": "number", "minimum": 0},
            "official_prompt_consumed": {"type": "boolean"}, "hidden_registry_loaded": {"type": "boolean"},
            "reference_labels_exposed_to_fixture": {"type": "boolean"},
            "benchmark_claim": {"const": False}, "model_quality_claim": {"const": False}, "live_web_claim": {"const": False}, **seal_field}),
    }
    return {"json_schema_dialect": "https://json-schema.org/draft/2020-12/schema", "schemas": schemas,
        "jsonl_semantics": "ONE_CANONICAL_SEALED_RECORD_PER_LINE_IN_CALL_AND_RANK_ORDER",
        "manifest_semantics": "SHA256_OF_EVERY_FINAL_PAYLOAD_BYTE_SEQUENCE; TWO_SPACES; BASENAME; NEWLINE; NO_SELF_ENTRY",
        "partial_run_policy": "KEEP_EVERY_CREATED_RECORD; DO_NOT_FABRICATE_MISSING_SUBMISSIONS_OR_METRICS; NOT_EVALUABLE"}


def _integrity_plan():
    rows = (
        ("Parent identity unchanged", ["preflight.json", "run-start.json", "run-end.json"], "All exact parent pins match accepted publication."),
        ("Runtime and retriever exact", ["preflight.json", "query-provenance.jsonl"], "Python3.11/Unicode14.0.0 and exact F1 descriptor/config."),
        ("Equal resource envelope", ["resource-receipts.json", "query-provenance.jsonl"], "Fresh distinct proxies; four tickets each; no retries, links or fallback."),
        ("Fixture behavior exact", ["run-start.json", "query-provenance.jsonl"], "Exact profiles, literal policy and predeclared query order."),
        ("Reference barrier", ["hidden-reference-barrier-audit.json", "entrant-a-output.json", "entrant-b-output.json"], "Both durable distinct submission commits precede reference load."),
        ("Entrant isolation", ["hidden-reference-barrier-audit.json", "resource-receipts.json"], "No peer query/result/output/budget input; only own visible results."),
        ("Provenance complete", ["query-provenance.jsonl", "result-provenance.jsonl", "entrant-a-output.json", "entrant-b-output.json"], "Every final record resolves exact request, backend, result rank, URL/doc_id and frozen evidence."),
        ("Typed visible-evidence semantics", ["entrant-a-output.json", "entrant-b-output.json", "result-provenance.jsonl"], "Recompute literal three-state decisions; preserve contradictions and UNKNOWN without reference-derived repair."),
        ("Zero external capability", ["resource-receipts.json", "post-run-receipt.json"], "All external/model/provider/live/credential/follow/fallback/spend counts zero; no official prompt or registry."),
        ("No mutation after STARTED", ["run-start.json", "run-end.json"], "Start/end parent, binding, profile, query, resource and environment fingerprints identical."),
    )
    return _sealed("integrity-plan", checks={f"I{i}": {"requirement": title, "required_evidence_files": files,
        "predicate": predicate, "run_status": "NOT_RUN", "actual_run_evidence": []}
        for i, (title, files, predicate) in enumerate(rows, 1)},
        pass_rule="ALL_I1_I10_PASS_WITH_NONEMPTY_VERIFIED_ACTUAL_RUN_EVIDENCE",
        failed_hard_gate_result="NOT_EVALUABLE", missing_hard_evidence_result="NOT_EVALUABLE",
        missing_or_unknown_gate_result="NOT_EVALUABLE", plan_is_run_evidence=False,
        evidence_resolution="Each evidence path/hash/record must resolve to this exact run; a PASS label or future-plan reference is insufficient.")


def execution_binding(components, method_sha256):
    """Hash all nine successor components. No run-ID cycle: components hold a template."""
    if set(components) != set(COMPONENTS):
        raise ValueError("EXECUTION_COMPONENT_SET_MISMATCH")
    for value in components.values():
        verify_seal(value)
    return _sealed("execution-binding", execution_id=EXECUTION_ID, version="1", work_order=WORK_ORDER,
        source_baseline=baseline(), mode=MODE, execution_class="SYNTHETIC_FIXTURE_REPLAY",
        parent_instance_id="T5-E1FROZEN-PV-001", parent_package_fingerprint=PARENT_PINS["package_fingerprint"],
        component_fingerprints={PAYLOADS[k]: v["canonical_fingerprint"] for k, v in components.items()},
        implementation_content_sha256=method_sha256, run_namespace_template=RUN_TEMPLATE,
        fingerprint_scope="ALL_NINE_COMPONENTS_PLUS_IMPLEMENTATION; RECEIPT_IS_DERIVED_AND_SEPARATELY_SEALED",
        authority_required="INDEPENDENT_EX0_ACCEPTANCE_AND_PUBLICATION_THEN_SEPARATE_EXECUTOR_AND_PHASE_B_AUTHORITY",
        authoring_approval={"work_order": WORK_ORDER, "scope": "FOUR_NEW_PATHS_AND_OFFLINE_READINESS_ONLY",
            "preconstruction_user_instruction": "WO-ENG-B1-SC-V23-T5-E1F-EX0 v0.1批准并施工",
            "source": "CURRENT_DEVELOPMENT_CONVERSATION_BEFORE_CONSTRUCTION", "execution_permission": False}, **boundary())


def _assemble(accepted, method_sha256):
    validate_parent(accepted)
    policy = decision_policy()
    roster = {e["entrant_id"]: e for e in accepted["roster"]["entrants"]}
    profiles = [_profile(alias, name, queries, roster[alias], policy) for alias, name, queries in QUERY_PROFILES]
    parent_binding = _sealed("parent-binding", instance_id="T5-E1FROZEN-PV-001", published_main=BASELINE_SHA,
        published_tree=BASELINE_TREE, accepted_pr=70, accepted_head="7f784379c7d015e66b00b9c8f78ed689bc93cc3b",
        artifact={"id": 10543468788, "digest": "sha256:7781d887f52475c390820dbe74acb6efbf7044950242271296a0d39fdf70e010"},
        exact_pins=PARENT_PINS, parent_payload_seals={parent.PAYLOADS[k]: v["canonical_fingerprint"] for k, v in accepted.items()},
        retained_source_pins={**accepted["manifest"]["instance_config"]["source_pins"], **SOURCE_PINS},
        accepted_gate=accepted["receipt"]["instance_gate"], parent_modified=False,
        verification_mode="OFFLINE_RECONSTRUCTION_OF_INDEPENDENTLY_ACCEPTED_PUBLISHED_PARENT_NOT_NEW_PARENT_QA")
    queries = _sealed("query-plan", version="1", entrant_order=list(ALIASES),
        profiles=[{"entrant_id": p["entrant_id"], "profile_fingerprint": p["canonical_fingerprint"], "queries": p["query_schedule"]} for p in profiles],
        queries_planned_before_started=True, adaptive_queries=False, max_attempts_per_query=1,
        union_policy=profiles[0]["union_policy"], inconsistent_url_doc_id_policy="TYPED_PROTOCOL_FAILURE",
        duplicate_visible_content_policy="FIRST_SEEN_ONLY; LATER_DIFFERENT_CONTENT_FOR_SAME_ID_IS_PROTOCOL_FAILURE",
        final_submission_order="FIRST_SEEN_QUERY_ORDER_THEN_RANK_FILTERED_BY_SHARED_POLICY", executed_query_count=0)
    resources = _sealed("resource-plan", parent_resource_envelope_fingerprint=PARENT_PINS["resource_envelope_fingerprint"],
        identical_envelope=accepted["resources"]["resources"], parent_retry_policy=accepted["resources"]["retry_policy"],
        per_entrant=[{"entrant_id": alias, "budget_state_id_template": "<run_id>:" + alias + ":budget",
            "constructor": "search_cup.tools:BudgetedSearchProxy", "constructor_max_calls": 4,
            "lifecycle": "FRESH_PROXY_BEFORE_EACH_ENTRANT", "initial_calls_used": 0, "initial_traces": [],
            "backend_identity": PARENT_PINS["retriever_descriptor_fingerprint"], "peer_budget_access": "FORBIDDEN"} for alias in ALIASES],
        backend_sharing="SAME_IMMUTABLE_RETRIEVER_CORPUS_CONFIG_ONLY", mutable_state_sharing="FORBIDDEN",
        ticket_transfer="FORBIDDEN", prebackend_rejection="NO_BACKEND_NO_TICKET", fallback_policy="NONE",
        enforcement_boundary="Proxy enforces ticket ceiling; later executor must enforce turns, result limits, timeout, total runtime, tokens and zero cost.",
        timeout_policy="STOP_AND_PRESERVE_PARTIAL_INFRASTRUCTURE_FAILURE; NO_RETRY",
        successful_path_planned_attempts=8, maximum_backend_attempts=8, maximum_result_provenance_rows=80)
    environment = _sealed("environment-recheck", parent_environment=accepted["environment"],
        parent_environment_seal=PARENT_PINS["environment_fingerprint"], authoring_publication_baseline=baseline(),
        required_runtime={"python_major_minor": "3.11", "unicode_data_version": "14.0.0"},
        descriptor_fingerprint=PARENT_PINS["retriever_descriptor_fingerprint"], config_fingerprint=parent.nfr.CONFIG_FINGERPRINT,
        required_eligibility="F1_ELIGIBLE", hosted_image_identity="RUNTIME_PREDICATE_NOT_PERMANENT_IMAGE_PIN",
        future_execution_baseline="SEPARATELY_AUTHORIZED_EXACT_MAIN_OF_PUBLISHED_EXECUTOR; VERIFY_PARENT_ANCESTRY_AND_PINNED_BYTES",
        parent_historical_baseline_not_rewritten=True, network_access="FORBIDDEN", provider_access="FORBIDDEN", credential_access="FORBIDDEN",
        before_start=["Fresh actual main/tree and execution-binding authority", "Exact parent pins and byte identity",
            "Python3.11/Unicode14.0.0", "Exact descriptor/config and F1_ELIGIBLE", "Fresh isolated proxies", "Reference barrier closed"],
        after_run=["Repeat all immutable source/component fingerprints", "Compare start/end pins", "Preserve partial evidence on failure"],
        recheck_status="PLANNED_NOT_RUN")
    schemas = _future_schemas(accepted)
    integrity = _integrity_plan()
    run = _sealed("future-run-plan", execution_id=EXECUTION_ID, run_suffix=RUN_SUFFIX, run_namespace_template=RUN_TEMPLATE,
        binding_substitution="Insert the complete execution-binding canonical_fingerprint; no abbreviated hash or caller-selected suffix.",
        entrant_order=list(ALIASES), planned_submissions=2, max_calls_per_entrant=4, max_backend_attempts=8,
        max_result_provenance_rows=80, formal_submissions_committed=0,
        schedule=[{"order": i, "entrant_id": p["entrant_id"], "profile_fingerprint": p["canonical_fingerprint"],
            "query_plan_fingerprint": queries["canonical_fingerprint"], "proxy": "NEW_ISOLATED_FOUR_TICKET_PROXY",
            "query_numbers": [1, 2, 3, 4], "peer_context": [], "state": "PLANNED_NOT_EXECUTED"} for i, p in enumerate(profiles, 1)],
        states=["PREPARED", "STARTED", "A_SUBMISSION_COMMITTED", "B_SUBMISSION_COMMITTED", "REFERENCE_ACCESS_ENABLED", "ADJUDICATED", "COMPLETED"],
        reference_barrier={"initial_state": "CLOSED", "requires_committed_entrants": list(ALIASES), "requires_distinct_submissions": 2,
            "durability": "FSYNC_OUTPUT_FILE; ATOMIC_COMMIT; FSYNC_PARENT_DIRECTORY; APPEND_HASH_CHAINED_COMMIT_RECEIPT",
            "open_predicate": "Both distinct exact-run output hashes and submission seals resolve; both durable commit events precede first reference-load event.",
            "fixture_reference_access": "NEVER", "adjudicator_reference_access": "AFTER_BOTH_DURABLE_SUBMISSIONS_ONLY",
            "no_cross_entrant_synthesis_before_barrier": True, "reference_bytes_loaded_for_replay": False},
        parent_validation_vs_replay_barrier="EX0 verifies parent reference fingerprints as author; future fixture code never receives those bytes. Future executor must keep parent-authority verification outside fixture context.",
        isolation={"per_entrant_fresh_state": True, "visible": ["OWN_TASK_CONTEXT", "OWN_SEARCHRESULT_TITLE_URL_SNIPPET"],
            "forbidden": ["PEER_QUERIES", "PEER_RESULTS", "PEER_OUTPUT", "PEER_BUDGET", "REFERENCE_LABELS", "CONDITION_EVIDENCE", "ENVIRONMENT_CONFIGURATION", "EXTERNAL_FILES"]},
        future_artifact_files=list(FORMAL_FILES), future_output_contracts=schemas,
        parent_output_contract=accepted["output"], parent_evidence_contract=accepted["manifest"]["evidence_contract"],
        parent_metric_definitions=accepted["searchspec"]["metrics"],
        parent_adjudication_fingerprint=accepted["adjudication"]["canonical_fingerprint"],
        output_compatibility="EX0 execution envelope adds run identity around an unchanged parent submission; no parent schema extension.",
        cross_field_checks=["Run ID equals namespace derived from exact execution-binding fingerprint in every record.",
            "Exactly one successful-run output per roster alias, in A then B order; embedded parent entrant identity agrees.",
            "All query strings and numbers equal the frozen per-alias schedule; backend/request/call links are complete.",
            "Each returned URL/doc_id/evidence locator and corpus fingerprint agrees with the frozen visible result provenance.",
            "No more than four attempts per alias, ten results per call, eight attempts and 80 result rows total.",
            "Parent submission/resource/provenance fingerprints resolve full actual records; submission hash excludes only submission_fingerprint.",
            "Resource receipt limits match parent envelope; every overrun yields NOT_EVALUABLE and preserves partial evidence.",
            "Measured external counts and spend all equal zero; official prompt, hidden registry and fixture reference exposure all false for PASS.",
            "Record token accounting basis for pure fixture computation; missing or ambiguous resource measurement blocks comparison.",
            "Distinct fsynced submissions with resolvable hashes precede reference-load sequence; no label-bearing fixture input.",
            "All I1-I10 have PASS and nonempty actual exact-run evidence before any comparable PASS.",
            "UNKNOWN labels excluded from binary denominators; zero denominator NOT_EVALUABLE; only frozen parent metric definitions.",
            "Start/end pins identical; failures stop without retry or fallback, preserve partial artifacts and keep unfinished reference barrier closed."],
        failure_policy="STOP_PRESERVE_PARTIAL_NOT_EVALUABLE; DO_NOT_FABRICATE_UNREACHED_FILES_OR_SCORES",
        formal_execution_allowed=False, formal_execution_performed=False)
    components = {"parent": parent_binding, "profile_a": profiles[0], "profile_b": profiles[1], "policy": policy,
        "queries": queries, "run": run, "environment": environment, "resources": resources, "integrity": integrity}
    binding = execution_binding(components, method_sha256)
    run_id = EXECUTION_ID + ":" + binding["canonical_fingerprint"] + ":" + RUN_SUFFIX
    receipt = _sealed("readiness-receipt", work_order=WORK_ORDER, execution_id=EXECUTION_ID, mode=MODE,
        source_baseline=baseline(), package_conformance="PASS", parent_identity="EXACT_PUBLISHED_UNCHANGED",
        execution_binding_fingerprint=binding["canonical_fingerprint"], planned_run_namespace=run_id,
        component_fingerprints=binding["component_fingerprints"], parent_gate=accepted["receipt"]["instance_gate"],
        parent_f1_eligibility="F1_ELIGIBLE", post_run_integrity="NOT_RUN",
        **{name: 0 for name in ZERO_FIELDS}, spend={"state": "KNOWN", "value": 0, "unit": "USD"},
        counter_scope="EX0_AUTHORING_ONLY; SYNTHETIC_POLICY_UNIT_TESTS_AND_CI_GIT_SETUP_UPLOAD_ACCOUNTED_SEPARATELY", **boundary())
    return {**components, "binding": binding, "receipt": receipt}


def build_bundle(**kwargs):
    with authoring_guard() as attempts:
        result = _assemble(*_resolve_parent(**kwargs))
        if attempts["fixture_decision"] or any(attempts["parent_guard"].values()):
            raise RuntimeError("BLOCKED_OPERATION_OBSERVED")
        return result


def validate_bundle(bundle, *, expected_fingerprint, **kwargs):
    if type(bundle) is not dict or set(bundle) != set(PAYLOADS):
        raise ValueError("READINESS_PACKAGE_SHAPE_MISMATCH")
    for value in bundle.values():
        verify_seal(value)
    expected = build_bundle(**kwargs)
    if expected["binding"]["canonical_fingerprint"] != expected_fingerprint:
        raise ValueError("RETAINED_EXECUTION_PIN_MISMATCH")
    if canonical_json(bundle) != canonical_json(expected):
        raise ValueError("FROZEN_READINESS_PACKAGE_MUTATED")


def write_bundle(output_dir, **kwargs):
    output = Path(output_dir)
    if output.exists():
        raise FileExistsError("OUTPUT_DIRECTORY_ALREADY_EXISTS")
    bundle = build_bundle(**kwargs)
    output.mkdir(parents=False, exist_ok=False)
    for key, name in PAYLOADS.items():
        (output / name).write_text(canonical_json(bundle[key]), encoding="utf-8")
    parent.write_manifest(output)
    return bundle["receipt"]


def validate_directory(output_dir, *, expected_fingerprint, **kwargs):
    output = Path(output_dir)
    expected_names = set(PAYLOADS.values()) | {"MANIFEST.sha256"}
    names = {p.name for p in output.iterdir()}
    if names not in (expected_names, expected_names | {"ci-source.json", "focused-tests.log"}):
        raise ValueError("READINESS_FILE_SET_MISMATCH")
    if any(p.is_symlink() or not p.is_file() for p in output.iterdir()):
        raise ValueError("READINESS_NONREGULAR_FILE")
    manifest = "".join(hashlib.sha256(p.read_bytes()).hexdigest() + "  " + p.name + "\n"
                       for p in sorted(output.iterdir()) if p.name != "MANIFEST.sha256")
    if (output / "MANIFEST.sha256").read_text(encoding="utf-8") != manifest:
        raise ValueError("READINESS_BYTE_MANIFEST_MISMATCH")
    bundle = {key: json.loads((output / name).read_bytes()) for key, name in PAYLOADS.items()}
    validate_bundle(bundle, expected_fingerprint=expected_fingerprint, **kwargs)
    return bundle["receipt"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("receipt", "bundle", "validate"))
    parser.add_argument("--expected-source-sha", required=True)
    parser.add_argument("--expected-source-tree", required=True)
    parser.add_argument("--expected-fingerprint")
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    if args.command in {"bundle", "validate"} and args.output is None:
        parser.error("--output required")
    if args.command == "validate" and args.expected_fingerprint is None:
        parser.error("--expected-fingerprint required from independently retained review authority")
    kwargs = {"expected_sha": args.expected_source_sha, "expected_tree": args.expected_source_tree}
    result = (build_bundle(**kwargs)["receipt"] if args.command == "receipt" else write_bundle(args.output, **kwargs)
              if args.command == "bundle" else validate_directory(args.output, expected_fingerprint=args.expected_fingerprint, **kwargs))
    print(canonical_json(result))


if __name__ == "__main__":
    main()
