"""Closed, versioned JSON Schema for the offline SEARCH-CUP v2.3 seam.

No instance defaults, transport, key lookup, runner or judge are provided here.
The small validator deliberately implements only the vocabulary used below.
"""

from __future__ import annotations

import math
import re


def obj(properties: dict, *, optional: tuple[str, ...] = ()) -> dict:
    return {"type": "object", "properties": properties,
            "required": [key for key in properties if key not in optional],
            "additionalProperties": False}


def arr(items: dict, minimum: int = 0) -> dict:
    return {"type": "array", "items": items, "minItems": minimum, "uniqueItems": True}


def enum(*values: str) -> dict:
    return {"type": "string", "enum": list(values)}


def const(value: object) -> dict:
    return {"const": value}


TEXT = {"type": "string", "minLength": 1, "pattern": r"\S"}
HASH = {"type": "string", "pattern": "^[0-9a-f]{64}$"}
COUNT = {"type": "integer", "minimum": 0}
NUMBER = {"type": "number", "minimum": 0}
TEXTS = arr(TEXT)
REF = obj({"id": TEXT, "version": TEXT, "fingerprint": HASH})
TERMINALS = ("PASS", "FAIL", "UNKNOWN", "BLOCKED", "NOT_EVALUABLE", "ERROR")
TRACKS = ("E1_LIVE", "E1_FROZEN", "E2_RETRIEVER", "JUDGMENT_ONLY",
          "E_PLUS_J", "GLM_SEARCH_STACK", "SYSTEM_PLAYOFF", "ECONOMIC_TRACK")
A1_BEHAVIORS = ("QUERY_WORDING", "SYNONYMS", "SUBDIRECTION", "BOUNDED_REFINEMENT",
                "EVIDENCE_FOLLOWING", "DECOMPOSITION", "QUERY_REWRITE", "SYNTHESIS",
                "CROSS_QUERY_PLANNING", "INTENT_EXPANSION")
E1_BEHAVIORS = A1_BEHAVIORS[:5]
ABLATION_CAPABILITIES = (*A1_BEHAVIORS, "RETRIEVAL", "RANKING", "AGGREGATION", "VERIFICATION")
MEASURE = obj({"state": enum("KNOWN", "UNKNOWN", "NOT_APPLICABLE"),
               "value": {"type": ["number", "null"], "minimum": 0},
               "unit": TEXT, "reason": TEXT})
CHECK = obj({"status": enum("PASS", "FAIL", "UNKNOWN"), "evidence": arr(REF)})
QUALIFICATION = obj({"backend_fingerprint": HASH,
                     "criteria": obj({f"R{i}": CHECK for i in range(1, 9)})})
RETRIEVER = obj({
    "identity": REF, "backend_id": TEXT,
    "class": enum("RAW_RETRIEVER", "FROZEN_RETRIEVER", "INTEGRATED_SEARCH_STACK"),
    "config_fingerprint": HASH, "request_schema": REF, "result_schema": REF,
    "capabilities": arr(enum(*A1_BEHAVIORS, "RANKING", "RETRIEVAL")),
    "qualification": {"anyOf": [QUALIFICATION, {"type": "null"}]},
})
RESOURCE = obj({
    "schema_id": const("search-resource/v2"),
    "max_search_calls": COUNT, "max_search_turns": COUNT,
    "max_results_per_call": COUNT, "max_follow_links": COUNT,
    "automatic_retries": COUNT, "retry_policy": REF,
    "manual_retry_policy": enum("FORBIDDEN", "NEW_BUDGETED_EVENT"),
    "timeout_per_call_ms": {"type": "number", "exclusiveMinimum": 0},
    "max_total_runtime_ms": MEASURE, "token_ceiling": MEASURE,
    "money_ceiling": MEASURE, "resource_unit_definition": TEXT,
    "search_unit": enum("RAW_BACKEND_ATTEMPT", "INTEGRATED_STACK_INVOCATION", "NONE"),
    "failure_policy": const("INFRASTRUCTURE_NOT_QUALITY"),
    "exhaustion_policy": const("STOP_NO_EXPANSION"),
    "budget_rejection_policy": const("NO_BACKEND_NO_TICKET"),
})
TASK = obj({
    "task_id": TEXT, "task_class": TEXT, "target": TEXT,
    "objective": TEXT, "success_criteria": arr(TEXT, 1),
    "unit_of_evaluation": TEXT,
    "output_cardinality": obj({"minimum": COUNT, "maximum": COUNT}),
    "inclusion_criteria": TEXTS, "exclusion_criteria": TEXTS,
    "evidence_requirements": arr(TEXT, 1),
    "unknown_semantics": const("INSUFFICIENT_EVIDENCE_NOT_NEGATIVE"),
    "stop_conditions": arr(TEXT, 1),
})
SCOPE = obj({
    "language_pool": arr(TEXT, 1),
    "geography_scope": obj({"included": arr(TEXT, 1), "excluded": TEXTS}),
    "source_classes_allowed": arr(TEXT, 1), "source_classes_excluded": TEXTS,
    "time_window": TEXT, "freshness_rule": TEXT,
    "verification_sources_allowed": TEXTS, "verification_sources_excluded": TEXTS,
    "privacy_class": const("PUBLIC_SAFE"), "public_safe_only": const(True),
})
CONTROLS = ("task", "scope", "a0", "a1", "resources", "output", "judgment",
            "candidate_set", "evidence_packet", "rubric", "ordering", "corpus",
            "index", "retriever", "time_window", "environment", "prompt_context",
            "tools", "privacy", "control_model", "system_disclosure",
            "economic_package", "architecture", "disclosure_standard")
PRINCIPAL = {
    "JUDGMENT_ONLY": "JUDGE_MODEL_CONFIG", "E1_FROZEN": "ENTRANT_MODEL_CONFIG",
    "E1_LIVE": "ENTRANT_MODEL_CONFIG", "E2_RETRIEVER": "RETRIEVER_CONFIG",
    "GLM_SEARCH_STACK": "SYSTEM", "SYSTEM_PLAYOFF": "SYSTEM",
    "ECONOMIC_TRACK": "SYSTEM_RESOURCE_PACKAGE", "E_PLUS_J": "COMPOSITE_SYSTEM",
}
CLAIMS = ("JUDGMENT_ON_FROZEN_PACKAGE", "EXECUTION_ON_FROZEN_ENVIRONMENT",
          "EXECUTION_IN_LIVE_WINDOW", "RETRIEVER_SYSTEM_PERFORMANCE",
          "DECLARED_SYSTEM_PERFORMANCE", "OBSERVED_ECONOMIC_EFFICIENCY",
          "SINGLE_CAPABILITY_EFFECT", "ABSOLUTE_RECALL")
FROZEN_OVERLAY = obj({
    "kind": const("FROZEN"), "corpus": REF, "collection_provenance": REF,
    "public_safe": const(True), "index": REF, "reference_set": REF,
    "reproduction_procedure": REF,
})
LIVE_OVERLAY = obj({
    "kind": const("LIVE"), "window_policy": REF, "backend": REF,
    "drift_policy": REF, "pooled_candidate_policy": REF,
    "adjudication_timing": REF, "capture_policy": REF,
    "exhaustive_reference": {"anyOf": [REF, {"type": "null"}]},
})
JUDGMENT_OVERLAY = obj({
    "kind": const("JUDGMENT"), "candidate_set": REF, "evidence_packet": REF,
    "rubric": REF, "output_schema": REF, "adjudication_policy": REF,
    "blind_transform": REF, "order_policy": REF, "aggregation_policy": REF,
    "allowed_tools": arr(TEXT), "independent_first_pass": const(True),
})
SYSTEM_DISCLOSURE = obj({
    "components": arr(REF, 1), "capabilities": TEXTS, "tool_classes": TEXTS,
    "retry_fallback_policy": REF, "human_intervention_policy": REF,
    "money_source": REF, "time_source": REF,
    "opaque_quantities": TEXTS,
})
ECONOMIC_PACKAGE = obj({
    "basis": enum("MONEY", "OPERATOR_TIME", "WALL_CLOCK", "MONEY_AND_TIME", "APPROVED_EQUIVALENT"),
    "definition": REF, "accounting_period": TEXT, "currency": TEXT,
    "billing_basis": TEXT, "price_source": REF, "tax_policy": TEXT,
    "exchange_policy": REF, "rounding_policy": TEXT,
    "free_credit_policy": TEXT, "prepaid_credit_policy": TEXT,
    "unused_credit_policy": TEXT,
    "cost_basis": enum("CASH_OUTLAY", "LIST_PRICE_EQUIVALENT", "BOTH"),
    "time_kinds": arr(enum("MACHINE_ELAPSED", "OPERATOR_ACTIVE", "WAITING_QUEUE"), 2),
})
METRIC = obj({
    "metric_id": TEXT, "numerator": TEXT, "denominator": TEXT,
    "population": REF, "exclusion_rule": TEXT,
    "missingness": const("PRESERVE_TYPED_STATES"),
    "zero_denominator": const("NOT_EVALUABLE"),
})

SEARCHSPEC_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "$id": "urn:search-cup:searchspec:v2",
    "title": "SEARCH-CUP v2.3 SearchSpec v2 (protocol, not execution authority)",
    **obj({
        "schema_id": const("searchspec/v2"), "spec_id": TEXT, "spec_version": TEXT,
        "spec_status": enum("DRAFT", "FROZEN", "RETIRED"),
        "architecture_authority": const("SEARCH-CUP/v2.3"),
        "created_at": TEXT, "frozen_at": {"type": ["string", "null"]},
        "track_id": enum(*TRACKS), "fairness_mode": enum("F1", "F2", "F3", "ABLATION"),
        "task": TASK, "scope": SCOPE,
        "a0": obj({"origin": const("HUMAN_MODEL_CO_DESIGN"), "scored": const(False),
                   "frozen": const(True), "task_fingerprint": HASH,
                   "scope_fingerprint": HASH, "resource_fingerprint": HASH,
                   "task_hierarchy": arr(TEXT, 1), "stop_on_signal": arr(TEXT, 1),
                   "economic_success_criteria": TEXTS}),
        "a1": obj({"owner": enum("ENTRANT", "SEARCH_STACK", "NONE"),
                   "allowed": arr(enum(*A1_BEHAVIORS)),
                   "forbidden_mutations": const(["TASK", "SCOPE", "BUDGET", "EVIDENCE", "UNKNOWN_RULE"])}),
        "variable_control": obj({"principal": enum(*sorted(set(PRINCIPAL.values())), "ONE_CAPABILITY"),
                                 "fixed": obj({name: HASH for name in CONTROLS}, optional=CONTROLS),
                                 "qualified_nuisance": TEXTS,
                                 "changed_capabilities": arr(enum(*ABLATION_CAPABILITIES)),
                                 "fixed_capabilities": obj({name: HASH for name in ABLATION_CAPABILITIES}, optional=ABLATION_CAPABILITIES)}),
        "retriever": {"anyOf": [RETRIEVER, {"type": "null"}]},
        "resources": RESOURCE,
        "output_contract": REF, "judgment_contract": REF,
        "overlay": {"anyOf": [FROZEN_OVERLAY, LIVE_OVERLAY, JUDGMENT_OVERLAY]},
        "system_disclosure": {"anyOf": [SYSTEM_DISCLOSURE, {"type": "null"}]},
        "economic_package": {"anyOf": [ECONOMIC_PACKAGE, {"type": "null"}]},
        "claims": arr(enum(*CLAIMS), 1), "metrics": arr(METRIC, 1),
        "privacy": obj({"public_safe_inputs_only": const(True),
                        "credential_access": const(False), "private_locator_access": const(False),
                        "hidden_authority_access": const(False), "official_prompt_access": const(False)}),
        "canonical_fingerprint": HASH,
    }),
}


def validate_shape(value: object, schema: dict, path: str = "contract") -> None:
    """Validate the closed subset above; errors never include input values."""
    if "anyOf" in schema:
        for alternative in schema["anyOf"]:
            try:
                validate_shape(value, alternative, path)
                return
            except ValueError:
                pass
        raise ValueError(f"{path}: no allowed shape")
    if "const" in schema and (type(value) is not type(schema["const"]) or value != schema["const"]):
        raise ValueError(f"{path}: invalid constant")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path}: invalid enum")
    kind = schema.get("type")
    if isinstance(kind, list):
        validate_shape(value, {"anyOf": [{**schema, "type": k} for k in kind]}, path)
        return
    matches = {"object": type(value) is dict, "array": type(value) is list,
               "string": type(value) is str, "integer": type(value) is int,
               "number": type(value) in (int, float), "boolean": type(value) is bool,
               "null": value is None}
    if kind is not None and not matches.get(kind, False):
        raise ValueError(f"{path}: invalid type")
    if kind == "object":
        if any(key not in value for key in schema["required"]):
            raise ValueError(f"{path}: missing required fields")
        if set(value) - set(schema["properties"]):
            raise ValueError(f"{path}: unexpected fields")
        for key, item in value.items():
            validate_shape(item, schema["properties"][key], f"{path}.{key}")
    elif kind == "array":
        if len(value) < schema.get("minItems", 0):
            raise ValueError(f"{path}: too few items")
        if schema.get("uniqueItems") and any(item in value[:i] for i, item in enumerate(value)):
            raise ValueError(f"{path}: duplicate items")
        for item in value:
            validate_shape(item, schema["items"], f"{path}[]")
    elif kind == "string":
        if len(value) < schema.get("minLength", 0) or ("pattern" in schema and not re.search(schema["pattern"], value)):
            raise ValueError(f"{path}: invalid text")
    elif kind in ("integer", "number"):
        if (type(value) is float and not math.isfinite(value)) or value < schema.get("minimum", -math.inf) or value <= schema.get("exclusiveMinimum", -math.inf):
            raise ValueError(f"{path}: invalid number")
