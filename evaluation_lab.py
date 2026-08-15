"""Reproducible public-safe failure benchmarks and runtime evaluations."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Sequence


__version__ = "0.4.0"

Child = Mapping[str, str]
Case = Mapping[str, object]
Policy = Callable[[Iterable[Child]], bool]
HistoricalPolicy = Callable[[Mapping[str, object]], bool]

DEFAULT_CASE_PATH = (
    Path(__file__).resolve().parent
    / "cases"
    / "anonymized"
    / "premature-parent-closure.md"
)
DEFAULT_MITIGATION_PATH = (
    Path(__file__).resolve().parent
    / "experiments"
    / "closure-guard-mitigation.md"
)


CASES: tuple[dict[str, object], ...] = (
    {
        "variant_id": "base-order",
        "children": (
            {"child_id": "quick-check", "status": "DONE"},
            {"child_id": "qualification", "status": "OPEN"},
        ),
        "expected_close": False,
    },
    {
        "variant_id": "reordered-children",
        "children": (
            {"child_id": "qualification", "status": "OPEN"},
            {"child_id": "quick-check", "status": "DONE"},
        ),
        "expected_close": False,
    },
    {
        "variant_id": "waiting-external",
        "children": (
            {"child_id": "quick-check", "status": "DONE"},
            {"child_id": "access-grant", "status": "WAITING-EXTERNAL"},
        ),
        "expected_close": False,
    },
    {
        "variant_id": "unknown-required-state",
        "children": (
            {"child_id": "quick-check", "status": "DONE"},
            {"child_id": "required-evidence", "status": "UNKNOWN"},
        ),
        "expected_close": False,
    },
    {
        "variant_id": "all-terminal",
        "children": (
            {"child_id": "quick-check", "status": "DONE"},
            {"child_id": "qualification", "status": "DONE"},
        ),
        "expected_close": True,
    },
)


BUILTIN_MITIGATION_SPEC: dict[str, object] = {
    "schema_version": "mitigation-spec/v1",
    "mitigation_id": "MIT-CLOSURE-GUARD-001",
    "target_failure": "premature_parent_closure",
    "intervention": "Require every required child to be terminal before closure.",
    "control": "naive_any_done",
    "treatment": "companion_mind.runtime.ClosureGuard",
    "metrics": [
        "accuracy",
        "premature_closure_rate",
        "known_bad_failures_detected",
    ],
    "decision_rule": (
        "Adopt only when premature closure falls to zero, the all-terminal case "
        "remains accepted, and the known-bad regression probe still fails."
    ),
    "regression_cases": ["EVAL-CASE-001"],
    "runtime": {
        "guard_type": "closure_guard",
        "safeguard_id": "CM-GUARD-001",
        "terminal_statuses": ["CANCELLED", "DONE"],
        "blocking_statuses": [
            "BLOCKED",
            "OPEN",
            "PENDING",
            "UNKNOWN",
            "WAITING",
            "WAITING-EXTERNAL",
            "WAITING-ON-TRIGGER",
        ],
        "empty_evidence_decision": "HOLD",
        "non_terminal_decision": "REJECT",
        "all_terminal_decision": "ACCEPT",
    },
}


@dataclass(frozen=True)
class CaseSuite:
    case_id: str
    title: str
    run_id: str
    mitigation_id: str
    safeguard_id: str
    privacy: str
    cases: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class HistoricalBenchmarkSuite:
    benchmark_id: str
    title: str
    run_id: str
    privacy: str
    source_observations: int
    source_categories: int
    mechanisms: tuple[dict[str, str], ...]
    cases: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class PolicyResult:
    policy: str
    accuracy: float
    premature_closure_rate: float
    failures: tuple[str, ...]
    predictions: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class BenchmarkPolicyResult:
    policy: str
    accuracy: float
    false_accept_rate: float
    failures: tuple[str, ...]
    predictions: tuple[dict[str, object], ...]


BUILTIN_SUITE = CaseSuite(
    case_id="EVAL-CASE-001",
    title="Premature Parent Closure",
    run_id="EVAL-RUN-001",
    mitigation_id="MIT-CLOSURE-GUARD-001",
    safeguard_id="CM-GUARD-001",
    privacy="PUBLIC_SAFE",
    cases=CASES,
)


def _read_case_document(path: Path) -> object:
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".md", ".markdown"}:
        match = re.search(r"```json\s*(\{.*?\})\s*```", text, flags=re.DOTALL)
        if match is None:
            raise ValueError(f"{path}: no fenced JSON case fixture found")
        text = match.group(1)
    return json.loads(text)


def _string_array(
    document: Mapping[str, object], key: str, path: Path
) -> list[str]:
    value = document.get(key)
    if not isinstance(value, list) or not value:
        raise ValueError(f"{path}: {key!r} must be a non-empty array")
    normalized: list[str] = []
    for index, item in enumerate(value):
        if not isinstance(item, str) or not item.strip():
            raise ValueError(
                f"{path}: {key}[{index}] must be a non-empty string"
            )
        normalized.append(item.strip())
    return normalized


def validate_mitigation_spec(
    document: object, path: str | Path = "<mitigation-spec>"
) -> dict[str, object]:
    """Validate the full evaluation-owned MitigationSpec contract."""

    spec_path = Path(path)
    if not isinstance(document, dict):
        raise ValueError(f"{spec_path}: mitigation spec must be an object")
    required_text = {
        key: _required_text(document, key, spec_path)
        for key in (
            "schema_version",
            "mitigation_id",
            "target_failure",
            "intervention",
            "control",
            "treatment",
            "decision_rule",
        )
    }
    if required_text["schema_version"] != "mitigation-spec/v1":
        raise ValueError(
            f"{spec_path}: unsupported schema_version "
            f"{required_text['schema_version']!r}"
        )
    if required_text["target_failure"] != "premature_parent_closure":
        raise ValueError(
            f"{spec_path}: unsupported target_failure "
            f"{required_text['target_failure']!r}"
        )

    runtime = document.get("runtime")
    if not isinstance(runtime, dict):
        raise ValueError(f"{spec_path}: 'runtime' must be an object")
    runtime_text = {
        key: _required_text(runtime, key, spec_path)
        for key in (
            "guard_type",
            "safeguard_id",
            "empty_evidence_decision",
            "non_terminal_decision",
            "all_terminal_decision",
        )
    }
    terminal = sorted(
        status.upper() for status in _string_array(runtime, "terminal_statuses", spec_path)
    )
    blocking = sorted(
        status.upper() for status in _string_array(runtime, "blocking_statuses", spec_path)
    )
    overlap = set(terminal) & set(blocking)
    if overlap:
        raise ValueError(
            f"{spec_path}: terminal and blocking statuses overlap: "
            + ", ".join(sorted(overlap))
        )

    normalized: dict[str, object] = {
        **required_text,
        "metrics": _string_array(document, "metrics", spec_path),
        "regression_cases": _string_array(
            document, "regression_cases", spec_path
        ),
        "runtime": {
            **runtime_text,
            "terminal_statuses": terminal,
            "blocking_statuses": blocking,
        },
    }

    try:
        from companion_mind.runtime import MitigationSpec
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Install the sibling Companion-Mind repository first: "
            "python -m pip install -e ../Companion-Mind"
        ) from exc
    MitigationSpec.from_mapping(normalized)
    return normalized


def load_mitigation_spec(path: str | Path) -> dict[str, object]:
    mitigation_path = Path(path)
    return validate_mitigation_spec(
        _read_case_document(mitigation_path), mitigation_path
    )


def _required_text(document: Mapping[str, object], key: str, path: Path) -> str:
    value = document.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{path}: {key!r} must be a non-empty string")
    return value


def _validate_cases(raw_cases: object, path: Path) -> tuple[dict[str, object], ...]:
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError(f"{path}: 'inputs' must be a non-empty array")

    normalized: list[dict[str, object]] = []
    seen: set[str] = set()
    for index, raw_case in enumerate(raw_cases):
        label = f"{path}: inputs[{index}]"
        if not isinstance(raw_case, dict):
            raise ValueError(f"{label} must be an object")

        variant_id = raw_case.get("variant_id")
        if not isinstance(variant_id, str) or not variant_id.strip():
            raise ValueError(f"{label}.variant_id must be a non-empty string")
        if variant_id in seen:
            raise ValueError(f"{path}: duplicate variant_id {variant_id!r}")
        seen.add(variant_id)

        expected = raw_case.get("expected_close")
        if not isinstance(expected, bool):
            raise ValueError(f"{label}.expected_close must be boolean")

        raw_children = raw_case.get("children")
        if not isinstance(raw_children, list) or not raw_children:
            raise ValueError(f"{label}.children must be a non-empty array")
        children: list[dict[str, str]] = []
        for child_index, raw_child in enumerate(raw_children):
            child_label = f"{label}.children[{child_index}]"
            if not isinstance(raw_child, dict):
                raise ValueError(f"{child_label} must be an object")
            child_id = raw_child.get("child_id")
            status = raw_child.get("status")
            if not isinstance(child_id, str) or not child_id.strip():
                raise ValueError(f"{child_label}.child_id must be a non-empty string")
            if not isinstance(status, str) or not status.strip():
                raise ValueError(f"{child_label}.status must be a non-empty string")
            children.append({"child_id": child_id, "status": status})

        normalized.append(
            {
                "variant_id": variant_id,
                "children": tuple(children),
                "expected_close": expected,
            }
        )
    return tuple(normalized)


def load_case_suite(path: str | Path) -> CaseSuite:
    """Load and validate a JSON or Markdown-embedded case suite."""

    case_path = Path(path)
    document = _read_case_document(case_path)
    if not isinstance(document, dict):
        raise ValueError(f"{case_path}: case document must be an object")

    privacy = _required_text(document, "privacy", case_path)
    if privacy not in {"PUBLIC", "PUBLIC_SAFE", "REDACTED"}:
        raise ValueError(f"{case_path}: unsupported privacy value {privacy!r}")

    return CaseSuite(
        case_id=_required_text(document, "case_id", case_path),
        title=_required_text(document, "title", case_path),
        run_id=_required_text(document, "run_id", case_path),
        mitigation_id=_required_text(document, "mitigation_id", case_path),
        safeguard_id=_required_text(document, "safeguard_id", case_path),
        privacy=privacy,
        cases=_validate_cases(document.get("inputs"), case_path),
    )


def _positive_integer(
    document: Mapping[str, object], key: str, path: Path
) -> int:
    value = document.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{path}: {key!r} must be a positive integer")
    return value


def _validate_mechanisms(
    raw_mechanisms: object, path: Path
) -> tuple[dict[str, str], ...]:
    if not isinstance(raw_mechanisms, list) or not raw_mechanisms:
        raise ValueError(f"{path}: 'mechanisms' must be a non-empty array")
    normalized: list[dict[str, str]] = []
    seen: set[str] = set()
    for index, raw_mechanism in enumerate(raw_mechanisms):
        label = f"{path}: mechanisms[{index}]"
        if not isinstance(raw_mechanism, dict):
            raise ValueError(f"{label} must be an object")
        mechanism_id = _required_text(raw_mechanism, "mechanism_id", path)
        if mechanism_id in seen:
            raise ValueError(f"{path}: duplicate mechanism_id {mechanism_id!r}")
        seen.add(mechanism_id)
        normalized.append(
            {
                "mechanism_id": mechanism_id,
                "name": _required_text(raw_mechanism, "name", path),
                "gate": _required_text(raw_mechanism, "gate", path),
                "source_categories": _required_text(
                    raw_mechanism, "source_categories", path
                ),
            }
        )
    return tuple(normalized)


def _validate_historical_cases(
    raw_cases: object,
    mechanism_ids: set[str],
    path: Path,
) -> tuple[dict[str, object], ...]:
    if not isinstance(raw_cases, list) or not raw_cases:
        raise ValueError(f"{path}: historical 'inputs' must be a non-empty array")

    normalized: list[dict[str, object]] = []
    seen: set[str] = set()
    pair_variants: dict[str, set[str]] = {item: set() for item in mechanism_ids}
    for index, raw_case in enumerate(raw_cases):
        label = f"{path}: historical inputs[{index}]"
        if not isinstance(raw_case, dict):
            raise ValueError(f"{label} must be an object")
        variant_id = _required_text(raw_case, "variant_id", path)
        if variant_id in seen:
            raise ValueError(f"{path}: duplicate historical variant_id {variant_id!r}")
        seen.add(variant_id)
        mechanism_id = _required_text(raw_case, "mechanism_id", path)
        if mechanism_id not in mechanism_ids:
            raise ValueError(f"{label}: unknown mechanism_id {mechanism_id!r}")
        variant = _required_text(raw_case, "variant", path)
        if variant not in {"TRAP", "CONTROL"}:
            raise ValueError(f"{label}: variant must be TRAP or CONTROL")
        if variant in pair_variants[mechanism_id]:
            raise ValueError(
                f"{path}: duplicate {variant} for mechanism {mechanism_id}"
            )
        pair_variants[mechanism_id].add(variant)

        evidence_state = _required_text(raw_case, "evidence_state", path)
        if evidence_state not in {
            "SUPPORTED",
            "CONTRADICTED",
            "UNKNOWN",
            "NOT_LOADED",
        }:
            raise ValueError(f"{label}: unsupported evidence_state {evidence_state!r}")
        surface_confidence = _required_text(
            raw_case, "surface_confidence", path
        )
        if surface_confidence not in {"HIGH", "LOW"}:
            raise ValueError(
                f"{label}: surface_confidence must be HIGH or LOW"
            )
        expected_accept = raw_case.get("expected_accept")
        if not isinstance(expected_accept, bool):
            raise ValueError(f"{label}.expected_accept must be boolean")

        raw_constraints = raw_case.get("constraints")
        if not isinstance(raw_constraints, list) or not raw_constraints:
            raise ValueError(f"{label}.constraints must be a non-empty array")
        constraints: list[dict[str, str]] = []
        for constraint_index, raw_constraint in enumerate(raw_constraints):
            constraint_label = f"{label}.constraints[{constraint_index}]"
            if not isinstance(raw_constraint, dict):
                raise ValueError(f"{constraint_label} must be an object")
            status = _required_text(raw_constraint, "status", path)
            if status not in {"PASS", "FAIL", "UNKNOWN"}:
                raise ValueError(f"{constraint_label}: unsupported status {status!r}")
            constraints.append(
                {
                    "constraint_id": _required_text(
                        raw_constraint, "constraint_id", path
                    ),
                    "status": status,
                }
            )

        normalized.append(
            {
                "variant_id": variant_id,
                "mechanism_id": mechanism_id,
                "variant": variant,
                "scenario": _required_text(raw_case, "scenario", path),
                "candidate": _required_text(raw_case, "candidate", path),
                "surface_confidence": surface_confidence,
                "evidence_state": evidence_state,
                "constraints": tuple(constraints),
                "expected_accept": expected_accept,
            }
        )

    incomplete = sorted(
        mechanism_id
        for mechanism_id, variants in pair_variants.items()
        if variants != {"TRAP", "CONTROL"}
    )
    if incomplete:
        raise ValueError(
            f"{path}: every mechanism needs one TRAP and one CONTROL: "
            + ", ".join(incomplete)
        )
    return tuple(normalized)


def load_historical_benchmark(path: str | Path) -> HistoricalBenchmarkSuite:
    """Load the synthetic mechanism-preserving historical benchmark."""

    case_path = Path(path)
    root = _read_case_document(case_path)
    if not isinstance(root, dict):
        raise ValueError(f"{case_path}: case document must be an object")
    document = root.get("historical_benchmark")
    if not isinstance(document, dict):
        raise ValueError(f"{case_path}: missing historical_benchmark object")
    privacy = _required_text(document, "privacy", case_path)
    if privacy != "PUBLIC_SAFE":
        raise ValueError(
            f"{case_path}: historical benchmark must be PUBLIC_SAFE"
        )
    source_scope = document.get("source_scope")
    if not isinstance(source_scope, dict):
        raise ValueError(f"{case_path}: source_scope must be an object")
    mechanisms = _validate_mechanisms(document.get("mechanisms"), case_path)
    cases = _validate_historical_cases(
        document.get("inputs"),
        {item["mechanism_id"] for item in mechanisms},
        case_path,
    )
    declared_mechanisms = _positive_integer(
        source_scope, "mechanism_clusters", case_path
    )
    declared_cases = _positive_integer(source_scope, "public_cases", case_path)
    if declared_mechanisms != len(mechanisms):
        raise ValueError(
            f"{case_path}: declared mechanism cluster count does not match fixture"
        )
    if declared_cases != len(cases):
        raise ValueError(
            f"{case_path}: declared public case count does not match fixture"
        )
    return HistoricalBenchmarkSuite(
        benchmark_id=_required_text(document, "benchmark_id", case_path),
        title=_required_text(document, "title", case_path),
        run_id=_required_text(document, "run_id", case_path),
        privacy=privacy,
        source_observations=_positive_integer(
            source_scope, "observations", case_path
        ),
        source_categories=_positive_integer(
            source_scope, "raw_categories", case_path
        ),
        mechanisms=mechanisms,
        cases=cases,
    )


def naive_any_done(children: Iterable[Child]) -> bool:
    """Known-bad baseline: local completion is mistaken for parent completion."""

    return any(str(child.get("status", "")).upper() == "DONE" for child in children)


def _runtime_guard(mitigation_spec: Mapping[str, object]):
    try:
        from companion_mind.runtime import ClosureGuard, MitigationSpec
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Install the sibling Companion-Mind repository first: "
            "python -m pip install -e ../Companion-Mind"
        ) from exc
    runtime_spec = MitigationSpec.from_mapping(mitigation_spec)
    return ClosureGuard(runtime_spec), runtime_spec


def closure_guard_policy(
    children: Iterable[Child],
    mitigation_spec: Mapping[str, object] = BUILTIN_MITIGATION_SPEC,
) -> bool:
    """Execute the actual Companion-Mind safeguard from a validated spec."""

    guard, _ = _runtime_guard(mitigation_spec)
    return guard.evaluate(children).decision == "ACCEPT"


def evaluate_policy(
    name: str,
    policy: Policy,
    cases: Iterable[Case] = CASES,
) -> PolicyResult:
    case_list = tuple(cases)
    if not case_list:
        raise ValueError("at least one evaluation case is required")

    predictions: list[dict[str, object]] = []
    failures: list[str] = []
    negatives = 0
    premature = 0

    for case in case_list:
        variant_id = str(case["variant_id"])
        expected = bool(case["expected_close"])
        predicted = policy(case["children"])  # type: ignore[arg-type]
        correct = predicted == expected
        if not correct:
            failures.append(variant_id)
        if not expected:
            negatives += 1
            if predicted:
                premature += 1
        predictions.append(
            {
                "variant_id": variant_id,
                "expected_close": expected,
                "predicted_close": predicted,
                "correct": correct,
            }
        )

    return PolicyResult(
        policy=name,
        accuracy=(len(case_list) - len(failures)) / len(case_list),
        premature_closure_rate=premature / negatives if negatives else 0.0,
        failures=tuple(failures),
        predictions=tuple(predictions),
    )


def run_experiment(
    suite: CaseSuite = BUILTIN_SUITE,
    mitigation_spec: Mapping[str, object] = BUILTIN_MITIGATION_SPEC,
) -> dict[str, object]:
    validated_spec = validate_mitigation_spec(mitigation_spec)
    runtime = validated_spec["runtime"]
    if not isinstance(runtime, Mapping):
        raise ValueError("validated mitigation runtime is missing")
    if validated_spec["mitigation_id"] != suite.mitigation_id:
        raise ValueError("case suite and MitigationSpec mitigation_id do not match")
    if runtime["safeguard_id"] != suite.safeguard_id:
        raise ValueError("case suite and MitigationSpec safeguard_id do not match")
    if suite.case_id not in validated_spec["regression_cases"]:
        raise ValueError("case suite is not registered by the MitigationSpec")

    guard, runtime_spec = _runtime_guard(validated_spec)

    def treatment_policy(children: Iterable[Child]) -> bool:
        return guard.evaluate(children).decision == "ACCEPT"

    baseline = evaluate_policy("naive_any_done", naive_any_done, suite.cases)
    treatment = evaluate_policy(suite.safeguard_id, treatment_policy, suite.cases)
    regression_probe = evaluate_policy(
        "known_bad_regression_probe", naive_any_done, suite.cases
    )
    return {
        "run_id": suite.run_id,
        "case_id": suite.case_id,
        "mitigation_id": suite.mitigation_id,
        "safeguard_id": suite.safeguard_id,
        "fixture_count": len(suite.cases),
        "baseline": asdict(baseline),
        "treatment": asdict(treatment),
        "accuracy_delta": treatment.accuracy - baseline.accuracy,
        "integration": {
            "status": "PASS" if not treatment.failures else "FAIL",
            "runtime": "companion_mind.runtime.ClosureGuard",
            "schema_version": runtime_spec.schema_version,
            "spec_fingerprint": runtime_spec.fingerprint,
            "loaded_mitigation_id": runtime_spec.mitigation_id,
            "loaded_safeguard_id": guard.safeguard_id,
        },
        "regression": {
            "known_bad_failures_detected": len(regression_probe.failures),
            "guard_failures": len(treatment.failures),
            "status": "PASS" if regression_probe.failures and not treatment.failures else "FAIL",
        },
        "evidence_level": "E3_EXECUTABLE_LOCAL_PROTOTYPE",
        "limitations": [
            "deterministic structural fixture",
            "no live LLM calls",
            "no production traffic",
            "no cross-model generalization claim",
        ],
    }


def confidence_only_baseline(case: Mapping[str, object]) -> bool:
    """Known-bad baseline: fluent confidence is treated as sufficient evidence."""

    return case.get("surface_confidence") == "HIGH"


def constraint_gate_policy(case: Mapping[str, object]) -> bool:
    """Uniform reference gate; it contains no mechanism- or case-specific branch."""

    if case.get("evidence_state") != "SUPPORTED":
        return False
    constraints = case.get("constraints")
    if not isinstance(constraints, Iterable):
        return False
    statuses: list[str] = []
    for constraint in constraints:
        if not isinstance(constraint, Mapping):
            return False
        statuses.append(str(constraint.get("status", "UNKNOWN")))
    return bool(statuses) and all(status == "PASS" for status in statuses)


def evaluate_historical_policy(
    name: str,
    policy: HistoricalPolicy,
    cases: Iterable[Mapping[str, object]],
) -> BenchmarkPolicyResult:
    case_list = tuple(cases)
    if not case_list:
        raise ValueError("at least one historical evaluation case is required")

    predictions: list[dict[str, object]] = []
    failures: list[str] = []
    negatives = 0
    false_accepts = 0
    for case in case_list:
        variant_id = str(case["variant_id"])
        expected = bool(case["expected_accept"])
        predicted = policy(case)
        correct = predicted == expected
        if not correct:
            failures.append(variant_id)
        if not expected:
            negatives += 1
            if predicted:
                false_accepts += 1
        predictions.append(
            {
                "variant_id": variant_id,
                "mechanism_id": str(case["mechanism_id"]),
                "variant": str(case["variant"]),
                "expected_accept": expected,
                "predicted_accept": predicted,
                "correct": correct,
            }
        )

    return BenchmarkPolicyResult(
        policy=name,
        accuracy=(len(case_list) - len(failures)) / len(case_list),
        false_accept_rate=false_accepts / negatives if negatives else 0.0,
        failures=tuple(failures),
        predictions=tuple(predictions),
    )


def run_historical_benchmark(
    suite: HistoricalBenchmarkSuite,
) -> dict[str, object]:
    """Run the 12-cluster public-safe benchmark with a uniform constraint gate."""

    baseline = evaluate_historical_policy(
        "confidence_only", confidence_only_baseline, suite.cases
    )
    treatment = evaluate_historical_policy(
        "uniform_constraint_gate", constraint_gate_policy, suite.cases
    )
    trap_count = sum(not bool(case["expected_accept"]) for case in suite.cases)
    controls = sum(bool(case["expected_accept"]) for case in suite.cases)
    regression_pass = (
        len(baseline.failures) == trap_count
        and not treatment.failures
        and trap_count == controls == len(suite.mechanisms)
    )
    return {
        "benchmark_id": suite.benchmark_id,
        "run_id": suite.run_id,
        "privacy": suite.privacy,
        "source_scope": {
            "observations": suite.source_observations,
            "raw_categories": suite.source_categories,
            "mechanism_clusters": len(suite.mechanisms),
            "public_cases": len(suite.cases),
            "transformation": "mechanism-preserving synthetic reconstruction",
        },
        "fixture_count": len(suite.cases),
        "mechanisms": [dict(item) for item in suite.mechanisms],
        "baseline": asdict(baseline),
        "treatment": asdict(treatment),
        "accuracy_delta": treatment.accuracy - baseline.accuracy,
        "regression": {
            "known_bad_failures_detected": len(baseline.failures),
            "reference_gate_failures": len(treatment.failures),
            "status": "PASS" if regression_pass else "FAIL",
        },
        "architecture": {
            "policy": "uniform evidence-and-constraint gate",
            "mechanism_specific_branches": 0,
            "per_observation_rules": 0,
        },
        "evidence_level": "E3_EXECUTABLE_PUBLIC_SAFE_BENCHMARK",
        "limitations": [
            "synthetic mechanism-preserving cases, not the private observations",
            "deterministic reference policies, not live LLM calls",
            "no production traffic",
            "no broad-model or scientific-benchmark validity claim",
        ],
    }


def _render_historical_report(result: Mapping[str, object]) -> str:
    baseline = result["baseline"]
    treatment = result["treatment"]
    regression = result["regression"]
    source_scope = result["source_scope"]
    if not all(
        isinstance(item, Mapping)
        for item in (baseline, treatment, regression, source_scope)
    ):
        raise ValueError("historical result is missing benchmark metrics")
    return "\n".join(
        (
            f"# {result['benchmark_id']} Evaluation Report",
            "",
            f"- Run: `{result['run_id']}`",
            f"- Evidence: `{result['evidence_level']}`",
            f"- Mechanism clusters: `{source_scope['mechanism_clusters']}`",
            f"- Public-safe cases: `{source_scope['public_cases']}`",
            "",
            "| Policy | Accuracy | False accept rate | Failures |",
            "|---|---:|---:|---:|",
            f"| Confidence-only baseline | {float(baseline['accuracy']):.0%} | "
            f"{float(baseline['false_accept_rate']):.0%} | "
            f"{len(baseline['failures'])} |",
            f"| Uniform constraint gate | {float(treatment['accuracy']):.0%} | "
            f"{float(treatment['false_accept_rate']):.0%} | "
            f"{len(treatment['failures'])} |",
            "",
            "## Regression",
            "",
            f"**{regression['status']}** — known-bad traps detected: "
            f"{regression['known_bad_failures_detected']}; reference-gate failures: "
            f"{regression['reference_gate_failures']}.",
            "",
            "## Evidence boundary",
            "",
            *[f"- {item}" for item in result["limitations"]],
            "",
        )
    )


def render_report(result: Mapping[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if output_format != "markdown":
        raise ValueError(f"unsupported output format: {output_format}")

    if "benchmark_id" in result:
        return _render_historical_report(result)

    baseline = result["baseline"]
    treatment = result["treatment"]
    regression = result["regression"]
    integration = result["integration"]
    if not isinstance(baseline, Mapping) or not isinstance(treatment, Mapping):
        raise ValueError("result is missing policy metrics")
    if not isinstance(regression, Mapping):
        raise ValueError("result is missing regression metrics")
    if not isinstance(integration, Mapping):
        raise ValueError("result is missing integration evidence")

    return "\n".join(
        (
            f"# {result['case_id']} Evaluation Report",
            "",
            f"- Run: `{result['run_id']}`",
            f"- Mitigation: `{result['mitigation_id']}`",
            f"- Safeguard: `{result['safeguard_id']}`",
            f"- Evidence: `{result['evidence_level']}`",
            f"- Runtime integration: `{integration['status']}`",
            f"- MitigationSpec SHA-256: `{integration['spec_fingerprint']}`",
            "",
            "| Policy | Accuracy | Premature closure rate | Failures |",
            "|---|---:|---:|---:|",
            f"| Baseline | {float(baseline['accuracy']):.0%} | "
            f"{float(baseline['premature_closure_rate']):.0%} | "
            f"{len(baseline['failures'])} |",
            f"| Closure Guard | {float(treatment['accuracy']):.0%} | "
            f"{float(treatment['premature_closure_rate']):.0%} | "
            f"{len(treatment['failures'])} |",
            "",
            "## Regression",
            "",
            f"**{regression['status']}** — known-bad failures detected: "
            f"{regression['known_bad_failures_detected']}; guard failures: "
            f"{regression['guard_failures']}.",
            "",
            "## Evidence boundary",
            "",
            *[f"- {item}" for item in result["limitations"]],
            "",
        )
    )


def write_report(path: str | Path, content: str) -> None:
    """Write a report atomically, creating its parent directory when needed."""

    output_path = Path(path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_name: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=output_path.parent,
            prefix=f".{output_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary.write(content)
            temporary_name = temporary.name
        os.replace(temporary_name, output_path)
    finally:
        if temporary_name and os.path.exists(temporary_name):
            os.unlink(temporary_name)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="llm-eval",
        description=(
            "Load public-safe cases, run closure or historical benchmark policies, "
            "grade outcomes, calculate metrics, and enforce regression checks."
        ),
    )
    parser.add_argument(
        "--suite",
        choices=("closure", "historical"),
        default="closure",
        help="evaluation suite to run (default: closure)",
    )
    parser.add_argument(
        "--cases",
        type=Path,
        help=(
            "JSON or Markdown case suite. If omitted, load the checked case card "
            "when available and otherwise use the built-in EVAL-CASE-001 fixture."
        ),
    )
    parser.add_argument(
        "--format",
        choices=("json", "markdown"),
        default="json",
        help="report format (default: json)",
    )
    parser.add_argument("--output", type=Path, help="write the report to this path")
    parser.add_argument(
        "--mitigation-spec",
        type=Path,
        help=(
            "JSON or Markdown-embedded MitigationSpec; defaults to the checked "
            "closure-guard experiment"
        ),
    )
    parser.add_argument(
        "--emit-mitigation",
        type=Path,
        help="write the validated canonical MitigationSpec as JSON",
    )
    parser.add_argument(
        "--allow-regression",
        action="store_true",
        help="return exit code 0 even when the regression gate fails",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        case_path = args.cases or DEFAULT_CASE_PATH
        if args.suite == "historical":
            if not case_path.exists():
                raise ValueError(
                    "historical suite requires the checked public-safe case document"
                )
            if args.mitigation_spec or args.emit_mitigation:
                raise ValueError(
                    "historical suite does not consume or emit a runtime MitigationSpec"
                )
            historical_suite = load_historical_benchmark(case_path)
            result = run_historical_benchmark(historical_suite)
        else:
            if case_path.exists():
                suite = load_case_suite(case_path)
            else:
                suite = BUILTIN_SUITE
            if args.mitigation_spec:
                mitigation_spec = load_mitigation_spec(args.mitigation_spec)
            elif DEFAULT_MITIGATION_PATH.exists():
                mitigation_spec = load_mitigation_spec(DEFAULT_MITIGATION_PATH)
            else:
                mitigation_spec = validate_mitigation_spec(BUILTIN_MITIGATION_SPEC)
            if args.emit_mitigation:
                write_report(
                    args.emit_mitigation,
                    json.dumps(
                        mitigation_spec,
                        ensure_ascii=False,
                        indent=2,
                        sort_keys=True,
                    )
                    + "\n",
                )
            result = run_experiment(suite, mitigation_spec)
        report = render_report(result, args.format)
        if args.output:
            write_report(args.output, report)
        else:
            print(report, end="")
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"llm-eval: error: {exc}", file=sys.stderr)
        return 2

    regression = result["regression"]
    if (
        isinstance(regression, Mapping)
        and regression.get("status") != "PASS"
        and not args.allow_regression
    ):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
