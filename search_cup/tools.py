"""Provider-neutral, budgeted tool boundary for SEARCH-CUP-02."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Sequence

from .contracts import SearchRequest, SearchResult, SearchTrace, URLReadResult


class SearchBudgetExceeded(RuntimeError):
    """Raised before any backend call when an entrant has spent all tickets."""


SearchBackend = Callable[[SearchRequest], Sequence[SearchResult]]


class BudgetedSearchProxy:
    """Count every attempted backend call exactly once and reject call 21."""

    def __init__(
        self,
        entrant_id: str,
        max_calls: int,
        backend: SearchBackend,
    ) -> None:
        if max_calls < 1:
            raise ValueError("max_calls must be positive")
        self._entrant_id = entrant_id
        self._max_calls = max_calls
        self._backend = backend
        self._traces: list[SearchTrace] = []

    @property
    def traces(self) -> tuple[SearchTrace, ...]:
        return tuple(self._traces)

    @property
    def calls_used(self) -> int:
        return len(self._traces)

    def search(self, query: str) -> tuple[SearchResult, ...]:
        if self.calls_used >= self._max_calls:
            raise SearchBudgetExceeded(
                f"{self._entrant_id}: search call {self.calls_used + 1} rejected; "
                f"budget is {self._max_calls}"
            )
        request = SearchRequest(entrant_id=self._entrant_id, query=query)
        call_number = self.calls_used + 1
        try:
            results = tuple(self._backend(request))
        except Exception as exc:
            self._traces.append(
                SearchTrace(
                    entrant_id=self._entrant_id,
                    call_number=call_number,
                    query=query,
                    status="FAILED",
                    result_count=0,
                    error_type=type(exc).__name__,
                )
            )
            raise
        self._traces.append(
            SearchTrace(
                entrant_id=self._entrant_id,
                call_number=call_number,
                query=query,
                status="SUCCEEDED",
                result_count=len(results),
            )
        )
        return results


class FakeSearchBackend:
    """Offline backend whose complete result set is supplied by a fixture."""

    def __init__(self, results_by_query: Mapping[str, Sequence[SearchResult]]) -> None:
        self._results = {
            query: tuple(results) for query, results in results_by_query.items()
        }

    def __call__(self, request: SearchRequest) -> tuple[SearchResult, ...]:
        return self._results.get(request.query, ())


class FakeURLReader:
    """Offline URL reader with typed outcomes and no network fallback."""

    def __init__(self, results_by_url: Mapping[str, URLReadResult]) -> None:
        self._results = dict(results_by_url)

    def read(self, url: str) -> URLReadResult:
        return self._results.get(url, URLReadResult(url=url, status="NOT_FOUND"))


@dataclass(frozen=True)
class EntrantTools:
    """The only tool surface passed to an entrant; it has no registry handle."""

    search_proxy: BudgetedSearchProxy
    url_reader: FakeURLReader

    def search_web(self, query: str) -> tuple[SearchResult, ...]:
        return self.search_proxy.search(query)

    def read_url(self, url: str) -> URLReadResult:
        return self.url_reader.read(url)

    @property
    def search_calls(self) -> int:
        return self.search_proxy.calls_used

    @property
    def traces(self) -> tuple[SearchTrace, ...]:
        return self.search_proxy.traces
