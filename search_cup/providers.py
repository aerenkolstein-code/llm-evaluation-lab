"""Entrant adapter contract and deterministic offline providers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from .contracts import EntrantConfig, Lead, Submission
from .tools import EntrantTools


class EntrantProvider(Protocol):
    """Provider adapters may translate syntax, but receive identical semantics."""

    def run(
        self,
        *,
        candidate_content: bytes,
        competition_content: bytes,
        candidate_fingerprint: str,
        competition_fingerprint: str,
        entrant: EntrantConfig,
        tools: EntrantTools,
    ) -> Submission: ...


@dataclass(frozen=True)
class FakeProvider:
    """Offline entrant used to verify orchestration without model API calls."""

    queries: tuple[str, ...]
    leads: tuple[Lead, ...]
    apply_now_urls: tuple[str, ...]
    search_strategy_summary: str = "offline deterministic discovery and verification"
    rejected_or_downgraded: tuple[str, ...] = ()
    uncertainties: tuple[str, ...] = ()

    def run(
        self,
        *,
        candidate_content: bytes,
        competition_content: bytes,
        candidate_fingerprint: str,
        competition_fingerprint: str,
        entrant: EntrantConfig,
        tools: EntrantTools,
    ) -> Submission:
        if not candidate_content or not competition_content:
            raise ValueError("canonical candidate and competition content are required")
        for query in self.queries:
            results = tools.search_web(query)
            for result in results:
                tools.read_url(result.url)
        return Submission(
            entrant=entrant,
            candidate_fingerprint=candidate_fingerprint,
            competition_fingerprint=competition_fingerprint,
            leads=self.leads,
            apply_now_urls=self.apply_now_urls,
            search_strategy_summary=self.search_strategy_summary,
            rejected_or_downgraded=self.rejected_or_downgraded,
            uncertainties=self.uncertainties,
            search_calls=tools.search_calls,
        )

@dataclass(frozen=True)
class FailingFakeProvider:
    """Fault injection adapter for provider-isolation tests."""

    message: str = "injected provider failure"

    def run(self, **_: object) -> Submission:
        raise RuntimeError(self.message)


class LiveProviderNotImplemented(RuntimeError):
    pass


@dataclass(frozen=True)
class LockedLiveProvider:
    """Explicit P0 stop: no paid/live provider can execute from this branch."""

    provider: str

    def run(self, **_: object) -> Submission:
        raise LiveProviderNotImplemented(
            f"{self.provider}: live adapters are outside ENG-SC-01-P0"
        )
