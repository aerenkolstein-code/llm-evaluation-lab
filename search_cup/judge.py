"""Hidden-registry gate and deterministic SEARCH-CUP-02 judge."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Mapping

from .contracts import (
    JudgeRegistrySnapshot,
    RegistryLeadAssessment,
    canonical_json,
    fingerprint,
)
from .runner import MatchRun


class RegistryAccessDenied(RuntimeError):
    pass


class HiddenRegistryGate:
    """Open the answer key only after every entrant is frozen and closed."""

    @staticmethod
    def open(
        match: MatchRun,
        snapshot: JudgeRegistrySnapshot,
    ) -> JudgeRegistrySnapshot:
        if not match.entrant_execution_closed:
            raise RegistryAccessDenied("entrant execution is still open")
        if not match.all_frozen:
            raise RegistryAccessDenied(
                "all configured entrant submissions must be frozen before judging"
            )
        snapshot.verify()
        return snapshot


@dataclass(frozen=True)
class LeadJudgment:
    source_url: str
    real_open_points: float
    practical_fit_points: float
    novelty_points: float
    geography_points: float
    actionability_points: float
    penalty: float
    apply_now: bool
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class SearchBehaviorProfile:
    entrant_id: str
    lead_count: int
    search_calls: int
    precision: float
    novelty_yield: float
    false_well_rate: float
    geography_error_rate: float


@dataclass(frozen=True)
class CompetitionScore:
    entrant_id: str
    provider: str
    exact_model_id: str
    real_open: float
    practical_fit: float
    novelty: float
    geography: float
    actionability: float
    search_efficiency: float
    penalties: float
    total: float
    submission_sha256: str
    judgments: tuple[LeadJudgment, ...]
    behavior: SearchBehaviorProfile


@dataclass(frozen=True)
class CompetitionReport:
    competition_id: str
    candidate_fingerprint: str
    competition_fingerprint: str
    registry_fingerprint: str
    scores: tuple[CompetitionScore, ...]
    report_fingerprint: str

    def as_dict(self) -> dict[str, object]:
        return {
            "competition_id": self.competition_id,
            "candidate_fingerprint": self.candidate_fingerprint,
            "competition_fingerprint": self.competition_fingerprint,
            "registry_fingerprint": self.registry_fingerprint,
            "scores": [asdict(score) for score in self.scores],
            "report_fingerprint": self.report_fingerprint,
        }

    def render_json(self) -> str:
        return (
            json.dumps(
                self.as_dict(), ensure_ascii=False, indent=2, sort_keys=True
            )
            + "\n"
        )

    def render_markdown(self) -> str:
        lines = [
            f"# {self.competition_id} Offline Scoreboard",
            "",
            f"- Candidate fingerprint: `{self.candidate_fingerprint}`",
            f"- Competition fingerprint: `{self.competition_fingerprint}`",
            f"- Registry fingerprint: `{self.registry_fingerprint}`",
            f"- Report fingerprint: `{self.report_fingerprint}`",
            "",
            "| Entrant | Exact model | Real/open | Fit | Novelty | Geography | "
            "Action | Efficiency | Penalties | Total |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for score in self.scores:
            lines.append(
                f"| {score.entrant_id} | {score.exact_model_id} | "
                f"{score.real_open:.2f} | {score.practical_fit:.2f} | "
                f"{score.novelty:.2f} | {score.geography:.2f} | "
                f"{score.actionability:.2f} | {score.search_efficiency:.2f} | "
                f"-{score.penalties:.2f} | **{score.total:.2f}** |"
            )
        lines.extend(
            [
                "",
                "> Offline fake evidence only. No live model, search, "
                "application, or production claim.",
                "",
            ]
        )
        return "\n".join(lines)


def _assessment_map(
    snapshot: JudgeRegistrySnapshot,
) -> Mapping[str, RegistryLeadAssessment]:
    return {item.key: item for item in snapshot.assessments}


def _lead_judgment(
    lead: object,
    assessment: RegistryLeadAssessment,
    known: set[str],
    apply_now: set[str],
) -> LeadJudgment:
    source_url = str(getattr(lead, "source_url"))
    key = source_url.strip().rstrip("/").lower()
    is_apply_now = source_url in apply_now
    multiplier = 2.0 if is_apply_now else 1.0
    reasons: list[str] = []

    if assessment.fabricated:
        reasons.append("fabricated lead: score forced to zero")
        return LeadJudgment(
            source_url=source_url,
            real_open_points=0.0,
            practical_fit_points=0.0,
            novelty_points=0.0,
            geography_points=0.0,
            actionability_points=0.0,
            penalty=0.0,
            apply_now=is_apply_now,
            reasons=tuple(reasons),
        )

    penalty = 0.0
    open_status = str(getattr(lead, "open_status"))
    claimed_novel = bool(getattr(lead, "claimed_novel"))
    official_source = bool(getattr(lead, "official_source"))
    remote_scope = str(getattr(lead, "remote_scope")).lower()
    if not assessment.real_open and open_status == "OPEN":
        penalty += 5.0 * multiplier
        reasons.append("closed/stale role reported as open")
    if assessment.us_only and any(term in remote_scope for term in ("world", "europe", "emea")):
        penalty += 8.0 * multiplier
        reasons.append("US-only role overstated as geographically applicable")
    if assessment.senior_or_phd_mismatch:
        penalty += 5.0 * multiplier
        reasons.append("senior/PhD mismatch sold as fit")
    if key in known and claimed_novel:
        penalty += 3.0 * multiplier
        reasons.append("known well presented as novel")
    if not assessment.primary_source or not official_source:
        penalty += 3.0 * multiplier
        reasons.append("credible primary source missing")

    return LeadJudgment(
        source_url=source_url,
        real_open_points=25.0 if assessment.real_open else 0.0,
        practical_fit_points=25.0 if assessment.practical_fit else 0.0,
        novelty_points=20.0 if key not in known else 0.0,
        geography_points=15.0 if assessment.geography_eligible else 0.0,
        actionability_points=10.0 if assessment.actionable else 0.0,
        penalty=penalty,
        apply_now=is_apply_now,
        reasons=tuple(reasons),
    )


def judge_match(
    match: MatchRun,
    snapshot: JudgeRegistrySnapshot,
) -> CompetitionReport:
    """Score frozen evidence only; this function performs no tool/model call."""

    opened = HiddenRegistryGate.open(match, snapshot)
    assessments = _assessment_map(opened)
    known = set(opened.known_well_keys)
    scores: list[CompetitionScore] = []
    for outcome in match.frozen_outcomes:
        frozen = outcome.frozen_submission
        if frozen is None:
            raise ValueError("frozen outcome is missing evidence")
        submission = frozen.thaw_verified()
        apply_now = set(submission.apply_now_urls)
        judgments: list[LeadJudgment] = []
        for lead in submission.leads:
            assessment = assessments.get(lead.key)
            if assessment is None:
                assessment = RegistryLeadAssessment(
                    source_url=lead.source_url,
                    real_open=False,
                    practical_fit=False,
                    geography_eligible=False,
                    actionable=False,
                    primary_source=False,
                )
            judgments.append(_lead_judgment(lead, assessment, known, apply_now))

        count = len(judgments)
        divisor = float(count or 1)
        real = sum(item.real_open_points for item in judgments) / divisor
        fit = sum(item.practical_fit_points for item in judgments) / divisor
        novelty = sum(item.novelty_points for item in judgments) / divisor
        geography = sum(item.geography_points for item in judgments) / divisor
        action = sum(item.actionability_points for item in judgments) / divisor
        penalties = sum(item.penalty for item in judgments) / divisor
        valid_actionable = sum(
            item.real_open_points > 0 and item.actionability_points > 0
            for item in judgments
        )
        efficiency = 5.0 * min(
            1.0,
            valid_actionable / max(1, submission.search_calls),
        )
        total = max(
            0.0,
            min(
                100.0,
                real
                + fit
                + novelty
                + geography
                + action
                + efficiency
                - penalties,
            ),
        )
        false_wells = sum(item.real_open_points == 0 for item in judgments)
        geo_errors = sum(item.geography_points == 0 for item in judgments)
        novel = sum(item.novelty_points > 0 for item in judgments)
        behavior = SearchBehaviorProfile(
            entrant_id=outcome.entrant_id,
            lead_count=count,
            search_calls=submission.search_calls,
            precision=(count - false_wells) / divisor,
            novelty_yield=novel / max(1, submission.search_calls),
            false_well_rate=false_wells / divisor,
            geography_error_rate=geo_errors / divisor,
        )
        scores.append(
            CompetitionScore(
                entrant_id=outcome.entrant_id,
                provider=submission.entrant.provider,
                exact_model_id=submission.entrant.exact_model_id,
                real_open=real,
                practical_fit=fit,
                novelty=novelty,
                geography=geography,
                actionability=action,
                search_efficiency=efficiency,
                penalties=penalties,
                total=total,
                submission_sha256=frozen.sha256,
                judgments=tuple(judgments),
                behavior=behavior,
            )
        )

    ordered = tuple(sorted(scores, key=lambda item: (-item.total, item.entrant_id)))
    payload = {
        "competition_id": match.competition_id,
        "candidate_fingerprint": match.candidate_fingerprint,
        "competition_fingerprint": match.competition_fingerprint,
        "registry_fingerprint": opened.fingerprint,
        "scores": [asdict(item) for item in ordered],
    }
    return CompetitionReport(
        competition_id=match.competition_id,
        candidate_fingerprint=match.candidate_fingerprint,
        competition_fingerprint=match.competition_fingerprint,
        registry_fingerprint=opened.fingerprint,
        scores=ordered,
        report_fingerprint=fingerprint(payload),
    )
