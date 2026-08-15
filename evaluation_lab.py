"""Reproducible CLI evaluation for Companion-Mind's Closure Guard."""

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


__version__ = "0.3.0"

Child = Mapping[str, str]
Case = Mapping[str, object]
Policy = Callable[[Iterable[Child]], bool]

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
class PolicyResult:
    policy: str
    accuracy: float
    premature_closure_rate: float
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


def render_report(result: Mapping[str, object], output_format: str) -> str:
    if output_format == "json":
        return json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if output_format != "markdown":
        raise ValueError(f"unsupported output format: {output_format}")

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
            "Load public-safe cases, run baseline and Closure Guard policies, "
            "grade outcomes, calculate metrics, and enforce regression checks."
        ),
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
        if args.cases:
            suite = load_case_suite(args.cases)
        elif DEFAULT_CASE_PATH.exists():
            suite = load_case_suite(DEFAULT_CASE_PATH)
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
