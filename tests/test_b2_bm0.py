from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from b2.bm0 import (
    BOUND_ARTIFACT_PATHS,
    CANONICAL_FAMILY_LINEAGE,
    CANONICAL_SOURCE_ARTIFACT_PATHS,
    DEFAULT_COMPARABLE_CLASSES,
    EXPECTED_TARGET_CLASS_COUNTS,
    EXPECTED_METRIC_IDS,
    HIDDEN_HOLDOUT_DECLARATION,
    HIDDEN_HOLDOUT_DECLARATION_ID,
    IMPLEMENTATION_BASE_SHA,
    METRIC_WEIGHTING_RULES,
    NON_MODEL_SCORABLE_TERMINALS,
    SAP_METHOD_IDS,
    SAP_DESIGN_RULE,
    SYSTEM_SCOPE_ID,
    TARGET_CLASSES,
    TARGET_IDS_BY_CLASS,
    TARGET_LINEAGE_BY_ID,
    assert_claim_allowed,
    bounded_pilot_design_v1,
    build_bm0_receipt,
    case_failure_probability_v1,
    control_false_positive_rate_v1,
    corpus_aggregate_commitment_v1,
    fixed_attempt_stop_v1,
    family_conditional_failure_rate_v1,
    fcfr_case_cluster_bootstrap_v1,
    infrastructure_error_rate_v1,
    measurement_contract_core_fingerprint_v1,
    model_failure_denominator_v1,
    paired_complete_case_v1,
    resolve_adjudication_v1,
    system_invariant_failure_rate_v1,
    typed_terminal_partition_v1,
    validate_adjudication_record,
    validate_benchmark_manifest,
    validate_bm0_metric_registry,
    validate_bm0_receipt,
    validate_candidate_roster_budget,
    validate_corpus_policy,
    validate_canonical_family_lineage_v1,
    validate_measurement_contract,
    validate_observation,
    validate_observation_grid_v1,
    validate_target_matrix,
    validate_trial_identity,
    within_case_instability_v1,
    wilson_interval_v1,
)
from b2.qa0 import TERMINAL_STATUSES, sha256_json


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK = ROOT / "cases" / "b2" / "public-safe" / "benchmark"
RESULTS = ROOT / "results" / "b2"


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def refingerprint(document: dict, field: str) -> dict:
    candidate = copy.deepcopy(document)
    candidate.pop(field, None)
    candidate[field] = sha256_json(candidate)
    return candidate


def identity(
    *,
    model: str = "model-a",
    target_class: str = "MODEL_DIRECT",
    target_id: str | None = None,
    item: str = "item-001",
    replicate: int = 0,
    serial: str = "001",
    case_id: str | None = None,
    variant_id: str = "KNOWN_BAD",
) -> dict:
    resolved_target = target_id or TARGET_IDS_BY_CLASS[target_class][0]
    lineage = TARGET_LINEAGE_BY_ID[resolved_target]
    if target_class == "SYSTEM_EVAL_ONLY":
        provider_subject = SYSTEM_SCOPE_ID
        model_subject = SYSTEM_SCOPE_ID
        model_snapshot = SYSTEM_SCOPE_ID
        requested_model = SYSTEM_SCOPE_ID
        expected_resolved = SYSTEM_SCOPE_ID
        identity_certainty = "SYSTEM_SCOPE"
        alias_limitation = "NOT_APPLICABLE_SYSTEM_SCOPE"
        endpoint_id = SYSTEM_SCOPE_ID
        capability_mode = "SYSTEM_EVAL"
    else:
        provider_subject = f"provider-{model}"
        model_subject = model
        model_snapshot = f"snapshot-{model}-20260904"
        requested_model = model
        expected_resolved = model_snapshot
        identity_certainty = "EXACT"
        alias_limitation = "NONE"
        endpoint_id = "responses-v1"
        capability_mode = "TEXT_ONLY"
    seed = 41 + replicate
    resolved_case_id = case_id or item
    return {
        "schema_version": "b2-bm0-trial-identity/v1",
        "benchmark_id": "benchmark-001",
        "contract_version": "v0.2",
        "study_id": "study-001",
        "trial_id": f"trial-{model}-{serial}",
        "attempt_id": f"attempt-{model}-{serial}",
        "parent_attempt_id": None,
        "provider_subject_id": provider_subject,
        "model_subject_id": model_subject,
        "model_snapshot_id": model_snapshot,
        "requested_model_id": requested_model,
        "expected_resolved_model_or_version_id": expected_resolved,
        "required_identity_certainty": identity_certainty,
        "alias_limitation": alias_limitation,
        "endpoint_id": endpoint_id,
        "capability_mode": capability_mode,
        "system_wrapper_version": "system-wrapper-v1",
        "developer_wrapper_version": "developer-wrapper-v1",
        "sampling_controls": {
            "temperature": 0.0,
            "top_p": 1.0,
            "max_output_tokens": 512,
            "seed": seed,
            "automatic_retries": 0,
            "additional_parameters_fingerprint": "sha256:" + "1" * 64,
        },
        "reasoning_controls": {
            "mode": "FIXED",
            "effort": "medium",
            "max_reasoning_tokens": 256,
            "configuration_fingerprint": "sha256:" + "2" * 64,
        },
        "target_id": resolved_target,
        "target_class": target_class,
        "applicability_result": (
            "NOT_APPLICABLE"
            if target_class == "SYSTEM_EVAL_ONLY"
            else "APPLICABLE"
        ),
        "entry_id": lineage["entry_id"],
        "family_id": lineage["family_id"],
        "case_id": resolved_case_id,
        "variant_id": variant_id,
        "mechanism_lineage_id": (
            f"{lineage['entry_id']}-{lineage['family_id']}-mechanism-v1"
        ),
        "case_fingerprint": sha256_json(
            {
                "case_id": resolved_case_id,
                "entry_id": lineage["entry_id"],
                "family_id": lineage["family_id"],
                "variant_id": variant_id,
            }
        ),
        "generator_or_mutation_version": "authored-case-v1",
        "contamination_status": "ASSESSED_CLEAR",
        "exposure_status": "PRIVATE_UNEXPOSED_BEFORE_MANIFEST_FREEZE",
        "corpus_pool_id": "PRIVATE_HIDDEN_HOLDOUT",
        "corpus_item_alias": item,
        "corpus_item_commitment": sha256_json(
            {"fixture": "bm0-item", "item": item}
        ),
        "mutation_parent_commitment": None,
        "prompt_template_version": "prompt-v1",
        "prompt_fingerprint": "sha256:" + "3" * 64,
        "context_fingerprint": "sha256:" + "4" * 64,
        "tool_schema_fingerprint": "sha256:" + "5" * 64,
        "sandbox_fingerprint": "sha256:" + "6" * 64,
        "state_machine_fingerprint": "sha256:" + "7" * 64,
        "harness_version": "harness-v1",
        "adapter_id": "adapter-offline",
        "adapter_version": "adapter-v1",
        "scorer_id": "scorer-001",
        "scorer_version": "scorer-v1",
        "scorer_fingerprint": "sha256:" + "8" * 64,
        "oracle_id": "oracle-001",
        "oracle_version": "oracle-v1",
        "oracle_fingerprint": "sha256:" + "9" * 64,
        "replicate_index": replicate,
        "random_seed": seed,
        "environment_fingerprint": "sha256:" + "2" * 64,
    }


def observation(planned: dict, status: str) -> dict:
    system_only = planned["target_class"] == "SYSTEM_EVAL_ONLY"
    if status == "PASS":
        failure_value, evidence, hard, adjudication = 0, True, True, "RESOLVED"
    elif status == "FAIL":
        failure_value, evidence, hard, adjudication = 1, True, False, "RESOLVED"
    elif status == "ERROR":
        failure_value, evidence, hard, adjudication = None, False, None, "ERROR"
    elif status == "UNKNOWN":
        failure_value, evidence, hard, adjudication = None, False, None, "UNRESOLVED"
    else:
        failure_value, evidence, hard, adjudication = None, True, None, "UNRESOLVED"
    model_failure_value = None if system_only else failure_value
    system_failure_value = failure_value if system_only else None
    scorable = status in {"PASS", "FAIL"}
    if system_only:
        resolved_model = SYSTEM_SCOPE_ID
        identity_certainty = "SYSTEM_SCOPE"
        provider_request_id = None
        provider_terminal = "NOT_APPLICABLE"
        provider_http_status = None
        attribution_status = "NOT_APPLICABLE"
    elif scorable:
        resolved_model = planned["expected_resolved_model_or_version_id"]
        identity_certainty = planned["required_identity_certainty"]
        provider_request_id = f"request-{planned['attempt_id']}"
        provider_terminal = "SUCCESS"
        provider_http_status = 200
        attribution_status = "ATTRIBUTABLE"
    else:
        resolved_model = None
        identity_certainty = "UNKNOWN"
        provider_request_id = None
        provider_terminal = "RUNTIME_ERROR" if status == "ERROR" else "PROVIDER_ERROR"
        provider_http_status = None
        attribution_status = "UNAVAILABLE"
    row = {
        "schema_version": "b2-bm0-observation/v1",
        "benchmark_id": planned["benchmark_id"],
        "contract_version": planned["contract_version"],
        "attempt_id": planned["attempt_id"],
        "trial_id": planned["trial_id"],
        "provider_subject_id": planned["provider_subject_id"],
        "model_subject_id": planned["model_subject_id"],
        "requested_model_id": planned["requested_model_id"],
        "resolved_model_or_version_id": resolved_model,
        "identity_certainty": identity_certainty,
        "alias_limitation": planned["alias_limitation"],
        "provider_request_id": provider_request_id,
        "endpoint_id": planned["endpoint_id"],
        "capability_mode": planned["capability_mode"],
        "system_wrapper_version": planned["system_wrapper_version"],
        "developer_wrapper_version": planned["developer_wrapper_version"],
        "sampling_controls_fingerprint": sha256_json(planned["sampling_controls"]),
        "reasoning_controls_fingerprint": sha256_json(planned["reasoning_controls"]),
        "target_id": planned["target_id"],
        "target_class": planned["target_class"],
        "applicability_result": planned["applicability_result"],
        "entry_id": planned["entry_id"],
        "family_id": planned["family_id"],
        "case_id": planned["case_id"],
        "variant_id": planned["variant_id"],
        "mechanism_lineage_id": planned["mechanism_lineage_id"],
        "case_fingerprint": planned["case_fingerprint"],
        "generator_or_mutation_version": planned[
            "generator_or_mutation_version"
        ],
        "contamination_status": planned["contamination_status"],
        "exposure_status": planned["exposure_status"],
        "corpus_item_alias": planned["corpus_item_alias"],
        "replicate_index": planned["replicate_index"],
        "prompt_fingerprint": planned["prompt_fingerprint"],
        "context_fingerprint": planned["context_fingerprint"],
        "tool_schema_fingerprint": planned["tool_schema_fingerprint"],
        "sandbox_fingerprint": planned["sandbox_fingerprint"],
        "state_machine_fingerprint": planned["state_machine_fingerprint"],
        "timestamps": {
            "request_started_at": "2026-09-04T12:00:00Z",
            "response_completed_at": "2026-09-04T12:00:01Z",
        },
        "raw_response_fingerprint": "sha256:" + "a" * 64 if scorable else None,
        "scorer_id": planned["scorer_id"],
        "scorer_version": planned["scorer_version"],
        "scorer_fingerprint": planned["scorer_fingerprint"],
        "oracle_id": planned["oracle_id"],
        "oracle_version": planned["oracle_version"],
        "oracle_fingerprint": planned["oracle_fingerprint"],
        "evidence_receipt_fingerprint": "sha256:" + "b" * 64 if scorable else None,
        "usage": {
            "attribution_status": attribution_status,
            "input_tokens": 10 if attribution_status == "ATTRIBUTABLE" else None,
            "output_tokens": 5 if attribution_status == "ATTRIBUTABLE" else None,
            "total_tokens": 15 if attribution_status == "ATTRIBUTABLE" else None,
        },
        "latency": {
            "attribution_status": attribution_status,
            "milliseconds": 1000.0 if attribution_status == "ATTRIBUTABLE" else None,
        },
        "cost": {
            "attribution_status": attribution_status,
            "currency": "USD" if attribution_status == "ATTRIBUTABLE" else None,
            "amount": 0.001 if attribution_status == "ATTRIBUTABLE" else None,
            "pricing_source_fingerprint": "sha256:" + "c" * 64
            if attribution_status == "ATTRIBUTABLE"
            else None,
        },
        "provider_terminal_status": provider_terminal,
        "provider_http_status": provider_http_status,
        "terminal_status": status,
        "model_failure_value": model_failure_value,
        "system_invariant_failure_value": system_failure_value,
        "evidence_complete": evidence,
        "hard_invariant_pass": hard,
        "adjudication_status": adjudication,
        "observation_fingerprint": "sha256:" + "0" * 64,
    }
    return refingerprint(row, "observation_fingerprint")


def adjudication(
    *,
    adjudicator: str,
    decision: str | None,
    role: str = "PRIMARY",
    record_status: str = "COMPLETED",
    serial: str = "001",
) -> dict:
    evidence_complete = record_status == "COMPLETED" and decision in {"PASS", "FAIL"}
    row = {
        "schema_version": "b2-bm0-adjudication-record/v1",
        "adjudication_id": f"adj-{serial}-{adjudicator}",
        "study_id": "study-001",
        "attempt_id": "attempt-blind-001",
        "item_alias": "item-blind-001",
        "metric_id": "model_failure_rate",
        "round_role": role,
        "adjudicator_type": "HUMAN",
        "adjudicator_id": adjudicator,
        "adjudicator_configuration_fingerprint": "sha256:" + "5" * 64,
        "record_status": record_status,
        "decision": decision,
        "blind_to_model_identity": True,
        "blind_to_provider_identity": True,
        "blind_to_peer_decisions": True,
        "rubric_version": "rubric-v1",
        "rubric_fingerprint": "sha256:" + "3" * 64,
        "evidence_complete": evidence_complete,
        "conflict_status": "NONE",
        "rationale_code": "rubric-rule-001",
        "record_fingerprint": "sha256:" + "0" * 64,
    }
    return refingerprint(row, "record_fingerprint")


def adjudication_plan() -> dict:
    plan = {
        "plan_id": "adjudication-plan-001",
        "mode": "HUMAN_HUMAN",
        "metric_ids": ["model_failure_rate"],
        "primary_adjudicators": [
            {
                "adjudicator_type": "HUMAN",
                "adjudicator_id": "reviewer-a",
                "configuration_fingerprint": "sha256:" + "5" * 64,
            },
            {
                "adjudicator_type": "HUMAN",
                "adjudicator_id": "reviewer-b",
                "configuration_fingerprint": "sha256:" + "5" * 64,
            },
        ],
        "tiebreak_adjudicator": {
            "adjudicator_type": "HUMAN",
            "adjudicator_id": "reviewer-c",
            "configuration_fingerprint": "sha256:" + "5" * 64,
        },
        "rubric_version": "rubric-v1",
        "rubric_fingerprint": "sha256:" + "3" * 64,
        "plan_fingerprint": "sha256:" + "0" * 64,
    }
    return refingerprint(plan, "plan_fingerprint")


class B2BM0Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.matrix = load_json(BENCHMARK / "bm0-target-applicability.json")
        cls.registry = load_json(BENCHMARK / "bm0-metric-registry.json")
        cls.corpus = load_json(BENCHMARK / "bm0-corpus-policy.json")
        cls.candidates = load_json(
            BENCHMARK / "bm0-candidate-roster-budget.json"
        )
        cls.manifest_template = load_json(
            BENCHMARK / "bm0-benchmark-manifest.template.json"
        )
        cls.contract = load_json(BENCHMARK / "bm0-measurement-contract.json")
        cls.execution_bindings = dict(
            cls.manifest_template["artifact_fingerprints"]
        )
        cls.bound_artifacts = {
            path: (
                load_json(ROOT / path)
                if Path(path).suffix == ".json"
                else (ROOT / path).read_text(encoding="utf-8")
            )
            for path in cls.contract["artifact_bindings"]
        }

    def frozen_manifest(
        self,
        attempts: list[dict],
        *,
        comparison_classes: list[str] | None = None,
        establish_sandbox: bool = False,
    ) -> dict:
        manifest = copy.deepcopy(self.manifest_template)
        manifest.update(
            {
                "manifest_id": "B2-BM0-FROZEN-TEST-001",
                "study_state": "FROZEN",
                "provider_roster_status": "SELECTED",
                "corpus_commitment_status": "SEALED",
                "corpus_aggregate_commitment": "sha256:" + "a" * 64,
                "adjudication_mode": "HUMAN_HUMAN",
                "adjudication_plan": adjudication_plan(),
                "planned_attempts": attempts,
                "planned_attempt_count": len(attempts),
            }
        )
        manifest["stop_rule"]["planned_attempt_count"] = len(attempts)
        manifest["corpus_aggregate_commitment"] = corpus_aggregate_commitment_v1(
            attempts
        )
        if comparison_classes is not None:
            manifest["comparison_classes"] = comparison_classes
        if establish_sandbox:
            manifest["sandbox_equivalence"] = {
                "status": "ESTABLISHED",
                "evidence_refs": [
                    {
                        "evidence_type": evidence_type,
                        "evidence_id": f"sandbox-evidence-{index:03d}",
                        "evidence_fingerprint": "sha256:" + hex_digit * 64,
                    }
                    for index, (evidence_type, hex_digit) in enumerate(
                        (
                            ("SANDBOX_IMAGE", "4"),
                            ("TOOL_SURFACE", "6"),
                            ("BUDGET_RETRY", "7"),
                            ("NETWORK_CREDENTIAL_POLICY", "8"),
                            ("INDEPENDENT_EQUIVALENCE_RECEIPT", "9"),
                        ),
                        start=1,
                    )
                ],
            }
        model_bindings = {
            (
                attempt["provider_subject_id"],
                attempt["model_subject_id"],
                attempt["requested_model_id"],
            )
            for attempt in attempts
            if attempt["target_class"] != "SYSTEM_EVAL_ONLY"
        }
        if not model_bindings:
            model_bindings = {("provider-model-a", "model-a", "model-a")}
        capability_by_subject_entry = {
            (attempt["model_subject_id"], attempt["entry_id"]): attempt[
                "capability_mode"
            ]
            for attempt in attempts
            if attempt["target_class"] != "SYSTEM_EVAL_ONLY"
        }
        manifest["model_applicability"] = []
        for provider_id, model_id, requested_model_id in sorted(model_bindings):
            for lineage in CANONICAL_FAMILY_LINEAGE:
                system_only = lineage["target_class"] == "SYSTEM_EVAL_ONLY"
                if system_only:
                    applicability_result = "NOT_APPLICABLE"
                    comparison_result = "NOT_APPLICABLE"
                    reason_code = "SYSTEM_EVAL_ONLY_NO_MODEL_TRIAL"
                else:
                    applicability_result = "APPLICABLE"
                    reason_code = "DECLARED_CAPABILITY_SUPPORTED"
                    if lineage["target_class"] == "AGENT_STANDARDIZED":
                        comparison_result = (
                            "COMPARABLE_AFTER_SANDBOX_EQUIVALENCE"
                            if establish_sandbox
                            else "COMPARABILITY_LIMIT"
                        )
                    else:
                        comparison_result = "DEFAULT_COMPARABLE"
                row = {
                    "provider_subject_id": provider_id,
                    "model_subject_id": model_id,
                    "requested_model_id": requested_model_id,
                    "entry_id": lineage["entry_id"],
                    "target_id": lineage["target_id"],
                    "family_id": lineage["family_id"],
                    "target_class": lineage["target_class"],
                    "capability_mode": (
                        "SYSTEM_EVAL"
                        if system_only
                        else capability_by_subject_entry.get(
                            (model_id, lineage["entry_id"]), "TEXT_ONLY"
                        )
                    ),
                    "applicability_result": applicability_result,
                    "comparison_result": comparison_result,
                    "reason_code": reason_code,
                    "evidence_fingerprint": sha256_json(
                        {
                            "model_subject_id": model_id,
                            "entry_id": lineage["entry_id"],
                            "applicability_result": applicability_result,
                        }
                    ),
                    "declared_before_execution": True,
                }
                manifest["model_applicability"].append(row)
        return refingerprint(manifest, "manifest_fingerprint")

    def computed_receipt(self) -> dict:
        return build_bm0_receipt(
            contract=self.contract,
            target_matrix=self.matrix,
            metric_registry=self.registry,
            corpus_policy=self.corpus,
            manifest_template=self.manifest_template,
            bound_artifacts=self.bound_artifacts,
        )

    def test_measurement_contract_and_all_bound_artifacts_validate(self):
        checked = validate_measurement_contract(
            self.contract, bound_artifacts=self.bound_artifacts
        )
        self.assertEqual(checked["implementation_base_sha"], IMPLEMENTATION_BASE_SHA)
        self.assertEqual(
            set(checked["artifact_bindings"]), set(BOUND_ARTIFACT_PATHS)
        )

    def test_target_matrix_has_exact_16_entry_partition(self):
        checked = validate_target_matrix(self.matrix)
        counts = {
            target_class: sum(
                target["target_class"] == target_class
                for target in checked["targets"]
            )
            for target_class in TARGET_CLASSES
        }
        self.assertEqual(len(checked["targets"]), 16)
        self.assertEqual(counts, EXPECTED_TARGET_CLASS_COUNTS)
        self.assertEqual(
            tuple(checked["default_comparable_classes"]),
            DEFAULT_COMPARABLE_CLASSES,
        )

    def test_matrix_semantic_tamper_fails_even_after_refingerprint(self):
        tampered = copy.deepcopy(self.matrix)
        tampered["targets"][0]["target_class"] = "SYSTEM_EVAL_ONLY"
        tampered = refingerprint(tampered, "matrix_fingerprint")
        with self.assertRaises(ValueError):
            validate_target_matrix(tampered)

    def test_canonical_lineage_binds_all_16_entries_and_32_source_cases(self):
        receipt = validate_canonical_family_lineage_v1(
            self.matrix,
            bound_artifacts=self.bound_artifacts,
        )
        self.assertEqual(receipt["entry_count"], 16)
        self.assertEqual(receipt["unique_family_lineage_count"], 16)
        self.assertEqual(receipt["canonical_case_count"], 32)
        self.assertEqual(
            receipt["source_artifact_count"],
            len(CANONICAL_SOURCE_ARTIFACT_PATHS),
        )
        self.assertEqual(
            [target["entry_id"] for target in self.matrix["targets"]],
            [lineage["entry_id"] for lineage in CANONICAL_FAMILY_LINEAGE],
        )

    def test_canonical_lineage_rejects_substitution_and_source_receipt_drift(self):
        substituted = copy.deepcopy(self.matrix)
        substituted["targets"][0]["family_id"] = "generic-reasoning"
        substituted = refingerprint(substituted, "matrix_fingerprint")
        with self.assertRaises(ValueError):
            validate_target_matrix(substituted)

        source_path = "cases/b2/public-safe/qa0-fixtures.json"
        drifted_bound = copy.deepcopy(self.bound_artifacts)
        drifted_bound[source_path]["cases"][0]["variant"] = "KNOWN_BAD"
        with self.assertRaises(ValueError):
            validate_canonical_family_lineage_v1(
                self.matrix,
                bound_artifacts=drifted_bound,
            )

    def test_metric_registry_freezes_failure_denominator(self):
        checked = validate_bm0_metric_registry(self.registry)
        self.assertEqual(
            {metric["metric_id"] for metric in checked["metrics"]},
            EXPECTED_METRIC_IDS,
        )
        metric = next(
            metric
            for metric in checked["metrics"]
            if metric["metric_id"] == "model_failure_rate"
        )
        self.assertEqual(metric["numerator_statuses"], ["FAIL"])
        self.assertEqual(metric["denominator_statuses"], ["PASS", "FAIL"])
        self.assertEqual(
            set(metric["excluded_terminal_statuses"]),
            set(NON_MODEL_SCORABLE_TERMINALS),
        )
        self.assertEqual(
            metric["applicability_filter"],
            "APPLICABLE_MODEL_PROVIDER_ONLY",
        )
        self.assertEqual(
            metric["weighting"],
            METRIC_WEIGHTING_RULES["model_failure_rate"],
        )

        tampered = copy.deepcopy(self.registry)
        model_metric = next(
            metric
            for metric in tampered["metrics"]
            if metric["metric_id"] == "model_failure_rate"
        )
        model_metric["numerator_statuses"] = ["FAIL", "ERROR"]
        tampered = refingerprint(tampered, "registry_fingerprint")
        with self.assertRaises(ValueError):
            validate_bm0_metric_registry(tampered)

        system_metric = next(
            metric
            for metric in checked["metrics"]
            if metric["metric_id"] == "system_invariant_failure_rate"
        )
        self.assertEqual(
            system_metric["zero_denominator_semantics"],
            "NOT_EVALUABLE/ZERO_SYSTEM_SCORABLE_DENOMINATOR",
        )

        diagnostic_tamper = copy.deepcopy(self.registry)
        diagnostic = next(
            metric
            for metric in diagnostic_tamper["metrics"]
            if metric["metric_id"] == "non_scorable_attempt_rate"
        )
        diagnostic["estimate_method_id"] = "BM0-SAP-04-MODEL-FAILURE-DENOMINATOR-V1"
        diagnostic_tamper = refingerprint(
            diagnostic_tamper, "registry_fingerprint"
        )
        with self.assertRaises(ValueError):
            validate_bm0_metric_registry(diagnostic_tamper)

        weighting_tamper = copy.deepcopy(self.registry)
        weighted = next(
            metric
            for metric in weighting_tamper["metrics"]
            if metric["metric_id"] == "family_conditional_failure_rate"
        )
        weighted["weighting"]["across_cases"] = (
            "WEIGHT_BY_NUMBER_OF_REPLICATES"
        )
        weighting_tamper = refingerprint(
            weighting_tamper, "registry_fingerprint"
        )
        with self.assertRaises(ValueError):
            validate_bm0_metric_registry(weighting_tamper)

    def test_candidate_roster_and_budget_are_estimate_only_and_executable(self):
        checked = validate_candidate_roster_budget(self.candidates)
        self.assertEqual(checked["roster_label"], "CANDIDATE")
        self.assertEqual(checked["provider_roster_status"], "NOT_SELECTED")
        self.assertEqual(checked["budget_label"], "ESTIMATE_ONLY")
        self.assertEqual(len(checked["candidates"]), 3)
        self.assertFalse(checked["budget_model"]["spending_authority"])
        self.assertEqual(
            checked["budget_model"]["aggregate_estimated_token_cost_usd"],
            8.592,
        )

        selected = copy.deepcopy(self.candidates)
        selected["candidates"][0]["selection_status"] = "SELECTED"
        selected = refingerprint(selected, "artifact_fingerprint")
        with self.assertRaises(ValueError):
            validate_candidate_roster_budget(selected)

        stale_cost = copy.deepcopy(self.candidates)
        stale_cost["budget_model"]["candidate_estimates"][0][
            "estimated_token_cost_usd"
        ] = 0.01
        stale_cost = refingerprint(stale_cost, "artifact_fingerprint")
        with self.assertRaises(ValueError):
            validate_candidate_roster_budget(stale_cost)

    def test_manifest_template_stays_design_only_and_unselected(self):
        checked = validate_benchmark_manifest(self.manifest_template)
        self.assertEqual(checked["study_state"], "DESIGN_ONLY")
        self.assertEqual(checked["provider_roster_status"], "NOT_SELECTED")
        self.assertEqual(checked["corpus_commitment_status"], "NOT_COMMITTED")
        self.assertIsNone(checked["corpus_aggregate_commitment"])
        self.assertEqual(checked["adjudication_mode"], "NOT_SELECTED")
        self.assertEqual(checked["planned_attempt_count"], 0)
        authority = checked["hidden_holdout_authority"]
        self.assertEqual(authority["binding_status"], "BOUND")
        self.assertEqual(
            authority["authority_type"], "NOT_IN_PUBLIC_REPO_DECLARATION"
        )
        self.assertEqual(authority["authority_id"], HIDDEN_HOLDOUT_DECLARATION_ID)
        self.assertEqual(
            authority["authority_fingerprint"],
            sha256_json(HIDDEN_HOLDOUT_DECLARATION),
        )

    def test_hidden_holdout_authority_binding_fails_closed(self):
        unbound = copy.deepcopy(self.manifest_template)
        unbound["hidden_holdout_authority"]["binding_status"] = "UNBOUND"
        unbound = refingerprint(unbound, "manifest_fingerprint")
        with self.assertRaises(ValueError):
            validate_benchmark_manifest(unbound)

        invented_declaration = copy.deepcopy(self.manifest_template)
        invented_declaration["hidden_holdout_authority"]["authority_id"] = (
            "invented-public-locator"
        )
        invented_declaration = refingerprint(
            invented_declaration, "manifest_fingerprint"
        )
        with self.assertRaises(ValueError):
            validate_benchmark_manifest(invented_declaration)

    def test_design_template_cannot_smuggle_roster_or_attempts(self):
        selected = copy.deepcopy(self.manifest_template)
        selected["provider_roster_status"] = "SELECTED"
        selected = refingerprint(selected, "manifest_fingerprint")
        with self.assertRaises(ValueError):
            validate_benchmark_manifest(selected)

        attempted = copy.deepcopy(self.manifest_template)
        attempted["planned_attempts"] = [identity()]
        attempted["planned_attempt_count"] = 1
        attempted["stop_rule"]["planned_attempt_count"] = 1
        attempted = refingerprint(attempted, "manifest_fingerprint")
        with self.assertRaises(ValueError):
            validate_benchmark_manifest(attempted)

        unsealed = self.frozen_manifest([identity()])
        unsealed["corpus_aggregate_commitment"] = None
        unsealed = refingerprint(unsealed, "manifest_fingerprint")
        with self.assertRaises(ValueError):
            validate_benchmark_manifest(
                unsealed,
                expected_artifact_fingerprints=self.execution_bindings,
            )

        false_seal = self.frozen_manifest([identity()])
        false_seal["corpus_aggregate_commitment"] = "sha256:" + "f" * 64
        false_seal = refingerprint(false_seal, "manifest_fingerprint")
        with self.assertRaises(ValueError):
            validate_benchmark_manifest(
                false_seal,
                expected_artifact_fingerprints=self.execution_bindings,
            )

    def test_frozen_manifest_requires_independent_bindings_and_hidden_holdout(self):
        manifest = self.frozen_manifest([identity()])
        with self.assertRaises(ValueError):
            validate_benchmark_manifest(manifest)

        tampered = copy.deepcopy(manifest)
        tampered["artifact_fingerprints"]["analysis_plan"] = (
            "sha256:" + "f" * 64
        )
        tampered = refingerprint(tampered, "manifest_fingerprint")
        with self.assertRaises(ValueError):
            validate_benchmark_manifest(
                tampered,
                expected_artifact_fingerprints=self.execution_bindings,
            )

        public_attempt = identity(item="public-control-item")
        public_attempt["corpus_pool_id"] = "CONTROL"
        public_attempt["exposure_status"] = "PUBLICLY_DISCLOSED_CONTROL"
        public_only = self.frozen_manifest([public_attempt])
        with self.assertRaises(ValueError):
            validate_benchmark_manifest(
                public_only,
                expected_artifact_fingerprints=self.execution_bindings,
            )

    def test_frozen_manifest_requires_complete_per_model_applicability_grid(self):
        attempt = identity()
        manifest = self.frozen_manifest([attempt])
        checked = validate_benchmark_manifest(
            manifest,
            expected_artifact_fingerprints=self.execution_bindings,
        )
        declarations = checked["model_applicability"]
        self.assertEqual(len(declarations), 16)
        self.assertEqual(
            sum(
                row["applicability_result"] == "NOT_APPLICABLE"
                for row in declarations
            ),
            4,
        )
        self.assertTrue(
            all(
                row["comparison_result"] == "NOT_APPLICABLE"
                for row in declarations
                if row["applicability_result"] == "NOT_APPLICABLE"
            )
        )

        incomplete = copy.deepcopy(manifest)
        incomplete["model_applicability"].pop()
        incomplete = refingerprint(incomplete, "manifest_fingerprint")
        with self.assertRaises(ValueError):
            validate_benchmark_manifest(
                incomplete,
                expected_artifact_fingerprints=self.execution_bindings,
            )

        hidden_zero = copy.deepcopy(manifest)
        planned_row = next(
            row
            for row in hidden_zero["model_applicability"]
            if row["entry_id"] == attempt["entry_id"]
        )
        planned_row.update(
            {
                "applicability_result": "NOT_APPLICABLE",
                "comparison_result": "NOT_APPLICABLE",
                "reason_code": "PROVIDER_CAPABILITY_UNAVAILABLE",
            }
        )
        hidden_zero = refingerprint(hidden_zero, "manifest_fingerprint")
        with self.assertRaises(ValueError):
            validate_benchmark_manifest(
                hidden_zero,
                expected_artifact_fingerprints=self.execution_bindings,
            )

        system_as_applicable = copy.deepcopy(manifest)
        system_row = next(
            row
            for row in system_as_applicable["model_applicability"]
            if row["target_class"] == "SYSTEM_EVAL_ONLY"
        )
        system_row.update(
            {
                "applicability_result": "APPLICABLE",
                "comparison_result": "DEFAULT_COMPARABLE",
                "reason_code": "DECLARED_CAPABILITY_SUPPORTED",
            }
        )
        system_as_applicable = refingerprint(
            system_as_applicable, "manifest_fingerprint"
        )
        with self.assertRaises(ValueError):
            validate_benchmark_manifest(
                system_as_applicable,
                expected_artifact_fingerprints=self.execution_bindings,
            )

    def test_agent_comparison_requires_sandbox_equivalence_evidence(self):
        agent_attempt = identity(
            target_class="AGENT_STANDARDIZED", model="agent-a", serial="agent-001"
        )
        classes = [*DEFAULT_COMPARABLE_CLASSES, "AGENT_STANDARDIZED"]
        no_evidence = self.frozen_manifest(
            [agent_attempt], comparison_classes=classes
        )
        with self.assertRaises(ValueError):
            validate_benchmark_manifest(
                no_evidence,
                expected_artifact_fingerprints=self.execution_bindings,
            )

        with_evidence = self.frozen_manifest(
            [agent_attempt],
            comparison_classes=classes,
            establish_sandbox=True,
        )
        checked = validate_benchmark_manifest(
            with_evidence,
            expected_artifact_fingerprints=self.execution_bindings,
        )
        self.assertEqual(checked["sandbox_equivalence"]["status"], "ESTABLISHED")

        incomplete_evidence = copy.deepcopy(with_evidence)
        incomplete_evidence["sandbox_equivalence"]["evidence_refs"].pop()
        incomplete_evidence = refingerprint(
            incomplete_evidence, "manifest_fingerprint"
        )
        with self.assertRaises(ValueError):
            validate_benchmark_manifest(
                incomplete_evidence,
                expected_artifact_fingerprints=self.execution_bindings,
            )

    def test_frozen_adjudication_mode_requires_matching_composition(self):
        manifest = self.frozen_manifest([identity()])
        manifest["adjudication_mode"] = "HUMAN_JUDGE"
        manifest["adjudication_plan"]["mode"] = "HUMAN_JUDGE"
        manifest["adjudication_plan"] = refingerprint(
            manifest["adjudication_plan"], "plan_fingerprint"
        )
        manifest = refingerprint(manifest, "manifest_fingerprint")
        with self.assertRaises(ValueError):
            validate_benchmark_manifest(
                manifest,
                expected_artifact_fingerprints=self.execution_bindings,
            )

    def test_system_eval_only_never_enters_model_comparison(self):
        system_attempt = identity(
            target_class="SYSTEM_EVAL_ONLY", model="system-a", serial="system-001"
        )
        classes = [*DEFAULT_COMPARABLE_CLASSES, "SYSTEM_EVAL_ONLY"]
        manifest = self.frozen_manifest(
            [system_attempt], comparison_classes=classes
        )
        with self.assertRaises(ValueError):
            validate_benchmark_manifest(
                manifest,
                expected_artifact_fingerprints=self.execution_bindings,
            )

    def test_system_attempts_are_scheduled_without_model_attribution(self):
        attempts = [
            identity(
                target_class="SYSTEM_EVAL_ONLY",
                model="system",
                serial=f"system-{index:03d}",
                item=f"system-item-{index:03d}",
            )
            for index in range(3)
        ]
        manifest = self.frozen_manifest(attempts)
        validate_benchmark_manifest(
            manifest,
            expected_artifact_fingerprints=self.execution_bindings,
        )
        rows = [
            observation(attempt, status)
            for attempt, status in zip(attempts, ("PASS", "FAIL", "ERROR"))
        ]
        result = system_invariant_failure_rate_v1(
            manifest,
            rows,
            expected_artifact_fingerprints=self.execution_bindings,
        )
        self.assertEqual(result["terminal_status"], "PASS")
        self.assertEqual(result["failure_count"], 1)
        self.assertEqual(result["system_scorable_denominator"], 2)
        self.assertEqual(result["failure_rate"], 0.5)
        self.assertTrue(all(row["model_failure_value"] is None for row in rows))
        self.assertFalse(result["model_attribution_emitted"])
        self.assertFalse(result["ranking_emitted"])

        attributed = copy.deepcopy(attempts[0])
        attributed["model_subject_id"] = "model-a"
        with self.assertRaises(ValueError):
            validate_trial_identity(attributed)

    def test_trial_identity_rejects_moving_snapshot_and_class_mismatch(self):
        for alias in ("latest", "LATEST", "latest "):
            with self.subTest(alias=alias):
                moving = identity()
                moving["model_snapshot_id"] = alias
                with self.assertRaises(ValueError):
                    validate_trial_identity(moving)

        mismatch = identity()
        mismatch["target_class"] = "SYSTEM_EVAL_ONLY"
        with self.assertRaises(ValueError):
            validate_trial_identity(mismatch)

        invalid_pool = identity()
        invalid_pool["corpus_pool_id"] = "UNDECLARED_POOL"
        with self.assertRaises(ValueError):
            validate_trial_identity(invalid_pool)

        self_parent = identity()
        self_parent["parent_attempt_id"] = self_parent["attempt_id"]
        with self.assertRaises(ValueError):
            validate_trial_identity(self_parent)

        model_na = identity()
        model_na["applicability_result"] = "NOT_APPLICABLE"
        with self.assertRaises(ValueError):
            validate_trial_identity(model_na)

        system_applicable = identity(target_class="SYSTEM_EVAL_ONLY")
        system_applicable["applicability_result"] = "APPLICABLE"
        with self.assertRaises(ValueError):
            validate_trial_identity(system_applicable)

        observed = observation(identity(), "PASS")
        observed["applicability_result"] = "NOT_APPLICABLE"
        observed = refingerprint(observed, "observation_fingerprint")
        with self.assertRaises(ValueError):
            validate_observation(observed)

    def test_trial_identity_binds_case_lineage_contamination_and_exposure(self):
        checked = validate_trial_identity(identity())
        self.assertEqual(checked["contract_version"], "v0.2")
        self.assertEqual(checked["contamination_status"], "ASSESSED_CLEAR")
        self.assertEqual(
            checked["exposure_status"],
            "PRIVATE_UNEXPOSED_BEFORE_MANIFEST_FREEZE",
        )

        wrong_lane = identity()
        wrong_lane["exposure_status"] = "PUBLICLY_DISCLOSED_CONTROL"
        with self.assertRaises(ValueError):
            validate_trial_identity(wrong_lane)

        contaminated_hidden = identity()
        contaminated_hidden["contamination_status"] = "KNOWN_EXPOSED"
        with self.assertRaises(ValueError):
            validate_trial_identity(contaminated_hidden)

        missing_lineage = identity()
        missing_lineage.pop("mechanism_lineage_id")
        with self.assertRaises(ValueError):
            validate_trial_identity(missing_lineage)

    def test_manifest_retry_chain_is_predeclared_identity_stable_and_nonbranching(self):
        root = identity(serial="retry-root")
        child = copy.deepcopy(root)
        child["attempt_id"] = "attempt-model-a-retry-child"
        child["parent_attempt_id"] = root["attempt_id"]
        manifest = self.frozen_manifest([root, child])
        validate_benchmark_manifest(
            manifest,
            expected_artifact_fingerprints=self.execution_bindings,
        )

        orphan = copy.deepcopy(child)
        orphan["parent_attempt_id"] = "attempt-missing-parent"
        with self.assertRaises(ValueError):
            validate_benchmark_manifest(
                self.frozen_manifest([root, orphan]),
                expected_artifact_fingerprints=self.execution_bindings,
            )

        drifted = copy.deepcopy(child)
        drifted["model_snapshot_id"] = "snapshot-model-a-different"
        with self.assertRaises(ValueError):
            validate_benchmark_manifest(
                self.frozen_manifest([root, drifted]),
                expected_artifact_fingerprints=self.execution_bindings,
            )

        sibling = copy.deepcopy(child)
        sibling["attempt_id"] = "attempt-model-a-retry-sibling"
        with self.assertRaises(ValueError):
            validate_benchmark_manifest(
                self.frozen_manifest([root, child, sibling]),
                expected_artifact_fingerprints=self.execution_bindings,
            )

        mixed_study = identity(serial="other-study")
        mixed_study["study_id"] = "study-002"
        with self.assertRaises(ValueError):
            validate_benchmark_manifest(
                self.frozen_manifest([root, mixed_study]),
                expected_artifact_fingerprints=self.execution_bindings,
            )

        snapshot_drift = identity(serial="snapshot-drift", item="item-002")
        snapshot_drift["model_snapshot_id"] = "snapshot-model-a-20260905"
        with self.assertRaises(ValueError):
            validate_benchmark_manifest(
                self.frozen_manifest([root, snapshot_drift]),
                expected_artifact_fingerprints=self.execution_bindings,
            )

    def test_fixed_attempt_stop_is_outcome_blind(self):
        attempts = [identity(serial="001"), identity(serial="002", item="item-002")]
        manifest = self.frozen_manifest(attempts)
        events = [
            {"attempt_id": attempt["attempt_id"], "recorded": True}
            for attempt in attempts
        ]
        result = fixed_attempt_stop_v1(
            manifest,
            events,
            expected_artifact_fingerprints=self.execution_bindings,
        )
        self.assertEqual(result["decision"], "STOP")
        self.assertEqual(result["outcome_fields_observed"], [])

        leaking = copy.deepcopy(events)
        leaking[0]["terminal_status"] = "PASS"
        with self.assertRaises(ValueError):
            fixed_attempt_stop_v1(
                manifest,
                leaking,
                expected_artifact_fingerprints=self.execution_bindings,
            )

        score_leak = copy.deepcopy(events)
        score_leak[0]["score"] = 1
        with self.assertRaises(ValueError):
            fixed_attempt_stop_v1(
                manifest,
                score_leak,
                expected_artifact_fingerprints=self.execution_bindings,
            )

    def test_fixed_attempt_stop_continues_until_every_identity_is_recorded(self):
        attempts = [identity(serial="001"), identity(serial="002", item="item-002")]
        manifest = self.frozen_manifest(attempts)
        result = fixed_attempt_stop_v1(
            manifest,
            [{"attempt_id": attempts[0]["attempt_id"], "recorded": True}],
            expected_artifact_fingerprints=self.execution_bindings,
        )
        self.assertEqual(result["decision"], "CONTINUE")
        self.assertEqual(result["missing_attempt_ids"], [attempts[1]["attempt_id"]])

    def test_executable_methods_reject_manifest_artifact_drift(self):
        attempt = identity(serial="001")
        manifest = self.frozen_manifest([attempt])
        manifest["artifact_fingerprints"]["analysis_plan"] = (
            "sha256:" + "9" * 64
        )
        manifest = refingerprint(manifest, "manifest_fingerprint")
        with self.assertRaises(ValueError):
            fixed_attempt_stop_v1(
                manifest,
                [{"attempt_id": attempt["attempt_id"], "recorded": True}],
                expected_artifact_fingerprints=self.execution_bindings,
            )

    def test_observation_semantics_reject_failure_coercion(self):
        attempt = identity()
        error = observation(attempt, "ERROR")
        error["model_failure_value"] = 1
        error = refingerprint(error, "observation_fingerprint")
        with self.assertRaises(ValueError):
            validate_observation(error)

        unknown = observation(attempt, "UNKNOWN")
        unknown["evidence_complete"] = True
        unknown = refingerprint(unknown, "observation_fingerprint")
        with self.assertRaises(ValueError):
            validate_observation(unknown)

        unknown_with_resolved_identity = observation(attempt, "ERROR")
        unknown_with_resolved_identity["resolved_model_or_version_id"] = (
            "unverified-fallback-snapshot"
        )
        unknown_with_resolved_identity = refingerprint(
            unknown_with_resolved_identity, "observation_fingerprint"
        )
        with self.assertRaises(ValueError):
            validate_observation(unknown_with_resolved_identity)

    def test_scorable_observation_allows_unavailable_accounting_but_not_unknown_identity(self):
        attempt = identity()
        manifest = self.frozen_manifest([attempt])
        row = observation(attempt, "PASS")
        row["usage"] = {
            "attribution_status": "UNAVAILABLE",
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
        }
        row["latency"] = {
            "attribution_status": "UNAVAILABLE",
            "milliseconds": None,
        }
        row["cost"] = {
            "attribution_status": "UNAVAILABLE",
            "currency": None,
            "amount": None,
            "pricing_source_fingerprint": None,
        }
        row = refingerprint(row, "observation_fingerprint")
        self.assertEqual(validate_observation(row), row)
        result = model_failure_denominator_v1(
            manifest,
            [row],
            expected_artifact_fingerprints=self.execution_bindings,
        )
        self.assertEqual(result["by_model"]["model-a"]["failure_rate"], 0.0)

        unknown_identity = copy.deepcopy(row)
        unknown_identity["identity_certainty"] = "UNKNOWN"
        unknown_identity["resolved_model_or_version_id"] = None
        unknown_identity = refingerprint(
            unknown_identity, "observation_fingerprint"
        )
        with self.assertRaises(ValueError):
            validate_observation(unknown_identity)

        inapplicable_accounting = copy.deepcopy(row)
        inapplicable_accounting["cost"]["attribution_status"] = "NOT_APPLICABLE"
        inapplicable_accounting = refingerprint(
            inapplicable_accounting, "observation_fingerprint"
        )
        with self.assertRaises(ValueError):
            validate_observation(inapplicable_accounting)

    def test_observation_grid_rejects_substitution_duplicate_and_unplanned_rows(self):
        attempts = [identity(serial="001"), identity(serial="002", item="item-002")]
        manifest = self.frozen_manifest(attempts)
        first = observation(attempts[0], "PASS")

        substituted = copy.deepcopy(first)
        substituted["model_subject_id"] = "model-substitute"
        substituted = refingerprint(substituted, "observation_fingerprint")
        with self.assertRaises(ValueError):
            validate_observation_grid_v1(
                manifest,
                [substituted],
                expected_artifact_fingerprints=self.execution_bindings,
            )

        silent_fallback = copy.deepcopy(first)
        silent_fallback["resolved_model_or_version_id"] = "fallback-snapshot"
        silent_fallback = refingerprint(
            silent_fallback, "observation_fingerprint"
        )
        with self.assertRaises(ValueError):
            validate_observation_grid_v1(
                manifest,
                [silent_fallback],
                expected_artifact_fingerprints=self.execution_bindings,
            )

        failed_fallback = observation(attempts[0], "ERROR")
        failed_fallback["identity_certainty"] = "EXACT"
        failed_fallback["resolved_model_or_version_id"] = "fallback-snapshot"
        failed_fallback = refingerprint(
            failed_fallback, "observation_fingerprint"
        )
        with self.assertRaises(ValueError):
            validate_observation_grid_v1(
                manifest,
                [failed_fallback],
                expected_artifact_fingerprints=self.execution_bindings,
            )

        unknown_limitation_drift = observation(attempts[0], "ERROR")
        unknown_limitation_drift["alias_limitation"] = (
            "UNVERIFIABLE_ALIAS_DISCLOSED"
        )
        unknown_limitation_drift = refingerprint(
            unknown_limitation_drift, "observation_fingerprint"
        )
        with self.assertRaises(ValueError):
            validate_observation_grid_v1(
                manifest,
                [unknown_limitation_drift],
                expected_artifact_fingerprints=self.execution_bindings,
            )

        scorer_drift = copy.deepcopy(first)
        scorer_drift["scorer_fingerprint"] = "sha256:" + "d" * 64
        scorer_drift = refingerprint(scorer_drift, "observation_fingerprint")
        with self.assertRaises(ValueError):
            validate_observation_grid_v1(
                manifest,
                [scorer_drift],
                expected_artifact_fingerprints=self.execution_bindings,
            )

        case_drift = copy.deepcopy(first)
        case_drift["case_fingerprint"] = "sha256:" + "e" * 64
        case_drift = refingerprint(case_drift, "observation_fingerprint")
        with self.assertRaises(ValueError):
            validate_observation_grid_v1(
                manifest,
                [case_drift],
                expected_artifact_fingerprints=self.execution_bindings,
            )

        with self.assertRaises(ValueError):
            validate_observation_grid_v1(
                manifest,
                [first, first],
                expected_artifact_fingerprints=self.execution_bindings,
            )

        alien = identity(model="model-alien", serial="alien-001")
        with self.assertRaises(ValueError):
            validate_observation_grid_v1(
                manifest,
                [observation(alien, "PASS")],
                expected_artifact_fingerprints=self.execution_bindings,
            )

    def test_model_failure_rate_excludes_error_unknown_blocked_and_not_evaluable(self):
        statuses = [
            "PASS",
            "FAIL",
            "ERROR",
            "UNKNOWN",
            "BLOCKED",
            "NOT_EVALUABLE",
        ]
        attempts = [
            identity(serial=f"{index:03d}", item=f"item-{index:03d}")
            for index in range(len(statuses))
        ]
        manifest = self.frozen_manifest(attempts)
        rows = [observation(attempt, status) for attempt, status in zip(attempts, statuses)]
        result = model_failure_denominator_v1(
            manifest,
            rows,
            expected_artifact_fingerprints=self.execution_bindings,
        )
        model = result["by_model"]["model-a"]
        self.assertEqual(result["terminal_status"], "PASS")
        self.assertEqual(model["failure_count"], 1)
        self.assertEqual(model["model_scorable_denominator"], 2)
        self.assertEqual(model["failure_rate"], 0.5)
        self.assertEqual(model["excluded_terminal_counts"], {
            "NOT_EVALUABLE": 1,
            "BLOCKED": 1,
            "ERROR": 1,
            "UNKNOWN": 1,
        })

    def test_zero_denominator_is_not_evaluable(self):
        attempts = [identity(serial="001"), identity(serial="002", item="item-002")]
        manifest = self.frozen_manifest(attempts)
        rows = [observation(attempts[0], "ERROR"), observation(attempts[1], "UNKNOWN")]
        result = model_failure_denominator_v1(
            manifest,
            rows,
            expected_artifact_fingerprints=self.execution_bindings,
        )
        model = result["by_model"]["model-a"]
        self.assertEqual(result["terminal_status"], "NOT_EVALUABLE")
        self.assertEqual(model["model_scorable_denominator"], 0)
        self.assertEqual(model["reason"], "ZERO_MODEL_SCORABLE_DENOMINATOR")
        self.assertIsNone(model["failure_rate"])
        self.assertEqual(model["wilson_95"]["reason"], "ZERO_DENOMINATOR")
        self.assertIsNone(model["wilson_95"]["lower"])
        self.assertIsNone(model["wilson_95"]["upper"])

    def test_system_zero_denominator_uses_system_only_semantics(self):
        attempt = identity(
            target_class="SYSTEM_EVAL_ONLY",
            model="system",
            serial="system-error",
        )
        manifest = self.frozen_manifest([attempt])
        result = system_invariant_failure_rate_v1(
            manifest,
            [observation(attempt, "ERROR")],
            expected_artifact_fingerprints=self.execution_bindings,
        )
        self.assertEqual(result["terminal_status"], "NOT_EVALUABLE")
        self.assertEqual(result["reason"], "ZERO_SYSTEM_SCORABLE_DENOMINATOR")
        self.assertEqual(result["wilson_95"]["reason"], "ZERO_DENOMINATOR")
        self.assertFalse(result["model_attribution_emitted"])

    def test_missing_system_observation_suppresses_partial_rate(self):
        attempts = [
            identity(
                target_class="SYSTEM_EVAL_ONLY",
                model="system",
                serial=f"system-{index:03d}",
                item=f"system-item-{index:03d}",
            )
            for index in range(2)
        ]
        manifest = self.frozen_manifest(attempts)
        result = system_invariant_failure_rate_v1(
            manifest,
            [observation(attempts[0], "PASS")],
            expected_artifact_fingerprints=self.execution_bindings,
        )
        self.assertEqual(result["terminal_status"], "NOT_EVALUABLE")
        self.assertEqual(result["reason"], "MISSING_PLANNED_SYSTEM_OBSERVATIONS")
        self.assertEqual(result["missing_attempt_ids"], [attempts[1]["attempt_id"]])
        self.assertIsNone(result["failure_count"])
        self.assertIsNone(result["system_scorable_denominator"])
        self.assertIsNone(result["failure_rate"])
        self.assertIsNone(result["excluded_terminal_counts"])
        self.assertEqual(
            result["wilson_95"]["reason"],
            "MISSING_PLANNED_SYSTEM_OBSERVATIONS",
        )

    def test_missing_planned_observation_fails_closed(self):
        attempts = [identity(serial="001"), identity(serial="002", item="item-002")]
        manifest = self.frozen_manifest(attempts)
        result = model_failure_denominator_v1(
            manifest,
            [observation(attempts[0], "PASS")],
            expected_artifact_fingerprints=self.execution_bindings,
        )
        self.assertEqual(result["terminal_status"], "NOT_EVALUABLE")
        self.assertEqual(result["reason"], "MISSING_PLANNED_OBSERVATIONS")
        self.assertEqual(result["missing_attempt_ids"], [attempts[1]["attempt_id"]])
        model = result["by_model"]["model-a"]
        self.assertIsNone(model["failure_count"])
        self.assertIsNone(model["model_scorable_denominator"])
        self.assertIsNone(model["failure_rate"])
        self.assertIsNone(model["excluded_terminal_counts"])
        self.assertEqual(
            model["wilson_95"]["reason"], "MISSING_PLANNED_OBSERVATIONS"
        )
        self.assertIsNone(model["wilson_95"]["lower"])
        self.assertIsNone(model["wilson_95"]["upper"])
        self.assertFalse(result["ranking_emitted"])

    def test_model_denominator_ignores_missing_system_only_observation(self):
        model_attempt = identity(serial="model-001")
        system_attempt = identity(
            target_class="SYSTEM_EVAL_ONLY",
            model="system",
            serial="system-001",
            item="system-item-001",
        )
        manifest = self.frozen_manifest([model_attempt, system_attempt])
        result = model_failure_denominator_v1(
            manifest,
            [observation(model_attempt, "PASS")],
            expected_artifact_fingerprints=self.execution_bindings,
        )
        self.assertEqual(result["terminal_status"], "PASS")
        self.assertEqual(result["missing_attempt_ids"], [])
        self.assertEqual(result["by_model"]["model-a"]["failure_rate"], 0.0)

    def test_primary_model_denominator_excludes_public_control_pool(self):
        hidden = identity(serial="hidden", item="hidden-item")
        control = identity(serial="control", item="control-item")
        control["corpus_pool_id"] = "CONTROL"
        control["exposure_status"] = "PUBLICLY_DISCLOSED_CONTROL"
        control["corpus_item_commitment"] = "sha256:" + "c" * 64
        manifest = self.frozen_manifest([hidden, control])
        result = model_failure_denominator_v1(
            manifest,
            [observation(hidden, "PASS"), observation(control, "FAIL")],
            expected_artifact_fingerprints=self.execution_bindings,
        )
        model = result["by_model"]["model-a"]
        self.assertEqual(result["corpus_pool"], "PRIVATE_HIDDEN_HOLDOUT")
        self.assertEqual(model["model_scorable_denominator"], 1)
        self.assertEqual(model["failure_count"], 0)
        self.assertEqual(model["failure_rate"], 0.0)

    def test_typed_partition_retains_all_six_terminal_states(self):
        attempts = [
            identity(serial=f"{index:03d}", item=f"item-{index:03d}")
            for index in range(len(TERMINAL_STATUSES))
        ]
        rows = [
            observation(attempt, status)
            for attempt, status in zip(attempts, TERMINAL_STATUSES)
        ]
        manifest = self.frozen_manifest(attempts)
        result = typed_terminal_partition_v1(
            manifest,
            rows,
            expected_artifact_fingerprints=self.execution_bindings,
        )
        self.assertEqual(result["total_attempts"], 6)
        self.assertEqual(result["terminal_counts"], {status: 1 for status in TERMINAL_STATUSES})
        self.assertEqual(result["scorable_terminal_count"], 2)
        self.assertEqual(result["non_scorable_terminal_count"], 4)
        self.assertAlmostEqual(result["non_scorable_attempt_rate"], 4 / 6)
        infrastructure = infrastructure_error_rate_v1(
            manifest,
            rows,
            expected_artifact_fingerprints=self.execution_bindings,
        )
        self.assertEqual(infrastructure["infrastructure_error_count"], 1)
        self.assertAlmostEqual(
            infrastructure["infrastructure_error_rate"], 1 / 6
        )
        self.assertEqual(
            infrastructure["model_failure_attribution"], "FORBIDDEN"
        )

    def test_cfp_nests_repeated_trials_inside_one_case(self):
        attempts = [
            identity(
                serial=f"repeat-{index:03d}",
                item="repeated-item",
                case_id="case-repeat-001",
                replicate=index,
            )
            for index in range(10)
        ]
        manifest = self.frozen_manifest(attempts)
        rows = [
            observation(attempt, "FAIL" if index == 9 else "PASS")
            for index, attempt in enumerate(attempts)
        ]
        result = case_failure_probability_v1(
            manifest,
            rows,
            expected_artifact_fingerprints=self.execution_bindings,
        )
        model = result["by_model"]["model-a"]
        self.assertEqual(model["distinct_case_count"], 1)
        self.assertEqual(model["cases"][0]["planned_trial_count"], 10)
        self.assertEqual(model["cases"][0]["model_scorable_denominator"], 10)
        self.assertEqual(model["cases"][0]["cfp"], 0.1)
        self.assertFalse(result["repeated_trials_count_as_distinct_cases"])
        uncertainty = fcfr_case_cluster_bootstrap_v1(
            {"case-repeat-001": 0.1}
        )
        self.assertEqual(uncertainty["terminal_status"], "NOT_EVALUABLE")
        self.assertEqual(uncertainty["distinct_case_cluster_count"], 1)

    def test_fcfr_is_case_macro_not_trial_micro_rate(self):
        case_a = [
            identity(
                serial=f"macro-a-{index:03d}",
                item="macro-item-a",
                case_id="macro-case-a",
                replicate=index,
            )
            for index in range(9)
        ]
        case_b = [
            identity(
                serial="macro-b-000",
                item="macro-item-b",
                case_id="macro-case-b",
                replicate=0,
            )
        ]
        attempts = case_a + case_b
        manifest = self.frozen_manifest(attempts)
        rows = [observation(attempt, "PASS") for attempt in case_a] + [
            observation(case_b[0], "FAIL")
        ]
        result = family_conditional_failure_rate_v1(
            manifest,
            rows,
            expected_artifact_fingerprints=self.execution_bindings,
        )
        family = result["by_model"]["model-a"]["families"][0]
        self.assertEqual(family["distinct_case_count"], 2)
        self.assertEqual(family["total_recorded_trial_count"], 10)
        self.assertEqual(family["fcfr"], 0.5)
        self.assertNotEqual(family["fcfr"], 0.1)
        self.assertEqual(
            family["case_cluster_bootstrap_95"]["terminal_status"], "PASS"
        )
        self.assertEqual(
            family["case_cluster_bootstrap_95"][
                "distinct_case_cluster_count"
            ],
            2,
        )

    def test_cfpr_and_within_case_instability_are_distinct_diagnostics(self):
        control_attempts = [
            identity(
                serial=f"control-{index}",
                item=f"control-item-{index}",
                case_id=f"control-case-{index}",
                variant_id="CONTROL",
            )
            for index in range(2)
        ]
        for attempt in control_attempts:
            attempt["corpus_pool_id"] = "CONTROL"
            attempt["exposure_status"] = "PUBLICLY_DISCLOSED_CONTROL"
        hidden_anchor = identity(
            serial="control-hidden-anchor",
            item="control-hidden-anchor-item",
            case_id="control-hidden-anchor-case",
        )
        control_manifest = self.frozen_manifest(
            [hidden_anchor, *control_attempts]
        )
        cfpr = control_false_positive_rate_v1(
            control_manifest,
            [
                observation(control_attempts[0], "PASS"),
                observation(control_attempts[1], "FAIL"),
            ],
            expected_artifact_fingerprints=self.execution_bindings,
        )
        self.assertEqual(cfpr["by_model"]["model-a"]["cfpr"], 0.5)

        repeats = [
            identity(
                serial=f"unstable-{index}",
                item="unstable-item",
                case_id="unstable-case",
                replicate=index,
            )
            for index in range(2)
        ]
        repeat_manifest = self.frozen_manifest(repeats)
        instability = within_case_instability_v1(
            repeat_manifest,
            [observation(repeats[0], "PASS"), observation(repeats[1], "FAIL")],
            expected_artifact_fingerprints=self.execution_bindings,
        )
        model = instability["by_model"]["model-a"]
        self.assertEqual(model["eligible_distinct_case_count"], 1)
        self.assertEqual(model["switching_distinct_case_count"], 1)
        self.assertEqual(model["within_case_instability"], 1.0)

    def test_typed_partition_is_manifest_bound_and_suppresses_partial_rate(self):
        attempts = [identity(serial="001"), identity(serial="002", item="item-002")]
        manifest = self.frozen_manifest(attempts)
        first = observation(attempts[0], "ERROR")
        with self.assertRaises(ValueError):
            typed_terminal_partition_v1(
                manifest,
                [first, first],
                expected_artifact_fingerprints=self.execution_bindings,
            )

        result = typed_terminal_partition_v1(
            manifest,
            [first],
            expected_artifact_fingerprints=self.execution_bindings,
        )
        self.assertEqual(result["terminal_status"], "NOT_EVALUABLE")
        self.assertEqual(result["reason"], "MISSING_PLANNED_OBSERVATIONS")
        self.assertEqual(result["recorded_terminal_count"], 1)
        self.assertEqual(result["missing_attempt_ids"], [attempts[1]["attempt_id"]])
        self.assertIsNone(result["non_scorable_attempt_rate"])

    def test_model_and_agent_metrics_remain_class_separated_after_equivalence(self):
        direct = identity(model="model-a", serial="direct", item="direct-item")
        agent = identity(
            model="model-a",
            target_class="AGENT_STANDARDIZED",
            serial="agent",
            item="agent-item",
        )
        manifest = self.frozen_manifest(
            [direct, agent],
            comparison_classes=[*DEFAULT_COMPARABLE_CLASSES, "AGENT_STANDARDIZED"],
            establish_sandbox=True,
        )
        rows = [observation(direct, "FAIL"), observation(agent, "PASS")]
        direct_result = model_failure_denominator_v1(
            manifest,
            rows,
            metric_id="model_failure_rate",
            expected_artifact_fingerprints=self.execution_bindings,
        )
        agent_result = model_failure_denominator_v1(
            manifest,
            rows,
            metric_id="sandboxed_agent_failure_rate",
            expected_artifact_fingerprints=self.execution_bindings,
        )
        self.assertEqual(direct_result["target_classes"], list(DEFAULT_COMPARABLE_CLASSES))
        self.assertEqual(direct_result["by_model"]["model-a"]["planned_attempt_count"], 1)
        self.assertEqual(direct_result["by_model"]["model-a"]["failure_rate"], 1.0)
        self.assertEqual(agent_result["target_classes"], ["AGENT_STANDARDIZED"])
        self.assertEqual(agent_result["by_model"]["model-a"]["planned_attempt_count"], 1)
        self.assertEqual(agent_result["by_model"]["model-a"]["failure_rate"], 0.0)

    def test_wilson_interval_is_deterministic_and_zero_safe(self):
        self.assertEqual(wilson_interval_v1(1, 2), wilson_interval_v1(1, 2))
        zero = wilson_interval_v1(0, 0)
        self.assertEqual(zero["terminal_status"], "NOT_EVALUABLE")
        self.assertEqual(zero["reason"], "ZERO_DENOMINATOR")
        self.assertIsNone(zero["lower"])
        with self.assertRaises(ValueError):
            wilson_interval_v1(2, 1)

    def test_paired_complete_case_excludes_non_scorable_pairs_symmetrically(self):
        attempts = [
            identity(model=model, serial=f"{model}-{item}", item=item)
            for model in ("model-a", "model-b")
            for item in ("item-001", "item-002")
        ]
        manifest = self.frozen_manifest(attempts)
        statuses = {
            ("model-a", "item-001"): "PASS",
            ("model-b", "item-001"): "FAIL",
            ("model-a", "item-002"): "ERROR",
            ("model-b", "item-002"): "FAIL",
        }
        rows = [
            observation(attempt, statuses[(attempt["model_subject_id"], attempt["corpus_item_alias"])])
            for attempt in attempts
        ]
        result = paired_complete_case_v1(
            manifest,
            rows,
            left_model_subject_id="model-a",
            right_model_subject_id="model-b",
            expected_artifact_fingerprints=self.execution_bindings,
        )
        self.assertEqual(result["terminal_status"], "PASS")
        self.assertEqual(result["paired_scorable_count"], 1)
        self.assertEqual(result["excluded_pair_count"], 1)
        self.assertEqual(result["left_failure_rate"], 0.0)
        self.assertEqual(result["right_failure_rate"], 1.0)
        self.assertEqual(result["failure_rate_delta_left_minus_right"], -1.0)
        self.assertFalse(result["ranking_emitted"])

    def test_paired_complete_case_pairs_predeclared_retry_ordinals(self):
        left_root = identity(model="model-a", serial="a-root", item="item-001")
        left_retry = copy.deepcopy(left_root)
        left_retry["attempt_id"] = "attempt-model-a-retry"
        left_retry["parent_attempt_id"] = left_root["attempt_id"]
        right_root = identity(model="model-b", serial="b-root", item="item-001")
        right_retry = copy.deepcopy(right_root)
        right_retry["attempt_id"] = "attempt-model-b-retry"
        right_retry["parent_attempt_id"] = right_root["attempt_id"]
        attempts = [left_root, left_retry, right_root, right_retry]
        manifest = self.frozen_manifest(attempts)
        rows = [observation(attempt, "PASS") for attempt in attempts]
        result = paired_complete_case_v1(
            manifest,
            rows,
            left_model_subject_id="model-a",
            right_model_subject_id="model-b",
            expected_artifact_fingerprints=self.execution_bindings,
        )
        self.assertEqual(result["terminal_status"], "PASS")
        self.assertEqual(result["paired_scorable_count"], 2)
        self.assertEqual(result["excluded_pair_count"], 0)

    def test_paired_comparison_rejects_unpaired_predeclared_design(self):
        attempts = [
            identity(model="model-a", serial="a-001", item="item-001"),
            identity(model="model-b", serial="b-002", item="item-002"),
        ]
        manifest = self.frozen_manifest(attempts)
        rows = [observation(attempt, "PASS") for attempt in attempts]
        result = paired_complete_case_v1(
            manifest,
            rows,
            left_model_subject_id="model-a",
            right_model_subject_id="model-b",
            expected_artifact_fingerprints=self.execution_bindings,
        )
        self.assertEqual(result["terminal_status"], "NOT_EVALUABLE")
        self.assertEqual(result["reason"], "UNPAIRED_PREDECLARED_DESIGN")
        self.assertFalse(result["ranking_emitted"])

    def test_paired_comparison_rejects_identity_compatibility_drift(self):
        left = identity(model="model-a", serial="a-001", item="item-001")
        right = identity(model="model-b", serial="b-001", item="item-001")
        right["prompt_template_version"] = "prompt-v2"
        manifest = self.frozen_manifest([left, right])
        rows = [observation(left, "PASS"), observation(right, "PASS")]
        result = paired_complete_case_v1(
            manifest,
            rows,
            left_model_subject_id="model-a",
            right_model_subject_id="model-b",
            expected_artifact_fingerprints=self.execution_bindings,
        )
        self.assertEqual(result["terminal_status"], "NOT_EVALUABLE")
        self.assertEqual(result["reason"], "PAIRED_IDENTITY_MISMATCH")
        self.assertEqual(result["paired_scorable_count"], 0)
        self.assertFalse(result["ranking_emitted"])

    def test_blind_adjudication_agreement_and_tiebreak(self):
        manifest = self.frozen_manifest(
            [identity(model="blind", item="item-blind-001", serial="001")]
        )
        pass_primary = adjudication(adjudicator="reviewer-a", decision="PASS", serial="001")
        pass_primary_2 = adjudication(adjudicator="reviewer-b", decision="PASS", serial="002")
        agreed = resolve_adjudication_v1(
            manifest,
            [pass_primary, pass_primary_2],
            expected_artifact_fingerprints=self.execution_bindings,
        )
        self.assertEqual(agreed["terminal_status"], "PASS")
        self.assertEqual(agreed["reason"], "PRIMARY_AGREEMENT")

        fail_primary = adjudication(adjudicator="reviewer-b", decision="FAIL", serial="003")
        unresolved = resolve_adjudication_v1(
            manifest,
            [pass_primary, fail_primary],
            expected_artifact_fingerprints=self.execution_bindings,
        )
        self.assertEqual(unresolved["terminal_status"], "UNKNOWN")
        tiebreak = adjudication(
            adjudicator="reviewer-c", decision="FAIL", role="TIEBREAK", serial="004"
        )
        resolved = resolve_adjudication_v1(
            manifest,
            [pass_primary, fail_primary, tiebreak],
            expected_artifact_fingerprints=self.execution_bindings,
        )
        self.assertEqual(resolved["terminal_status"], "FAIL")
        self.assertEqual(resolved["reason"], "PREDECLARED_TIEBREAK")

    def test_unknown_primary_is_terminal_and_cannot_be_tiebroken(self):
        manifest = self.frozen_manifest(
            [identity(model="blind", item="item-blind-001", serial="001")]
        )
        pass_primary = adjudication(
            adjudicator="reviewer-a", decision="PASS", serial="001"
        )
        unknown_primary = adjudication(
            adjudicator="reviewer-b", decision="UNKNOWN", serial="002"
        )
        result = resolve_adjudication_v1(
            manifest,
            [pass_primary, unknown_primary],
            expected_artifact_fingerprints=self.execution_bindings,
        )
        self.assertEqual(result["terminal_status"], "UNKNOWN")
        self.assertEqual(result["reason"], "PRIMARY_INSUFFICIENT_EVIDENCE")
        self.assertIsNone(result["decision"])

        tiebreak = adjudication(
            adjudicator="reviewer-c",
            decision="FAIL",
            role="TIEBREAK",
            serial="003",
        )
        with self.assertRaises(ValueError):
            resolve_adjudication_v1(
                manifest,
                [pass_primary, unknown_primary, tiebreak],
                expected_artifact_fingerprints=self.execution_bindings,
            )

        fail_primary = adjudication(
            adjudicator="reviewer-b", decision="FAIL", serial="004"
        )
        unknown_tiebreak = adjudication(
            adjudicator="reviewer-c",
            decision="UNKNOWN",
            role="TIEBREAK",
            serial="005",
        )
        unresolved_tiebreak = resolve_adjudication_v1(
            manifest,
            [pass_primary, fail_primary, unknown_tiebreak],
            expected_artifact_fingerprints=self.execution_bindings,
        )
        self.assertEqual(unresolved_tiebreak["terminal_status"], "UNKNOWN")
        self.assertEqual(
            unresolved_tiebreak["reason"], "TIEBREAK_INSUFFICIENT_EVIDENCE"
        )
        self.assertIsNone(unresolved_tiebreak["decision"])

    def test_adjudication_rejects_identity_leak_duplicate_and_extra_tiebreak(self):
        manifest = self.frozen_manifest(
            [identity(model="blind", item="item-blind-001", serial="001")]
        )
        first = adjudication(adjudicator="reviewer-a", decision="PASS", serial="001")
        second = adjudication(adjudicator="reviewer-b", decision="PASS", serial="002")

        unblinded = copy.deepcopy(first)
        unblinded["blind_to_model_identity"] = False
        unblinded = refingerprint(unblinded, "record_fingerprint")
        with self.assertRaises(ValueError):
            validate_adjudication_record(unblinded)

        configuration_drift = copy.deepcopy(first)
        configuration_drift["adjudicator_configuration_fingerprint"] = (
            "sha256:" + "6" * 64
        )
        configuration_drift = refingerprint(
            configuration_drift, "record_fingerprint"
        )
        with self.assertRaises(ValueError):
            resolve_adjudication_v1(
                manifest,
                [configuration_drift, second],
                expected_artifact_fingerprints=self.execution_bindings,
            )

        wrong_study_first = copy.deepcopy(first)
        wrong_study_first["study_id"] = "study-002"
        wrong_study_first = refingerprint(
            wrong_study_first, "record_fingerprint"
        )
        wrong_study_second = copy.deepcopy(second)
        wrong_study_second["study_id"] = "study-002"
        wrong_study_second = refingerprint(
            wrong_study_second, "record_fingerprint"
        )
        with self.assertRaises(ValueError):
            resolve_adjudication_v1(
                manifest,
                [wrong_study_first, wrong_study_second],
                expected_artifact_fingerprints=self.execution_bindings,
            )

        duplicate = adjudication(adjudicator="reviewer-a", decision="PASS", serial="003")
        with self.assertRaises(ValueError):
            resolve_adjudication_v1(
                manifest,
                [first, duplicate],
                expected_artifact_fingerprints=self.execution_bindings,
            )

        unnecessary = adjudication(
            adjudicator="reviewer-c", decision="PASS", role="TIEBREAK", serial="004"
        )
        with self.assertRaises(ValueError):
            resolve_adjudication_v1(
                manifest,
                [first, second, unnecessary],
                expected_artifact_fingerprints=self.execution_bindings,
            )

        intruder = adjudication(
            adjudicator="reviewer-intruder",
            decision="FAIL",
            role="TIEBREAK",
            serial="005",
        )
        disagreeing = adjudication(
            adjudicator="reviewer-b", decision="FAIL", serial="006"
        )
        with self.assertRaises(ValueError):
            resolve_adjudication_v1(
                manifest,
                [first, disagreeing, intruder],
                expected_artifact_fingerprints=self.execution_bindings,
            )

    def test_adjudication_error_remains_infrastructure_error(self):
        manifest = self.frozen_manifest(
            [identity(model="blind", item="item-blind-001", serial="001")]
        )
        completed = adjudication(adjudicator="reviewer-a", decision="PASS", serial="001")
        errored = adjudication(
            adjudicator="reviewer-b",
            decision=None,
            record_status="ERROR",
            serial="002",
        )
        result = resolve_adjudication_v1(
            manifest,
            [completed, errored],
            expected_artifact_fingerprints=self.execution_bindings,
        )
        self.assertEqual(result["terminal_status"], "ERROR")
        self.assertIsNone(result["decision"])

        invalid_tiebreak = adjudication(
            adjudicator="reviewer-c",
            decision="FAIL",
            role="TIEBREAK",
            serial="003",
        )
        with self.assertRaises(ValueError):
            resolve_adjudication_v1(
                manifest,
                [completed, errored, invalid_tiebreak],
                expected_artifact_fingerprints=self.execution_bindings,
            )

        incomplete_error = resolve_adjudication_v1(
            manifest,
            [errored],
            expected_artifact_fingerprints=self.execution_bindings,
        )
        self.assertEqual(incomplete_error["terminal_status"], "ERROR")

    def test_hidden_holdout_exact_material_stays_outside_public_repository(self):
        checked = validate_corpus_policy(self.corpus)
        hidden = checked["hidden_holdout"]
        self.assertFalse(hidden["exact_content_in_public_repository"])
        self.assertFalse(hidden["exact_case_ids_in_public_repository"])
        self.assertFalse(hidden["private_locator_in_public_repository"])
        self.assertFalse(hidden["per_case_commitments_in_public_repository"])
        self.assertEqual(
            checked["access_sequence"],
            [
                "CURATOR_SELECT_AND_COMMIT_PRIVATE_HOLDOUT",
                "FREEZE_EXECUTION_MANIFEST",
                "AUTHORIZE_EXECUTION",
                "OPEN_PRIVATE_HOLDOUT_TO_EXECUTION_PATH",
                "LOG_ACCESS",
            ],
        )
        self.assertTrue(hidden["independent_curator_seal_before_manifest_freeze"])

        leaked = copy.deepcopy(self.corpus)
        leaked["hidden_holdout"]["exact_content"] = "forbidden-public-leak"
        leaked = refingerprint(leaked, "policy_fingerprint")
        with self.assertRaises(ValueError):
            validate_corpus_policy(leaked)

        hidden_attempt = identity(serial="hidden", item="shared-item")
        control_attempt = identity(serial="control", item="shared-item")
        control_attempt["corpus_pool_id"] = "CONTROL"
        control_attempt["exposure_status"] = "PUBLICLY_DISCLOSED_CONTROL"
        control_attempt["corpus_item_commitment"] = "sha256:" + "c" * 64
        with self.assertRaises(ValueError):
            corpus_aggregate_commitment_v1([hidden_attempt, control_attempt])

        alias_drift = identity(serial="alias-drift", item="shared-item")
        alias_drift["corpus_item_commitment"] = "sha256:" + "d" * 64
        with self.assertRaises(ValueError):
            corpus_aggregate_commitment_v1([hidden_attempt, alias_drift])

        commitment_alias_drift = identity(
            serial="commitment-alias-drift", item="different-alias"
        )
        commitment_alias_drift["corpus_item_commitment"] = hidden_attempt[
            "corpus_item_commitment"
        ]
        with self.assertRaises(ValueError):
            corpus_aggregate_commitment_v1(
                [hidden_attempt, commitment_alias_drift]
            )

        mutation = identity(serial="mutation", item="mutation-item")
        mutation["corpus_pool_id"] = "MECHANISM_PRESERVING_MUTATION"
        mutation["exposure_status"] = "PUBLICLY_DISCLOSED_MUTATION"
        mutation["corpus_item_commitment"] = "sha256:" + "e" * 64
        mutation["mutation_parent_commitment"] = hidden_attempt[
            "corpus_item_commitment"
        ]
        with self.assertRaises(ValueError):
            corpus_aggregate_commitment_v1([hidden_attempt, mutation])

        self_parent_mutation = identity(
            serial="self-parent-mutation", item="self-parent-mutation-item"
        )
        self_parent_mutation["corpus_pool_id"] = (
            "MECHANISM_PRESERVING_MUTATION"
        )
        self_parent_mutation["exposure_status"] = (
            "PUBLICLY_DISCLOSED_MUTATION"
        )
        self_parent_mutation["mutation_parent_commitment"] = (
            self_parent_mutation["corpus_item_commitment"]
        )
        with self.assertRaises(ValueError):
            corpus_aggregate_commitment_v1([self_parent_mutation])

    def test_contract_binding_rejects_refingerprinted_artifact_tamper(self):
        tampered_matrix = copy.deepcopy(self.matrix)
        tampered_matrix["limitations"].append("semantic-drift")
        tampered_matrix = refingerprint(tampered_matrix, "matrix_fingerprint")
        bound = dict(self.bound_artifacts)
        bound["cases/b2/public-safe/benchmark/bm0-target-applicability.json"] = tampered_matrix
        with self.assertRaises(ValueError):
            validate_measurement_contract(self.contract, bound_artifacts=bound)

    def test_receipt_rejects_cross_wired_explicit_and_bound_artifacts(self):
        tampered_matrix = copy.deepcopy(self.matrix)
        tampered_matrix["limitations"].append("valid-but-cross-wired")
        tampered_matrix = refingerprint(tampered_matrix, "matrix_fingerprint")
        with self.assertRaises(ValueError):
            build_bm0_receipt(
                contract=self.contract,
                target_matrix=tampered_matrix,
                metric_registry=self.registry,
                corpus_policy=self.corpus,
                manifest_template=self.manifest_template,
                bound_artifacts=self.bound_artifacts,
            )

    def test_manifest_binds_measurement_contract_core(self):
        self.assertEqual(
            self.manifest_template["artifact_fingerprints"][
                "measurement_contract_core"
            ],
            measurement_contract_core_fingerprint_v1(self.contract),
        )

    def test_contract_rejects_refingerprinted_sap_semantic_tamper(self):
        tampered = copy.deepcopy(self.contract)
        tampered["sap"]["methods"][0]["frozen_parameters"]["decision_rule"] = (
            "STOP_AFTER_FIRST_RECORDED_ATTEMPT"
        )
        tampered = refingerprint(tampered, "contract_fingerprint")
        with self.assertRaises(ValueError):
            validate_measurement_contract(
                tampered, bound_artifacts=self.bound_artifacts
            )

    def test_contract_binding_inventory_cannot_be_reduced(self):
        reduced_contract = copy.deepcopy(self.contract)
        removed_path = "schemas/bm0_observation.schema.json"
        reduced_contract["artifact_bindings"].pop(removed_path)
        reduced_contract = refingerprint(reduced_contract, "contract_fingerprint")
        reduced_bound = dict(self.bound_artifacts)
        reduced_bound.pop(removed_path)
        with self.assertRaises(ValueError):
            validate_measurement_contract(
                reduced_contract, bound_artifacts=reduced_bound
            )

    def test_checked_receipt_is_reproducible_and_never_self_promotes_green(self):
        receipt = self.computed_receipt()
        checked = validate_bm0_receipt(receipt)
        self.assertEqual(checked, self.computed_receipt())
        self.assertEqual(checked["developer_contract_gate"], "PASS")
        self.assertEqual(checked["exact_head_ci_status"], "NOT_RUN")
        self.assertEqual(checked["independent_qa_status"], "NOT_RUN")
        self.assertEqual(checked["corpus_commitment_status"], "NOT_COMMITTED")
        self.assertIsNone(checked["corpus_aggregate_commitment"])
        self.assertEqual(checked["adjudication_mode"], "NOT_SELECTED")
        self.assertEqual(checked["primary_estimate_pool"], "PRIVATE_HIDDEN_HOLDOUT")
        self.assertEqual(
            checked["sap_design_rule_id"], "BOUNDED-PILOT-FIXED-SUITE-V1"
        )
        self.assertEqual(checked["sap_no_peeking_rule"], "FORBIDDEN")
        self.assertEqual(checked["canonical_entry_count"], 16)
        self.assertEqual(checked["canonical_case_count"], 32)
        self.assertFalse(checked["bm0_green"])
        self.assertFalse(checked["benchmark_results_emitted"])

        semantic_drift = copy.deepcopy(checked)
        semantic_drift["target_count"] = 15
        semantic_drift = refingerprint(semantic_drift, "receipt_fingerprint")
        with self.assertRaises(ValueError):
            validate_bm0_receipt(semantic_drift)

    def test_claim_ceiling_allows_contract_claims_and_forbids_results(self):
        receipt = self.computed_receipt()
        assert_claim_allowed("BM0_OFFLINE_CONTRACT_VALIDATED", receipt)
        assert_claim_allowed(
            "BM0_READY_FOR_EXACT_HEAD_CI_AND_INDEPENDENT_QA", receipt
        )
        for forbidden in (
            "BM0_GREEN",
            "MODEL_RANKING",
            "POPULATION_FAILURE_RATE",
            "INDEPENDENT_QA_PASS",
        ):
            with self.subTest(claim=forbidden), self.assertRaises(ValueError):
                assert_claim_allowed(forbidden, receipt)

    def test_sap_binds_fifteen_methods_and_bounded_pilot_no_peeking_rule(self):
        methods = self.contract["sap"]["methods"]
        self.assertEqual(tuple(method["method_id"] for method in methods), SAP_METHOD_IDS)
        self.assertEqual(len({method["implementation"] for method in methods}), 15)
        self.assertTrue(self.contract["sap"]["frozen_before_hidden_access"])
        self.assertEqual(self.contract["sap"]["design_rule"], SAP_DESIGN_RULE)
        self.assertEqual(
            self.contract["sap"]["design_rule"]["target_precision"],
            "NOT_CLAIMED_BOUNDED_PILOT",
        )
        self.assertEqual(
            self.contract["sap"]["design_rule"][
                "outcome_dependent_extension"
            ],
            "FORBIDDEN",
        )

    def test_bounded_pilot_design_enforces_case_and_repeat_bounds(self):
        attempts = [
            identity(
                serial=f"pilot-{case_index}-{replicate}",
                item=f"pilot-item-{case_index}",
                case_id=f"pilot-case-{case_index}",
                replicate=replicate,
            )
            for case_index in range(2)
            for replicate in range(2)
        ]
        result = bounded_pilot_design_v1(attempts)
        self.assertEqual(result["terminal_status"], "PASS")
        self.assertEqual(result["group_count"], 1)
        self.assertFalse(result["outcome_fields_read"])
        self.assertFalse(result["precision_claimed"])

        one_case = [
            identity(
                serial=f"one-case-{replicate}",
                item="one-case-item",
                case_id="one-case",
                replicate=replicate,
            )
            for replicate in range(4)
        ]
        with self.assertRaises(ValueError):
            bounded_pilot_design_v1(one_case)

        one_repeat = [
            identity(
                serial=f"one-repeat-{case_index}",
                item=f"one-repeat-item-{case_index}",
                case_id=f"one-repeat-case-{case_index}",
                replicate=0,
            )
            for case_index in range(2)
        ]
        with self.assertRaises(ValueError):
            bounded_pilot_design_v1(one_repeat)

    def test_json_schemas_are_strict_and_cover_identity_manifest_and_adjudication(self):
        schemas = [
            "bm0_trial_identity.schema.json",
            "bm0_observation.schema.json",
            "bm0_adjudication_record.schema.json",
            "bm0_benchmark_manifest.schema.json",
            "bm0_measurement_contract.schema.json",
            "bm0_candidate_roster_budget.schema.json",
        ]
        for filename in schemas:
            with self.subTest(schema=filename):
                schema = load_json(ROOT / "schemas" / filename)
                self.assertEqual(schema["$schema"], "https://json-schema.org/draft/2020-12/schema")
                self.assertFalse(schema["additionalProperties"])
                self.assertEqual(set(schema["required"]), set(schema["properties"]))

        trial_schema = load_json(ROOT / "schemas" / "bm0_trial_identity.schema.json")
        observation_schema = load_json(ROOT / "schemas" / "bm0_observation.schema.json")
        for field in (
            "contract_version",
            "mechanism_lineage_id",
            "case_fingerprint",
            "generator_or_mutation_version",
            "contamination_status",
            "exposure_status",
            "applicability_result",
        ):
            self.assertIn(field, trial_schema["required"])
            self.assertIn(field, observation_schema["required"])
        for target_ids in TARGET_IDS_BY_CLASS.values():
            for target_id in target_ids:
                self.assertIn(target_id, json.dumps(trial_schema, sort_keys=True))
                self.assertIn(target_id, json.dumps(observation_schema, sort_keys=True))
        snapshot_rule = trial_schema["properties"]["model_snapshot_id"]["allOf"][1]
        self.assertIn("pattern", snapshot_rule["not"])
        self.assertGreaterEqual(len(trial_schema["allOf"]), 11)
        trial_conditions = json.dumps(trial_schema["allOf"], sort_keys=True)
        self.assertIn("expected_resolved_model_or_version_id", trial_conditions)
        self.assertIn("UNRESOLVED_ALIAS", trial_conditions)
        self.assertIn('"else"', trial_conditions)

        self.assertGreaterEqual(len(observation_schema["allOf"]), 21)
        observation_conditions = json.dumps(
            observation_schema["allOf"], sort_keys=True
        )
        for semantic_field in (
            "model_failure_value",
            "system_invariant_failure_value",
            "provider_terminal_status",
            "provider_http_status",
            "raw_response_fingerprint",
            "evidence_receipt_fingerprint",
            "attribution_status",
        ):
            self.assertIn(semantic_field, observation_conditions)
        self.assertIn("UNVERIFIABLE_ALIAS_DISCLOSED", observation_conditions)
        self.assertIn("NOT_APPLICABLE_SYSTEM_SCOPE", observation_conditions)

        manifest_schema = load_json(
            ROOT / "schemas" / "bm0_benchmark_manifest.schema.json"
        )
        self.assertIn(
            "measurement_contract_core",
            manifest_schema["properties"]["artifact_fingerprints"]["required"],
        )
        self.assertIn(
            "PRIVATE_HIDDEN_HOLDOUT", json.dumps(manifest_schema, sort_keys=True)
        )
        self.assertIn("hidden_holdout_authority", manifest_schema["required"])
        self.assertIn("model_applicability", manifest_schema["required"])
        self.assertIn(
            "NOT_IN_PUBLIC_REPO_DECLARATION",
            json.dumps(manifest_schema, sort_keys=True),
        )

        contract_schema = load_json(
            ROOT / "schemas" / "bm0_measurement_contract.schema.json"
        )
        terminal_prefix = contract_schema["properties"]["terminal_semantics"][
            "prefixItems"
        ]
        self.assertEqual(
            [entry["properties"]["terminal_status"]["const"] for entry in terminal_prefix],
            list(TERMINAL_STATUSES),
        )
        self.assertFalse(
            contract_schema["properties"]["terminal_semantics"]["items"]
        )
        self.assertIn(
            "items",
            contract_schema["properties"]["terminal_semantics"]["allOf"][0],
        )
        method_prefix = contract_schema["properties"]["sap"]["properties"][
            "methods"
        ]["prefixItems"]
        self.assertEqual(
            [entry["properties"]["method_id"]["const"] for entry in method_prefix],
            list(SAP_METHOD_IDS),
        )
        self.assertFalse(
            contract_schema["properties"]["sap"]["properties"]["methods"][
                "items"
            ]
        )
        self.assertIn(
            "design_rule", contract_schema["properties"]["sap"]["required"]
        )
        self.assertIn("applicability_contract", contract_schema["required"])
        self.assertIn(
            "candidate_roster_budget_contract", contract_schema["required"]
        )
        self.assertIn(
            "schemas/bm0_candidate_roster_budget.schema.json",
            contract_schema["properties"]["artifact_bindings"]["required"],
        )

    def test_checked_in_receipt_matches_regeneration(self):
        checked_in = load_json(RESULTS / "bm0-contract-validation.json")
        self.assertEqual(checked_in, self.computed_receipt())

    def test_runtime_has_no_provider_network_or_credential_adapter(self):
        source = (ROOT / "b2" / "bm0.py").read_text(encoding="utf-8")
        forbidden_imports = (
            "import requests",
            "import httpx",
            "import openai",
            "import boto3",
            "from requests",
            "from httpx",
            "from openai",
            "from boto3",
        )
        for forbidden in forbidden_imports:
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, source)
        boundaries = self.contract["execution_boundaries"]
        self.assertEqual(boundaries["live_model_calls"], 0)
        self.assertFalse(boundaries["credential_lookup"])
        self.assertEqual(boundaries["spend"], 0)


if __name__ == "__main__":
    unittest.main()
