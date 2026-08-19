"""Provider-neutral, budgeted tool boundary for SEARCH-CUP-02."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from typing import Callable, Mapping, Sequence
from uuid import uuid4

from .contracts import SearchRequest, SearchResult, SearchTrace, URLReadResult


class SearchBudgetExceeded(RuntimeError):
    """Raised before any backend call when an entrant has spent all tickets."""


class SearchBackendError(RuntimeError):
    """Typed, credential-free failure surfaced by a live search backend."""

    def __init__(
        self,
        message: str,
        *,
        backend_id: str,
        error_code: str,
        request_id: str | None = None,
        response_id: str | None = None,
        http_status: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.backend_id = backend_id
        self.error_code = error_code
        self.request_id = request_id
        self.response_id = response_id
        self.http_status = http_status
        self.retryable = retryable


@dataclass(frozen=True)
class SearchBackendResponse:
    """Provider response normalized before it crosses the SearchProxy boundary."""

    results: tuple[SearchResult, ...]
    backend_id: str
    request_id: str
    response_id: str | None = None


SearchBackend = Callable[
    [SearchRequest], SearchBackendResponse | Sequence[SearchResult]
]


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
        call_number = self.calls_used + 1
        request_id = f"sc-{uuid4().hex}"
        started_at = datetime.now(timezone.utc).isoformat()
        started_clock = perf_counter()
        backend_id = getattr(self._backend, "backend_id", type(self._backend).__name__)
        try:
            request = SearchRequest(
                entrant_id=self._entrant_id,
                query=query,
                call_number=call_number,
                request_id=request_id,
            )
            raw_response = self._backend(request)
            if isinstance(raw_response, SearchBackendResponse):
                results = raw_response.results
                backend_id = raw_response.backend_id
                backend_request_id = raw_response.request_id
                backend_response_id = raw_response.response_id
            else:
                results = tuple(raw_response)
                backend_request_id = request_id
                backend_response_id = None
            if not all(isinstance(item, SearchResult) for item in results):
                raise TypeError("search backend returned a non-SearchResult item")
        except SearchBackendError as exc:
            duration_ms = round((perf_counter() - started_clock) * 1000, 3)
            self._traces.append(
                SearchTrace(
                    entrant_id=self._entrant_id,
                    call_number=call_number,
                    query=query,
                    status="FAILED",
                    result_count=0,
                    error_type=type(exc).__name__,
                    error_code=exc.error_code,
                    error_message=str(exc),
                    backend_id=exc.backend_id,
                    backend_request_id=exc.request_id or request_id,
                    backend_response_id=exc.response_id,
                    http_status=exc.http_status,
                    retryable=exc.retryable,
                    started_at_utc=started_at,
                    duration_ms=duration_ms,
                )
            )
            raise
        except Exception as exc:
            duration_ms = round((perf_counter() - started_clock) * 1000, 3)
            self._traces.append(
                SearchTrace(
                    entrant_id=self._entrant_id,
                    call_number=call_number,
                    query=query,
                    status="FAILED",
                    result_count=0,
                    error_type=type(exc).__name__,
                    error_code="UNEXPECTED_BACKEND_ERROR",
                    error_message=str(exc),
                    backend_id=str(backend_id),
                    backend_request_id=request_id,
                    retryable=False,
                    started_at_utc=started_at,
                    duration_ms=duration_ms,
                )
            )
            raise
        duration_ms = round((perf_counter() - started_clock) * 1000, 3)
        self._traces.append(
            SearchTrace(
                entrant_id=self._entrant_id,
                call_number=call_number,
                query=query,
                status="SUCCEEDED",
                result_count=len(results),
                backend_id=str(backend_id),
                backend_request_id=backend_request_id,
                backend_response_id=backend_response_id,
                http_status=200,
                retryable=False,
                started_at_utc=started_at,
                duration_ms=duration_ms,
            )
        )
        return tuple(results)


class FakeSearchBackend:
    """Offline backend whose complete result set is supplied by a fixture."""

    def __init__(self, results_by_query: Mapping[str, Sequence[SearchResult]]) -> None:
        self.backend_id = "fake-search-pro-offline"
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
