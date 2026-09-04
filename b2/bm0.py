"""B2 BM0: offline multi-model benchmark measurement contracts.

BM0 freezes identities, applicability, denominators, terminal semantics, analysis
methods, corpus boundaries, adjudication, and claim ceilings.  This module is
deliberately pure and offline: it has no provider, credential, network, storage,
or execution adapter.
"""

from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from copy import deepcopy
from typing import Any, Iterable, Mapping, Sequence

from .qa0 import TERMINAL_STATUSES, assert_public_safe, sha256_json

CONTRACT_SCHEMA_VERSION = "b2-bm0-measurement-contract/v1"
MATRIX_SCHEMA_VERSION = "b2-bm0-target-applicability/v1"
METRIC_REGISTRY_SCHEMA_VERSION = "b2-bm0-metric-registry/v1"
CORPUS_POLICY_SCHEMA_VERSION = "b2-bm0-corpus-policy/v1"
TRIAL_IDENTITY_SCHEMA_VERSION = "b2-bm0-trial-identity/v1"
MANIFEST_SCHEMA_VERSION = "b2-bm0-benchmark-manifest/v1"
OBSERVATION_SCHEMA_VERSION = "b2-bm0-observation/v1"
ADJUDICATION_SCHEMA_VERSION = "b2-bm0-adjudication-record/v1"
RECEIPT_SCHEMA_VERSION = "b2-bm0-contract-validation-receipt/v1"

WORK_ORDER_ID = "WO-B2-BM0"
WORK_ORDER_REVISION = "v0.2"
IMPLEMENTATION_BASE_SHA = "901ba05b99c413d45415c474c71b5969c155dea1"
SYSTEM_SCOPE_ID = "SYSTEM_SCOPE"
PRIMARY_ESTIMATE_POOL_ID = "PRIVATE_HIDDEN_HOLDOUT"

TARGET_CLASSES = (
    "MODEL_DIRECT",
    "MODEL_CONTEXT_GROUNDED",
    "AGENT_STANDARDIZED",
    "SYSTEM_EVAL_ONLY",
)
DEFAULT_COMPARABLE_CLASSES = (
    "MODEL_DIRECT",
    "MODEL_CONTEXT_GROUNDED",
)
TARGET_IDS_BY_CLASS = {
    "MODEL_DIRECT": (
        "BM0-TUT-D01-CONSTRAINT-ADHERENCE",
        "BM0-TUT-D02-REASONING-INTEGRITY",
        "BM0-TUT-D03-CALIBRATED-ABSTENTION",
    ),
    "MODEL_CONTEXT_GROUNDED": (
        "BM0-TUT-G01-ENTITY-ATTRIBUTE-BINDING",
        "BM0-TUT-G02-INVENTORY-EVIDENCE-SCOPE",
        "BM0-TUT-G03-SOURCE-MODALITY-PROVENANCE",
        "BM0-TUT-G04-LONG-CONTEXT-CONSTRAINT-PERSISTENCE",
        "BM0-TUT-G05-CITATION-EVIDENCE-COMPLETENESS",
    ),
    "AGENT_STANDARDIZED": (
        "BM0-TUT-A01-CONNECTOR-SCHEMA-READBACK-RETRY",
        "BM0-TUT-A02-CAPABILITY-PERMISSION-ROUTING",
        "BM0-TUT-A03-DESTRUCTIVE-WRITE-RECOVERY",
        "BM0-TUT-A04-TOOL-SEQUENCE-GLOBAL-INTEGRITY",
    ),
    "SYSTEM_EVAL_ONLY": (
        "BM0-TUT-S01-FULL-SET-PROJECTION-COMPLETENESS",
        "BM0-TUT-S02-TERMINAL-STATE-PERSISTENCE",
        "BM0-TUT-S03-ADAPTER-RECONCILIATION",
        "BM0-TUT-S04-CLAIM-EVIDENCE-INTEGRITY",
    ),
}
EXPECTED_TARGET_CLASS_COUNTS = {
    target_class: len(target_ids)
    for target_class, target_ids in TARGET_IDS_BY_CLASS.items()
}

MODEL_SCORABLE_TERMINALS = ("PASS", "FAIL")
NON_MODEL_SCORABLE_TERMINALS = (
    "NOT_EVALUABLE",
    "BLOCKED",
    "ERROR",
    "UNKNOWN",
)
TERMINAL_CONTRACT = {
    "PASS": {
        "category": "MODEL_SCORABLE",
        "model_failure_denominator": True,
        "model_failure_numerator": False,
    },
    "FAIL": {
        "category": "MODEL_SCORABLE",
        "model_failure_denominator": True,
        "model_failure_numerator": True,
    },
    "NOT_EVALUABLE": {
        "category": "NON_EVALUABLE",
        "model_failure_denominator": False,
        "model_failure_numerator": False,
    },
    "BLOCKED": {
        "category": "GOVERNANCE_BLOCK",
        "model_failure_denominator": False,
        "model_failure_numerator": False,
    },
    "ERROR": {
        "category": "INFRASTRUCTURE_ERROR",
        "model_failure_denominator": False,
        "model_failure_numerator": False,
    },
    "UNKNOWN": {
        "category": "INSUFFICIENT_EVIDENCE",
        "model_failure_denominator": False,
        "model_failure_numerator": False,
    },
}

SAP_METHOD_IDS = (
    "BM0-SAP-01-FIXED-ATTEMPT-STOP-V1",
    "BM0-SAP-02-IDENTITY-GRID-V1",
    "BM0-SAP-03-TYPED-TERMINAL-PARTITION-V1",
    "BM0-SAP-04-MODEL-FAILURE-DENOMINATOR-V1",
    "BM0-SAP-05-WILSON-INTERVAL-V1",
    "BM0-SAP-06-PAIRED-COMPLETE-CASE-V1",
    "BM0-SAP-07-ADJUDICATION-RESOLUTION-V1",
    "BM0-SAP-08-SYSTEM-INVARIANT-FAILURE-RATE-V1",
)
SAP_IMPLEMENTATIONS = {
    SAP_METHOD_IDS[0]: "fixed_attempt_stop_v1",
    SAP_METHOD_IDS[1]: "validate_observation_grid_v1",
    SAP_METHOD_IDS[2]: "typed_terminal_partition_v1",
    SAP_METHOD_IDS[3]: "model_failure_denominator_v1",
    SAP_METHOD_IDS[4]: "wilson_interval_v1",
    SAP_METHOD_IDS[5]: "paired_complete_case_v1",
    SAP_METHOD_IDS[6]: "resolve_adjudication_v1",
    SAP_METHOD_IDS[7]: "system_invariant_failure_rate_v1",
}
PAIR_COMPATIBILITY_FIELDS = (
    "target_id",
    "target_class",
    "corpus_item_alias",
    "corpus_item_commitment",
    "corpus_pool_id",
    "mutation_parent_commitment",
    "prompt_template_version",
    "harness_version",
    "adapter_version",
    "replicate_index",
    "random_seed",
    "environment_fingerprint",
)
SAP_FROZEN_PARAMETERS = {
    SAP_METHOD_IDS[0]: {
        "required_event_fields": ["attempt_id", "recorded"],
        "forbidden_event_fields": [
            "terminal_status",
            "model_failure_value",
            "score",
            "output",
            "adjudication_decision",
        ],
        "decision_rule": "STOP_IFF_ALL_PREDECLARED_ATTEMPTS_RECORDED",
    },
    SAP_METHOD_IDS[1]: {
        "duplicate_policy": "ERROR",
        "unplanned_policy": "ERROR",
        "missing_policy": "NOT_EVALUABLE",
    },
    SAP_METHOD_IDS[2]: {
        "terminal_statuses": list(TERMINAL_STATUSES),
        "coercion": "FORBIDDEN",
        "diagnostic_numerator": list(NON_MODEL_SCORABLE_TERMINALS),
        "diagnostic_denominator": list(TERMINAL_STATUSES),
        "zero_scheduled_attempts": "NOT_EVALUABLE",
        "corpus_pool": "ALL_DECLARED_POOLS",
    },
    SAP_METHOD_IDS[3]: {
        "numerator": ["FAIL"],
        "denominator": ["PASS", "FAIL"],
        "excluded": list(NON_MODEL_SCORABLE_TERMINALS),
        "zero_denominator": "NOT_EVALUABLE",
        "ranking": "FORBIDDEN_AT_BM0",
        "corpus_pool": PRIMARY_ESTIMATE_POOL_ID,
    },
    SAP_METHOD_IDS[4]: {
        "confidence_level": 0.95,
        "z": 1.959963984540054,
        "zero_denominator": "NOT_EVALUABLE",
    },
    SAP_METHOD_IDS[5]: {
        "pair_key": [
            "target_id",
            "corpus_item_alias",
            "replicate_index",
            "retry_ordinal",
        ],
        "compatibility_fields": list(PAIR_COMPATIBILITY_FIELDS),
        "non_scorable_pair_policy": "SYMMETRIC_EXCLUSION",
        "unpaired_design": "NOT_EVALUABLE",
        "identity_mismatch": "NOT_EVALUABLE",
        "ranking": "NOT_EMITTED",
        "corpus_pool": PRIMARY_ESTIMATE_POOL_ID,
    },
    SAP_METHOD_IDS[6]: {
        "primary_records": 2,
        "distinct_adjudicators": True,
        "tiebreakers_on_disagreement": 1,
        "identity_blinding": True,
        "peer_decision_blinding": True,
    },
    SAP_METHOD_IDS[7]: {
        "target_class": "SYSTEM_EVAL_ONLY",
        "subject_identity": SYSTEM_SCOPE_ID,
        "numerator": ["FAIL"],
        "denominator": ["PASS", "FAIL"],
        "excluded": list(NON_MODEL_SCORABLE_TERMINALS),
        "model_attribution": "FORBIDDEN",
        "ranking": "FORBIDDEN",
        "corpus_pool": PRIMARY_ESTIMATE_POOL_ID,
    },
}

EXPECTED_METRIC_IDS = {
    "model_failure_rate",
    "sandboxed_agent_failure_rate",
    "system_invariant_failure_rate",
    "non_scorable_attempt_rate",
}
EXPECTED_POOL_IDS = {
    "PUBLIC_DEVELOPMENT",
    "PUBLIC_CONTROL",
    "MUTATION",
    "PRIVATE_HIDDEN_HOLDOUT",
}
SANDBOX_EQUIVALENCE_EVIDENCE_TYPES = (
    "SANDBOX_IMAGE",
    "TOOL_SURFACE",
    "BUDGET_RETRY",
    "NETWORK_CREDENTIAL_POLICY",
    "INDEPENDENT_EQUIVALENCE_RECEIPT",
)
BOUND_ARTIFACT_PATHS = (
    "b2/bm0.py",
    "tests/test_b2_bm0.py",
    "cases/b2/public-safe/benchmark/bm0-target-applicability.json",
    "cases/b2/public-safe/benchmark/bm0-metric-registry.json",
    "cases/b2/public-safe/benchmark/bm0-corpus-policy.json",
    "cases/b2/public-safe/benchmark/bm0-benchmark-manifest.template.json",
    "schemas/bm0_trial_identity.schema.json",
    "schemas/bm0_observation.schema.json",
    "schemas/bm0_adjudication_record.schema.json",
    "schemas/bm0_benchmark_manifest.schema.json",
    "schemas/bm0_measurement_contract.schema.json",
)
CONTRACT_ARTIFACT_PATH = (
    "cases/b2/public-safe/benchmark/bm0-measurement-contract.json"
)
ALLOWED_CLAIM_CODES = {
    "BM0_OFFLINE_CONTRACT_VALIDATED",
    "BM0_READY_FOR_EXACT_HEAD_CI_AND_INDEPENDENT_QA",
}
FORBIDDEN_CLAIM_CODES = {
    "BM0_GREEN",
    "MODEL_RANKING",
    "MODEL_WINNER",
    "LIVE_PROVIDER_PERFORMANCE",
    "POPULATION_FAILURE_RATE",
    "CAUSAL_IMPROVEMENT",
    "FAIRNESS_VALIDATED",
    "LQE_VALIDATED",
    "PRODUCTION_READY",
    "INDEPENDENT_QA_PASS",
}

_SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@+\-/]{0,191}$")


def _obj(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be an object")
    return value


def _exact_keys(document: Mapping[str, Any], keys: set[str], label: str) -> None:
    actual = set(document)
    if actual != keys:
        missing = sorted(keys - actual)
        extra = sorted(actual - keys)
        raise ValueError(f"{label} keys mismatch; missing={missing}, extra={extra}")


def _text(document: Mapping[str, Any], key: str, label: str) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}.{key} must be a non-empty string")
    return value.strip()


def _identifier(document: Mapping[str, Any], key: str, label: str) -> str:
    value = _text(document, key, label)
    if _IDENTIFIER_RE.fullmatch(value) is None:
        raise ValueError(f"{label}.{key} must be an opaque bounded identifier")
    return value


def _boolean(document: Mapping[str, Any], key: str, label: str) -> bool:
    value = document.get(key)
    if not isinstance(value, bool):
        raise ValueError(f"{label}.{key} must be boolean")
    return value


def _integer(
    document: Mapping[str, Any], key: str, label: str, *, minimum: int = 0
) -> int:
    value = document.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        raise ValueError(f"{label}.{key} must be an integer >= {minimum}")
    return value


def _strings(
    document: Mapping[str, Any],
    key: str,
    label: str,
    *,
    allow_empty: bool = False,
    unique: bool = True,
) -> list[str]:
    value = document.get(key)
    if not isinstance(value, list) or (not allow_empty and not value):
        requirement = "an array" if allow_empty else "a non-empty array"
        raise ValueError(f"{label}.{key} must be {requirement}")
    result: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(f"{label}.{key}[{index}] must be a non-empty string")
        result.append(item.strip())
    if unique and len(result) != len(set(result)):
        raise ValueError(f"{label}.{key} must contain unique values")
    return result


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and _SHA256_RE.fullmatch(value) is not None


def _require_sha256(value: object, label: str) -> str:
    if not _is_sha256(value):
        raise ValueError(f"{label} must be sha256:<64hex>")
    return str(value)


def _require_git_sha(value: object, label: str) -> str:
    if not isinstance(value, str) or _GIT_SHA_RE.fullmatch(value) is None:
        raise ValueError(f"{label} must be a 40-character lowercase Git SHA")
    return value


def _verify_fingerprint(
    document: Mapping[str, Any], field: str, label: str
) -> dict[str, Any]:
    copied = deepcopy(dict(document))
    claimed = copied.pop(field, None)
    _require_sha256(claimed, f"{label}.{field}")
    computed = sha256_json(copied)
    if claimed != computed:
        raise ValueError(f"{label}.{field} does not match canonical content")
    copied[field] = claimed
    return copied


def validate_target_matrix(document: object) -> dict[str, Any]:
    label = "target-matrix"
    doc = _obj(document, label)
    _exact_keys(
        doc,
        {
            "schema_version",
            "matrix_id",
            "classes",
            "targets",
            "default_comparable_classes",
            "sandbox_equivalence_gate",
            "limitations",
            "matrix_fingerprint",
        },
        label,
    )
    if _text(doc, "schema_version", label) != MATRIX_SCHEMA_VERSION:
        raise ValueError("unsupported target matrix schema")
    _identifier(doc, "matrix_id", label)
    default_classes = _strings(doc, "default_comparable_classes", label)
    if tuple(default_classes) != DEFAULT_COMPARABLE_CLASSES:
        raise ValueError("default comparable classes must remain model-only")

    classes_raw = doc.get("classes")
    if not isinstance(classes_raw, list) or len(classes_raw) != 4:
        raise ValueError("target-matrix.classes must contain exactly four classes")
    classes: dict[str, Mapping[str, Any]] = {}
    for index, raw in enumerate(classes_raw):
        entry_label = f"{label}.classes[{index}]"
        entry = _obj(raw, entry_label)
        _exact_keys(
            entry,
            {"class_id", "definition", "current_status", "model_failure_eligibility"},
            entry_label,
        )
        class_id = _text(entry, "class_id", entry_label)
        if class_id not in TARGET_CLASSES or class_id in classes:
            raise ValueError("target classes must be exact and unique")
        _text(entry, "definition", entry_label)
        classes[class_id] = entry
    if tuple(entry["class_id"] for entry in classes_raw) != TARGET_CLASSES:
        raise ValueError("target classes must use the frozen order")
    expected_class_states = {
        "MODEL_DIRECT": ("DEFAULT_COMPARABLE", "CURRENT_MODEL_FAILURE_ELIGIBLE"),
        "MODEL_CONTEXT_GROUNDED": (
            "DEFAULT_COMPARABLE",
            "CURRENT_MODEL_FAILURE_ELIGIBLE",
        ),
        "AGENT_STANDARDIZED": (
            "WAIT_SANDBOX_EQUIVALENCE",
            "CONDITIONAL_AFTER_EQUIVALENCE",
        ),
        "SYSTEM_EVAL_ONLY": ("SYSTEM_ONLY", "NEVER_MODEL_FAILURE"),
    }
    for class_id, (status, eligibility) in expected_class_states.items():
        if classes[class_id]["current_status"] != status:
            raise ValueError(f"{class_id} has an invalid current status")
        if classes[class_id]["model_failure_eligibility"] != eligibility:
            raise ValueError(f"{class_id} has invalid model-failure eligibility")

    targets_raw = doc.get("targets")
    if not isinstance(targets_raw, list) or len(targets_raw) != 16:
        raise ValueError("target matrix must contain exactly 16 targets")
    seen_ids: set[str] = set()
    observed_by_class: dict[str, list[str]] = defaultdict(list)
    for index, raw in enumerate(targets_raw):
        entry_label = f"{label}.targets[{index}]"
        target = _obj(raw, entry_label)
        _exact_keys(
            target,
            {
                "target_id",
                "target_class",
                "capability",
                "unit_under_test",
                "observable",
                "primary_metric_id",
                "model_failure_eligibility",
                "current_comparability",
                "requires_sandbox_equivalence",
                "scope_limit",
            },
            entry_label,
        )
        target_id = _identifier(target, "target_id", entry_label)
        target_class = _text(target, "target_class", entry_label)
        if target_id in seen_ids or target_class not in TARGET_CLASSES:
            raise ValueError("target IDs must be unique and classes supported")
        seen_ids.add(target_id)
        observed_by_class[target_class].append(target_id)
        for key in ("capability", "unit_under_test", "observable", "scope_limit"):
            _text(target, key, entry_label)
        metric_id = _text(target, "primary_metric_id", entry_label)
        eligibility = _text(target, "model_failure_eligibility", entry_label)
        comparability = _text(target, "current_comparability", entry_label)
        requires_sandbox = _boolean(
            target, "requires_sandbox_equivalence", entry_label
        )
        if target_class in DEFAULT_COMPARABLE_CLASSES:
            expected = (
                "model_failure_rate",
                "CURRENT_MODEL_FAILURE_ELIGIBLE",
                "DEFAULT_COMPARABLE",
                False,
            )
        elif target_class == "AGENT_STANDARDIZED":
            expected = (
                "sandboxed_agent_failure_rate",
                "CONDITIONAL_AFTER_EQUIVALENCE",
                "WAIT_SANDBOX_EQUIVALENCE",
                True,
            )
        else:
            expected = (
                "system_invariant_failure_rate",
                "NEVER_MODEL_FAILURE",
                "SYSTEM_ONLY",
                False,
            )
        if (metric_id, eligibility, comparability, requires_sandbox) != expected:
            raise ValueError(f"{target_id} violates its class applicability contract")

    for target_class, expected_ids in TARGET_IDS_BY_CLASS.items():
        if tuple(observed_by_class[target_class]) != expected_ids:
            raise ValueError(f"{target_class} target inventory/order drifted")

    gate = _obj(doc.get("sandbox_equivalence_gate"), f"{label}.sandbox_equivalence_gate")
    _exact_keys(
        gate,
        {"status", "required_evidence", "activation_effect"},
        f"{label}.sandbox_equivalence_gate",
    )
    if gate.get("status") != "NOT_ESTABLISHED":
        raise ValueError("BM0 cannot pre-declare sandbox equivalence")
    required_evidence = _strings(
        gate, "required_evidence", f"{label}.sandbox_equivalence_gate"
    )
    if set(required_evidence) != {
        "sandbox image fingerprint",
        "tool surface fingerprint",
        "budget and retry equivalence",
        "network and credential policy equivalence",
        "independent equivalence receipt",
    }:
        raise ValueError("sandbox equivalence evidence set drifted")
    if gate.get("activation_effect") != (
        "AGENT_STANDARDIZED may be added by a later frozen manifest; "
        "SYSTEM_EVAL_ONLY never enters a model-failure denominator"
    ):
        raise ValueError("sandbox equivalence activation effect drifted")
    _strings(doc, "limitations", label)
    assert_public_safe(doc)
    return _verify_fingerprint(doc, "matrix_fingerprint", label)


def validate_bm0_metric_registry(document: object) -> dict[str, Any]:
    label = "bm0-metric-registry"
    doc = _obj(document, label)
    _exact_keys(
        doc,
        {"schema_version", "registry_id", "metrics", "registry_fingerprint"},
        label,
    )
    if _text(doc, "schema_version", label) != METRIC_REGISTRY_SCHEMA_VERSION:
        raise ValueError("unsupported BM0 metric registry schema")
    _identifier(doc, "registry_id", label)
    metrics_raw = doc.get("metrics")
    if not isinstance(metrics_raw, list) or len(metrics_raw) != len(EXPECTED_METRIC_IDS):
        raise ValueError("BM0 metric registry must contain the frozen metric set")
    metrics: dict[str, Mapping[str, Any]] = {}
    for index, raw in enumerate(metrics_raw):
        entry_label = f"{label}.metrics[{index}]"
        metric = _obj(raw, entry_label)
        _exact_keys(
            metric,
            {
                "metric_id",
                "version",
                "kind",
                "description",
                "applicability_classes",
                "numerator_statuses",
                "denominator_statuses",
                "excluded_terminal_statuses",
                "corpus_pool",
                "activation_gate",
                "estimate_method_id",
                "uncertainty_method_id",
                "zero_denominator_semantics",
                "directionality",
                "claim_scope",
            },
            entry_label,
        )
        metric_id = _identifier(metric, "metric_id", entry_label)
        if metric_id in metrics:
            raise ValueError("duplicate BM0 metric ID")
        metrics[metric_id] = metric
        _text(metric, "version", entry_label)
        _text(metric, "description", entry_label)
        applicability = _strings(metric, "applicability_classes", entry_label)
        if not set(applicability).issubset(TARGET_CLASSES):
            raise ValueError(f"{metric_id} has an unsupported applicability class")
        numerator = _strings(
            metric, "numerator_statuses", entry_label, allow_empty=True
        )
        denominator = _strings(metric, "denominator_statuses", entry_label)
        excluded = _strings(
            metric, "excluded_terminal_statuses", entry_label, allow_empty=True
        )
        if not set(numerator + denominator + excluded).issubset(TERMINAL_STATUSES):
            raise ValueError(f"{metric_id} uses an unsupported terminal status")
        if set(numerator) - set(denominator):
            raise ValueError(f"{metric_id} numerator must be inside denominator")
        if set(denominator) & set(excluded):
            raise ValueError(f"{metric_id} denominator and exclusions overlap")
        for key in (
            "kind",
            "corpus_pool",
            "activation_gate",
            "estimate_method_id",
            "uncertainty_method_id",
            "zero_denominator_semantics",
            "directionality",
            "claim_scope",
        ):
            _text(metric, key, entry_label)

    if set(metrics) != EXPECTED_METRIC_IDS:
        raise ValueError("BM0 metric inventory drifted")
    failure_rules = {
        "model_failure_rate": (
            set(DEFAULT_COMPARABLE_CLASSES),
            PRIMARY_ESTIMATE_POOL_ID,
            "NONE",
            "MODEL_QUALITY",
            "MODEL_ONLY_DESCRIPTIVE",
            "BM0-SAP-04-MODEL-FAILURE-DENOMINATOR-V1",
            "NOT_EVALUABLE/ZERO_MODEL_SCORABLE_DENOMINATOR",
        ),
        "sandboxed_agent_failure_rate": (
            {"AGENT_STANDARDIZED"},
            PRIMARY_ESTIMATE_POOL_ID,
            "SANDBOX_EQUIVALENCE_ESTABLISHED",
            "MODEL_QUALITY_CONDITIONAL",
            "MODEL_ONLY_AFTER_EQUIVALENCE",
            "BM0-SAP-04-MODEL-FAILURE-DENOMINATOR-V1",
            "NOT_EVALUABLE/ZERO_MODEL_SCORABLE_DENOMINATOR",
        ),
        "system_invariant_failure_rate": (
            {"SYSTEM_EVAL_ONLY"},
            PRIMARY_ESTIMATE_POOL_ID,
            "SYSTEM_ONLY",
            "SYSTEM_QUALITY",
            "SYSTEM_ONLY_NOT_MODEL_QUALITY",
            "BM0-SAP-08-SYSTEM-INVARIANT-FAILURE-RATE-V1",
            "NOT_EVALUABLE/ZERO_SYSTEM_SCORABLE_DENOMINATOR",
        ),
    }
    for metric_id, (
        classes,
        corpus_pool,
        gate,
        kind,
        claim_scope,
        estimate_method,
        zero_denominator_semantics,
    ) in failure_rules.items():
        metric = metrics[metric_id]
        if set(metric["applicability_classes"]) != classes:
            raise ValueError(f"{metric_id} applicability drifted")
        if metric["numerator_statuses"] != ["FAIL"]:
            raise ValueError(f"{metric_id} must count only FAIL in its numerator")
        if metric["denominator_statuses"] != ["PASS", "FAIL"]:
            raise ValueError(f"{metric_id} denominator must be PASS + FAIL")
        if set(metric["excluded_terminal_statuses"]) != set(
            NON_MODEL_SCORABLE_TERMINALS
        ):
            raise ValueError(f"{metric_id} non-model terminals must be excluded")
        if (
            metric["corpus_pool"] != corpus_pool
            or metric["activation_gate"] != gate
            or metric["kind"] != kind
            or metric["claim_scope"] != claim_scope
            or metric["estimate_method_id"] != estimate_method
            or metric["uncertainty_method_id"]
            != "BM0-SAP-05-WILSON-INTERVAL-V1"
            or metric["zero_denominator_semantics"]
            != zero_denominator_semantics
            or metric["version"] != "v1"
            or metric["directionality"] != "LOWER_IS_BETTER"
        ):
            raise ValueError(f"{metric_id} analysis contract drifted")

    diagnostic = metrics["non_scorable_attempt_rate"]
    if (
        set(diagnostic["applicability_classes"]) != set(TARGET_CLASSES)
        or set(diagnostic["numerator_statuses"])
        != set(NON_MODEL_SCORABLE_TERMINALS)
        or tuple(diagnostic["denominator_statuses"]) != TERMINAL_STATUSES
        or diagnostic["excluded_terminal_statuses"] != []
        or diagnostic["kind"] != "INFRASTRUCTURE_AND_EVIDENCE_DIAGNOSTIC"
        or diagnostic["version"] != "v1"
        or diagnostic["corpus_pool"] != "ALL_DECLARED_POOLS"
        or diagnostic["activation_gate"] != "NONE"
        or diagnostic["estimate_method_id"]
        != "BM0-SAP-03-TYPED-TERMINAL-PARTITION-V1"
        or diagnostic["uncertainty_method_id"]
        != "NONE_DIAGNOSTIC_COUNTING_ONLY"
        or diagnostic["zero_denominator_semantics"]
        != "NOT_EVALUABLE/ZERO_SCHEDULED_ATTEMPTS"
        or diagnostic["directionality"] != "DIAGNOSTIC_ONLY"
        or diagnostic["claim_scope"] != "DIAGNOSTIC_ONLY_NOT_MODEL_FAILURE"
    ):
        raise ValueError("non-scorable diagnostic contract drifted")
    assert_public_safe(doc)
    return _verify_fingerprint(doc, "registry_fingerprint", label)


def validate_corpus_policy(document: object) -> dict[str, Any]:
    label = "bm0-corpus-policy"
    doc = _obj(document, label)
    _exact_keys(
        doc,
        {
            "schema_version",
            "policy_id",
            "pools",
            "split_rules",
            "access_sequence",
            "hidden_holdout",
            "forbidden_reuse",
            "policy_fingerprint",
        },
        label,
    )
    if _text(doc, "schema_version", label) != CORPUS_POLICY_SCHEMA_VERSION:
        raise ValueError("unsupported BM0 corpus policy schema")
    _identifier(doc, "policy_id", label)
    pools_raw = doc.get("pools")
    if not isinstance(pools_raw, list) or len(pools_raw) != 4:
        raise ValueError("BM0 corpus policy must contain exactly four pools")
    pools: dict[str, Mapping[str, Any]] = {}
    for index, raw in enumerate(pools_raw):
        entry_label = f"{label}.pools[{index}]"
        pool = _obj(raw, entry_label)
        _exact_keys(
            pool,
            {
                "pool_id",
                "visibility",
                "purpose",
                "allowed_in_primary_estimate",
                "content_location",
                "selection_timing",
                "lineage_role",
            },
            entry_label,
        )
        pool_id = _text(pool, "pool_id", entry_label)
        if pool_id not in EXPECTED_POOL_IDS or pool_id in pools:
            raise ValueError("corpus pool IDs must be exact and unique")
        pools[pool_id] = pool
        for key in (
            "visibility",
            "purpose",
            "content_location",
            "selection_timing",
            "lineage_role",
        ):
            _text(pool, key, entry_label)
        _boolean(pool, "allowed_in_primary_estimate", entry_label)
    if tuple(pool["pool_id"] for pool in pools_raw) != (
        "PUBLIC_DEVELOPMENT",
        "PUBLIC_CONTROL",
        "MUTATION",
        "PRIVATE_HIDDEN_HOLDOUT",
    ):
        raise ValueError("corpus pool order drifted")
    hidden_pool = pools["PRIVATE_HIDDEN_HOLDOUT"]
    if (
        hidden_pool["visibility"] != "PRIVATE_EXTERNAL"
        or hidden_pool["content_location"] != "OUTSIDE_PUBLIC_REPOSITORY"
        or hidden_pool["selection_timing"] != "AFTER_FROZEN_MANIFEST"
        or hidden_pool["allowed_in_primary_estimate"] is not True
    ):
        raise ValueError("hidden holdout boundary is not fail closed")
    for pool_id in ("PUBLIC_DEVELOPMENT", "PUBLIC_CONTROL", "MUTATION"):
        if pools[pool_id]["allowed_in_primary_estimate"] is not False:
            raise ValueError(f"{pool_id} must not enter the primary hidden estimate")

    split = _obj(doc.get("split_rules"), f"{label}.split_rules")
    _exact_keys(
        split,
        {
            "lineage_disjoint",
            "case_identity_disjoint",
            "mutation_parent_disclosed",
            "tuning_on_hidden_forbidden",
            "promotion_requires_new_contract_version",
        },
        f"{label}.split_rules",
    )
    if not all(_boolean(split, key, f"{label}.split_rules") for key in split):
        raise ValueError("all corpus split rules must fail closed")
    access_sequence = _strings(doc, "access_sequence", label)
    if access_sequence != [
        "FREEZE_MANIFEST",
        "SEAL_AGGREGATE_COMMITMENT",
        "AUTHORIZE_EXECUTION",
        "OPEN_PRIVATE_HOLDOUT",
        "LOG_ACCESS",
    ]:
        raise ValueError("hidden corpus access sequence drifted")
    hidden = _obj(doc.get("hidden_holdout"), f"{label}.hidden_holdout")
    _exact_keys(
        hidden,
        {
            "exact_content_in_public_repository",
            "exact_case_ids_in_public_repository",
            "private_locator_in_public_repository",
            "per_case_commitments_in_public_repository",
            "aggregate_commitment_required_before_execution",
            "access_after_manifest_freeze",
            "access_log_required",
        },
        f"{label}.hidden_holdout",
    )
    for key in (
        "exact_content_in_public_repository",
        "exact_case_ids_in_public_repository",
        "private_locator_in_public_repository",
        "per_case_commitments_in_public_repository",
    ):
        if _boolean(hidden, key, f"{label}.hidden_holdout") is not False:
            raise ValueError(f"hidden holdout public field {key} must remain false")
    for key in (
        "aggregate_commitment_required_before_execution",
        "access_after_manifest_freeze",
        "access_log_required",
    ):
        if _boolean(hidden, key, f"{label}.hidden_holdout") is not True:
            raise ValueError(f"hidden holdout control {key} must remain true")
    forbidden_reuse = _strings(doc, "forbidden_reuse", label)
    if set(forbidden_reuse) != {
        "B2-BLIND-01/PR-30 corpus or output by assumption",
        "development examples as hidden evidence",
        "control cases as hidden model-quality evidence",
        "mutation children across train and holdout lineage",
    }:
        raise ValueError("forbidden corpus reuse set drifted")
    assert_public_safe(doc)
    return _verify_fingerprint(doc, "policy_fingerprint", label)


def validate_trial_identity(document: object) -> dict[str, Any]:
    label = "trial-identity"
    doc = _obj(document, label)
    _exact_keys(
        doc,
        {
            "schema_version",
            "study_id",
            "trial_id",
            "attempt_id",
            "parent_attempt_id",
            "provider_subject_id",
            "model_subject_id",
            "model_snapshot_id",
            "target_id",
            "target_class",
            "corpus_pool_id",
            "corpus_item_alias",
            "corpus_item_commitment",
            "mutation_parent_commitment",
            "prompt_template_version",
            "harness_version",
            "adapter_id",
            "adapter_version",
            "replicate_index",
            "random_seed",
            "environment_fingerprint",
        },
        label,
    )
    if _text(doc, "schema_version", label) != TRIAL_IDENTITY_SCHEMA_VERSION:
        raise ValueError("unsupported BM0 trial identity schema")
    for key in (
        "study_id",
        "trial_id",
        "attempt_id",
        "provider_subject_id",
        "model_subject_id",
        "model_snapshot_id",
        "target_id",
        "corpus_item_alias",
        "prompt_template_version",
        "harness_version",
        "adapter_id",
        "adapter_version",
    ):
        _identifier(doc, key, label)
    parent_attempt_id = doc.get("parent_attempt_id")
    if parent_attempt_id is not None:
        if not isinstance(parent_attempt_id, str) or _IDENTIFIER_RE.fullmatch(parent_attempt_id) is None:
            raise ValueError("parent_attempt_id must be null or an opaque identifier")
        if parent_attempt_id == doc["attempt_id"]:
            raise ValueError("an attempt cannot be its own parent")
    target_class = _text(doc, "target_class", label)
    if target_class not in TARGET_CLASSES:
        raise ValueError("trial identity target class is unsupported")
    if doc["target_id"] not in TARGET_IDS_BY_CLASS[target_class]:
        raise ValueError("trial target ID does not belong to its declared class")
    corpus_pool_id = _text(doc, "corpus_pool_id", label)
    if corpus_pool_id not in EXPECTED_POOL_IDS:
        raise ValueError("trial corpus pool is unsupported")
    mutation_parent_commitment = doc.get("mutation_parent_commitment")
    if corpus_pool_id == "MUTATION":
        _require_sha256(
            mutation_parent_commitment, "mutation_parent_commitment"
        )
    elif mutation_parent_commitment is not None:
        raise ValueError(
            "only mutation-pool attempts may bind a mutation parent"
        )
    subject_identity = (
        doc["provider_subject_id"],
        doc["model_subject_id"],
        doc["model_snapshot_id"],
    )
    if target_class == "SYSTEM_EVAL_ONLY":
        if subject_identity != (SYSTEM_SCOPE_ID, SYSTEM_SCOPE_ID, SYSTEM_SCOPE_ID):
            raise ValueError("system-only trials must use the non-model SYSTEM_SCOPE identity")
    elif SYSTEM_SCOPE_ID in subject_identity:
        raise ValueError("model and agent trials cannot use the SYSTEM_SCOPE identity")
    if str(doc["model_snapshot_id"]).lower() in {
        "latest",
        "default",
        "auto",
        "not_selected",
    }:
        raise ValueError("model snapshot identity must be immutable, not a moving alias")
    _require_sha256(doc.get("corpus_item_commitment"), "corpus_item_commitment")
    _require_sha256(doc.get("environment_fingerprint"), "environment_fingerprint")
    _integer(doc, "replicate_index", label)
    _integer(doc, "random_seed", label)
    assert_public_safe(doc)
    return dict(doc)


def validate_adjudication_plan(document: object) -> dict[str, Any]:
    label = "adjudication-plan"
    doc = _obj(document, label)
    _exact_keys(
        doc,
        {
            "plan_id",
            "mode",
            "metric_ids",
            "primary_adjudicators",
            "tiebreak_adjudicator",
            "rubric_version",
            "rubric_fingerprint",
            "plan_fingerprint",
        },
        label,
    )
    _identifier(doc, "plan_id", label)
    mode = _text(doc, "mode", label)
    if mode not in {"HUMAN_HUMAN", "HUMAN_JUDGE", "JUDGE_JUDGE"}:
        raise ValueError("adjudication plan mode is unsupported")
    metric_ids = _strings(doc, "metric_ids", label)
    if not set(metric_ids).issubset(EXPECTED_METRIC_IDS):
        raise ValueError("adjudication plan contains an unsupported metric")
    _identifier(doc, "rubric_version", label)
    _require_sha256(
        doc.get("rubric_fingerprint"), "adjudication-plan.rubric_fingerprint"
    )

    primaries_raw = doc.get("primary_adjudicators")
    if not isinstance(primaries_raw, list) or len(primaries_raw) != 2:
        raise ValueError("adjudication plan requires exactly two primaries")

    def checked_assignment(raw: object, assignment_label: str) -> dict[str, str]:
        assignment = _obj(raw, assignment_label)
        _exact_keys(
            assignment,
            {
                "adjudicator_type",
                "adjudicator_id",
                "configuration_fingerprint",
            },
            assignment_label,
        )
        adjudicator_type = _text(
            assignment, "adjudicator_type", assignment_label
        )
        if adjudicator_type not in {"HUMAN", "FIXED_JUDGE"}:
            raise ValueError("adjudicator assignment type is unsupported")
        adjudicator_id = _identifier(
            assignment, "adjudicator_id", assignment_label
        )
        configuration_fingerprint = _require_sha256(
            assignment.get("configuration_fingerprint"),
            f"{assignment_label}.configuration_fingerprint",
        )
        return {
            "adjudicator_type": adjudicator_type,
            "adjudicator_id": adjudicator_id,
            "configuration_fingerprint": configuration_fingerprint,
        }

    primaries = [
        checked_assignment(raw, f"{label}.primary_adjudicators[{index}]")
        for index, raw in enumerate(primaries_raw)
    ]
    tiebreak = checked_assignment(
        doc.get("tiebreak_adjudicator"), f"{label}.tiebreak_adjudicator"
    )
    all_ids = [entry["adjudicator_id"] for entry in primaries] + [
        tiebreak["adjudicator_id"]
    ]
    if len(all_ids) != len(set(all_ids)):
        raise ValueError("adjudication plan identities must be distinct")
    primary_types = sorted(entry["adjudicator_type"] for entry in primaries)
    expected_types = {
        "HUMAN_HUMAN": ["HUMAN", "HUMAN"],
        "HUMAN_JUDGE": ["FIXED_JUDGE", "HUMAN"],
        "JUDGE_JUDGE": ["FIXED_JUDGE", "FIXED_JUDGE"],
    }[mode]
    if primary_types != expected_types:
        raise ValueError("primary adjudicator composition does not match mode")
    assert_public_safe(doc)
    return _verify_fingerprint(doc, "plan_fingerprint", label)


def corpus_aggregate_commitment_v1(
    planned_attempts: Iterable[Mapping[str, Any]],
) -> str:
    """Commit the unique private-holdout item identities in a stable order."""

    attempts = [validate_trial_identity(attempt) for attempt in planned_attempts]
    alias_bindings: dict[tuple[str, str], str] = {}
    commitment_pools: dict[str, str] = {}
    mutation_parents: set[str] = set()
    for attempt in attempts:
        pool_id = attempt["corpus_pool_id"]
        alias = attempt["corpus_item_alias"]
        commitment = attempt["corpus_item_commitment"]
        alias_key = (pool_id, alias)
        if alias_key in alias_bindings and alias_bindings[alias_key] != commitment:
            raise ValueError("one corpus alias cannot bind multiple item commitments")
        alias_bindings[alias_key] = commitment
        if (
            commitment in commitment_pools
            and commitment_pools[commitment] != pool_id
        ):
            raise ValueError("one corpus item commitment cannot cross corpus pools")
        commitment_pools[commitment] = pool_id
        if attempt["mutation_parent_commitment"] is not None:
            mutation_parents.add(attempt["mutation_parent_commitment"])
    hidden_items = sorted(
        {
            (alias, commitment)
            for (pool_id, alias), commitment in alias_bindings.items()
            if pool_id == PRIMARY_ESTIMATE_POOL_ID
        }
    )
    hidden_commitments = {commitment for _, commitment in hidden_items}
    if mutation_parents & hidden_commitments:
        raise ValueError(
            "a mutation parent cannot belong to the private hidden holdout"
        )
    return sha256_json(
        {
            "commitment_scheme": "B2-BM0-CORPUS-AGGREGATE-V1",
            "corpus_pool_id": PRIMARY_ESTIMATE_POOL_ID,
            "item_count": len(hidden_items),
            "items": [
                {
                    "corpus_item_alias": alias,
                    "corpus_item_commitment": commitment,
                }
                for alias, commitment in hidden_items
            ],
        }
    )


def validate_benchmark_manifest(
    document: object,
    *,
    expected_artifact_fingerprints: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    label = "benchmark-manifest"
    doc = _obj(document, label)
    _exact_keys(
        doc,
        {
            "schema_version",
            "manifest_id",
            "contract_id",
            "contract_revision",
            "implementation_base_sha",
            "study_state",
            "provider_roster_status",
            "corpus_commitment_status",
            "corpus_aggregate_commitment",
            "adjudication_mode",
            "adjudication_plan",
            "frozen_before_hidden_access",
            "comparison_classes",
            "sandbox_equivalence",
            "artifact_fingerprints",
            "planned_attempts",
            "planned_attempt_count",
            "stop_rule",
            "manifest_fingerprint",
        },
        label,
    )
    if _text(doc, "schema_version", label) != MANIFEST_SCHEMA_VERSION:
        raise ValueError("unsupported BM0 benchmark manifest schema")
    _identifier(doc, "manifest_id", label)
    if doc.get("contract_id") != WORK_ORDER_ID or doc.get("contract_revision") != WORK_ORDER_REVISION:
        raise ValueError("manifest work-order binding drifted")
    if _require_git_sha(doc.get("implementation_base_sha"), "implementation_base_sha") != IMPLEMENTATION_BASE_SHA:
        raise ValueError("manifest implementation baseline drifted")
    state = _text(doc, "study_state", label)
    if state not in {"DESIGN_ONLY", "FROZEN"}:
        raise ValueError("manifest study state is unsupported")
    roster = _text(doc, "provider_roster_status", label)
    corpus_status = _text(doc, "corpus_commitment_status", label)
    corpus_aggregate_commitment = doc.get("corpus_aggregate_commitment")
    if corpus_aggregate_commitment is not None:
        _require_sha256(
            corpus_aggregate_commitment,
            f"{label}.corpus_aggregate_commitment",
        )
    adjudication_mode = _text(doc, "adjudication_mode", label)
    plan_raw = doc.get("adjudication_plan")
    adjudication_plan = (
        None if plan_raw is None else validate_adjudication_plan(plan_raw)
    )
    if _boolean(doc, "frozen_before_hidden_access", label) is not True:
        raise ValueError("manifest must freeze before hidden-corpus access")

    sandbox = _obj(doc.get("sandbox_equivalence"), f"{label}.sandbox_equivalence")
    _exact_keys(sandbox, {"status", "evidence_refs"}, f"{label}.sandbox_equivalence")
    sandbox_status = _text(sandbox, "status", f"{label}.sandbox_equivalence")
    evidence_refs = sandbox.get("evidence_refs")
    if not isinstance(evidence_refs, list):
        raise ValueError("sandbox equivalence evidence_refs must be an array")
    for index, raw in enumerate(evidence_refs):
        ref = _obj(raw, f"sandbox.evidence_refs[{index}]")
        _exact_keys(
            ref,
            {"evidence_type", "evidence_id", "evidence_fingerprint"},
            f"sandbox.evidence_refs[{index}]",
        )
        evidence_type = _text(
            ref, "evidence_type", f"sandbox.evidence_refs[{index}]"
        )
        if evidence_type not in SANDBOX_EQUIVALENCE_EVIDENCE_TYPES:
            raise ValueError("sandbox equivalence evidence type is unsupported")
        _identifier(ref, "evidence_id", f"sandbox.evidence_refs[{index}]")
        _require_sha256(ref.get("evidence_fingerprint"), "sandbox evidence fingerprint")
    evidence_types = [ref["evidence_type"] for ref in evidence_refs]
    evidence_ids = [ref["evidence_id"] for ref in evidence_refs]
    if len(evidence_ids) != len(set(evidence_ids)):
        raise ValueError("sandbox equivalence evidence IDs must be unique")
    comparison_classes = _strings(doc, "comparison_classes", label)
    if sandbox_status == "NOT_ESTABLISHED":
        if evidence_refs or tuple(comparison_classes) != DEFAULT_COMPARABLE_CLASSES:
            raise ValueError("unproven sandbox equivalence cannot expand comparability")
    elif sandbox_status == "ESTABLISHED":
        if (
            tuple(evidence_types) != SANDBOX_EQUIVALENCE_EVIDENCE_TYPES
            or tuple(comparison_classes)
            != DEFAULT_COMPARABLE_CLASSES + ("AGENT_STANDARDIZED",)
        ):
            raise ValueError("established equivalence requires evidence and exact expansion")
    else:
        raise ValueError("unsupported sandbox equivalence status")
    if "SYSTEM_EVAL_ONLY" in comparison_classes:
        raise ValueError("system-only targets can never enter model comparison")

    artifact_fingerprints = _obj(
        doc.get("artifact_fingerprints"), f"{label}.artifact_fingerprints"
    )
    _exact_keys(
        artifact_fingerprints,
        {
            "target_matrix",
            "metric_registry",
            "corpus_policy",
            "analysis_plan",
            "analysis_implementation",
        },
        f"{label}.artifact_fingerprints",
    )
    for key, value in artifact_fingerprints.items():
        _require_sha256(value, f"artifact_fingerprints.{key}")
    if expected_artifact_fingerprints is not None:
        if dict(artifact_fingerprints) != dict(expected_artifact_fingerprints):
            raise ValueError("manifest artifact fingerprint binding drifted")

    attempts_raw = doc.get("planned_attempts")
    if not isinstance(attempts_raw, list):
        raise ValueError("planned_attempts must be an array")
    attempts = [validate_trial_identity(attempt) for attempt in attempts_raw]
    planned_count = _integer(doc, "planned_attempt_count", label)
    if planned_count != len(attempts):
        raise ValueError("planned_attempt_count does not match planned_attempts")
    attempt_ids = [attempt["attempt_id"] for attempt in attempts]
    if len(attempt_ids) != len(set(attempt_ids)):
        raise ValueError("planned attempt IDs must be unique")
    if len({attempt["study_id"] for attempt in attempts}) > 1:
        raise ValueError("a frozen manifest cannot mix study identities")
    expected_corpus_aggregate = corpus_aggregate_commitment_v1(attempts)
    model_subject_bindings: dict[str, tuple[str, str]] = {}
    for attempt in attempts:
        if attempt["target_class"] == "SYSTEM_EVAL_ONLY":
            continue
        subject_id = attempt["model_subject_id"]
        binding = (
            attempt["provider_subject_id"],
            attempt["model_snapshot_id"],
        )
        if subject_id in model_subject_bindings and model_subject_bindings[subject_id] != binding:
            raise ValueError(
                "one model subject cannot aggregate multiple providers or snapshots"
            )
        model_subject_bindings[subject_id] = binding
    attempt_index = {
        attempt["attempt_id"]: index for index, attempt in enumerate(attempts)
    }
    attempts_by_id = {
        attempt["attempt_id"]: attempt for attempt in attempts
    }
    children_by_parent: Counter[str] = Counter()
    retry_identity_fields = (
        "study_id",
        "trial_id",
        "provider_subject_id",
        "model_subject_id",
        "model_snapshot_id",
        "target_id",
        "target_class",
        "corpus_pool_id",
        "corpus_item_alias",
        "corpus_item_commitment",
        "mutation_parent_commitment",
        "prompt_template_version",
        "harness_version",
        "adapter_id",
        "adapter_version",
        "replicate_index",
        "random_seed",
        "environment_fingerprint",
    )
    for attempt in attempts:
        parent_id = attempt["parent_attempt_id"]
        if parent_id is None:
            continue
        parent = attempts_by_id.get(parent_id)
        if parent is None:
            raise ValueError("retry parent must be present in the frozen manifest")
        if attempt_index[parent_id] >= attempt_index[attempt["attempt_id"]]:
            raise ValueError("retry parent must precede its child in manifest order")
        if any(attempt[field] != parent[field] for field in retry_identity_fields):
            raise ValueError("retry attempt identity drifted from its parent")
        children_by_parent[parent_id] += 1
    if any(count > 1 for count in children_by_parent.values()):
        raise ValueError("retry chains cannot branch")
    for trial_id in {attempt["trial_id"] for attempt in attempts}:
        trial_attempts = [
            attempt for attempt in attempts if attempt["trial_id"] == trial_id
        ]
        roots = [
            attempt for attempt in trial_attempts if attempt["parent_attempt_id"] is None
        ]
        if len(roots) != 1:
            raise ValueError("each trial must have exactly one root attempt")
    if any(
        attempt["target_class"] not in comparison_classes
        and attempt["target_class"] != "SYSTEM_EVAL_ONLY"
        for attempt in attempts
    ):
        raise ValueError(
            "planned model/agent attempts must stay inside comparison classes"
        )

    stop_rule = _obj(doc.get("stop_rule"), f"{label}.stop_rule")
    _exact_keys(
        stop_rule,
        {
            "method_id",
            "outcome_blind",
            "required_event_fields",
            "forbidden_event_fields",
            "planned_attempt_count",
        },
        f"{label}.stop_rule",
    )
    if (
        stop_rule.get("method_id") != SAP_METHOD_IDS[0]
        or _boolean(stop_rule, "outcome_blind", f"{label}.stop_rule") is not True
        or _strings(stop_rule, "required_event_fields", f"{label}.stop_rule")
        != ["attempt_id", "recorded"]
        or set(_strings(stop_rule, "forbidden_event_fields", f"{label}.stop_rule"))
        != {
            "terminal_status",
            "model_failure_value",
            "score",
            "output",
            "adjudication_decision",
        }
        or _integer(stop_rule, "planned_attempt_count", f"{label}.stop_rule")
        != planned_count
    ):
        raise ValueError("manifest stop rule is not the frozen no-peeking method")

    if state == "DESIGN_ONLY":
        if (
            roster != "NOT_SELECTED"
            or corpus_status != "NOT_COMMITTED"
            or corpus_aggregate_commitment is not None
            or adjudication_mode != "NOT_SELECTED"
            or adjudication_plan is not None
            or attempts
            or planned_count != 0
            or sandbox_status != "NOT_ESTABLISHED"
        ):
            raise ValueError("design-only template cannot select roster/corpus/adjudication")
    else:
        if (
            roster != "SELECTED"
            or corpus_status != "SEALED"
            or corpus_aggregate_commitment is None
            or corpus_aggregate_commitment != expected_corpus_aggregate
            or adjudication_mode
            not in {"HUMAN_HUMAN", "HUMAN_JUDGE", "JUDGE_JUDGE"}
            or adjudication_plan is None
            or adjudication_plan["mode"] != adjudication_mode
            or not attempts
        ):
            raise ValueError("frozen execution manifest is incomplete")
    assert_public_safe(doc)
    return _verify_fingerprint(doc, "manifest_fingerprint", label)


def fixed_attempt_stop_v1(
    manifest: object,
    collection_events: Iterable[Mapping[str, Any]],
    *,
    expected_artifact_fingerprints: Mapping[str, str],
) -> dict[str, Any]:
    """Apply the predeclared stop rule using identity/presence fields only.

    Outcome-bearing fields are rejected rather than ignored, which makes it
    impossible for a caller to smuggle metric values into the stopping view.
    """

    checked = validate_benchmark_manifest(
        manifest,
        expected_artifact_fingerprints=expected_artifact_fingerprints,
    )
    if checked["study_state"] != "FROZEN":
        raise ValueError("the stop rule requires a FROZEN manifest")
    planned_ids = {attempt["attempt_id"] for attempt in checked["planned_attempts"]}
    seen: dict[str, bool] = {}
    for index, raw in enumerate(collection_events):
        event = _obj(raw, f"collection_events[{index}]")
        _exact_keys(event, {"attempt_id", "recorded"}, f"collection_events[{index}]")
        attempt_id = _identifier(event, "attempt_id", f"collection_events[{index}]")
        recorded = _boolean(event, "recorded", f"collection_events[{index}]")
        if attempt_id not in planned_ids:
            raise ValueError("collection event references an unplanned attempt")
        if attempt_id in seen:
            raise ValueError("collection event attempt IDs must be unique")
        seen[attempt_id] = recorded
    recorded_ids = {attempt_id for attempt_id, recorded in seen.items() if recorded}
    missing = sorted(planned_ids - recorded_ids)
    return {
        "method_id": SAP_METHOD_IDS[0],
        "decision": "STOP" if not missing else "CONTINUE",
        "planned_attempt_count": len(planned_ids),
        "recorded_attempt_count": len(recorded_ids),
        "missing_attempt_ids": missing,
        "outcome_fields_observed": [],
    }


def validate_observation(document: object) -> dict[str, Any]:
    label = "bm0-observation"
    doc = _obj(document, label)
    _exact_keys(
        doc,
        {
            "schema_version",
            "attempt_id",
            "trial_id",
            "model_subject_id",
            "target_id",
            "target_class",
            "corpus_item_alias",
            "replicate_index",
            "terminal_status",
            "model_failure_value",
            "system_invariant_failure_value",
            "evidence_complete",
            "hard_invariant_pass",
            "adjudication_status",
            "observation_fingerprint",
        },
        label,
    )
    if _text(doc, "schema_version", label) != OBSERVATION_SCHEMA_VERSION:
        raise ValueError("unsupported BM0 observation schema")
    for key in (
        "attempt_id",
        "trial_id",
        "model_subject_id",
        "target_id",
        "corpus_item_alias",
    ):
        _identifier(doc, key, label)
    target_class = _text(doc, "target_class", label)
    if target_class not in TARGET_CLASSES or doc["target_id"] not in TARGET_IDS_BY_CLASS[target_class]:
        raise ValueError("observation target identity is inconsistent")
    if target_class == "SYSTEM_EVAL_ONLY":
        if doc["model_subject_id"] != SYSTEM_SCOPE_ID:
            raise ValueError("system-only observations cannot identify a model subject")
    elif doc["model_subject_id"] == SYSTEM_SCOPE_ID:
        raise ValueError("model and agent observations cannot use SYSTEM_SCOPE")
    _integer(doc, "replicate_index", label)
    terminal = _text(doc, "terminal_status", label)
    if terminal not in TERMINAL_STATUSES:
        raise ValueError("unsupported BM0 terminal status")
    evidence_complete = _boolean(doc, "evidence_complete", label)
    hard_state = doc.get("hard_invariant_pass")
    if hard_state is not None and not isinstance(hard_state, bool):
        raise ValueError("hard_invariant_pass must be boolean or null")
    value = doc.get("model_failure_value")
    if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value not in {0, 1}):
        raise ValueError("model_failure_value must be 0, 1, or null")
    system_value = doc.get("system_invariant_failure_value")
    if system_value is not None and (
        not isinstance(system_value, int)
        or isinstance(system_value, bool)
        or system_value not in {0, 1}
    ):
        raise ValueError("system_invariant_failure_value must be 0, 1, or null")
    adjudication = _text(doc, "adjudication_status", label)
    if adjudication not in {"NOT_REQUIRED", "RESOLVED", "UNRESOLVED", "ERROR"}:
        raise ValueError("unsupported adjudication status")
    expected_model_value = None if target_class == "SYSTEM_EVAL_ONLY" else (
        0 if terminal == "PASS" else 1 if terminal == "FAIL" else None
    )
    expected_system_value = (
        0 if terminal == "PASS" else 1 if terminal == "FAIL" else None
    ) if target_class == "SYSTEM_EVAL_ONLY" else None
    if value != expected_model_value or system_value != expected_system_value:
        raise ValueError("failure value does not match terminal and attribution class")
    if terminal == "PASS" and hard_state is not True:
        raise ValueError("PASS requires hard invariant PASS")
    if terminal == "FAIL" and hard_state is not False:
        raise ValueError("FAIL requires hard invariant FAIL")
    if terminal not in MODEL_SCORABLE_TERMINALS and hard_state is not None:
        raise ValueError("non-scorable terminals cannot carry a hard verdict")
    if terminal == "UNKNOWN" and evidence_complete:
        raise ValueError("UNKNOWN must retain incomplete evidence state")
    if terminal in MODEL_SCORABLE_TERMINALS and (
        not evidence_complete or adjudication not in {"NOT_REQUIRED", "RESOLVED"}
    ):
        raise ValueError("model-scorable terminals require complete/resolved evidence")
    if terminal == "ERROR" and adjudication == "RESOLVED":
        raise ValueError("ERROR cannot claim resolved adjudication")
    assert_public_safe(doc)
    return _verify_fingerprint(doc, "observation_fingerprint", label)


def validate_observation_grid_v1(
    manifest: object,
    observations: Iterable[Mapping[str, Any]],
    *,
    expected_artifact_fingerprints: Mapping[str, str],
) -> dict[str, Any]:
    checked_manifest = validate_benchmark_manifest(
        manifest,
        expected_artifact_fingerprints=expected_artifact_fingerprints,
    )
    if checked_manifest["study_state"] != "FROZEN":
        raise ValueError("observation grid requires a FROZEN manifest")
    planned = {
        attempt["attempt_id"]: attempt
        for attempt in checked_manifest["planned_attempts"]
    }
    observed: dict[str, dict[str, Any]] = {}
    for raw in observations:
        row = validate_observation(raw)
        attempt_id = row["attempt_id"]
        if attempt_id not in planned:
            raise ValueError("observation references an unplanned attempt")
        if attempt_id in observed:
            raise ValueError("duplicate observation attempt ID")
        identity = planned[attempt_id]
        for key in (
            "attempt_id",
            "trial_id",
            "model_subject_id",
            "target_id",
            "target_class",
            "corpus_item_alias",
            "replicate_index",
        ):
            if row[key] != identity[key]:
                raise ValueError(f"observation identity mismatch for {key}")
        observed[attempt_id] = row
    missing = sorted(set(planned) - set(observed))
    return {
        "method_id": SAP_METHOD_IDS[1],
        "planned": planned,
        "observed": observed,
        "missing_attempt_ids": missing,
        "complete": not missing,
    }


def typed_terminal_partition_v1(
    observations: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    rows = [validate_observation(row) for row in observations]
    counts = Counter(row["terminal_status"] for row in rows)
    non_scorable_count = sum(
        counts.get(status, 0) for status in NON_MODEL_SCORABLE_TERMINALS
    )
    return {
        "method_id": SAP_METHOD_IDS[2],
        "terminal_status": "PASS" if rows else "NOT_EVALUABLE",
        "reason": None if rows else "ZERO_SCHEDULED_ATTEMPTS",
        "total_attempts": len(rows),
        "terminal_counts": {status: counts.get(status, 0) for status in TERMINAL_STATUSES},
        "scorable_terminal_count": sum(
            counts.get(status, 0) for status in MODEL_SCORABLE_TERMINALS
        ),
        "non_scorable_terminal_count": non_scorable_count,
        "non_scorable_attempt_rate": (
            round(non_scorable_count / len(rows), 12) if rows else None
        ),
    }


def wilson_interval_v1(failures: int, denominator: int) -> dict[str, Any]:
    if (
        not isinstance(failures, int)
        or isinstance(failures, bool)
        or not isinstance(denominator, int)
        or isinstance(denominator, bool)
        or failures < 0
        or denominator < 0
        or failures > denominator
    ):
        raise ValueError("Wilson inputs must satisfy 0 <= failures <= denominator")
    if denominator == 0:
        return {
            "method_id": SAP_METHOD_IDS[4],
            "terminal_status": "NOT_EVALUABLE",
            "reason": "ZERO_DENOMINATOR",
            "confidence_level": 0.95,
            "lower": None,
            "upper": None,
        }
    z = 1.959963984540054
    p = failures / denominator
    z2 = z * z
    center = (p + z2 / (2 * denominator)) / (1 + z2 / denominator)
    half = z * math.sqrt(
        (p * (1 - p) + z2 / (4 * denominator)) / denominator
    ) / (1 + z2 / denominator)
    return {
        "method_id": SAP_METHOD_IDS[4],
        "terminal_status": "PASS",
        "reason": None,
        "confidence_level": 0.95,
        "lower": round(max(0.0, center - half), 12),
        "upper": round(min(1.0, center + half), 12),
    }


def model_failure_denominator_v1(
    manifest: object,
    observations: Iterable[Mapping[str, Any]],
    *,
    expected_artifact_fingerprints: Mapping[str, str],
) -> dict[str, Any]:
    rows = list(observations)
    grid = validate_observation_grid_v1(
        manifest,
        rows,
        expected_artifact_fingerprints=expected_artifact_fingerprints,
    )
    checked_manifest = validate_benchmark_manifest(
        manifest,
        expected_artifact_fingerprints=expected_artifact_fingerprints,
    )
    comparison_classes = set(checked_manifest["comparison_classes"])
    comparable_rows = [
        row
        for attempt_id, row in grid["observed"].items()
        if row["target_class"] in comparison_classes
        and grid["planned"][attempt_id]["corpus_pool_id"]
        == PRIMARY_ESTIMATE_POOL_ID
    ]
    missing_comparable = sorted(
        attempt_id
        for attempt_id in grid["missing_attempt_ids"]
        if grid["planned"][attempt_id]["target_class"] in comparison_classes
        and grid["planned"][attempt_id]["corpus_pool_id"]
        == PRIMARY_ESTIMATE_POOL_ID
    )
    by_model: dict[str, dict[str, Any]] = {}
    for model_id in sorted({row["model_subject_id"] for row in comparable_rows}):
        model_rows = [row for row in comparable_rows if row["model_subject_id"] == model_id]
        counts = Counter(row["terminal_status"] for row in model_rows)
        numerator = counts.get("FAIL", 0)
        denominator = counts.get("PASS", 0) + numerator
        interval = wilson_interval_v1(numerator, denominator)
        by_model[model_id] = {
            "terminal_status": "PASS" if denominator else "NOT_EVALUABLE",
            "reason": None if denominator else "ZERO_MODEL_SCORABLE_DENOMINATOR",
            "failure_count": numerator,
            "model_scorable_denominator": denominator,
            "failure_rate": round(numerator / denominator, 12) if denominator else None,
            "excluded_terminal_counts": {
                status: counts.get(status, 0)
                for status in NON_MODEL_SCORABLE_TERMINALS
            },
            "wilson_95": interval,
        }
    if missing_comparable:
        study_terminal = "NOT_EVALUABLE"
        reason = "MISSING_PLANNED_OBSERVATIONS"
    elif not by_model or any(
        result["terminal_status"] != "PASS" for result in by_model.values()
    ):
        study_terminal = "NOT_EVALUABLE"
        reason = "ONE_OR_MORE_ZERO_MODEL_SCORABLE_DENOMINATORS"
    else:
        study_terminal = "PASS"
        reason = None
    return {
        "method_id": SAP_METHOD_IDS[3],
        "terminal_status": study_terminal,
        "reason": reason,
        "missing_attempt_ids": missing_comparable,
        "comparison_classes": list(checked_manifest["comparison_classes"]),
        "corpus_pool": PRIMARY_ESTIMATE_POOL_ID,
        "by_model": by_model,
        "ranking_emitted": False,
        "claim_scope": "DESCRIPTIVE_CONTRACT_ONLY",
    }


def system_invariant_failure_rate_v1(
    manifest: object,
    observations: Iterable[Mapping[str, Any]],
    *,
    expected_artifact_fingerprints: Mapping[str, str],
) -> dict[str, Any]:
    """Compute the system-only invariant rate without model attribution."""

    rows = list(observations)
    grid = validate_observation_grid_v1(
        manifest,
        rows,
        expected_artifact_fingerprints=expected_artifact_fingerprints,
    )
    system_attempt_ids = {
        attempt_id
        for attempt_id, attempt in grid["planned"].items()
        if attempt["target_class"] == "SYSTEM_EVAL_ONLY"
        and attempt["corpus_pool_id"] == PRIMARY_ESTIMATE_POOL_ID
    }
    missing = sorted(system_attempt_ids - set(grid["observed"]))
    system_rows = [
        row
        for attempt_id, row in grid["observed"].items()
        if attempt_id in system_attempt_ids
    ]
    counts = Counter(row["terminal_status"] for row in system_rows)
    failures = counts.get("FAIL", 0)
    denominator = counts.get("PASS", 0) + failures
    if missing:
        terminal_status = "NOT_EVALUABLE"
        reason = "MISSING_PLANNED_SYSTEM_OBSERVATIONS"
    elif not system_attempt_ids:
        terminal_status = "NOT_EVALUABLE"
        reason = "NO_PREDECLARED_SYSTEM_ATTEMPTS"
    elif denominator == 0:
        terminal_status = "NOT_EVALUABLE"
        reason = "ZERO_SYSTEM_SCORABLE_DENOMINATOR"
    else:
        terminal_status = "PASS"
        reason = None
    return {
        "method_id": SAP_METHOD_IDS[7],
        "terminal_status": terminal_status,
        "reason": reason,
        "planned_system_attempt_count": len(system_attempt_ids),
        "corpus_pool": PRIMARY_ESTIMATE_POOL_ID,
        "missing_attempt_ids": missing,
        "failure_count": failures,
        "system_scorable_denominator": denominator,
        "failure_rate": (
            round(failures / denominator, 12) if denominator else None
        ),
        "excluded_terminal_counts": {
            status: counts.get(status, 0)
            for status in NON_MODEL_SCORABLE_TERMINALS
        },
        "wilson_95": wilson_interval_v1(failures, denominator),
        "model_attribution_emitted": False,
        "ranking_emitted": False,
        "claim_scope": "SYSTEM_ONLY_NOT_MODEL_QUALITY",
    }


def paired_complete_case_v1(
    manifest: object,
    observations: Iterable[Mapping[str, Any]],
    *,
    left_model_subject_id: str,
    right_model_subject_id: str,
    expected_artifact_fingerprints: Mapping[str, str],
) -> dict[str, Any]:
    if left_model_subject_id == right_model_subject_id:
        raise ValueError("paired comparison requires two distinct model subjects")
    rows = list(observations)
    grid = validate_observation_grid_v1(
        manifest,
        rows,
        expected_artifact_fingerprints=expected_artifact_fingerprints,
    )
    comparison_classes = set(
        validate_benchmark_manifest(
            manifest,
            expected_artifact_fingerprints=expected_artifact_fingerprints,
        )["comparison_classes"]
    )
    relevant_missing = sorted(
        attempt_id
        for attempt_id in grid["missing_attempt_ids"]
        if grid["planned"][attempt_id]["target_class"] in comparison_classes
        and grid["planned"][attempt_id]["model_subject_id"]
        in {left_model_subject_id, right_model_subject_id}
        and grid["planned"][attempt_id]["corpus_pool_id"]
        == PRIMARY_ESTIMATE_POOL_ID
    )
    if relevant_missing:
        return {
            "method_id": SAP_METHOD_IDS[5],
            "terminal_status": "NOT_EVALUABLE",
            "reason": "MISSING_PLANNED_OBSERVATIONS",
            "paired_scorable_count": 0,
            "excluded_pair_count": 0,
            "left_failure_rate": None,
            "right_failure_rate": None,
            "failure_rate_delta_left_minus_right": None,
            "corpus_pool": PRIMARY_ESTIMATE_POOL_ID,
            "ranking_emitted": False,
        }

    retry_ordinals: dict[str, int] = {}
    for attempt_id, attempt in grid["planned"].items():
        ordinal = 0
        parent_id = attempt["parent_attempt_id"]
        while parent_id is not None:
            ordinal += 1
            parent_id = grid["planned"][parent_id]["parent_attempt_id"]
        retry_ordinals[attempt_id] = ordinal

    def pair_key(row: Mapping[str, Any]) -> tuple[str, str, int, int]:
        return (
            str(row["target_id"]),
            str(row["corpus_item_alias"]),
            int(row["replicate_index"]),
            retry_ordinals[str(row["attempt_id"])],
        )

    model_rows: dict[
        str, dict[tuple[str, str, int, int], Mapping[str, Any]]
    ] = {}
    for model_id in (left_model_subject_id, right_model_subject_id):
        selected = [
            row
            for attempt_id, row in grid["observed"].items()
            if row["model_subject_id"] == model_id
            and row["target_class"] in comparison_classes
            and grid["planned"][attempt_id]["corpus_pool_id"]
            == PRIMARY_ESTIMATE_POOL_ID
        ]
        keyed = {pair_key(row): row for row in selected}
        if len(keyed) != len(selected):
            raise ValueError("duplicate paired comparison identity")
        model_rows[model_id] = keyed
    left = model_rows[left_model_subject_id]
    right = model_rows[right_model_subject_id]
    if not left or set(left) != set(right):
        return {
            "method_id": SAP_METHOD_IDS[5],
            "terminal_status": "NOT_EVALUABLE",
            "reason": "UNPAIRED_PREDECLARED_DESIGN",
            "paired_scorable_count": 0,
            "excluded_pair_count": 0,
            "left_failure_rate": None,
            "right_failure_rate": None,
            "failure_rate_delta_left_minus_right": None,
            "corpus_pool": PRIMARY_ESTIMATE_POOL_ID,
            "ranking_emitted": False,
        }
    for key in sorted(left):
        left_identity = grid["planned"][left[key]["attempt_id"]]
        right_identity = grid["planned"][right[key]["attempt_id"]]
        if any(
            left_identity[field] != right_identity[field]
            for field in PAIR_COMPATIBILITY_FIELDS
        ):
            return {
                "method_id": SAP_METHOD_IDS[5],
                "terminal_status": "NOT_EVALUABLE",
                "reason": "PAIRED_IDENTITY_MISMATCH",
                "paired_scorable_count": 0,
                "excluded_pair_count": 0,
                "left_failure_rate": None,
                "right_failure_rate": None,
                "failure_rate_delta_left_minus_right": None,
                "corpus_pool": PRIMARY_ESTIMATE_POOL_ID,
                "ranking_emitted": False,
            }
    included = [
        key
        for key in sorted(left)
        if left[key]["terminal_status"] in MODEL_SCORABLE_TERMINALS
        and right[key]["terminal_status"] in MODEL_SCORABLE_TERMINALS
    ]
    if not included:
        return {
            "method_id": SAP_METHOD_IDS[5],
            "terminal_status": "NOT_EVALUABLE",
            "reason": "ZERO_PAIRED_MODEL_SCORABLE_DENOMINATOR",
            "paired_scorable_count": 0,
            "excluded_pair_count": len(left),
            "left_failure_rate": None,
            "right_failure_rate": None,
            "failure_rate_delta_left_minus_right": None,
            "corpus_pool": PRIMARY_ESTIMATE_POOL_ID,
            "ranking_emitted": False,
        }
    left_rate = sum(left[key]["terminal_status"] == "FAIL" for key in included) / len(included)
    right_rate = sum(right[key]["terminal_status"] == "FAIL" for key in included) / len(included)
    return {
        "method_id": SAP_METHOD_IDS[5],
        "terminal_status": "PASS",
        "reason": None,
        "paired_scorable_count": len(included),
        "excluded_pair_count": len(left) - len(included),
        "left_failure_rate": round(left_rate, 12),
        "right_failure_rate": round(right_rate, 12),
        "failure_rate_delta_left_minus_right": round(left_rate - right_rate, 12),
        "corpus_pool": PRIMARY_ESTIMATE_POOL_ID,
        "ranking_emitted": False,
    }


def validate_adjudication_record(document: object) -> dict[str, Any]:
    label = "adjudication-record"
    doc = _obj(document, label)
    _exact_keys(
        doc,
        {
            "schema_version",
            "adjudication_id",
            "study_id",
            "attempt_id",
            "item_alias",
            "metric_id",
            "round_role",
            "adjudicator_type",
            "adjudicator_id",
            "adjudicator_configuration_fingerprint",
            "record_status",
            "decision",
            "blind_to_model_identity",
            "blind_to_provider_identity",
            "blind_to_peer_decisions",
            "rubric_version",
            "rubric_fingerprint",
            "evidence_complete",
            "conflict_status",
            "rationale_code",
            "record_fingerprint",
        },
        label,
    )
    if _text(doc, "schema_version", label) != ADJUDICATION_SCHEMA_VERSION:
        raise ValueError("unsupported BM0 adjudication schema")
    for key in (
        "adjudication_id",
        "study_id",
        "attempt_id",
        "item_alias",
        "metric_id",
        "adjudicator_id",
        "rubric_version",
        "rationale_code",
    ):
        _identifier(doc, key, label)
    if doc.get("round_role") not in {"PRIMARY", "TIEBREAK"}:
        raise ValueError("adjudication round role is unsupported")
    if doc.get("adjudicator_type") not in {"HUMAN", "FIXED_JUDGE"}:
        raise ValueError("adjudicator type is unsupported")
    _require_sha256(
        doc.get("adjudicator_configuration_fingerprint"),
        "adjudicator_configuration_fingerprint",
    )
    if doc.get("record_status") not in {"COMPLETED", "ERROR"}:
        raise ValueError("adjudication record status is unsupported")
    if doc.get("decision") not in {"PASS", "FAIL", "UNKNOWN", None}:
        raise ValueError("adjudication decision is unsupported")
    for key in (
        "blind_to_model_identity",
        "blind_to_provider_identity",
        "blind_to_peer_decisions",
        "evidence_complete",
    ):
        _boolean(doc, key, label)
    if not all(
        doc[key]
        for key in (
            "blind_to_model_identity",
            "blind_to_provider_identity",
            "blind_to_peer_decisions",
        )
    ):
        raise ValueError("adjudication must remain blind to identity and peer decisions")
    _require_sha256(doc.get("rubric_fingerprint"), "rubric_fingerprint")
    if doc.get("conflict_status") != "NONE":
        raise ValueError("conflicted adjudicators must be excluded, not scored")
    if doc["record_status"] == "COMPLETED":
        if doc["decision"] is None:
            raise ValueError("completed adjudication requires a decision")
        if doc["decision"] in {"PASS", "FAIL"} and not doc["evidence_complete"]:
            raise ValueError("PASS/FAIL adjudication requires complete evidence")
        if doc["decision"] == "UNKNOWN" and doc["evidence_complete"]:
            raise ValueError("UNKNOWN adjudication must preserve missing evidence")
    elif doc["decision"] is not None or doc["evidence_complete"]:
        raise ValueError("adjudication ERROR cannot carry a decision or complete evidence")
    assert_public_safe(doc)
    return _verify_fingerprint(doc, "record_fingerprint", label)


def resolve_adjudication_v1(
    manifest: object,
    records: Iterable[Mapping[str, Any]],
    *,
    expected_artifact_fingerprints: Mapping[str, str],
) -> dict[str, Any]:
    checked_manifest = validate_benchmark_manifest(
        manifest,
        expected_artifact_fingerprints=expected_artifact_fingerprints,
    )
    if checked_manifest["study_state"] != "FROZEN":
        raise ValueError("adjudication resolution requires a FROZEN manifest")
    plan = checked_manifest["adjudication_plan"]
    if plan is None:
        raise ValueError("frozen manifest is missing its adjudication plan")
    rows = [validate_adjudication_record(record) for record in records]
    if not rows:
        return {
            "method_id": SAP_METHOD_IDS[6],
            "terminal_status": "UNKNOWN",
            "reason": "MISSING_PRIMARY_ADJUDICATIONS",
            "decision": None,
        }
    identity_fields = ("study_id", "attempt_id", "item_alias", "metric_id", "rubric_version", "rubric_fingerprint")
    for field in identity_fields:
        if len({row[field] for row in rows}) != 1:
            raise ValueError(f"adjudication records disagree on {field}")
    planned_attempts = {
        attempt["attempt_id"]: attempt
        for attempt in checked_manifest["planned_attempts"]
    }
    planned = planned_attempts.get(rows[0]["attempt_id"])
    if planned is None:
        raise ValueError("adjudication references an unplanned attempt")
    if rows[0]["study_id"] != planned["study_id"]:
        raise ValueError("adjudication study does not match the planned attempt")
    if rows[0]["item_alias"] != planned["corpus_item_alias"]:
        raise ValueError("adjudication item alias does not match the planned attempt")
    if rows[0]["metric_id"] not in plan["metric_ids"]:
        raise ValueError("adjudication metric is absent from the frozen plan")
    if (
        rows[0]["rubric_version"] != plan["rubric_version"]
        or rows[0]["rubric_fingerprint"] != plan["rubric_fingerprint"]
    ):
        raise ValueError("adjudication rubric drifted from the frozen plan")
    adjudicator_ids = [row["adjudicator_id"] for row in rows]
    if len(adjudicator_ids) != len(set(adjudicator_ids)):
        raise ValueError("adjudicators must be distinct across all rounds")
    primaries = [row for row in rows if row["round_role"] == "PRIMARY"]
    tiebreakers = [row for row in rows if row["round_role"] == "TIEBREAK"]
    planned_primaries = {
        (
            entry["adjudicator_id"],
            entry["adjudicator_type"],
            entry["configuration_fingerprint"],
        )
        for entry in plan["primary_adjudicators"]
    }
    supplied_primaries = {
        (
            entry["adjudicator_id"],
            entry["adjudicator_type"],
            entry["adjudicator_configuration_fingerprint"],
        )
        for entry in primaries
    }
    if not supplied_primaries.issubset(planned_primaries):
        raise ValueError("an unplanned primary adjudicator was supplied")
    if len(tiebreakers) > 1:
        raise ValueError("at most one predeclared tiebreak adjudicator is allowed")
    if tiebreakers:
        supplied_tiebreak = (
            tiebreakers[0]["adjudicator_id"],
            tiebreakers[0]["adjudicator_type"],
            tiebreakers[0]["adjudicator_configuration_fingerprint"],
        )
        planned_tiebreak = (
            plan["tiebreak_adjudicator"]["adjudicator_id"],
            plan["tiebreak_adjudicator"]["adjudicator_type"],
            plan["tiebreak_adjudicator"]["configuration_fingerprint"],
        )
        if supplied_tiebreak != planned_tiebreak:
            raise ValueError("an unplanned tiebreak adjudicator was supplied")
    if len(primaries) > 2:
        raise ValueError("at most two predeclared primary adjudicators are allowed")
    if any(row["record_status"] == "ERROR" for row in primaries):
        return {
            "method_id": SAP_METHOD_IDS[6],
            "terminal_status": "ERROR",
            "reason": "ADJUDICATION_INFRASTRUCTURE_ERROR",
            "decision": None,
        }
    if len(primaries) != 2:
        return {
            "method_id": SAP_METHOD_IDS[6],
            "terminal_status": "UNKNOWN",
            "reason": "INCOMPLETE_OR_AMBIGUOUS_ADJUDICATION_SET",
            "decision": None,
        }
    if supplied_primaries != planned_primaries:
        raise ValueError("the primary adjudicator set drifted from the frozen plan")
    primary_decisions = {row["decision"] for row in primaries}
    if len(primary_decisions) == 1:
        if tiebreakers:
            raise ValueError("a tiebreaker is forbidden when primaries agree")
        decision = primaries[0]["decision"]
        return {
            "method_id": SAP_METHOD_IDS[6],
            "terminal_status": decision,
            "reason": "PRIMARY_AGREEMENT",
            "decision": decision,
        }
    if len(tiebreakers) != 1:
        return {
            "method_id": SAP_METHOD_IDS[6],
            "terminal_status": "UNKNOWN",
            "reason": "PRIMARY_DISAGREEMENT_REQUIRES_TIEBREAK",
            "decision": None,
        }
    if tiebreakers[0]["record_status"] == "ERROR":
        return {
            "method_id": SAP_METHOD_IDS[6],
            "terminal_status": "ERROR",
            "reason": "ADJUDICATION_INFRASTRUCTURE_ERROR",
            "decision": None,
        }
    decision = tiebreakers[0]["decision"]
    return {
        "method_id": SAP_METHOD_IDS[6],
        "terminal_status": decision,
        "reason": "PREDECLARED_TIEBREAK",
        "decision": decision,
    }


def validate_measurement_contract(
    document: object,
    *,
    bound_artifacts: Mapping[str, object],
) -> dict[str, Any]:
    label = "bm0-measurement-contract"
    doc = _obj(document, label)
    _exact_keys(
        doc,
        {
            "schema_version",
            "work_order_id",
            "work_order_revision",
            "stage",
            "implementation_base_sha",
            "authority",
            "provider_roster_status",
            "artifact_bindings",
            "target_contract",
            "terminal_semantics",
            "model_failure_denominator",
            "sap",
            "adjudication_contract",
            "claim_ceiling",
            "execution_boundaries",
            "bm0_green_gate",
            "limitations",
            "contract_fingerprint",
        },
        label,
    )
    if _text(doc, "schema_version", label) != CONTRACT_SCHEMA_VERSION:
        raise ValueError("unsupported BM0 measurement contract schema")
    if doc.get("work_order_id") != WORK_ORDER_ID or doc.get("work_order_revision") != WORK_ORDER_REVISION:
        raise ValueError("BM0 work-order identity drifted")
    if doc.get("stage") != "BOUNDED_OFFLINE_MEASUREMENT_CONTRACT":
        raise ValueError("BM0 stage must remain offline contract-only")
    if _require_git_sha(doc.get("implementation_base_sha"), "implementation_base_sha") != IMPLEMENTATION_BASE_SHA:
        raise ValueError("BM0 implementation baseline drifted")
    if doc.get("authority") != "MEASUREMENT_CONTRACT_NOT_BENCHMARK_RESULT":
        raise ValueError("BM0 contract cannot assert result authority")
    if doc.get("provider_roster_status") != "NOT_SELECTED":
        raise ValueError("BM0 cannot select a provider/model roster")

    bindings = _obj(doc.get("artifact_bindings"), f"{label}.artifact_bindings")
    if set(bindings) != set(BOUND_ARTIFACT_PATHS) or set(bindings) != set(
        bound_artifacts
    ):
        raise ValueError("BM0 artifact binding inventory is incomplete or excessive")
    for path, artifact in bound_artifacts.items():
        claimed = _require_sha256(bindings.get(path), f"artifact_bindings[{path}]")
        if claimed != sha256_json(artifact):
            raise ValueError(f"BM0 artifact binding mismatch for {path}")

    target = _obj(doc.get("target_contract"), f"{label}.target_contract")
    _exact_keys(
        target,
        {"target_count", "class_counts", "default_comparable_classes", "sandbox_equivalence_status"},
        f"{label}.target_contract",
    )
    if (
        _integer(target, "target_count", f"{label}.target_contract") != 16
        or dict(_obj(target.get("class_counts"), "target_contract.class_counts"))
        != EXPECTED_TARGET_CLASS_COUNTS
        or tuple(_strings(target, "default_comparable_classes", "target_contract"))
        != DEFAULT_COMPARABLE_CLASSES
        or target.get("sandbox_equivalence_status") != "NOT_ESTABLISHED"
    ):
        raise ValueError("BM0 target contract drifted")

    terminal_raw = doc.get("terminal_semantics")
    if not isinstance(terminal_raw, list) or len(terminal_raw) != len(TERMINAL_STATUSES):
        raise ValueError("BM0 terminal semantics must enumerate all six states")
    reconstructed: dict[str, dict[str, Any]] = {}
    for index, raw in enumerate(terminal_raw):
        entry = _obj(raw, f"terminal_semantics[{index}]")
        _exact_keys(
            entry,
            {"terminal_status", "category", "model_failure_denominator", "model_failure_numerator"},
            f"terminal_semantics[{index}]",
        )
        status = _text(entry, "terminal_status", f"terminal_semantics[{index}]")
        if status in reconstructed:
            raise ValueError("duplicate terminal semantics")
        reconstructed[status] = {
            "category": _text(entry, "category", f"terminal_semantics[{index}]"),
            "model_failure_denominator": _boolean(entry, "model_failure_denominator", f"terminal_semantics[{index}]"),
            "model_failure_numerator": _boolean(entry, "model_failure_numerator", f"terminal_semantics[{index}]"),
        }
    if reconstructed != TERMINAL_CONTRACT or tuple(entry["terminal_status"] for entry in terminal_raw) != TERMINAL_STATUSES:
        raise ValueError("BM0 terminal semantics drifted")

    denominator = _obj(doc.get("model_failure_denominator"), f"{label}.model_failure_denominator")
    _exact_keys(
        denominator,
        {"unit", "corpus_pool", "eligible_classes", "included_statuses", "failure_status", "excluded_statuses", "zero_denominator", "partial_grid", "retry_semantics"},
        f"{label}.model_failure_denominator",
    )
    if (
        denominator.get("unit") != "UNIQUE_PREDECLARED_ATTEMPT"
        or denominator.get("corpus_pool") != PRIMARY_ESTIMATE_POOL_ID
        or tuple(denominator.get("eligible_classes", [])) != DEFAULT_COMPARABLE_CLASSES
        or denominator.get("included_statuses") != ["PASS", "FAIL"]
        or denominator.get("failure_status") != "FAIL"
        or set(denominator.get("excluded_statuses", [])) != set(NON_MODEL_SCORABLE_TERMINALS)
        or denominator.get("zero_denominator") != "NOT_EVALUABLE/ZERO_MODEL_SCORABLE_DENOMINATOR"
        or denominator.get("partial_grid") != "NOT_EVALUABLE/MISSING_PLANNED_OBSERVATIONS"
        or denominator.get("retry_semantics") != "NEW_PREDECLARED_ATTEMPT_ID_NEVER_SILENT_REPLACEMENT"
    ):
        raise ValueError("BM0 model-failure denominator drifted")

    sap = _obj(doc.get("sap"), f"{label}.sap")
    _exact_keys(sap, {"sap_id", "frozen_before_hidden_access", "methods"}, f"{label}.sap")
    _identifier(sap, "sap_id", f"{label}.sap")
    if _boolean(sap, "frozen_before_hidden_access", f"{label}.sap") is not True:
        raise ValueError("SAP must freeze before hidden access")
    methods_raw = sap.get("methods")
    if not isinstance(methods_raw, list) or len(methods_raw) != len(SAP_METHOD_IDS):
        raise ValueError("SAP must bind every named method")
    for index, raw in enumerate(methods_raw):
        method = _obj(raw, f"sap.methods[{index}]")
        _exact_keys(method, {"method_id", "implementation", "purpose", "frozen_parameters"}, f"sap.methods[{index}]")
        method_id = _text(method, "method_id", f"sap.methods[{index}]")
        if method_id != SAP_METHOD_IDS[index] or method.get("implementation") != SAP_IMPLEMENTATIONS[method_id]:
            raise ValueError("SAP method identity or implementation drifted")
        _text(method, "purpose", f"sap.methods[{index}]")
        frozen_parameters = method.get("frozen_parameters")
        if not isinstance(frozen_parameters, Mapping):
            raise ValueError("SAP frozen_parameters must be an object")
        if dict(frozen_parameters) != SAP_FROZEN_PARAMETERS[method_id]:
            raise ValueError("SAP frozen parameters drifted")

    adjudication = _obj(doc.get("adjudication_contract"), f"{label}.adjudication_contract")
    _exact_keys(
        adjudication,
        {"schema_path", "plan_location", "mode_status", "minimum_primary_records", "distinct_adjudicators_required", "adjudicator_configuration_bound", "predeclared_tiebreaker_required", "tiebreak_rule", "model_identity_blinded", "provider_identity_blinded", "peer_decisions_blinded"},
        f"{label}.adjudication_contract",
    )
    if (
        adjudication.get("schema_path") != "schemas/bm0_adjudication_record.schema.json"
        or adjudication.get("plan_location") != "FROZEN_MANIFEST"
        or adjudication.get("mode_status") != "NOT_SELECTED"
        or _integer(adjudication, "minimum_primary_records", "adjudication_contract", minimum=2) != 2
        or any(
            adjudication.get(key) is not True
            for key in (
                "distinct_adjudicators_required",
                "adjudicator_configuration_bound",
                "predeclared_tiebreaker_required",
                "model_identity_blinded",
                "provider_identity_blinded",
                "peer_decisions_blinded",
            )
        )
        or adjudication.get("tiebreak_rule") != "EXACTLY_ONE_PREDECLARED_DISTINCT_TIEBREAKER_ON_DISAGREEMENT"
    ):
        raise ValueError("BM0 adjudication contract drifted")

    claims = _obj(doc.get("claim_ceiling"), f"{label}.claim_ceiling")
    _exact_keys(claims, {"allowed_claim_codes", "forbidden_claim_codes"}, f"{label}.claim_ceiling")
    if set(_strings(claims, "allowed_claim_codes", "claim_ceiling")) != ALLOWED_CLAIM_CODES:
        raise ValueError("BM0 allowed claim ceiling drifted")
    if set(_strings(claims, "forbidden_claim_codes", "claim_ceiling")) != FORBIDDEN_CLAIM_CODES:
        raise ValueError("BM0 forbidden claim ceiling drifted")

    boundaries = _obj(doc.get("execution_boundaries"), f"{label}.execution_boundaries")
    _exact_keys(
        boundaries,
        {"live_model_calls", "credential_lookup", "spend", "provider_roster_selection", "benchmark_results", "b2_blind_reuse_by_assumption", "b1_pr17_mutation", "qa_receipt_history_rewrite", "fairness_lqe_promotion", "dependency_workflow_docker_version_change", "merge_release"},
        f"{label}.execution_boundaries",
    )
    if boundaries != {
        "live_model_calls": 0,
        "credential_lookup": False,
        "spend": 0,
        "provider_roster_selection": False,
        "benchmark_results": False,
        "b2_blind_reuse_by_assumption": False,
        "b1_pr17_mutation": False,
        "qa_receipt_history_rewrite": False,
        "fairness_lqe_promotion": False,
        "dependency_workflow_docker_version_change": False,
        "merge_release": False,
    }:
        raise ValueError("BM0 execution boundary drifted")

    green = _obj(doc.get("bm0_green_gate"), f"{label}.bm0_green_gate")
    _exact_keys(green, {"developer_regressions", "exact_head_ci", "independent_qa", "current_state"}, f"{label}.bm0_green_gate")
    if green != {
        "developer_regressions": "REQUIRED",
        "exact_head_ci": "REQUIRED",
        "independent_qa": "DISTINCT_PASS_REQUIRED",
        "current_state": "NOT_EVALUATED",
    }:
        raise ValueError("BM0 GREEN gate cannot be self-promoted")
    _strings(doc, "limitations", label)
    assert_public_safe(doc)
    return _verify_fingerprint(doc, "contract_fingerprint", label)


def build_bm0_receipt(
    *,
    contract: object,
    target_matrix: object,
    metric_registry: object,
    corpus_policy: object,
    manifest_template: object,
    bound_artifacts: Mapping[str, object],
) -> dict[str, Any]:
    checked_matrix = validate_target_matrix(target_matrix)
    checked_registry = validate_bm0_metric_registry(metric_registry)
    checked_corpus = validate_corpus_policy(corpus_policy)
    checked_contract = validate_measurement_contract(
        contract, bound_artifacts=bound_artifacts
    )
    sap_fingerprint = sha256_json(checked_contract["sap"])
    expected_manifest_artifacts = {
        "target_matrix": checked_matrix["matrix_fingerprint"],
        "metric_registry": checked_registry["registry_fingerprint"],
        "corpus_policy": checked_corpus["policy_fingerprint"],
        "analysis_plan": sap_fingerprint,
        "analysis_implementation": checked_contract["artifact_bindings"]["b2/bm0.py"],
    }
    checked_manifest = validate_benchmark_manifest(
        manifest_template,
        expected_artifact_fingerprints=expected_manifest_artifacts,
    )
    class_counts = Counter(target["target_class"] for target in checked_matrix["targets"])
    receipt = {
        "schema_version": RECEIPT_SCHEMA_VERSION,
        "work_order_id": WORK_ORDER_ID,
        "work_order_revision": WORK_ORDER_REVISION,
        "implementation_base_sha": IMPLEMENTATION_BASE_SHA,
        "validation_scope": "OFFLINE_MEASUREMENT_CONTRACT_ONLY",
        "artifact_count": len(bound_artifacts) + 1,
        "artifact_fingerprints": {
            **dict(sorted(checked_contract["artifact_bindings"].items())),
            "cases/b2/public-safe/benchmark/bm0-measurement-contract.json": checked_contract["contract_fingerprint"],
        },
        "target_count": len(checked_matrix["targets"]),
        "target_class_counts": {
            target_class: class_counts[target_class] for target_class in TARGET_CLASSES
        },
        "default_comparable_classes": list(DEFAULT_COMPARABLE_CLASSES),
        "primary_estimate_pool": PRIMARY_ESTIMATE_POOL_ID,
        "sandbox_equivalence_status": "NOT_ESTABLISHED",
        "terminal_statuses": list(TERMINAL_STATUSES),
        "model_failure_denominator_statuses": list(MODEL_SCORABLE_TERMINALS),
        "non_model_failure_statuses": list(NON_MODEL_SCORABLE_TERMINALS),
        "sap_method_ids": list(SAP_METHOD_IDS),
        "manifest_template_state": checked_manifest["study_state"],
        "provider_roster_status": checked_manifest["provider_roster_status"],
        "corpus_commitment_status": checked_manifest["corpus_commitment_status"],
        "corpus_aggregate_commitment": checked_manifest[
            "corpus_aggregate_commitment"
        ],
        "adjudication_mode": checked_manifest["adjudication_mode"],
        "planned_attempt_count": checked_manifest["planned_attempt_count"],
        "hidden_exact_content_in_public_repository": checked_corpus["hidden_holdout"]["exact_content_in_public_repository"],
        "live_model_calls": 0,
        "credential_lookups": 0,
        "spend": 0,
        "benchmark_results_emitted": False,
        "developer_contract_gate": "PASS",
        "exact_head_ci_status": "NOT_RUN",
        "independent_qa_status": "NOT_RUN",
        "bm0_green": False,
        "bm0_status": "READY_FOR_EXACT_HEAD_CI_AND_INDEPENDENT_QA",
        "limitations": [
            "This receipt validates an offline measurement contract; it is not a benchmark result.",
            "No provider/model roster, hidden corpus, live call, ranking, or population estimate is selected or executed.",
            "Developer validation cannot satisfy the distinct BM0 Independent QA gate.",
        ],
    }
    receipt["receipt_fingerprint"] = sha256_json(receipt)
    return receipt


def validate_bm0_receipt(document: object) -> dict[str, Any]:
    label = "bm0-receipt"
    doc = _obj(document, label)
    expected_keys = {
        "schema_version",
        "work_order_id",
        "work_order_revision",
        "implementation_base_sha",
        "validation_scope",
        "artifact_count",
        "artifact_fingerprints",
        "target_count",
        "target_class_counts",
        "default_comparable_classes",
        "primary_estimate_pool",
        "sandbox_equivalence_status",
        "terminal_statuses",
        "model_failure_denominator_statuses",
        "non_model_failure_statuses",
        "sap_method_ids",
        "manifest_template_state",
        "provider_roster_status",
        "corpus_commitment_status",
        "corpus_aggregate_commitment",
        "adjudication_mode",
        "planned_attempt_count",
        "hidden_exact_content_in_public_repository",
        "live_model_calls",
        "credential_lookups",
        "spend",
        "benchmark_results_emitted",
        "developer_contract_gate",
        "exact_head_ci_status",
        "independent_qa_status",
        "bm0_green",
        "bm0_status",
        "limitations",
        "receipt_fingerprint",
    }
    _exact_keys(doc, expected_keys, label)
    if doc.get("schema_version") != RECEIPT_SCHEMA_VERSION:
        raise ValueError("unsupported BM0 receipt schema")
    if (
        doc.get("work_order_id") != WORK_ORDER_ID
        or doc.get("work_order_revision") != WORK_ORDER_REVISION
        or doc.get("implementation_base_sha") != IMPLEMENTATION_BASE_SHA
        or doc.get("validation_scope") != "OFFLINE_MEASUREMENT_CONTRACT_ONLY"
        or doc.get("artifact_count") != len(BOUND_ARTIFACT_PATHS) + 1
        or doc.get("target_count") != 16
        or doc.get("target_class_counts") != EXPECTED_TARGET_CLASS_COUNTS
        or tuple(doc.get("default_comparable_classes", []))
        != DEFAULT_COMPARABLE_CLASSES
        or doc.get("primary_estimate_pool") != PRIMARY_ESTIMATE_POOL_ID
        or doc.get("sandbox_equivalence_status") != "NOT_ESTABLISHED"
        or tuple(doc.get("terminal_statuses", [])) != TERMINAL_STATUSES
        or tuple(doc.get("model_failure_denominator_statuses", []))
        != MODEL_SCORABLE_TERMINALS
        or tuple(doc.get("non_model_failure_statuses", []))
        != NON_MODEL_SCORABLE_TERMINALS
        or tuple(doc.get("sap_method_ids", [])) != SAP_METHOD_IDS
        or doc.get("manifest_template_state") != "DESIGN_ONLY"
        or doc.get("provider_roster_status") != "NOT_SELECTED"
        or doc.get("corpus_commitment_status") != "NOT_COMMITTED"
        or doc.get("corpus_aggregate_commitment") is not None
        or doc.get("adjudication_mode") != "NOT_SELECTED"
        or doc.get("planned_attempt_count") != 0
        or doc.get("hidden_exact_content_in_public_repository") is not False
        or doc.get("live_model_calls") != 0
        or doc.get("credential_lookups") != 0
        or doc.get("spend") != 0
        or doc.get("developer_contract_gate") != "PASS"
        or doc.get("exact_head_ci_status") != "NOT_RUN"
        or doc.get("independent_qa_status") != "NOT_RUN"
        or doc.get("bm0_green") is not False
        or doc.get("benchmark_results_emitted") is not False
        or doc.get("bm0_status")
        != "READY_FOR_EXACT_HEAD_CI_AND_INDEPENDENT_QA"
    ):
        raise ValueError("BM0 developer receipt overstates authority or readiness")
    fingerprints = _obj(doc.get("artifact_fingerprints"), "bm0-receipt.artifact_fingerprints")
    if set(fingerprints) != set(BOUND_ARTIFACT_PATHS) | {CONTRACT_ARTIFACT_PATH}:
        raise ValueError("BM0 receipt artifact inventory drifted")
    for path, value in fingerprints.items():
        _require_sha256(value, f"bm0-receipt.artifact_fingerprints[{path}]")
    if doc.get("limitations") != [
        "This receipt validates an offline measurement contract; it is not a benchmark result.",
        "No provider/model roster, hidden corpus, live call, ranking, or population estimate is selected or executed.",
        "Developer validation cannot satisfy the distinct BM0 Independent QA gate.",
    ]:
        raise ValueError("BM0 receipt limitations drifted")
    assert_public_safe(doc)
    return _verify_fingerprint(doc, "receipt_fingerprint", label)


def assert_claim_allowed(claim_code: str, developer_receipt: object) -> None:
    checked = validate_bm0_receipt(developer_receipt)
    if claim_code in FORBIDDEN_CLAIM_CODES:
        raise ValueError(f"claim {claim_code} exceeds the BM0 claim ceiling")
    if claim_code not in ALLOWED_CLAIM_CODES:
        raise ValueError(f"claim {claim_code} is not declared by the BM0 contract")
    if checked["developer_contract_gate"] != "PASS":
        raise ValueError("BM0 developer contract gate is not PASS")
