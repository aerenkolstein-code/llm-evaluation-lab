"""First public closed-loop evaluation for Companion-Mind's Closure Guard."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Callable, Iterable, Mapping


Child = Mapping[str, str]
Policy = Callable[[Iterable[Child]], bool]


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


@dataclass(frozen=True)
class PolicyResult:
    policy: str
    accuracy: float
    premature_closure_rate: float
    failures: tuple[str, ...]
    predictions: tuple[dict[str, object], ...]


def naive_any_done(children: Iterable[Child]) -> bool:
    """Known-bad baseline: local completion is mistaken for parent completion."""

    return any(str(child.get("status", "")).upper() == "DONE" for child in children)


def closure_guard_policy(children: Iterable[Child]) -> bool:
    """Use the actual Companion-Mind safeguard as the treatment."""

    try:
        from companion_mind.runtime import ClosureGuard
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "Install the sibling Companion-Mind repository first: "
            "python -m pip install -e ../Companion-Mind"
        ) from exc
    return ClosureGuard().evaluate(children).decision == "ACCEPT"


def evaluate_policy(name: str, policy: Policy) -> PolicyResult:
    predictions: list[dict[str, object]] = []
    failures: list[str] = []
    negatives = 0
    premature = 0

    for case in CASES:
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
        accuracy=(len(CASES) - len(failures)) / len(CASES),
        premature_closure_rate=premature / negatives,
        failures=tuple(failures),
        predictions=tuple(predictions),
    )


def run_experiment() -> dict[str, object]:
    baseline = evaluate_policy("naive_any_done", naive_any_done)
    treatment = evaluate_policy("CM-GUARD-001", closure_guard_policy)
    regression_probe = evaluate_policy("known_bad_regression_probe", naive_any_done)
    return {
        "run_id": "EVAL-RUN-001",
        "case_id": "EVAL-CASE-001",
        "mitigation_id": "MIT-CLOSURE-GUARD-001",
        "safeguard_id": "CM-GUARD-001",
        "fixture_count": len(CASES),
        "baseline": asdict(baseline),
        "treatment": asdict(treatment),
        "accuracy_delta": treatment.accuracy - baseline.accuracy,
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


def main() -> None:
    import json

    print(json.dumps(run_experiment(), ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()

