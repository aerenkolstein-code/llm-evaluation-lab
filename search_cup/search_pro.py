"""Narrow P1 adapter for Zhipu's real ``search_pro`` Web Search API."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from typing import Callable, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from uuid import uuid4

from .contracts import SearchRequest, SearchResult
from .tools import (
    BudgetedSearchProxy,
    EntrantTools,
    FakeURLReader,
    SearchBackendError,
    SearchBackendResponse,
)


SEARCH_PRO_BACKEND_ID = "zhipu-web-search/search_pro"
SEARCH_PRO_ENDPOINT = "https://open.bigmodel.cn/api/paas/v4/web_search"


@dataclass(frozen=True)
class TransportResponse:
    status_code: int
    body: bytes


SearchTransport = Callable[
    [str, Mapping[str, str], Mapping[str, object], float], TransportResponse
]


def _default_transport(
    endpoint: str,
    headers: Mapping[str, str],
    payload: Mapping[str, object],
    timeout_seconds: float,
) -> TransportResponse:
    request = Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=dict(headers),
        method="POST",
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return TransportResponse(
                status_code=int(response.status),
                body=response.read(),
            )
    except HTTPError as exc:
        return TransportResponse(status_code=int(exc.code), body=exc.read())
    except (URLError, TimeoutError, OSError) as exc:
        raise SearchBackendError(
            f"search_pro network request failed: {type(exc).__name__}",
            backend_id=SEARCH_PRO_BACKEND_ID,
            error_code="NETWORK_ERROR",
            retryable=True,
        ) from exc


def _text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _decode_json(body: bytes, request_id: str) -> Mapping[str, object]:
    try:
        document = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SearchBackendError(
            "search_pro returned invalid JSON",
            backend_id=SEARCH_PRO_BACKEND_ID,
            error_code="INVALID_JSON",
            request_id=request_id,
        ) from exc
    if not isinstance(document, Mapping):
        raise SearchBackendError(
            "search_pro returned a non-object response",
            backend_id=SEARCH_PRO_BACKEND_ID,
            error_code="INVALID_RESPONSE",
            request_id=request_id,
        )
    return document


def _error_details(document: Mapping[str, object]) -> tuple[str, str]:
    error = document.get("error")
    if not isinstance(error, Mapping):
        return "HTTP_ERROR", "search_pro request failed"
    code = _text(error.get("code")) or "API_ERROR"
    message = _text(error.get("message")) or "search_pro request failed"
    return code, message[:500]


class SearchProBackend:
    """One SearchRequest becomes exactly one HTTP request; no hidden retries."""

    backend_id = SEARCH_PRO_BACKEND_ID

    def __init__(
        self,
        api_key: str,
        *,
        count: int = 10,
        timeout_seconds: float = 30.0,
        endpoint: str = SEARCH_PRO_ENDPOINT,
        transport: SearchTransport = _default_transport,
    ) -> None:
        if not api_key.strip():
            raise ValueError("search_pro API key must not be empty")
        if not 1 <= count <= 50:
            raise ValueError("search_pro count must be between 1 and 50")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._api_key = api_key.strip()
        self._count = count
        self._timeout_seconds = timeout_seconds
        self._endpoint = endpoint
        self._transport = transport

    @classmethod
    def from_env(
        cls,
        env_name: str = "GLM_API_KEY",
        **kwargs: object,
    ) -> "SearchProBackend":
        api_key = os.environ.get(env_name, "")
        if not api_key.strip():
            raise RuntimeError(f"required API key environment variable is not set: {env_name}")
        return cls(api_key, **kwargs)

    def __call__(self, request: SearchRequest) -> SearchBackendResponse:
        request_id = request.request_id or f"sc-{uuid4().hex}"
        if len(request.query) > 70:
            raise SearchBackendError(
                "search_pro query exceeds the 70-character API limit",
                backend_id=self.backend_id,
                error_code="INVALID_QUERY",
                request_id=request_id,
            )
        payload = {
            "search_query": request.query,
            "search_engine": "search_pro",
            "search_intent": False,
            "count": self._count,
            "search_recency_filter": "noLimit",
            "content_size": "medium",
            "request_id": request_id,
        }
        response = self._transport(
            self._endpoint,
            {
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            payload,
            self._timeout_seconds,
        )
        if not 200 <= response.status_code < 300:
            try:
                document = _decode_json(response.body, request_id)
            except SearchBackendError as exc:
                raise SearchBackendError(
                    f"search_pro HTTP {response.status_code} returned no valid error object",
                    backend_id=self.backend_id,
                    error_code=f"HTTP_{response.status_code}",
                    request_id=request_id,
                    http_status=response.status_code,
                    retryable=response.status_code in {408, 429, 500, 502, 503, 504},
                ) from exc
            response_request_id = _text(document.get("request_id")) or request_id
            response_id = _text(document.get("id")) or None
            code, message = _error_details(document)
            raise SearchBackendError(
                f"search_pro request failed: {code}: {message}",
                backend_id=self.backend_id,
                error_code=code,
                request_id=response_request_id,
                response_id=response_id,
                http_status=response.status_code,
                retryable=response.status_code in {408, 429, 500, 502, 503, 504},
            )
        document = _decode_json(response.body, request_id)
        response_request_id = _text(document.get("request_id")) or request_id
        response_id = _text(document.get("id")) or None
        if "error" in document:
            code, message = _error_details(document)
            raise SearchBackendError(
                f"search_pro request failed: {code}: {message}",
                backend_id=self.backend_id,
                error_code=code,
                request_id=response_request_id,
                response_id=response_id,
                http_status=response.status_code,
                retryable=False,
            )
        raw_results = document.get("search_result")
        if not isinstance(raw_results, list):
            raise SearchBackendError(
                "search_pro response is missing search_result[]",
                backend_id=self.backend_id,
                error_code="INVALID_RESPONSE",
                request_id=response_request_id,
                response_id=response_id,
                http_status=response.status_code,
            )
        normalized: list[SearchResult] = []
        for index, item in enumerate(raw_results):
            if not isinstance(item, Mapping):
                raise SearchBackendError(
                    f"search_pro result {index} is not an object",
                    backend_id=self.backend_id,
                    error_code="INVALID_RESULT",
                    request_id=response_request_id,
                    response_id=response_id,
                    http_status=response.status_code,
                )
            title = _text(item.get("title"))
            url = _text(item.get("link"))
            if not title or not url:
                raise SearchBackendError(
                    f"search_pro result {index} is missing title or link",
                    backend_id=self.backend_id,
                    error_code="INVALID_RESULT",
                    request_id=response_request_id,
                    response_id=response_id,
                    http_status=response.status_code,
                )
            normalized.append(
                SearchResult(
                    title=title,
                    url=url,
                    snippet=_text(item.get("content")),
                )
            )
        return SearchBackendResponse(
            results=tuple(normalized),
            backend_id=self.backend_id,
            request_id=response_request_id,
            response_id=response_id,
        )


def run_live_smoke(
    queries: Sequence[str],
    *,
    api_key_env: str = "GLM_API_KEY",
    count: int = 5,
    timeout_seconds: float = 30.0,
) -> tuple[dict[str, object], bool]:
    """Run at most three non-official Fake Entrant queries through the real backend."""

    normalized_queries = tuple(query.strip() for query in queries if query.strip())
    if not 1 <= len(normalized_queries) <= 3:
        raise ValueError("P1 live smoke requires between one and three non-empty queries")
    backend = SearchProBackend.from_env(
        api_key_env,
        count=count,
        timeout_seconds=timeout_seconds,
    )
    proxy = BudgetedSearchProxy(
        entrant_id="fake-search-pro-smoke",
        max_calls=20,
        backend=backend,
    )
    tools = EntrantTools(search_proxy=proxy, url_reader=FakeURLReader({}))
    calls: list[dict[str, object]] = []
    smoke_green = True
    for query in normalized_queries:
        try:
            results = tools.search_web(query)
            if not results:
                smoke_green = False
            calls.append(
                {
                    "query": query,
                    "status": "SUCCEEDED",
                    "results": [asdict(item) for item in results],
                }
            )
            if not results:
                break
        except SearchBackendError as exc:
            smoke_green = False
            calls.append(
                {
                    "query": query,
                    "status": "FAILED",
                    "error_type": type(exc).__name__,
                    "error_code": exc.error_code,
                    "error_message": str(exc),
                }
            )
            break
    artifact = {
        "phase": "ENG-SC-01-P1",
        "gate": "GREEN" if smoke_green else "RED",
        "entrant_type": "Fake Entrant",
        "backend_id": SEARCH_PRO_BACKEND_ID,
        "search_budget": 20,
        "calls_requested": len(normalized_queries),
        "calls_used": tools.search_calls,
        "automatic_retries": 0,
        "official_match_authorized": False,
        "provider_adapters_invoked": 0,
        "hidden_registry_loaded": False,
        "credentials_logged": False,
        "calls": calls,
        "traces": [asdict(trace) for trace in tools.traces],
    }
    return artifact, smoke_green
