"""T6 Brave Web Search RAW candidate. No default transport, key lookup or retry.

An HTTP-shaped transport is explicitly injected. Qualification supplies only a
fake transport; publishing this module does not grant live execution authority.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from time import perf_counter
from types import MappingProxyType
from typing import Callable, Mapping
from urllib.parse import urlencode, urlsplit
from uuid import uuid4

from .contracts import SearchRequest, SearchResult, canonical_json, fingerprint
from .protocol_v23 import assert_content_safe
from .tools import SearchBackendError, SearchBackendResponse

CANDIDATE_ID = "search-cup-v23-live-brave-web-raw-v1"
BACKEND_ID = "brave-search-api/web"
API_VERSION = "2023-01-01"
DEFAULT_CONFIG = MappingProxyType({
    "schema_id": "search-cup-v23-live-brave-raw-config/v1",
    "candidate_id": CANDIDATE_ID, "backend_id": BACKEND_ID,
    "endpoint": "https://api.search.brave.com/res/v1/web/search", "method": "GET",
    "api_version": API_VERSION, "result_filter": "web", "count": 10,
    "offset": 0, "country": "US", "search_lang": "en", "ui_lang": "en-US",
    "spellcheck": False, "text_decorations": False, "summary": False,
    "extra_snippets": False, "enable_rich_callback": False,
    "include_fetch_metadata": False, "operators": False, "safesearch": "moderate",
    "goggles": None, "freshness": None, "automatic_retries": 0,
    "fallback_policy": "NONE", "follow_links": 0, "timeout_per_call_ms": 15000,
    "max_response_bytes": 1048576,
})
PARAMETERS = (
    "result_filter", "count", "offset", "country", "search_lang", "ui_lang",
    "spellcheck", "text_decorations", "summary", "extra_snippets",
    "enable_rich_callback", "include_fetch_metadata", "operators", "safesearch",
)


@dataclass(frozen=True)
class WebRequest:
    method: str
    url: str
    headers: tuple[tuple[str, str], ...]
    timeout_ms: int


@dataclass(frozen=True)
class WebResponse:
    status: int
    body: bytes


Transport = Callable[[WebRequest], WebResponse]


def validate_config(config: Mapping[str, object]) -> dict:
    """Closed exact profile: reject unknown keys, coercions and any mutation."""
    value = dict(config)
    if canonical_json(value) != canonical_json(dict(DEFAULT_CONFIG)):
        raise ValueError("CONFIG_DRIFT")
    return value


def _pairs(pairs: list[tuple[str, object]]) -> dict:
    result: dict = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _invalid_constant(_: str) -> None:
    raise ValueError("non-finite JSON")


def _safe_url(value: str) -> bool:
    try:
        parts = urlsplit(value)
        return (parts.scheme in {"http", "https"} and bool(parts.hostname)
                and parts.username is None and parts.password is None)
    except ValueError:
        return False


class BraveWebRawRetriever:
    backend_id = BACKEND_ID

    def __init__(self, transport: Transport | None = None,
                 config: Mapping[str, object] = DEFAULT_CONFIG) -> None:
        self._config_json = canonical_json(validate_config(config))
        self._transport = transport
        self._receipts: list[dict] = []

    @property
    def config(self) -> Mapping[str, object]:
        return MappingProxyType(json.loads(self._config_json))

    @property
    def config_fingerprint(self) -> str:
        return fingerprint(dict(self.config))

    @property
    def receipts(self) -> tuple[dict, ...]:
        # Return detached values: callers cannot rewrite already observed traces.
        return tuple(json.loads(canonical_json(row)) for row in self._receipts)

    def build_request(self, request: SearchRequest) -> WebRequest:
        if not isinstance(request, SearchRequest):
            raise ValueError("INVALID_REQUEST_TYPE")
        if (not request.query.strip() or len(request.query) > 400
                or len(request.query.split()) > 50):
            raise ValueError("INVALID_QUERY")
        if type(request.call_number) is not int or request.call_number < 0:
            raise ValueError("INVALID_CALL_NUMBER")
        assert_content_safe({"query": request.query, "request_id": request.request_id,
                             "entrant_id": request.entrant_id})
        config = self.config
        params = {"q": request.query}
        for key in PARAMETERS:
            value = config[key]
            params[key] = str(value).lower() if type(value) is bool else str(value)
        return WebRequest(
            method="GET", url=str(config["endpoint"]) + "?" + urlencode(params),
            headers=(("Accept", "application/json"), ("Api-Version", API_VERSION)),
            timeout_ms=int(config["timeout_per_call_ms"]),
        )

    @staticmethod
    def _error(code: str, request_id: str, status: int | None = None,
               retryable: bool = False) -> SearchBackendError:
        # Never interpolate transport exceptions, bodies or response headers.
        return SearchBackendError(code, backend_id=BACKEND_ID, error_code=code,
                                  request_id=request_id, http_status=status,
                                  retryable=retryable)

    def __call__(self, request: SearchRequest) -> SearchBackendResponse:
        safe_error_id = "t6-" + uuid4().hex
        try:
            wire = self.build_request(request)
        except (ValueError, TypeError, AttributeError):
            raise self._error("INVALID_OR_UNSAFE_REQUEST", safe_error_id) from None
        request_id = request.request_id or safe_error_id
        started = perf_counter()
        trace = {
            "request_id": request_id, "query": request.query,
            "call_number": request.call_number,
            "started_at_utc": datetime.now(timezone.utc).isoformat(),
            "backend_id": BACKEND_ID, "endpoint": self.config["endpoint"],
            "config_fingerprint": self.config_fingerprint,
            "http_status": None, "result_count": 0, "error_code": None,
            "retryable": False, "backend_attempts": 0, "automatic_retries": 0,
            "query_state": None, "response_body_sha256": None,
            "normalized_result_fingerprint": None,
        }
        try:
            if self._transport is None:
                raise self._error("LIVE_TRANSPORT_NOT_CONFIGURED", request_id)
            trace["backend_attempts"] = 1
            try:
                response = self._transport(wire)
            except TimeoutError:
                raise self._error("NETWORK_TIMEOUT", request_id, retryable=True) from None
            except Exception:
                raise self._error("TRANSPORT_ERROR", request_id) from None
            if not isinstance(response, WebResponse) or type(response.status) is not int:
                raise self._error("INVALID_TRANSPORT_RESPONSE", request_id)
            trace["http_status"] = response.status
            if response.status != 200:
                code = ("RATE_LIMIT" if response.status == 429 else
                        "HTTP_SERVER_ERROR" if 500 <= response.status < 600 else "HTTP_ERROR")
                raise self._error(code, request_id, response.status,
                                  response.status == 429 or 500 <= response.status < 600)
            if type(response.body) is not bytes or len(response.body) > self.config["max_response_bytes"]:
                raise self._error("INVALID_OR_OVERSIZE_BODY", request_id, 200)
            try:
                body = json.loads(response.body.decode("utf-8"), object_pairs_hook=_pairs,
                                  parse_constant=_invalid_constant)
            except (ValueError, UnicodeError):
                raise self._error("INVALID_JSON", request_id, 200) from None
            if type(body) is not dict or body.get("type", "search") != "search":
                raise self._error("INVALID_RESPONSE_SCHEMA", request_id, 200)
            try:
                assert_content_safe(body)
            except ValueError:
                raise self._error("UNSAFE_RESPONSE", request_id, 200) from None
            import hashlib
            trace["response_body_sha256"] = hashlib.sha256(response.body).hexdigest()
            query = body.get("query")
            if query is not None:
                if type(query) is not dict:
                    raise self._error("INVALID_QUERY_STATE", request_id, 200)
                trace["query_state"] = {k: query.get(k) for k in
                                        ("original", "altered", "spellcheck_off", "should_fallback")}
                if "original" in query and query["original"] != request.query:
                    raise self._error("NON_COMPARABLE_QUERY_ORIGINAL", request_id, 200)
                if query.get("altered") is not None:
                    raise self._error("NON_COMPARABLE_QUERY_ALTERED", request_id, 200)
                if "spellcheck_off" in query and query["spellcheck_off"] is not True:
                    raise self._error("NON_COMPARABLE_SPELLCHECK", request_id, 200)
                if "should_fallback" in query and type(query["should_fallback"]) is not bool:
                    raise self._error("INVALID_QUERY_STATE", request_id, 200)
                if query.get("should_fallback") is True:
                    raise self._error("NON_COMPARABLE_BACKEND_FALLBACK", request_id, 200)
            for key in ("summarizer", "summary", "goggles", "goggles_id", "rerank", "rich"):
                if body.get(key):
                    raise self._error("NON_COMPARABLE_ENHANCEMENT", request_id, 200)
            web = body.get("web")
            if type(web) is not dict or type(web.get("results")) is not list:
                raise self._error("MISSING_WEB_RESULTS", request_id, 200)
            raw_results = web["results"]
            if len(raw_results) > self.config["count"]:
                raise self._error("RESULT_LIMIT_EXCEEDED", request_id, 200)
            results = []
            for item in raw_results:
                if type(item) is not dict:
                    raise self._error("INVALID_RESULT", request_id, 200)
                if any(item.get(k) for k in ("extra_snippets", "summary", "rerank", "goggles")):
                    raise self._error("NON_COMPARABLE_ENHANCEMENT", request_id, 200)
                title, url, snippet = item.get("title"), item.get("url"), item.get("description", "")
                if (type(title) is not str or not title.strip() or type(url) is not str
                        or not _safe_url(url) or type(snippet) is not str):
                    raise self._error("INVALID_RESULT", request_id, 200)
                results.append(SearchResult(title=title, url=url, snippet=snippet))
            trace["result_count"] = len(results)
            trace["normalized_result_fingerprint"] = fingerprint([asdict(r) for r in results])
            return SearchBackendResponse(tuple(results), BACKEND_ID, request_id)
        except SearchBackendError as exc:
            trace["error_code"], trace["retryable"] = exc.error_code, exc.retryable
            raise
        finally:
            trace["duration_ms"] = round((perf_counter() - started) * 1000, 3)
            self._receipts.append(trace)
