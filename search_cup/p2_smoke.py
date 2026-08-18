"""Bounded, non-official P2 smoke for the four live provider adapters."""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import asdict, dataclass
from typing import Callable, Mapping

from .contracts import (
    CandidateCard,
    CompetitionSpec,
    EntrantConfig,
    canonical_json,
)
from .demo import DEFAULT_CANDIDATE, DEFAULT_COMPETITION
from .provider_adapters import (
    GeminiAdapter,
    OpenAICompatibleAdapter,
    P2_SMOKE_INSTRUCTION,
    P2_SMOKE_QUERY,
    ProviderAdapterError,
    ProviderTransport,
)
from .search_pro import SearchProBackend
from .tools import BudgetedSearchProxy, EntrantTools, FakeURLReader, SearchBackend


P2_PHASE = "ENG-SC-01-P2"
P2_SMOKE_COMPETITION = {
    "competition_id": "SEARCH-CUP-02-P2-ADAPTER-SMOKE",
    "evaluation": "NOT_SCORED",
    "official_match": False,
    "query": P2_SMOKE_QUERY,
    "required_search_calls": 1,
    "submission_contract": "Submission",
}
P2_SMOKE_CONTENT = canonical_json(P2_SMOKE_COMPETITION).encode("utf-8")
P2_SMOKE_INSTRUCTION_FINGERPRINT = hashlib.sha256(
    P2_SMOKE_INSTRUCTION.encode("utf-8")
).hexdigest()
P2_SMOKE_ENVELOPE_FINGERPRINT = hashlib.sha256(P2_SMOKE_CONTENT).hexdigest()


@dataclass(frozen=True)
class ProviderDefinition:
    provider: str
    entrant_id: str
    api_key_env: str
    default_model: str
    endpoint_mode: str
    endpoint: str
    sampling: Mapping[str, object]
    protocol: str
    token_field: str | None = None
    provider_options: Mapping[str, object] | None = None


PROVIDER_DEFINITIONS = (
    ProviderDefinition(
        provider="OpenAI",
        entrant_id="openai-p2-smoke",
        api_key_env="OPENAI_API_KEY",
        default_model="gpt-4.1-mini-2025-04-14",
        endpoint_mode="chat-completions/v1",
        endpoint="https://api.openai.com/v1/chat/completions",
        sampling={"temperature": 0, "max_completion_tokens": 2500, "stream": False},
        protocol="openai-compatible",
        token_field="max_completion_tokens",
        provider_options={"temperature": 0},
    ),
    ProviderDefinition(
        provider="Gemini",
        entrant_id="gemini-p2-smoke",
        api_key_env="GEMINI_API_KEY",
        default_model="gemini-2.5-flash",
        endpoint_mode="generateContent/v1beta",
        endpoint=(
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "{model}:generateContent"
        ),
        sampling={"temperature": 0, "max_output_tokens": 2500},
        protocol="gemini-generate-content",
    ),
    ProviderDefinition(
        provider="DeepSeek",
        entrant_id="deepseek-p2-smoke",
        api_key_env="DEEPSEEK_API_KEY",
        default_model="deepseek-v4-flash",
        endpoint_mode="chat-completions/v1",
        endpoint="https://api.deepseek.com/chat/completions",
        sampling={
            "temperature": 0,
            "max_tokens": 2500,
            "stream": False,
            "thinking": {"type": "disabled"},
        },
        protocol="openai-compatible",
        token_field="max_tokens",
        provider_options={"temperature": 0, "thinking": {"type": "disabled"}},
    ),
    ProviderDefinition(
        provider="GLM",
        entrant_id="glm-p2-smoke",
        api_key_env="GLM_API_KEY",
        default_model="glm-4.5-flash",
        endpoint_mode="chat-completions/v4",
        endpoint="https://open.bigmodel.cn/api/paas/v4/chat/completions",
        sampling={
            "do_sample": False,
            "max_tokens": 2500,
            "stream": False,
            "thinking": {"type": "disabled"},
        },
        protocol="openai-compatible",
        token_field="max_tokens",
        provider_options={"do_sample": False, "thinking": {"type": "disabled"}},
    ),
)


TransportFactory = Callable[[ProviderDefinition], ProviderTransport | None]
SearchBackendFactory = Callable[[ProviderDefinition], SearchBackend]


def _model_env(provider: str) -> str:
    return f"{provider.upper()}_MODEL".replace(" ", "_")


def _entrant(definition: ProviderDefinition) -> EntrantConfig:
    model = os.environ.get(_model_env(definition.provider), definition.default_model)
    return EntrantConfig.from_mapping(
        {
            "entrant_id": definition.entrant_id,
            "provider": definition.provider,
            "exact_model_id": model,
            "endpoint_mode": definition.endpoint_mode,
            "sampling": definition.sampling,
        }
    )


def _adapter(
    definition: ProviderDefinition,
    entrant: EntrantConfig,
    *,
    api_key: str,
    timeout_seconds: float,
    transport: ProviderTransport | None,
):
    endpoint = definition.endpoint.format(model=entrant.exact_model_id)
    if definition.protocol == "gemini-generate-content":
        return GeminiAdapter(
            provider=definition.provider,
            api_key=api_key,
            endpoint=endpoint,
            endpoint_mode=definition.endpoint_mode,
            timeout_seconds=timeout_seconds,
            transport=transport,
        )
    return OpenAICompatibleAdapter(
        provider=definition.provider,
        api_key=api_key,
        endpoint=endpoint,
        endpoint_mode=definition.endpoint_mode,
        token_field=definition.token_field or "max_tokens",
        provider_options=definition.provider_options,
        timeout_seconds=timeout_seconds,
        transport=transport,
    )


def _failure(
    *,
    definition: ProviderDefinition,
    entrant: EntrantConfig,
    error_code: str,
    error_type: str,
    error_message: str,
    phase: str,
    api_attempts: int,
    provider_traces: list[dict[str, object]],
    search_traces: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "provider": definition.provider,
        "entrant": entrant.as_dict(),
        "requested_model_id": entrant.exact_model_id,
        "resolved_model_id": None,
        "endpoint": definition.endpoint.format(model=entrant.exact_model_id),
        "endpoint_mode": definition.endpoint_mode,
        "sampling": json.loads(entrant.sampling_json),
        "status": "NOT_EVALUABLE",
        "quality_score": None,
        "failure": {
            "evaluation_status": "NOT_EVALUABLE",
            "phase": phase,
            "error_code": error_code,
            "error_type": error_type,
            "message": error_message,
        },
        "api_attempts": api_attempts,
        "automatic_retries": 0,
        "search_calls": len(search_traces),
        "provider_traces": provider_traces,
        "search_traces": search_traces,
        "submission_sha256": None,
        "lead_count": None,
    }


def _scrub(value: object, secrets: tuple[str, ...]) -> object:
    if isinstance(value, str):
        clean = value
        for secret in secrets:
            if secret:
                clean = clean.replace(secret, "[REDACTED]")
        return clean
    if isinstance(value, list):
        return [_scrub(item, secrets) for item in value]
    if isinstance(value, tuple):
        return [_scrub(item, secrets) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _scrub(item, secrets) for key, item in value.items()}
    return value


def run_p2_smoke(
    *,
    candidate_path=DEFAULT_CANDIDATE,
    competition_path=DEFAULT_COMPETITION,
    search_api_key_env: str = "GLM_API_KEY",
    search_count: int = 5,
    timeout_seconds: float = 60.0,
    transport_factory: TransportFactory | None = None,
    search_backend_factory: SearchBackendFactory | None = None,
) -> tuple[dict[str, object], bool]:
    """Run four adapters sequentially; each receives a fresh one-ticket proxy."""

    candidate = CandidateCard.load(candidate_path)
    competition = CompetitionSpec.load(competition_path)
    if competition.official_match_authorized:
        raise ValueError("P2 smoke refuses an authorized official-match spec")
    if not 1 <= search_count <= 10:
        raise ValueError("P2 smoke search count must be between 1 and 10")

    known_secrets = tuple(
        value
        for name in {
            search_api_key_env,
            *(item.api_key_env for item in PROVIDER_DEFINITIONS),
        }
        if (value := os.environ.get(name, ""))
    )
    outcomes: list[dict[str, object]] = []
    for definition in PROVIDER_DEFINITIONS:
        entrant = _entrant(definition)
        provider_key = os.environ.get(definition.api_key_env, "").strip()
        search_key = os.environ.get(search_api_key_env, "").strip()
        if not provider_key:
            outcomes.append(
                _failure(
                    definition=definition,
                    entrant=entrant,
                    error_code="MISSING_API_KEY",
                    error_type="ProviderAdapterError",
                    error_message=(
                        "required provider key is not configured: "
                        f"{definition.api_key_env}"
                    ),
                    phase="CONFIGURATION",
                    api_attempts=0,
                    provider_traces=[],
                    search_traces=[],
                )
            )
            continue
        if not search_key and search_backend_factory is None:
            outcomes.append(
                _failure(
                    definition=definition,
                    entrant=entrant,
                    error_code="MISSING_SEARCH_API_KEY",
                    error_type="RuntimeError",
                    error_message=(
                        "required search key is not configured: "
                        f"{search_api_key_env}"
                    ),
                    phase="CONFIGURATION",
                    api_attempts=0,
                    provider_traces=[],
                    search_traces=[],
                )
            )
            continue

        backend = (
            search_backend_factory(definition)
            if search_backend_factory
            else SearchProBackend(
                search_key,
                count=search_count,
                timeout_seconds=timeout_seconds,
            )
        )
        proxy = BudgetedSearchProxy(entrant.entrant_id, 1, backend)
        tools = EntrantTools(proxy, FakeURLReader({}))
        transport = transport_factory(definition) if transport_factory else None
        adapter = _adapter(
            definition,
            entrant,
            api_key=provider_key,
            timeout_seconds=timeout_seconds,
            transport=transport,
        )
        try:
            submission = adapter.run(
                candidate_content=candidate.canonical_bytes,
                competition_content=P2_SMOKE_CONTENT,
                candidate_fingerprint=candidate.fingerprint,
                competition_fingerprint=competition.fingerprint,
                entrant=entrant,
                tools=tools,
            )
            submission_content = canonical_json(submission.as_dict()).encode("utf-8")
            outcomes.append(
                {
                    "provider": definition.provider,
                    "entrant": entrant.as_dict(),
                    "requested_model_id": entrant.exact_model_id,
                    "resolved_model_id": adapter.resolved_model_id,
                    "endpoint": definition.endpoint.format(model=entrant.exact_model_id),
                    "endpoint_mode": definition.endpoint_mode,
                    "sampling": json.loads(entrant.sampling_json),
                    "status": "PASS",
                    "quality_score": None,
                    "failure": None,
                    "api_attempts": adapter.api_attempts,
                    "automatic_retries": adapter.automatic_retries,
                    "search_calls": tools.search_calls,
                    "provider_traces": [asdict(trace) for trace in adapter.traces],
                    "search_traces": [asdict(trace) for trace in tools.traces],
                    "submission_sha256": hashlib.sha256(submission_content).hexdigest(),
                    "lead_count": len(submission.leads),
                }
            )
        except Exception as exc:
            if isinstance(exc, ProviderAdapterError):
                error_code = exc.error_code
                phase = exc.phase
            else:
                error_code = getattr(exc, "error_code", "UNEXPECTED_PROVIDER_FAILURE")
                phase = "SEARCH_PROXY" if tools.search_calls else "PROVIDER_CALL"
            outcomes.append(
                _failure(
                    definition=definition,
                    entrant=entrant,
                    error_code=str(error_code),
                    error_type=type(exc).__name__,
                    error_message=str(exc),
                    phase=phase,
                    api_attempts=adapter.api_attempts,
                    provider_traces=[asdict(trace) for trace in adapter.traces],
                    search_traces=[asdict(trace) for trace in tools.traces],
                )
            )

    artifact: dict[str, object] = {
        "phase": P2_PHASE,
        "gate": "GREEN" if all(item["status"] == "PASS" for item in outcomes) else "NOT_EVALUABLE",
        "evaluation": "NOT_SCORED",
        "authorization": "Issue #8 comment 5321078001",
        "candidate_fingerprint": candidate.fingerprint,
        "competition_fingerprint": competition.fingerprint,
        "smoke_envelope_fingerprint": P2_SMOKE_ENVELOPE_FINGERPRINT,
        "smoke_instruction_fingerprint": P2_SMOKE_INSTRUCTION_FINGERPRINT,
        "provider_adapters_configured": 4,
        "providers_executed_sequentially": True,
        "max_search_calls_per_provider": 1,
        "automatic_retries": 0,
        "official_prompt_consumed": False,
        "official_match_authorized": False,
        "hidden_registry_loaded": False,
        "judge_invoked": False,
        "credentials_logged": False,
        "outcomes": outcomes,
    }
    artifact = _scrub(artifact, known_secrets)  # type: ignore[assignment]
    serialized = json.dumps(artifact, ensure_ascii=False, sort_keys=True)
    if any(secret and secret in serialized for secret in known_secrets):
        raise RuntimeError("credential redaction invariant failed")
    green = artifact["gate"] == "GREEN"
    return artifact, green
