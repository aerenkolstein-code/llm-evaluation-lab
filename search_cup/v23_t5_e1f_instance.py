"""Author one frozen synthetic instance. No query, entrant, judge or runner exists here."""
from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

from .contracts import canonical_json, fingerprint
from .protocol_v23 import (SearchSpecV2, assert_content_safe, control_bindings,
    f1_eligibility, instance_gate, reference, seal, verify_seal)
from . import v23_frozen_retriever as nfr
from . import v23_t3_f1q_r2 as qualification

WORK_ORDER = "WO-ENG-B1-SC-V23-T5-E1F-PV-01 v0.1"
BASELINE_SHA = "4785c392eb0b9e5d04c8eef04289a4888c222839"
BASELINE_TREE = "07849a3696009c47d284b896fd3f1676f617e98b"
INSTANCE_ID = "T5-E1FROZEN-PV-001"
SPEC_ID = "SEARCH-CUP-V23-T5-E1FROZEN-PV-001"
CLAIMS_CEILING = "E1_FROZEN_PROTOCOL_VALIDATION_ONLY"
CONFIG_PATH = "configs/search-cup-v23-t5-e1f-pv-001.json"
CORPUS_PATH = "fixtures/search-cup/v23-t5-e1f-pv-001-corpus.json"
REFERENCE_PATH = "fixtures/search-cup/v23-t5-e1f-pv-001-reference.json"
MODULE_PATH = "search_cup/v23_t5_e1f_instance.py"
CONFIG_FINGERPRINT = "6cdca1869965624d6de9ed9b1591308e4ac55382ab8a92d697bee18260592e50"
DESCRIPTOR_FINGERPRINT = "6715a759a36dd3039dbf36bb15636eb683e107caec3953c68adb8e92c93d4281"
ACCEPTED_F1Q_PACKAGE = "ff59157de522b8d7b17cea5908a094449b76be7f606b13bffb9b703285721886"
APPROVED_PATHS = tuple(sorted((MODULE_PATH, CONFIG_PATH, CORPUS_PATH, REFERENCE_PATH,
    "tests/test_search_cup_v23_t5_e1f_instance.py", "docs/search-cup-v23-t5-e1f-pv-001.md",
    ".github/workflows/t5-e1f-instance-offline.yml")))
REQUIRED_DECISIONS = ("D1", "D2", "D4", "D5", "D6", "D7")
PAYLOADS = {"manifest": "manifest.json", "searchspec": "searchspec.json", "corpus": "corpus.json",
    "provenance": "collection-provenance.json", "index": "index-descriptor.json",
    "reference": "reference-set.json", "reproduction": "reproduction-procedure.json",
    "roster": "entrant-roster.json", "retriever": "retriever-binding.json",
    "resources": "resource-envelope.json", "environment": "environment.json",
    "output": "output-contract.json", "adjudication": "adjudication-contract.json",
    "bindings": "instance-bindings.json", "receipt": "receipt.json"}
ZERO_FIELDS = ("entrant_calls", "provider_calls", "model_calls", "live_search_calls", "e1_frozen_runs",
    "e1_live_runs", "judge_calls", "follow_links", "credential_reads", "credit_consumption",
    "automatic_retries", "fallback_calls", "network_calls", "subprocess_calls",
    "local_fixture_retriever_calls", "proxy_calls")
QUERY_GUARDS = (
    "search_cup.v23_frozen_retriever.FrozenLexicalRetriever.__call__",
    "search_cup.tools.BudgetedSearchProxy.search",
    "search_cup.v23_t3_f1q_r2.run_probe_pass", "search_cup.v23_t3_f1q_r2.build_bundle",
    "search_cup.v23_frozen_retriever.build_bundle", "search_cup.v23_frozen_retriever.run_fixture_conformance",
)


def baseline(sha=BASELINE_SHA, tree=BASELINE_TREE):
    if (sha, tree) != (BASELINE_SHA, BASELINE_TREE):
        raise ValueError("BASELINE_DRIFT")
    return {"sha": sha, "tree": tree}


def boundary():
    return {"instance_class": "SYNTHETIC_PROTOCOL_VALIDATION", "claims_ceiling": CLAIMS_CEILING,
        "execution_allowed": False, "formal_e1_execution_performed": False,
        "benchmark_claim": False, "model_quality_claim": False, "live_web_claim": False,
        "independent_acceptance": "PENDING", "merge_authorized": False,
        "successor_execution_authorized": False}


@contextmanager
def authoring_guard():
    """Known call seams plus pinned closed sources; not a hostile-code sandbox."""
    with qualification.external_guard() as external, ExitStack() as stack:
        blocked = []
        def deny(*args, **kwargs):
            blocked.append("QUERY_OR_EXECUTION")
            raise qualification.ExternalOperationBlocked("AUTHORING_ONLY_NO_QUERY_OR_EXECUTION")
        for target in QUERY_GUARDS:
            stack.enter_context(patch(target, side_effect=deny))
        yield {"external": external, "query_or_execution": blocked}


def _sealed(kind, **fields):
    return seal({"schema_id": f"search-cup-t5-{kind}/v1", **fields})


def _measure(value, unit):
    return {"state": "KNOWN", "value": value, "unit": unit, "reason": "FROZEN_AUTHORING_ENVELOPE_NOT_CONSUMPTION"}


def resolve_inputs(root=None, *, expected_sha=BASELINE_SHA, expected_tree=BASELINE_TREE):
    baseline(expected_sha, expected_tree)
    if qualification.runtime_identity() != {"python_major_minor": "3.11", "unicode_data_version": "14.0.0"}:
        raise ValueError("RUNTIME_MISMATCH")
    root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    config = json.loads((root / CONFIG_PATH).read_bytes())
    if fingerprint(config) != CONFIG_FINGERPRINT:
        raise ValueError("INSTANCE_CONFIG_MISMATCH")
    for name, digest in config["source_pins"].items():
        if hashlib.sha256((root / name).read_bytes()).hexdigest() != digest:
            raise ValueError("RETAINED_SOURCE_MUTATED")
    if (root / MODULE_PATH).read_bytes() != Path(__file__).resolve().read_bytes():
        raise ValueError("LOADED_AUTHORING_MODULE_MISMATCH")
    corpus = json.loads((root / CORPUS_PATH).read_bytes())
    labels = json.loads((root / REFERENCE_PATH).read_bytes())
    if fingerprint(corpus) != config["corpus_input_fingerprint"]:
        raise ValueError("CORPUS_INPUT_MISMATCH")
    if fingerprint(labels) != config["reference_input_fingerprint"]:
        raise ValueError("REFERENCE_INPUT_MISMATCH")
    assert_content_safe(corpus)
    assert_content_safe(labels)
    frozen = nfr.FrozenCorpus(corpus["documents"], expected_fingerprint=config["corpus_fingerprint"])
    retriever_config = nfr.FrozenConfig(json.loads((root / nfr.CONFIG_PATH).read_bytes()))
    return root, config, corpus, labels, frozen, retriever_config


def reproduce_index(corpus, config, *, expected_corpus, expected_index,
                    descriptor_fingerprint=DESCRIPTOR_FINGERPRINT):
    if descriptor_fingerprint != DESCRIPTOR_FINGERPRINT:
        raise ValueError("DESCRIPTOR_MISMATCH")
    if qualification.runtime_identity() != {"python_major_minor": "3.11", "unicode_data_version": "14.0.0"}:
        raise ValueError("RUNTIME_MISMATCH")
    if type(corpus) is not nfr.FrozenCorpus or corpus.canonical_fingerprint != expected_corpus:
        raise ValueError("CORPUS_FINGERPRINT_MISMATCH")
    if type(config) is not nfr.FrozenConfig or config.canonical_fingerprint != nfr.CONFIG_FINGERPRINT:
        raise ValueError("RETRIEVER_CONFIG_MISMATCH")
    candidate = nfr.FrozenLexicalRetriever(corpus, config)
    content = {"schema_id": "search-cup-t5-lexical-index/v1", "documents": [
        {"doc_id": doc.doc_id, "units": [list(pair) for pair in units]} for doc, units in candidate._index]}
    if fingerprint(content) != expected_index:
        raise ValueError("INDEX_FINGERPRINT_MISMATCH")
    return content


def published_retriever(root):
    """Reconstruct accepted PR69 bytes from pinned sources/goldens, never rerun probes.

    Nested published receipts retain historical status/call counts. They describe
    PR69, not activity or independent acceptance of this T5 authoring package.
    """
    context = qualification.resolve_target(root=root)
    historical = qualification.assemble(context, qualification.expected_probe_pass(context),
                                       qualification.source_observations(context))
    qualification.validate_bundle(historical, root=root)
    if historical["receipt"]["package_fingerprint"] != ACCEPTED_F1Q_PACKAGE:
        raise ValueError("ACCEPTED_QUALIFICATION_MISMATCH")
    retriever = historical["qualification"]["protocol_retriever"]
    if (context["descriptor"]["canonical_fingerprint"] != DESCRIPTOR_FINGERPRINT
            or f1_eligibility(retriever) != "F1_ELIGIBLE"):
        raise ValueError("F1_BINDING_MISMATCH")
    return retriever, context["descriptor"], historical


def _assemble(root, config, corpus_input, labels, frozen, retriever_config):
    retriever, descriptor, historical = published_retriever(root)
    index_args = {"expected_corpus": config["corpus_fingerprint"], "expected_index": config["index_fingerprint"]}
    first = reproduce_index(frozen, retriever_config, **index_args)
    second = reproduce_index(nfr.FrozenCorpus(corpus_input["documents"]),
                            nfr.FrozenConfig(json.loads(retriever_config.canonical_content)), **index_args)
    if canonical_json(first) != canonical_json(second):
        raise ValueError("INDEX_NOT_DETERMINISTIC")
    materials = {}
    def bind(value, identity):
        ref = reference(value, identity)
        materials[ref["fingerprint"]] = value
        return ref
    corpus = seal({**corpus_input, "corpus_fingerprint": frozen.canonical_fingerprint,
                   "privacy_class": "PUBLIC_SAFE", "synthetic": True})
    refset = seal(labels)
    corpus_ref = bind(corpus, corpus["corpus_id"])
    labels_ref = bind(refset, refset["reference_set_id"])
    provenance = _sealed("collection-provenance", instance_id=INSTANCE_ID, corpus=corpus_ref,
        source="LITERAL_SYNTHETIC_DOCUMENTS", source_path=CORPUS_PATH,
        input_fingerprint=config["corpus_input_fingerprint"], corpus_fingerprint=frozen.canonical_fingerprint,
        collection_network_calls=0, randomness_used=False, external_sources_used=False,
        public_safe=True, real_opportunity_claim=False, urls="NONRESOLVED_EXAMPLE_INVALID_LOCATORS")
    reproduction = _sealed("reproduction-procedure", procedure_id="t5-e1frozen-pv-001-reproduction", version="1",
        source_baseline=baseline(), source_pins=config["source_pins"], instance_config_fingerprint=CONFIG_FINGERPRINT,
        corpus_fingerprint=frozen.canonical_fingerprint, index_fingerprint=fingerprint(first),
        retriever_descriptor_fingerprint=DESCRIPTOR_FINGERPRINT, config_fingerprint=nfr.CONFIG_FINGERPRINT,
        runtime=config["runtime"], network_access="FORBIDDEN", query_calls=0,
        invocation="python -m search_cup.v23_t5_e1f_instance bundle --expected-source-sha " + BASELINE_SHA
            + " --expected-source-tree " + BASELINE_TREE + " --output NEW_DIRECTORY",
        steps=["Verify actual Git base/tree, ancestry, exact seven additions and clean checkout outside builder.",
            "Validate supplied baseline, runtime, input fingerprints and retained source bytes; fail closed on mismatch.",
            "Reconstruct and validate accepted PR69 binding using source/golden identities without running its probes.",
            "Construct two fresh FrozenCorpus/FrozenConfig/FrozenLexicalRetriever objects; never call either retriever.",
            "Serialize doc_id and sorted character-unit counts from each immutable index; require identical pinned hashes.",
            "Freeze concrete artifacts and SearchSpec; resolve D1-D8 and require BLOCKED with no missing decisions.",
            "Seal every payload, validate exact reconstruction, and hash all final file bytes into MANIFEST.sha256."],
        baseline_verification="CALLER_GIT_ATTESTATION_PLUS_BUILDER_SOURCE_PINS_NOT_A_GIT_CLAIM_FROM_A_DEFAULT_ARGUMENT")
    reproduction_ref = bind(reproduction, reproduction["procedure_id"])
    cfg = json.loads(retriever_config.canonical_content)
    index = _sealed("index-descriptor", index_id="t5-e1frozen-pv-001-index", version="1",
        corpus_fingerprint=frozen.canonical_fingerprint, retriever_descriptor_fingerprint=DESCRIPTOR_FINGERPRINT,
        config_fingerprint=nfr.CONFIG_FINGERPRINT, normalization_id=cfg["normalization_id"], algorithm_id=cfg["algorithm_id"],
        result_limit=10, index_fingerprint=fingerprint(first), document_count=24, index_content=first,
        reproduction_procedure=reproduction_ref, reproduction_procedure_fingerprint=reproduction["canonical_fingerprint"],
        two_build_fingerprints=[fingerprint(first), fingerprint(second)], query_calls=0)
    environment = _sealed("environment", environment_id="t5-e1frozen-pv-001-offline-runtime-v1", version="1",
        **config["runtime"], source_baseline=baseline(), retriever_descriptor_fingerprint=DESCRIPTOR_FINGERPRINT,
        network_access="FORBIDDEN", provider_access="FORBIDDEN", model_access="FORBIDDEN", credential_access="FORBIDDEN",
        identity_semantics="RUNTIME_PREDICATE_NOT_PERMANENT_HOSTED_IMAGE_IDENTITY", future_execution_recheck_required=True)
    environment_ref = bind(environment, environment["environment_id"])
    retry = _sealed("retry-policy", policy_id="t5-e1frozen-pv-001-no-retry", version="1",
        automatic_retries=0, manual_retry_policy="FORBIDDEN", fallback_policy="NONE",
        failure_policy="INFRASTRUCTURE_NOT_QUALITY", budget_rejection_policy="NO_BACKEND_NO_TICKET")
    resources = {"schema_id": "search-resource/v2", "max_search_calls": 4, "max_search_turns": 4,
        "max_results_per_call": 10, "max_follow_links": 0, "automatic_retries": 0,
        "retry_policy": bind(retry, retry["policy_id"]), "manual_retry_policy": "FORBIDDEN",
        "timeout_per_call_ms": 1000, "max_total_runtime_ms": _measure(60000, "ms"),
        "token_ceiling": _measure(8000, "tokens"), "money_ceiling": _measure(0, "USD"),
        "resource_unit_definition": "One authorized BudgetedSearchProxy/backend attempt; rejected calls use no backend or ticket.",
        "search_unit": "RAW_BACKEND_ATTEMPT", "failure_policy": "INFRASTRUCTURE_NOT_QUALITY",
        "exhaustion_policy": "STOP_NO_EXPANSION", "budget_rejection_policy": "NO_BACKEND_NO_TICKET"}
    resource_envelope = _sealed("resource-envelope", resources=resources, retry_policy=retry,
        envelope_is_future_ceiling_not_execution_permission=True)
    entrants, entrant_configs = [], []
    for suffix in ("a", "b"):
        model_id = f"fixture-agent-{suffix}-v1"
        entrant_config = _sealed("entrant-config", config_id=model_id, fixture_only=True,
            endpoint_mode="NOT_CONNECTED", provider="synthetic-not-connected", connection_details=None)
        entrant_configs.append(entrant_config)
        materials[fingerprint(entrant_config)] = entrant_config
        entrants.append({"entrant_id": f"t5-fixture-agent-{suffix}", "provider": "synthetic-not-connected",
            "requested_model_id": model_id, "resolved_model_id": model_id, "resolution_status": "KNOWN",
            "identity_status": "AS_REQUESTED", "alias_evidence": None, "endpoint_mode": "NOT_CONNECTED",
            "config_fingerprint": fingerprint(entrant_config)})
    roster = _sealed("entrant-roster", roster_id="t5-e1frozen-pv-001-roster", version="1",
        entrants=entrants, configurations=entrant_configs, entrant_calls=0)
    binding = _sealed("retriever-binding", retriever=retriever, descriptor=descriptor,
        retriever_fingerprint=fingerprint(retriever), descriptor_fingerprint=DESCRIPTOR_FINGERPRINT,
        module_class=nfr.IMPLEMENTATION, config=cfg, config_fingerprint=nfr.CONFIG_FINGERPRINT,
        runtime=config["runtime"], eligibility=f1_eligibility(retriever),
        accepted_f1q_r2_package_fingerprint=ACCEPTED_F1Q_PACKAGE,
        publication={"pull_request": 69, "published_main": BASELINE_SHA, "published_tree": BASELINE_TREE},
        historical_qualification_package=historical,
        historical_material_policy="PR69_EVIDENCE_RECONSTRUCTION_ONLY_NOT_T5_PROBE_EXECUTION",
        qualification_rerun=False, retriever_query_calls=0)
    def closed(properties):
        return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}
    hash_schema = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
    text_schema = {"type": "string", "minLength": 1}
    terminal_schema = {"enum": ["PASS", "FAIL", "UNKNOWN", "BLOCKED", "NOT_EVALUABLE", "ERROR"]}
    doc_id_schema = {"enum": [d.doc_id for d in frozen.documents]}
    evidence_schema = closed({"doc_id": doc_id_schema,
        "evidence_locator": {"enum": [d.url + "#text" for d in frozen.documents]},
        "corpus_fingerprint": {"const": frozen.canonical_fingerprint}})
    evidence = _sealed("evidence-contract", contract_id="t5-e1frozen-pv-001-evidence", version="1",
        corpus=corpus_ref, corpus_fingerprint=frozen.canonical_fingerprint,
        evidence_locator_rule="Exact document URL plus #text; doc_id and corpus fingerprint must agree.",
        fields=["doc_id", "evidence_locator", "corpus_fingerprint"], json_schema=evidence_schema,
        evidence_text_rule="ONLY_FROZEN_TEXT",
        outside_corpus_evidence="FORBIDDEN", follow_links=0, live_verification="FORBIDDEN",
        unknown_semantics="INSUFFICIENT_EVIDENCE_NOT_NEGATIVE", inference_beyond_literal_text="FORBIDDEN")
    evidence_ref = bind(evidence, evidence["contract_id"])
    output_fields = ["spec_fingerprint", "entrant_identity", "environment_fingerprint", "retriever_fingerprint",
        "resource_receipt_fingerprint", "query_call_provenance", "result_provenance", "results",
        "submission_fingerprint", "terminal_status"]
    query_schema = closed({"call_id": text_schema, "request_id": text_schema, "original_query": text_schema,
        "entrant_id": {"enum": [e["entrant_id"] for e in entrants]}, "backend_id": {"const": nfr.BACKEND_ID},
        "terminal_status": terminal_schema, "backend_attempts": {"type": "integer", "minimum": 0, "maximum": 1}})
    result_schema = closed({"call_id": text_schema, "request_id": text_schema, "backend_id": {"const": nfr.BACKEND_ID},
        "rank": {"type": "integer", "minimum": 1, "maximum": 10}, "doc_id": doc_id_schema,
        "url": {"enum": [d.url for d in frozen.documents]}})
    output_schema = closed({"spec_fingerprint": hash_schema, "entrant_identity": {"enum": entrants},
        "environment_fingerprint": {"const": fingerprint(environment)}, "retriever_fingerprint": {"const": fingerprint(retriever)},
        "resource_receipt_fingerprint": hash_schema,
        "query_call_provenance": {"type": "array", "items": query_schema, "maxItems": 4, "uniqueItems": True},
        "result_provenance": {"type": "array", "items": result_schema, "maxItems": 40, "uniqueItems": True},
        "results": {"type": "array", "items": evidence_schema, "maxItems": 24, "uniqueItems": True},
        "submission_fingerprint": hash_schema, "terminal_status": terminal_schema})
    output = _sealed("output-contract", contract_id="t5-e1frozen-pv-001-output", version="1",
        evidence_contract=evidence_ref, environment=environment_ref, retriever_fingerprint=fingerprint(retriever),
        required_fields=output_fields, additional_fields="FORBIDDEN", json_schema=output_schema,
        field_contracts={
            "spec_fingerprint": "SHA256 equal to enclosing frozen SearchSpec canonical_fingerprint",
            "entrant_identity": "Exact one D5 roster entry; all identity/config fields required; no substitution",
            "environment_fingerprint": "SHA256 equal to environment reference fingerprint (complete sealed object)",
            "retriever_fingerprint": "SHA256 of exact SearchSpec retriever object",
            "resource_receipt_fingerprint": "SHA256 of the separately supplied sealed per-entrant resource receipt",
            "query_call_provenance": "Ordered unique call_id, request_id, original_query, entrant_id, backend_id, terminal_status, backend_attempts; max 4",
            "result_provenance": "For each result: call_id, request_id, backend_id, rank (1..10), doc_id, frozen URL; must resolve a query receipt",
            "results": "Ordered unique doc_id, evidence_locator and corpus_fingerprint records; 0..24, each with result provenance",
            "submission_fingerprint": "SHA256 of canonical submission excluding only this field",
            "terminal_status": "PASS|FAIL|UNKNOWN|BLOCKED|NOT_EVALUABLE|ERROR"},
        invalid_output_policy="TYPED_PROTOCOL_FAILURE_NO_SILENT_REPAIR_OR_INFERRED_EVIDENCE",
        no_successful_output_without_resource_and_provenance_material=True,
        claims_ceiling=CLAIMS_CEILING, benchmark_claim=False, model_quality_claim=False)
    adjudication = _sealed("adjudication-contract", contract_id="t5-e1frozen-pv-001-adjudication", version="1",
        corpus=corpus_ref, reference_set=labels_ref, evidence_contract=evidence_ref,
        pipeline=["Validate output identity, resource/provenance references and exact frozen evidence locators.",
            "Reject duplicate IDs, outside-corpus material or unresolved provenance as typed protocol failure.",
            "For valid unique returned IDs, join independently authored reference labels by exact doc_id.",
            "Keep UNKNOWN separate; never impute it as NOT_RELEVANT.",
            "Compute only declared within-population metrics if a separately authorized execution supplies valid receipts."],
        rule="ALL_THREE_EXPLICIT_TRUE_IS_RELEVANT; EXPLICIT_FALSE_IS_NOT_RELEVANT; OTHERWISE_UNKNOWN",
        reference_visible_to_entrant=False, deterministic=True, judge_model="NONE", judge_calls=0,
        follow_links=0, outside_corpus_evidence="FORBIDDEN", live_verification="FORBIDDEN",
        ordering="FIRST_RETURN_CALL_THEN_RANK; DEDUPLICATE_DOC_ID_KEEP_FIRST",
        unknown_binary_denominator_policy="EXCLUDE_FROM_BINARY_TRUTH_DENOMINATORS_COUNT_SEPARATELY",
        zero_denominator="NOT_EVALUABLE", missingness="PRESERVE_TYPED_STATES",
        metrics_executed=False, claims_ceiling=CLAIMS_CEILING)
    task = {"task_id": INSTANCE_ID, "task_class": "SYNTHETIC_FROZEN_RETRIEVAL_PROTOCOL_VALIDATION",
        "target": "Synthetic opportunity records in the frozen 24-document corpus only.",
        "objective": "Identify every record explicitly permitting remote work, requiring Python and accepting applications.",
        "success_criteria": ["All three predicates must be explicitly true in frozen text.",
            "Return frozen doc IDs with exact frozen evidence locators; never extrapolate."],
        "unit_of_evaluation": "UNIQUE_FROZEN_DOCUMENT", "output_cardinality": {"minimum": 0, "maximum": 24},
        "inclusion_criteria": ["Remote work explicitly permitted", "Python explicitly required", "Applications explicitly open"],
        "exclusion_criteria": ["An explicitly false required predicate", "Outside the frozen corpus"],
        "evidence_requirements": ["Exact frozen doc_id plus URL#text and corpus fingerprint", "No unstated inference"],
        "unknown_semantics": "INSUFFICIENT_EVIDENCE_NOT_NEGATIVE",
        "stop_conditions": ["Resource ceiling reached", "Protocol or infrastructure failure", "Entrant submits final output"]}
    scope = {"language_pool": ["en"], "geography_scope": {"included": ["SYNTHETIC_NO_REAL_GEOGRAPHY"], "excluded": []},
        "source_classes_allowed": ["FROZEN_SYNTHETIC_OPPORTUNITY_RECORD"], "source_classes_excluded": ["LIVE_WEB", "PRIVATE_DATA"],
        "time_window": "FROZEN_VERSION_1_NO_LIVE_WINDOW", "freshness_rule": "NO_REFRESH_AFTER_FREEZE",
        "verification_sources_allowed": ["EXACT_FROZEN_CORPUS"], "verification_sources_excluded": ["EXTERNAL_SOURCES"],
        "privacy_class": "PUBLIC_SAFE", "public_safe_only": True}
    a0 = {"origin": "HUMAN_MODEL_CO_DESIGN", "scored": False, "frozen": True,
        "task_fingerprint": fingerprint(task), "scope_fingerprint": fingerprint(scope),
        "resource_fingerprint": fingerprint(resources), "task_hierarchy": ["Retrieve", "Check explicit predicates", "Submit frozen evidence"],
        "stop_on_signal": task["stop_conditions"], "economic_success_criteria": []}
    a1 = {"owner": "ENTRANT", "allowed": ["QUERY_WORDING", "SYNONYMS", "SUBDIRECTION", "BOUNDED_REFINEMENT", "EVIDENCE_FOLLOWING"],
          "forbidden_mutations": ["TASK", "SCOPE", "BUDGET", "EVIDENCE", "UNKNOWN_RULE"]}
    prompt = _sealed("prompt-context", context_id="t5-e1frozen-pv-001-prompt", version="1", task=task, scope=scope,
        a1=a1, resources=resources, output_contract=bind(output, output["contract_id"]), evidence_contract=evidence_ref,
        entrant_visible_material=["TASK", "SCOPE", "A1", "RESOURCES", "OUTPUT_CONTRACT", "EVIDENCE_CONTRACT", "RETRIEVER_INTERFACE"],
        reference_labels_in_context=False, reference_material_access="FORBIDDEN_DURING_FUTURE_EXECUTION")
    tools = _sealed("tools", tool_id="t5-e1frozen-pv-001-tools", version="1",
        allowed_future_tool="BudgetedSearchProxy.search", backend_id=nfr.BACKEND_ID,
        retriever_fingerprint=fingerprint(retriever), max_results_per_call=10, follow_links=0,
        live_verification="FORBIDDEN", tool_execution_in_this_work_order=False)
    bind(prompt, prompt["context_id"])
    bind(tools, tools["tool_id"])
    metric_base = {"population": labels_ref, "missingness": "PRESERVE_TYPED_STATES", "zero_denominator": "NOT_EVALUABLE"}
    metrics = [
        {**metric_base, "metric_id": "Recall@Budget", "numerator": "Unique RELEVANT IDs returned within the four-attempt budget",
         "denominator": "6 frozen RELEVANT documents", "exclusion_rule": "UNKNOWN excluded from binary truth; no outside-corpus items"},
        {**metric_base, "metric_id": "Precision@K", "numerator": "RELEVANT IDs among first K=10 unique returned documents",
         "denominator": "KNOWN labels among first K=10 unique returned documents; UNKNOWN excluded without backfill",
         "exclusion_rule": "Deduplicate by first return order; count UNKNOWN separately; zero KNOWN denominator NOT_EVALUABLE"},
        {**metric_base, "metric_id": "UNKNOWN_RETURN_COUNT", "numerator": "Unique UNKNOWN IDs returned within budget",
         "denominator": "1 (count representation; not a binary quality rate)", "exclusion_rule": "Deduplicate; do not relabel UNKNOWN as negative"}]
    spec_doc = {"schema_id": "searchspec/v2", "spec_id": SPEC_ID, "spec_version": "1", "spec_status": "FROZEN",
        "architecture_authority": "SEARCH-CUP/v2.3", "created_at": config["freeze_timestamp"], "frozen_at": config["freeze_timestamp"],
        "track_id": "E1_FROZEN", "fairness_mode": "F1", "task": task, "scope": scope, "a0": a0, "a1": a1,
        "variable_control": {"principal": "ENTRANT_MODEL_CONFIG", "fixed": {}, "qualified_nuisance": [],
                             "changed_capabilities": [], "fixed_capabilities": {}},
        "retriever": retriever, "resources": resources, "output_contract": bind(output, output["contract_id"]),
        "judgment_contract": bind(adjudication, adjudication["contract_id"]),
        "overlay": {"kind": "FROZEN", "corpus": corpus_ref, "collection_provenance": bind(provenance, "t5-pv-collection"),
            "public_safe": True, "index": bind(index, index["index_id"]), "reference_set": labels_ref,
            "reproduction_procedure": reproduction_ref}, "system_disclosure": None, "economic_package": None,
        "claims": ["EXECUTION_ON_FROZEN_ENVIRONMENT"], "metrics": metrics,
        "privacy": {"public_safe_inputs_only": True, "credential_access": False, "private_locator_access": False,
                    "hidden_authority_access": False, "official_prompt_access": False}}
    fixed = {**control_bindings(spec_doc), "environment": fingerprint(environment),
             "prompt_context": fingerprint(prompt), "tools": fingerprint(tools)}
    spec_doc["variable_control"]["fixed"] = fixed
    # Retain concrete material for every control hash, including unsealed strict protocol objects.
    for key in ("task", "scope", "a0", "a1", "resources", "privacy", "retriever"):
        materials[fingerprint(spec_doc[key])] = spec_doc[key]
    spec = SearchSpecV2.from_mapping(seal(spec_doc))
    approval = _sealed("authoring-approval", work_order=WORK_ORDER, source_baseline=baseline(),
        approved_scope=list(APPROVED_PATHS), scope="INSTANCE_AUTHORING_AND_OFFLINE_TESTS_ONLY", execution_allowed=False)
    approval_ref = bind(approval, "t5-pv-user-approved-authoring")
    d_payloads = {"D1": {"binding": "E1_FROZEN"}, "D2": {"binding": spec.fingerprint, "searchspec": spec.as_dict()},
        "D4": {"frozen_overlay": spec.as_dict()["overlay"]}, "D5": {"roster": entrants}, "D6": {"retriever": retriever},
        "D7": {"binding": fingerprint(resources), "resources": resources}}
    decisions = {}
    for i in range(1, 9):
        name = f"D{i}"
        if name in d_payloads:
            material = {"schema_id": f"search-instance/{name.lower()}/v2", "spec_fingerprint": spec.fingerprint, **d_payloads[name]}
            decisions[name] = {"status": "FROZEN", "artifact": bind(material, f"t5-pv-{name.lower()}"),
                               "approval": approval_ref, "reason": "Exact inert authoring material; no execution authority."}
        else:
            decisions[name] = {"status": "NOT_APPLICABLE", "artifact": None, "approval": None,
                "reason": "E1_FROZEN is not Judgment-only." if name == "D3" else "F1 has no F2/F3/ablation system package."}
    bindings = seal({"schema_id": "search-instance-bindings/v2", "spec_fingerprint": spec.fingerprint, "decisions": decisions})
    gate = instance_gate(spec, bindings, materials)
    if gate["missing_decisions"] or gate["execution_allowed"] or gate["reason_codes"] != ["T1_IMPLEMENTATION_ONLY"]:
        raise ValueError("INSTANCE_GATE_CONFORMANCE_FAILED")
    bundle = {"searchspec": spec.as_dict(), "corpus": corpus, "provenance": provenance, "index": index,
        "reference": refset, "reproduction": reproduction, "roster": roster, "retriever": binding,
        "resources": resource_envelope, "environment": environment, "output": output,
        "adjudication": adjudication, "bindings": bindings}
    manifest = _sealed("manifest", work_order=WORK_ORDER, instance_id=INSTANCE_ID, source_baseline=baseline(),
        approved_paths=list(APPROVED_PATHS), instance_config=config, authoring_module_sha256=hashlib.sha256((root / MODULE_PATH).read_bytes()).hexdigest(),
        payload_fingerprints={PAYLOADS[k]: v["canonical_fingerprint"] for k, v in bundle.items()},
        artifacts=materials, authoring_approval=approval, evidence_contract=evidence, prompt_context=prompt, tools=tools,
        reference_hash_semantics="NEW_REFS_HASH_COMPLETE_SEALED_OBJECT; CANONICAL_SEALS_OMIT_ONLY_TOP_SEAL; PR69_REFS_RETAIN_PUBLISHED_SEMANTICS",
        **boundary())
    bundle["manifest"] = manifest
    receipt = _sealed("receipt", work_order=WORK_ORDER, instance_id=INSTANCE_ID, source_baseline=baseline(),
        package_conformance="PASS", instance_identity="EXACT_FROZEN", spec_fingerprint=spec.fingerprint,
        corpus_fingerprint=frozen.canonical_fingerprint, reference_set_fingerprint=refset["canonical_fingerprint"],
        index_fingerprint=fingerprint(first), reproduction_procedure_fingerprint=reproduction["canonical_fingerprint"],
        environment_fingerprint=environment["canonical_fingerprint"], entrant_roster_fingerprint=roster["canonical_fingerprint"],
        retriever_binding_fingerprint=binding["canonical_fingerprint"], retriever_descriptor_fingerprint=DESCRIPTOR_FINGERPRINT,
        resource_envelope_fingerprint=resource_envelope["canonical_fingerprint"], f1_eligibility=f1_eligibility(retriever),
        decision_statuses={k: v["status"] for k, v in decisions.items()}, instance_gate=gate,
        package_fingerprint=fingerprint({PAYLOADS[k]: v["canonical_fingerprint"] for k, v in bundle.items()}),
        index_reproduction={"build_count": 2, "fingerprints": [fingerprint(first), fingerprint(second)], "identical": True},
        **{k: 0 for k in ZERO_FIELDS}, spend=_measure(0, "USD"), official_prompt_consumed=False, hidden_registry_loaded=False,
        qualification_probes_rerun=False, blocked_external_attempts=0, metrics_executed=False,
        resource_scope="THIS_T5_AUTHORING_PATH_ONLY; PR69_NESTED_RECEIPTS_ARE_HISTORICAL; CI_SETUP_AND_GIT_ARE_INFRASTRUCTURE",
        **boundary())
    return {**bundle, "receipt": receipt}


def build_bundle(**kwargs):
    with authoring_guard() as attempts:
        bundle = _assemble(*resolve_inputs(**kwargs))
        if any(attempts.values()):
            raise qualification.ExternalOperationBlocked("BLOCKED_OPERATION_OBSERVED")
        return bundle


def validate_bundle(bundle, **kwargs):
    if type(bundle) is not dict or set(bundle) != set(PAYLOADS):
        raise ValueError("PACKAGE_SHAPE_MISMATCH")
    for payload in bundle.values():
        verify_seal(payload)
    # Full deterministic reconstruction binds labels, source bytes, nested contracts,
    # approvals and all control material, rather than trusting mutable PASS claims.
    expected = build_bundle(**kwargs)
    if canonical_json(bundle) != canonical_json(expected):
        raise ValueError("T5_PACKAGE_MUTATED")
    artifacts = bundle["manifest"]["artifacts"]
    if any(fingerprint(value) != key for key, value in artifacts.items()):
        raise ValueError("ARTIFACT_CONTENT_MISMATCH")
    gate = instance_gate(SearchSpecV2.from_mapping(bundle["searchspec"]), bundle["bindings"], artifacts)
    if gate != bundle["receipt"]["instance_gate"]:
        raise ValueError("GATE_RECEIPT_MISMATCH")


def write_manifest(output):
    output = Path(output)
    entries = sorted(p for p in output.iterdir() if p.name != "MANIFEST.sha256")
    if any(not p.is_file() or p.is_symlink() for p in entries):
        raise ValueError("ARTIFACT_NONREGULAR_FILE")
    text = "".join(hashlib.sha256(p.read_bytes()).hexdigest() + "  " + p.name + "\n" for p in entries)
    (output / "MANIFEST.sha256").write_text(text, encoding="utf-8")
    return text


def write_bundle(output_dir, **kwargs):
    output = Path(output_dir)
    if output.exists():
        raise FileExistsError("OUTPUT_DIRECTORY_ALREADY_EXISTS")
    bundle = build_bundle(**kwargs)
    validate_bundle(bundle, **kwargs)
    output.mkdir(parents=False, exist_ok=False)
    for key, name in PAYLOADS.items():
        (output / name).write_text(canonical_json(bundle[key]), encoding="utf-8")
    write_manifest(output)
    return bundle["receipt"]


def validate_directory(output_dir, **kwargs):
    output = Path(output_dir)
    allowed = set(PAYLOADS.values()) | {"MANIFEST.sha256"}
    names = {p.name for p in output.iterdir()}
    if names not in (allowed, allowed | {"ci-source.json", "focused-tests.log"}):
        raise ValueError("ARTIFACT_FILE_SET_MISMATCH")
    if any(not p.is_file() or p.is_symlink() for p in output.iterdir()):
        raise ValueError("ARTIFACT_NONREGULAR_FILE")
    expected = "".join(hashlib.sha256(p.read_bytes()).hexdigest() + "  " + p.name + "\n"
                       for p in sorted(output.iterdir()) if p.name != "MANIFEST.sha256")
    if (output / "MANIFEST.sha256").read_text(encoding="utf-8") != expected:
        raise ValueError("ARTIFACT_BYTE_MANIFEST_MISMATCH")
    bundle = {k: json.loads((output / name).read_bytes()) for k, name in PAYLOADS.items()}
    validate_bundle(bundle, **kwargs)
    return bundle["receipt"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("receipt", "bundle", "validate"))
    parser.add_argument("--expected-source-sha", required=True)
    parser.add_argument("--expected-source-tree", required=True)
    parser.add_argument("--output")
    args = parser.parse_args(argv)
    kwargs = {"expected_sha": args.expected_source_sha, "expected_tree": args.expected_source_tree}
    if args.command != "receipt" and args.output is None:
        parser.error("--output is required")
    result = (build_bundle(**kwargs)["receipt"] if args.command == "receipt" else
              write_bundle(args.output, **kwargs) if args.command == "bundle" else validate_directory(args.output, **kwargs))
    print(canonical_json(result))


if __name__ == "__main__":
    main()
