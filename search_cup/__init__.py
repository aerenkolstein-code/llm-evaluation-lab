"""Closed-book, provider-neutral search benchmark primitives."""

from .contracts import (
    CandidateCard,
    CompetitionSpec,
    EntrantConfig,
    FrozenSubmission,
    JudgeRegistrySnapshot,
    Lead,
    RegistryLeadAssessment,
    Submission,
)
from .judge import CompetitionReport, HiddenRegistryGate, judge_match
from .runner import MatchRun, run_match
from .search_pro import SearchProBackend

__all__ = [
    "CandidateCard",
    "CompetitionReport",
    "CompetitionSpec",
    "EntrantConfig",
    "FrozenSubmission",
    "HiddenRegistryGate",
    "JudgeRegistrySnapshot",
    "Lead",
    "MatchRun",
    "RegistryLeadAssessment",
    "Submission",
    "SearchProBackend",
    "judge_match",
    "run_match",
]
