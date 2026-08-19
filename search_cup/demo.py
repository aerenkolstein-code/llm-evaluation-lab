"""Deterministic four-entrant P0 demonstration using synthetic fixtures."""

from __future__ import annotations

import sys
from pathlib import Path

from .contracts import (
    CandidateCard,
    CompetitionSpec,
    JudgeRegistrySnapshot,
    Lead,
    RegistryLeadAssessment,
    SearchResult,
    URLReadResult,
)
from .judge import CompetitionReport, judge_match
from .providers import FakeProvider
from .runner import MatchRun, run_match


ROOT = Path(__file__).resolve().parent.parent


def _data_path(directory: str, filename: str) -> Path:
    source_tree = ROOT / directory / filename
    if source_tree.is_file():
        return source_tree
    return Path(sys.prefix) / directory / filename


DEFAULT_CANDIDATE = _data_path(
    "candidates", "curator-jieyi-pan.public-safe.json"
)
DEFAULT_COMPETITION = _data_path(
    "competitions", "search-cup-02.offline.json"
)


def _lead(index: int, *, known: bool = False, stale: bool = False) -> Lead:
    url = f"https://jobs.example.test/ai-evaluation-{index}"
    return Lead(
        company=f"Synthetic Employer {index}",
        role="AI Evaluation Engineer",
        source_url=url,
        official_source=True,
        open_status="OPEN" if not stale else "OPEN",
        remote_scope="Europe Remote",
        location_constraint="Spain / Europe eligible",
        employment_type="Contract",
        required_skills=("Python", "LLM evaluation"),
        candidate_fit="Public portfolio demonstrates relevant evaluation engineering.",
        mismatch_risks=(),
        portfolio_relevance="Directly relevant to both public repositories.",
        confidence=0.9,
        next_action="Human review of the synthetic official fixture.",
        evidence_urls=(url,),
        claimed_novel=not known,
    )


def build_offline_demo(
    candidate_path: str | Path = DEFAULT_CANDIDATE,
    competition_path: str | Path = DEFAULT_COMPETITION,
) -> tuple[MatchRun, JudgeRegistrySnapshot, CompetitionReport]:
    candidate = CandidateCard.load(candidate_path)
    competition = CompetitionSpec.load(competition_path)
    if competition.official_match_authorized:
        raise ValueError("P0 offline demo refuses an authorized official-match spec")
    providers: dict[str, FakeProvider] = {}
    search_by_entrant: dict[str, dict[str, tuple[SearchResult, ...]]] = {}
    url_by_entrant: dict[str, dict[str, URLReadResult]] = {}
    assessments: list[RegistryLeadAssessment] = []
    known_urls: list[str] = []

    for index, entrant in enumerate(competition.entrants, start=1):
        known = index == 2
        stale = index == 3
        lead = _lead(index, known=known, stale=stale)
        query = f"synthetic ai evaluation opportunity {index}"
        providers[entrant.entrant_id] = FakeProvider(
            queries=(query,),
            leads=(lead,),
            apply_now_urls=(lead.source_url,),
        )
        search_by_entrant[entrant.entrant_id] = {
            query: (
                SearchResult(
                    title=f"Synthetic result {index}",
                    url=lead.source_url,
                    snippet="Offline fixture; not a real job listing.",
                ),
            )
        }
        url_by_entrant[entrant.entrant_id] = {
            lead.source_url: URLReadResult(
                url=lead.source_url,
                status="OK",
                title=f"Synthetic role {index}",
                text="Deterministic public-safe offline fixture.",
            )
        }
        if known:
            known_urls.append(lead.source_url)
        assessments.append(
            RegistryLeadAssessment(
                source_url=lead.source_url,
                real_open=not stale,
                practical_fit=not stale,
                geography_eligible=True,
                actionable=not stale,
                primary_source=True,
            )
        )

    match = run_match(
        candidate,
        competition,
        providers,
        search_fixtures=lambda entrant_id: search_by_entrant[entrant_id],
        url_fixtures=lambda entrant_id: url_by_entrant[entrant_id],
    )
    snapshot = JudgeRegistrySnapshot.create(
        "SYNTHETIC-REGISTRY-P0",
        known_urls,
        assessments,
    )
    report = judge_match(match, snapshot)
    return match, snapshot, report
