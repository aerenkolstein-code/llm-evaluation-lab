"""Closed-book, provider-isolated match runner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

from .contracts import (
    CandidateCard,
    CompetitionSpec,
    FrozenSubmission,
    SearchResult,
    SearchTrace,
    URLReadResult,
)
from .providers import EntrantProvider
from .tools import BudgetedSearchProxy, EntrantTools, FakeSearchBackend, FakeURLReader


SearchFixtures = Mapping[str, tuple[SearchResult, ...]]
URLFixtures = Mapping[str, URLReadResult]
SearchFixtureFactory = Callable[[str], SearchFixtures]
URLFixtureFactory = Callable[[str], URLFixtures]


@dataclass(frozen=True)
class EntrantOutcome:
    entrant_id: str
    status: str
    frozen_submission: FrozenSubmission | None
    traces: tuple[SearchTrace, ...]
    error_type: str | None = None
    error_message: str | None = None


@dataclass(frozen=True)
class MatchRun:
    competition_id: str
    candidate_fingerprint: str
    competition_fingerprint: str
    expected_entrant_ids: tuple[str, ...]
    outcomes: tuple[EntrantOutcome, ...]
    entrant_execution_closed: bool

    @property
    def frozen_outcomes(self) -> tuple[EntrantOutcome, ...]:
        return tuple(item for item in self.outcomes if item.status == "FROZEN")

    @property
    def failed_outcomes(self) -> tuple[EntrantOutcome, ...]:
        return tuple(item for item in self.outcomes if item.status == "FAILED")

    @property
    def all_frozen(self) -> bool:
        return (
            self.entrant_execution_closed
            and len(self.outcomes) == len(self.expected_entrant_ids)
            and all(item.status == "FROZEN" for item in self.outcomes)
        )


def run_match(
    candidate: CandidateCard,
    competition: CompetitionSpec,
    providers: Mapping[str, EntrantProvider],
    *,
    search_fixtures: SearchFixtureFactory,
    url_fixtures: URLFixtureFactory,
) -> MatchRun:
    """Run all entrants independently and preserve evidence from partial success."""

    outcomes: list[EntrantOutcome] = []
    expected = tuple(item.entrant_id for item in competition.entrants)
    for entrant in competition.entrants:
        proxy = BudgetedSearchProxy(
            entrant_id=entrant.entrant_id,
            max_calls=competition.max_search_calls,
            backend=FakeSearchBackend(search_fixtures(entrant.entrant_id)),
        )
        tools = EntrantTools(
            search_proxy=proxy,
            url_reader=FakeURLReader(url_fixtures(entrant.entrant_id)),
        )
        provider = providers.get(entrant.entrant_id)
        if provider is None:
            outcomes.append(
                EntrantOutcome(
                    entrant_id=entrant.entrant_id,
                    status="FAILED",
                    frozen_submission=None,
                    traces=(),
                    error_type="MissingProvider",
                    error_message="no provider adapter configured",
                )
            )
            continue
        try:
            submission = provider.run(
                candidate_content=candidate.canonical_bytes,
                competition_content=competition.canonical_bytes,
                candidate_fingerprint=candidate.fingerprint,
                competition_fingerprint=competition.fingerprint,
                entrant=entrant,
                tools=tools,
            )
            if submission.entrant != entrant:
                raise ValueError("provider changed entrant identity or configuration")
            if submission.candidate_fingerprint != candidate.fingerprint:
                raise ValueError("provider returned a different Candidate Card fingerprint")
            if submission.competition_fingerprint != competition.fingerprint:
                raise ValueError("provider returned a different CompetitionSpec fingerprint")
            if submission.search_calls != tools.search_calls:
                raise ValueError("provider search-call count does not match tool trace")
            frozen = FrozenSubmission.freeze(submission)
            outcomes.append(
                EntrantOutcome(
                    entrant_id=entrant.entrant_id,
                    status="FROZEN",
                    frozen_submission=frozen,
                    traces=tools.traces,
                )
            )
        except Exception as exc:
            outcomes.append(
                EntrantOutcome(
                    entrant_id=entrant.entrant_id,
                    status="FAILED",
                    frozen_submission=None,
                    traces=tools.traces,
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                )
            )

    return MatchRun(
        competition_id=competition.competition_id,
        candidate_fingerprint=candidate.fingerprint,
        competition_fingerprint=competition.fingerprint,
        expected_entrant_ids=expected,
        outcomes=tuple(outcomes),
        entrant_execution_closed=True,
    )
