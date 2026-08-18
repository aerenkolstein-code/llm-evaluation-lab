"""Live P2 provider adapters with one provider-neutral semantic contract.

The adapters in this module translate API and tool-call syntax only.  They do
not own search policy, retry policy, or benchmark scoring.  Every attempted
provider request is recorded once and is never retried automatically.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from time import perf_counter
from typing import Callable, Mapping, Sequence
from urllib import error, request

from .contracts import EntrantConfig, Submission, canonical_json
from .tools import EntrantTools


SEARCH_WEB_DESCRIPTION = (
    "Run one provider-independent public-web search through the shared "
    "SearchProxy and return normalized title/url/snippet results."
)
SEARCH_WEB_PARAMETERS: Mapping[str, object] = {
    "type": "object",
    "properties": {
        "query": {
            "type": "string",
            "description": "The complete public-web search query.",
            "minLength": 1,
        }
    },
    "required": ["query"],
    "additionalProperties": False,
}

P2_SMOKE_QUERY = "Python dataclasses official documentation"
P2_SMOKE_INSTRUCTION = """This is ENG-SC-01-P2 adapter smoke, not the official
job-search match and not a scored evaluation. Call search_web exactly once with
the non-official query `Python dataclasses official documentation`. Consume the
normalized results, continue reasoning, and return only one JSON object matching
the supplied Submission template. If results exist, use at most the first result
as a synthetic contract lead and explicitly state that it is not a job opening;
otherwise return no leads and record the uncertainty. Do not call any other tool.
""".strip()

COMMON_SYSTEM_INSTRUCTION = """You are executing a bounded provider-adapter
contract smoke. Candidate Card bytes and smoke instructions are identical for
all providers. Provider identity metadata is experiment metadata, not an extra
semantic hint. You must call only the supplied search_web tool exactly once,
consume its normalized structured result, then emit only valid Submission JSON.
This is not the official competition prompt and must not be scored.
""".strip()


@dataclass(frozen=True)
class ProviderHTTPResponse:
    status: int
    body: bytes


ProviderTransport = Callable[
    [str, Mapping[str, str], Mapping[str, object], float],
    ProviderHTTPResponse,
]


def _default_transport(
    endpoint: str,
    headers: Mapping[str, str],
    payload: Mapping[str, object],
    timeout: float,
) -> ProviderHTTPResponse:
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(endpoint, data=encoded, headers=dict(headers), method="POST")
    try:
        with request.urlopen(req, timeout=timeout) as response:
            return ProviderHTTPResponse(response.status, response.read())
    except error.HTTPError as exc:
        return ProviderHTTPResponse(exc.code, exc.read())


@dataclass(frozen=True)
class ProviderCallTrace:
    provider: str
    attempt: int
    phase: str
    status: str
    endpoint_mode: str
    endpoint: str
    requested_model_id: str
    resolved_model_id: str | None = None
    response_id: str | None = None
    http_status: int | None = None
    error_code: str | None = None
    error_message: str | None = None
    retryable: bool = False
    automatic_retries: int = 0
    duration_ms: float | None = None


class ProviderAdapterError(RuntimeError):
    """Credential-free typed failure; never interpreted as model quality."""

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        phase: str,
        error_code: str,
        http_status: int | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.phase = phase
        self.error_code = error_code
        self.http_status = http_status
        self.retryable = retryable
        self.evaluation_status = "NOT_EVALUABLE"


def _error_details(document: object, status: int) -> tuple[str, str]:
    if isinstance(document, Mapping):
        raw = document.get("error")
        if isinstance(raw, Mapping):
            code = raw.get("code") or raw.get("type") or status
            message = raw.get("message") or "provider request failed"
            return str(code), str(message)
        if isinstance(raw, str):
            return str(status), raw
        message = document.get("message")
        if isinstance(message, str):
            return str(status), message
    return str(status), "provider request failed"


def _json_object(text: object, *, provider: str, phase: str) -> Mapping[str, object]:
    if not isinstance(text, str) or not text.strip():
        raise ProviderAdapterError(
            "provider returned no final JSON content",
            provider=provider,
            phase=phase,
            error_code="EMPTY_FINAL_CONTENT",
        )
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    try:
        document = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ProviderAdapterError(
            f"provider final content is not JSON: {exc.msg}",
            provider=provider,
            phase=phase,
            error_code="INVALID_FINAL_JSON",
        ) from exc
    if not isinstance(document, Mapping):
        raise ProviderAdapterError(
            "provider final JSON must be an object",
            provider=provider,
            phase=phase,
            error_code="INVALID_FINAL_JSON",
        )
    return document


def _tool_arguments(value: object, *, provider: str) -> str:
    if isinstance(value, str):
        try:
            document = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ProviderAdapterError(
                f"search_web arguments are not JSON: {exc.msg}",
                provider=provider,
                phase="TOOL_REQUEST",
                error_code="INVALID_TOOL_ARGUMENTS",
            ) from exc
    elif isinstance(value, Mapping):
        document = value
    else:
        document = None
    if not isinstance(document, Mapping) or set(document) != {"query"}:
        raise ProviderAdapterError(
            "search_web requires exactly one query argument",
            provider=provider,
            phase="TOOL_REQUEST",
            error_code="INVALID_TOOL_ARGUMENTS",
        )
    query = document.get("query")
    if not isinstance(query, str) or not query.strip():
        raise ProviderAdapterError(
            "search_web query must be non-empty",
            provider=provider,
            phase="TOOL_REQUEST",
            error_code="INVALID_TOOL_ARGUMENTS",
        )
    return query.strip()


def _normalized_results(tools: EntrantTools, query: str) -> list[dict[str, str]]:
    return [asdict(item) for item in tools.search_web(query)]


def _submission_template(
    entrant: EntrantConfig,
    candidate_fingerprint: str,
    competition_fingerprint: str,
) -> dict[str, object]:
    return {
        "entrant": entrant.as_dict(),
        "candidate_fingerprint": candidate_fingerprint,
        "competition_fingerprint": competition_fingerprint,
        "leads": [
            {
                "company": "Python Software Foundation",
                "role": "Documentation verification smoke (not a job)",
                "source_url": "COPY_FROM_SEARCH_RESULT",
                "official_source": True,
                "open_status": "UNVERIFIED",
                "remote_scope": "N/A — adapter smoke",
                "location_constraint": "N/A — adapter smoke",
                "employment_type": "N/A — adapter smoke",
                "required_skills": [],
                "candidate_fit": "Synthetic contract validation only.",
                "mismatch_risks": ["Not a job opportunity."],
                "portfolio_relevance": "Proves normalized tool-result consumption.",
                "confidence": 0.5,
                "next_action": "No application; retain only as smoke evidence.",
                "evidence_urls": ["COPY_FROM_SEARCH_RESULT"],
                "claimed_novel": False,
            }
        ],
        "apply_now_urls": [],
        "search_strategy_summary": "One non-official contract-smoke query.",
        "rejected_or_downgraded": [],
        "uncertainties": ["This smoke is not a job-search evaluation."],
        "search_calls": 1,
    }


def build_final_submission_instruction(
    *,
    entrant: EntrantConfig,
    candidate_fingerprint: str,
    competition_fingerprint: str,
    normalized_results: Sequence[Mapping[str, str]],
) -> str:
    """Render one provider-neutral, fully grounded final contract directive.

    The P2 smoke measures adapter conformance rather than model quality.  After
    the shared SearchProxy result is available, every provider therefore sees
    the same explicit output shape and is asked to reproduce one complete
    Submission object without a wrapper.  Provider identity is experiment
    metadata already required by the frozen common contract.
    """

    submission = _submission_template(
        entrant,
        candidate_fingerprint,
        competition_fingerprint,
    )
    if normalized_results:
        source_url = normalized_results[0]["url"]
        lead = submission["leads"][0]
        lead["source_url"] = source_url
        lead["evidence_urls"] = [source_url]
    else:
        submission["leads"] = []
        submission["uncertainties"] = [
            "SearchProxy returned no results for the non-official smoke query."
        ]

    return canonical_json(
        {
            "directive": (
                "Return only the complete required_output JSON object. Do not "
                "omit fields, rename fields, add a wrapper key, or add prose."
            ),
            "required_top_level_keys": list(submission),
            "required_output": submission,
            "submission_contract": "Submission",
        }
    )


def build_provider_prompt(
    *,
    candidate_content: bytes,
    competition_content: bytes,
    candidate_fingerprint: str,
    competition_fingerprint: str,
    entrant: EntrantConfig,
) -> str:
    """Render the common semantics plus required identity metadata."""

    try:
        candidate = json.loads(candidate_content.decode("utf-8"))
        smoke_competition = json.loads(competition_content.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("candidate and smoke competition must be canonical JSON") from exc
    return canonical_json(
        {
            "candidate_card": candidate,
            "candidate_fingerprint": candidate_fingerprint,
            "entrant_identity_metadata": entrant.as_dict(),
            "non_official_smoke_competition": smoke_competition,
            "required_submission_template": _submission_template(
                entrant,
                candidate_fingerprint,
                competition_fingerprint,
            ),
            "smoke_instruction": P2_SMOKE_INSTRUCTION,
        }
    )


class _ProviderAdapterBase:
    def __init__(
        self,
        *,
        provider: str,
        api_key: str,
        endpoint: str,
        endpoint_mode: str,
        timeout_seconds: float = 60.0,
        transport: ProviderTransport | None = None,
    ) -> None:
        if not api_key:
            raise ProviderAdapterError(
                "provider API key is not configured",
                provider=provider,
                phase="CONFIGURATION",
                error_code="MISSING_API_KEY",
            )
        self.provider = provider
        self.api_key = api_key
        self.endpoint = endpoint
        self.endpoint_mode = endpoint_mode
        self.timeout_seconds = timeout_seconds
        self.transport = transport or _default_transport
        self._traces: list[ProviderCallTrace] = []

    @property
    def traces(self) -> tuple[ProviderCallTrace, ...]:
        return tuple(self._traces)

    @property
    def api_attempts(self) -> int:
        return len(self._traces)

    @property
    def automatic_retries(self) -> int:
        return 0

    @property
    def resolved_model_id(self) -> str | None:
        for trace in reversed(self._traces):
            if trace.resolved_model_id:
                return trace.resolved_model_id
        return None

    def _post(
        self,
        *,
        phase: str,
        requested_model_id: str,
        headers: Mapping[str, str],
        payload: Mapping[str, object],
    ) -> Mapping[str, object]:
        attempt = self.api_attempts + 1
        started = perf_counter()
        try:
            response = self.transport(
                self.endpoint,
                headers,
                payload,
                self.timeout_seconds,
            )
        except (error.URLError, TimeoutError, OSError) as exc:
            duration = round((perf_counter() - started) * 1000, 3)
            self._traces.append(
                ProviderCallTrace(
                    provider=self.provider,
                    attempt=attempt,
                    phase=phase,
                    status="FAILED",
                    endpoint_mode=self.endpoint_mode,
                    endpoint=self.endpoint,
                    requested_model_id=requested_model_id,
                    error_code="PROVIDER_NETWORK_ERROR",
                    error_message=type(exc).__name__,
                    retryable=True,
                    duration_ms=duration,
                )
            )
            raise ProviderAdapterError(
                f"{self.provider} network request failed ({type(exc).__name__})",
                provider=self.provider,
                phase=phase,
                error_code="PROVIDER_NETWORK_ERROR",
                retryable=True,
            ) from exc

        duration = round((perf_counter() - started) * 1000, 3)
        try:
            document = json.loads(response.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._traces.append(
                ProviderCallTrace(
                    provider=self.provider,
                    attempt=attempt,
                    phase=phase,
                    status="FAILED",
                    endpoint_mode=self.endpoint_mode,
                    endpoint=self.endpoint,
                    requested_model_id=requested_model_id,
                    http_status=response.status,
                    error_code="INVALID_PROVIDER_JSON",
                    error_message=type(exc).__name__,
                    duration_ms=duration,
                )
            )
            raise ProviderAdapterError(
                f"{self.provider} response was not JSON",
                provider=self.provider,
                phase=phase,
                error_code="INVALID_PROVIDER_JSON",
                http_status=response.status,
            ) from exc
        if not isinstance(document, Mapping):
            document = {"error": {"message": "provider response must be an object"}}
        if not 200 <= response.status < 300:
            code, message = _error_details(document, response.status)
            retryable = response.status in {408, 409, 429} or response.status >= 500
            self._traces.append(
                ProviderCallTrace(
                    provider=self.provider,
                    attempt=attempt,
                    phase=phase,
                    status="FAILED",
                    endpoint_mode=self.endpoint_mode,
                    endpoint=self.endpoint,
                    requested_model_id=requested_model_id,
                    http_status=response.status,
                    error_code=code,
                    error_message=message,
                    retryable=retryable,
                    duration_ms=duration,
                )
            )
            raise ProviderAdapterError(
                f"{self.provider} request failed: {code}: {message}",
                provider=self.provider,
                phase=phase,
                error_code=code,
                http_status=response.status,
                retryable=retryable,
            )

        resolved_model = document.get("model") or document.get("modelVersion")
        response_id = document.get("id") or document.get("responseId")
        self._traces.append(
            ProviderCallTrace(
                provider=self.provider,
                attempt=attempt,
                phase=phase,
                status="SUCCEEDED",
                endpoint_mode=self.endpoint_mode,
                endpoint=self.endpoint,
                requested_model_id=requested_model_id,
                resolved_model_id=str(resolved_model) if resolved_model else None,
                response_id=str(response_id) if response_id else None,
                http_status=response.status,
                duration_ms=duration,
            )
        )
        return document

    def _validate_submission(
        self,
        document: Mapping[str, object],
        *,
        entrant: EntrantConfig,
        candidate_fingerprint: str,
        competition_fingerprint: str,
        search_calls: int,
        allowed_result_urls: frozenset[str],
    ) -> Submission:
        try:
            submission = Submission.from_mapping(document)
        except (TypeError, ValueError) as exc:
            raise ProviderAdapterError(
                f"final Submission validation failed: {exc}",
                provider=self.provider,
                phase="FINAL_SUBMISSION",
                error_code="INVALID_SUBMISSION",
            ) from exc
        if submission.entrant != entrant:
            raise ProviderAdapterError(
                "provider changed exact entrant identity/configuration",
                provider=self.provider,
                phase="FINAL_SUBMISSION",
                error_code="ENTRANT_IDENTITY_MISMATCH",
            )
        if submission.candidate_fingerprint != candidate_fingerprint:
            raise ProviderAdapterError(
                "provider changed Candidate Card fingerprint",
                provider=self.provider,
                phase="FINAL_SUBMISSION",
                error_code="CANDIDATE_FINGERPRINT_MISMATCH",
            )
        if submission.competition_fingerprint != competition_fingerprint:
            raise ProviderAdapterError(
                "provider changed CompetitionSpec fingerprint",
                provider=self.provider,
                phase="FINAL_SUBMISSION",
                error_code="COMPETITION_FINGERPRINT_MISMATCH",
            )
        if submission.search_calls != search_calls:
            raise ProviderAdapterError(
                "provider search_calls does not match SearchProxy trace",
                provider=self.provider,
                phase="FINAL_SUBMISSION",
                error_code="SEARCH_CALL_COUNT_MISMATCH",
            )
        submitted_urls = {
            url
            for lead in submission.leads
            for url in (lead.source_url, *lead.evidence_urls)
        }
        if not submitted_urls.issubset(allowed_result_urls):
            raise ProviderAdapterError(
                "submission contains a URL not returned by SearchProxy",
                provider=self.provider,
                phase="FINAL_SUBMISSION",
                error_code="UNSOURCED_SMOKE_URL",
            )
        return submission


class OpenAICompatibleAdapter(_ProviderAdapterBase):
    """Chat Completions tool loop used by OpenAI, DeepSeek, and GLM."""

    def __init__(
        self,
        *,
        provider: str,
        api_key: str,
        endpoint: str,
        endpoint_mode: str,
        token_field: str,
        provider_options: Mapping[str, object] | None = None,
        timeout_seconds: float = 60.0,
        transport: ProviderTransport | None = None,
    ) -> None:
        super().__init__(
            provider=provider,
            api_key=api_key,
            endpoint=endpoint,
            endpoint_mode=endpoint_mode,
            timeout_seconds=timeout_seconds,
            transport=transport,
        )
        self.token_field = token_field
        self.provider_options = dict(provider_options or {})

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
        prompt = build_provider_prompt(
            candidate_content=candidate_content,
            competition_content=competition_content,
            candidate_fingerprint=candidate_fingerprint,
            competition_fingerprint=competition_fingerprint,
            entrant=entrant,
        )
        messages: list[dict[str, object]] = [
            {"role": "system", "content": COMMON_SYSTEM_INSTRUCTION},
            {"role": "user", "content": prompt},
        ]
        tool = {
            "type": "function",
            "function": {
                "name": "search_web",
                "description": SEARCH_WEB_DESCRIPTION,
                "parameters": dict(SEARCH_WEB_PARAMETERS),
            },
        }
        base: dict[str, object] = {
            "model": entrant.exact_model_id,
            "stream": False,
            self.token_field: 2500,
            **self.provider_options,
        }
        first = self._post(
            phase="TOOL_REQUEST",
            requested_model_id=entrant.exact_model_id,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            payload={
                **base,
                "messages": messages,
                "tools": [tool],
                "tool_choice": "auto",
            },
        )
        choices = first.get("choices")
        if not isinstance(choices, Sequence) or isinstance(choices, (str, bytes)) or len(choices) != 1:
            raise ProviderAdapterError(
                "provider must return exactly one choice",
                provider=self.provider,
                phase="TOOL_REQUEST",
                error_code="INVALID_PROVIDER_RESPONSE",
            )
        choice = choices[0]
        message = choice.get("message") if isinstance(choice, Mapping) else None
        tool_calls = message.get("tool_calls") if isinstance(message, Mapping) else None
        if not isinstance(tool_calls, Sequence) or isinstance(tool_calls, (str, bytes)) or len(tool_calls) != 1:
            raise ProviderAdapterError(
                "provider must call search_web exactly once",
                provider=self.provider,
                phase="TOOL_REQUEST",
                error_code="EXACT_ONE_TOOL_CALL_REQUIRED",
            )
        tool_call = tool_calls[0]
        function = tool_call.get("function") if isinstance(tool_call, Mapping) else None
        if not isinstance(function, Mapping) or function.get("name") != "search_web":
            raise ProviderAdapterError(
                "provider called an unsupported tool",
                provider=self.provider,
                phase="TOOL_REQUEST",
                error_code="UNSUPPORTED_TOOL",
            )
        tool_call_id = tool_call.get("id") if isinstance(tool_call, Mapping) else None
        if not isinstance(tool_call_id, str) or not tool_call_id:
            raise ProviderAdapterError(
                "provider tool call has no ID",
                provider=self.provider,
                phase="TOOL_REQUEST",
                error_code="INVALID_PROVIDER_RESPONSE",
            )
        query = _tool_arguments(function.get("arguments"), provider=self.provider)
        if query != P2_SMOKE_QUERY:
            raise ProviderAdapterError(
                "provider changed the authorized non-official smoke query",
                provider=self.provider,
                phase="TOOL_REQUEST",
                error_code="SMOKE_QUERY_MISMATCH",
            )
        results = _normalized_results(tools, query)
        messages.append(
            {
                "role": "assistant",
                "content": message.get("content"),
                "tool_calls": list(tool_calls),
            }
        )
        messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "name": "search_web",
                "content": canonical_json({"results": results}),
            }
        )
        messages.append(
            {
                "role": "user",
                "content": build_final_submission_instruction(
                    entrant=entrant,
                    candidate_fingerprint=candidate_fingerprint,
                    competition_fingerprint=competition_fingerprint,
                    normalized_results=results,
                ),
            }
        )
        final = self._post(
            phase="FINAL_SUBMISSION",
            requested_model_id=entrant.exact_model_id,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            payload={
                **base,
                "messages": messages,
                "response_format": {"type": "json_object"},
            },
        )
        final_choices = final.get("choices")
        if not isinstance(final_choices, Sequence) or isinstance(final_choices, (str, bytes)) or len(final_choices) != 1:
            raise ProviderAdapterError(
                "provider must return exactly one final choice",
                provider=self.provider,
                phase="FINAL_SUBMISSION",
                error_code="INVALID_PROVIDER_RESPONSE",
            )
        final_choice = final_choices[0]
        final_message = final_choice.get("message") if isinstance(final_choice, Mapping) else None
        content = final_message.get("content") if isinstance(final_message, Mapping) else None
        document = _json_object(content, provider=self.provider, phase="FINAL_SUBMISSION")
        return self._validate_submission(
            document,
            entrant=entrant,
            candidate_fingerprint=candidate_fingerprint,
            competition_fingerprint=competition_fingerprint,
            search_calls=tools.search_calls,
            allowed_result_urls=frozenset(item["url"] for item in results),
        )


class GeminiAdapter(_ProviderAdapterBase):
    """Gemini generateContent function-call translation."""

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
        prompt = build_provider_prompt(
            candidate_content=candidate_content,
            competition_content=competition_content,
            candidate_fingerprint=candidate_fingerprint,
            competition_fingerprint=competition_fingerprint,
            entrant=entrant,
        )
        contents: list[dict[str, object]] = [
            {
                "role": "user",
                "parts": [
                    {"text": COMMON_SYSTEM_INSTRUCTION + "\n\n" + prompt},
                ],
            }
        ]
        tools_schema = [
            {
                "functionDeclarations": [
                    {
                        "name": "search_web",
                        "description": SEARCH_WEB_DESCRIPTION,
                        "parameters": dict(SEARCH_WEB_PARAMETERS),
                    }
                ]
            }
        ]
        first = self._post(
            phase="TOOL_REQUEST",
            requested_model_id=entrant.exact_model_id,
            headers={
                "x-goog-api-key": self.api_key,
                "Content-Type": "application/json",
            },
            payload={
                "contents": contents,
                "tools": tools_schema,
                "toolConfig": {"functionCallingConfig": {"mode": "AUTO"}},
                "generationConfig": {"temperature": 0, "maxOutputTokens": 2500},
            },
        )
        candidates = first.get("candidates")
        if not isinstance(candidates, Sequence) or isinstance(candidates, (str, bytes)) or len(candidates) != 1:
            raise ProviderAdapterError(
                "Gemini must return exactly one candidate",
                provider=self.provider,
                phase="TOOL_REQUEST",
                error_code="INVALID_PROVIDER_RESPONSE",
            )
        candidate = candidates[0]
        content = candidate.get("content") if isinstance(candidate, Mapping) else None
        parts = content.get("parts") if isinstance(content, Mapping) else None
        if not isinstance(parts, Sequence) or isinstance(parts, (str, bytes)):
            parts = ()
        calls = [
            part.get("functionCall")
            for part in parts
            if isinstance(part, Mapping) and isinstance(part.get("functionCall"), Mapping)
        ]
        if len(calls) != 1 or calls[0].get("name") != "search_web":
            raise ProviderAdapterError(
                "Gemini must call search_web exactly once",
                provider=self.provider,
                phase="TOOL_REQUEST",
                error_code="EXACT_ONE_TOOL_CALL_REQUIRED",
            )
        query = _tool_arguments(calls[0].get("args"), provider=self.provider)
        if query != P2_SMOKE_QUERY:
            raise ProviderAdapterError(
                "provider changed the authorized non-official smoke query",
                provider=self.provider,
                phase="TOOL_REQUEST",
                error_code="SMOKE_QUERY_MISMATCH",
            )
        results = _normalized_results(tools, query)
        contents.append({"role": "model", "parts": list(parts)})
        contents.append(
            {
                "role": "user",
                "parts": [
                    {
                        "functionResponse": {
                            "name": "search_web",
                            "response": {"results": results},
                        }
                    },
                    {
                        "text": build_final_submission_instruction(
                            entrant=entrant,
                            candidate_fingerprint=candidate_fingerprint,
                            competition_fingerprint=competition_fingerprint,
                            normalized_results=results,
                        )
                    },
                ],
            }
        )
        final = self._post(
            phase="FINAL_SUBMISSION",
            requested_model_id=entrant.exact_model_id,
            headers={
                "x-goog-api-key": self.api_key,
                "Content-Type": "application/json",
            },
            payload={
                "contents": contents,
                "generationConfig": {
                    "temperature": 0,
                    "maxOutputTokens": 2500,
                    "responseMimeType": "application/json",
                },
            },
        )
        final_candidates = final.get("candidates")
        if not isinstance(final_candidates, Sequence) or isinstance(final_candidates, (str, bytes)) or len(final_candidates) != 1:
            raise ProviderAdapterError(
                "Gemini must return exactly one final candidate",
                provider=self.provider,
                phase="FINAL_SUBMISSION",
                error_code="INVALID_PROVIDER_RESPONSE",
            )
        final_candidate = final_candidates[0]
        final_content = final_candidate.get("content") if isinstance(final_candidate, Mapping) else None
        final_parts = final_content.get("parts") if isinstance(final_content, Mapping) else None
        if not isinstance(final_parts, Sequence) or isinstance(final_parts, (str, bytes)):
            final_parts = ()
        text = "".join(
            str(part.get("text", ""))
            for part in final_parts
            if isinstance(part, Mapping)
        )
        document = _json_object(text, provider=self.provider, phase="FINAL_SUBMISSION")
        return self._validate_submission(
            document,
            entrant=entrant,
            candidate_fingerprint=candidate_fingerprint,
            competition_fingerprint=competition_fingerprint,
            search_calls=tools.search_calls,
            allowed_result_urls=frozenset(item["url"] for item in results),
        )
