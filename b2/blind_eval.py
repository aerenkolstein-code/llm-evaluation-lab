"""Generic B2 blind-evaluation bridge.

The bridge sends two byte-frozen UTF-8 inputs (long context + prompt) through
one explicitly authorized provider request and returns the raw answer separately
from a sanitized, body-free receipt. It never scores model quality, calls tools
or search, or retries a provider automatically.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Callable, Mapping, Sequence
from urllib import error, request

BLIND_EVAL_PROTOCOL_VERSION = "b2-blind-eval-bridge/v1"
BLIND_INPUT_ENVELOPE_VERSION = "b2-blind-input-envelope/v1"
OPENAI_COMPATIBLE_PROTOCOL = "openai-compatible-chat-completions/v1"
AUTOMATIC_RETRIES = 0
TERMINAL_STATUSES = {"PASS", "NOT_EVALUABLE", "ERROR"}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _safe_error_message(message: object, secrets: Sequence[str]) -> str:
    """Redact credentials from local/transport exceptions.

    Provider response bodies are deliberately never passed to this function;
    HTTP failures are normalized to status-only messages before receipt creation.
    """

    text = str(message)
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[SECRET_REDACTED]")
    text = re.sub(
        r"(?i)authorization\s*:\s*bearer\s+[^\s,;]+",
        "Authorization: Bearer [SECRET_REDACTED]",
        text,
    )
    text = re.sub(r"\bsk-[A-Za-z0-9_-]{8,}\b", "[SECRET_REDACTED]", text)
    if len(text) > 500:
        text = text[:500] + "…"
    return text


def build_input_envelope(context_bytes: bytes, prompt_bytes: bytes) -> bytes:
    """Build the fixed, versioned user-message envelope without semantic hints."""

    context = context_bytes.decode("utf-8")
    prompt = prompt_bytes.decode("utf-8")
    return (
        f"===== LONG_CONTEXT | {BLIND_INPUT_ENVELOPE_VERSION} =====\n"
        f"{context}\n"
        "===== TASK =====\n"
        f"{prompt}"
    ).encode("utf-8")


@dataclass(frozen=True)
class BlindEvalRequest:
    run_id: str
    provider_label: str
    provider_protocol: str
    requested_model_id: str
    endpoint: str
    api_key_env: str
    context_bytes: bytes
    prompt_bytes: bytes
    timeout_seconds: float = 120.0
    temperature: float = 0.0
    max_tokens: int = 8192
    git_commit: str | None = None


@dataclass(frozen=True)
class ProviderHTTPResponse:
    status: int
    body: bytes


@dataclass(frozen=True)
class ProviderResult:
    raw_output: str
    resolved_model_id: str | None
    response_id: str | None
    http_status: int
    usage: Mapping[str, int] | None


@dataclass(frozen=True)
class BlindEvalReceipt:
    schema_version: str
    run_id: str
    terminal_status: str
    protocol_version: str
    envelope_version: str
    provider_label: str
    provider_protocol: str
    requested_model_id: str
    resolved_model_id: str | None
    context_sha256: str
    prompt_sha256: str
    input_envelope_sha256: str
    context_bytes: int
    prompt_bytes: int
    raw_output_sha256: str | None
    raw_output_bytes: int | None
    started_at: str
    completed_at: str
    duration_ms: float
    http_status: int | None
    provider_response_id: str | None
    usage: Mapping[str, int] | None
    automatic_retries: int
    error_code: str | None
    safe_error_message: str | None
    git_commit: str | None

    def as_dict(self) -> dict[str, object]:
        document = asdict(self)
        if document["terminal_status"] not in TERMINAL_STATUSES:
            raise ValueError("invalid terminal status")
        return document

    def render_json(self) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=False, sort_keys=True, indent=2) + "\n"


class ProviderCallError(RuntimeError):
    """Typed provider failure carrying no provider response body."""

    def __init__(
        self,
        *,
        error_code: str,
        safe_message: str,
        http_status: int | None = None,
    ) -> None:
        super().__init__(safe_message)
        self.error_code = error_code
        self.safe_message = safe_message
        self.http_status = http_status


Transport = Callable[[str, Mapping[str, str], Mapping[str, object], float], ProviderHTTPResponse]
CredentialLookup = Callable[[str], str | None]
NowFn = Callable[[], str]
PerfFn = Callable[[], float]


def _default_transport(
    endpoint: str,
    headers: Mapping[str, str],
    payload: Mapping[str, object],
    timeout_seconds: float,
) -> ProviderHTTPResponse:
    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(endpoint, data=encoded, headers=dict(headers), method="POST")
    try:
        with request.urlopen(req, timeout=timeout_seconds) as response:
            return ProviderHTTPResponse(response.status, response.read())
    except error.HTTPError as exc:
        return ProviderHTTPResponse(exc.code, exc.read())


def _extract_text_content(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for part in value:
            if isinstance(part, Mapping):
                text = part.get("text")
                if isinstance(text, str):
                    parts.append(text)
        return "".join(parts) if parts else None
    return None


def _extract_usage(value: object) -> Mapping[str, int] | None:
    if not isinstance(value, Mapping):
        return None
    aliases = {
        "prompt_tokens": ("prompt_tokens", "input_tokens"),
        "completion_tokens": ("completion_tokens", "output_tokens"),
        "total_tokens": ("total_tokens",),
    }
    normalized: dict[str, int] = {}
    for target, candidates in aliases.items():
        for key in candidates:
            raw = value.get(key)
            if isinstance(raw, int) and not isinstance(raw, bool):
                normalized[target] = raw
                break
    return normalized or None


def _invoke_openai_compatible(
    *,
    endpoint: str,
    api_key: str,
    requested_model_id: str,
    envelope: bytes,
    timeout_seconds: float,
    temperature: float,
    max_tokens: int,
    transport: Transport,
) -> ProviderResult:
    payload: dict[str, object] = {
        "model": requested_model_id,
        "messages": [{"role": "user", "content": envelope.decode("utf-8")}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": "llm-evaluation-lab-b2-blind-eval/1",
    }
    response = transport(endpoint, headers, payload, timeout_seconds)
    if response.status < 200 or response.status >= 300:
        # Never include a provider error body in a public-safe receipt. Providers
        # may echo request content, so status-only normalization is intentional.
        raise ProviderCallError(
            error_code="PROVIDER_HTTP_ERROR",
            safe_message=f"provider returned HTTP {response.status}",
            http_status=response.status,
        )

    try:
        document = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderCallError(
            error_code="INVALID_PROVIDER_JSON",
            safe_message="provider response is not valid UTF-8 JSON",
            http_status=response.status,
        ) from exc
    if not isinstance(document, Mapping):
        raise ProviderCallError(
            error_code="INVALID_PROVIDER_SCHEMA",
            safe_message="provider response JSON must be an object",
            http_status=response.status,
        )

    choices = document.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
        raise ProviderCallError(
            error_code="INVALID_PROVIDER_SCHEMA",
            safe_message="provider response has no choices[0]",
            http_status=response.status,
        )
    message = choices[0].get("message")
    if not isinstance(message, Mapping):
        raise ProviderCallError(
            error_code="INVALID_PROVIDER_SCHEMA",
            safe_message="provider response has no choices[0].message",
            http_status=response.status,
        )
    content = _extract_text_content(message.get("content"))
    if content is None or not content.strip():
        raise ProviderCallError(
            error_code="EMPTY_FINAL_CONTENT",
            safe_message="provider returned empty final content",
            http_status=response.status,
        )

    resolved_model = document.get("model")
    response_id = document.get("id")
    return ProviderResult(
        raw_output=content,
        resolved_model_id=resolved_model if isinstance(resolved_model, str) else None,
        response_id=response_id if isinstance(response_id, str) else None,
        http_status=response.status,
        usage=_extract_usage(document.get("usage")),
    )


def _receipt(
    *,
    req: BlindEvalRequest,
    terminal_status: str,
    envelope: bytes,
    started_at: str,
    started_perf: float,
    now_fn: NowFn,
    perf_fn: PerfFn,
    resolved_model_id: str | None = None,
    raw_output: str | None = None,
    http_status: int | None = None,
    provider_response_id: str | None = None,
    usage: Mapping[str, int] | None = None,
    error_code: str | None = None,
    safe_error_message: str | None = None,
) -> BlindEvalReceipt:
    completed_at = now_fn()
    raw_bytes = raw_output.encode("utf-8") if raw_output is not None else None
    return BlindEvalReceipt(
        schema_version=BLIND_EVAL_PROTOCOL_VERSION,
        run_id=req.run_id,
        terminal_status=terminal_status,
        protocol_version=BLIND_EVAL_PROTOCOL_VERSION,
        envelope_version=BLIND_INPUT_ENVELOPE_VERSION,
        provider_label=req.provider_label,
        provider_protocol=req.provider_protocol,
        requested_model_id=req.requested_model_id,
        resolved_model_id=resolved_model_id,
        context_sha256=_sha256_bytes(req.context_bytes),
        prompt_sha256=_sha256_bytes(req.prompt_bytes),
        input_envelope_sha256=_sha256_bytes(envelope),
        context_bytes=len(req.context_bytes),
        prompt_bytes=len(req.prompt_bytes),
        raw_output_sha256=_sha256_bytes(raw_bytes) if raw_bytes is not None else None,
        raw_output_bytes=len(raw_bytes) if raw_bytes is not None else None,
        started_at=started_at,
        completed_at=completed_at,
        duration_ms=round((perf_fn() - started_perf) * 1000.0, 3),
        http_status=http_status,
        provider_response_id=provider_response_id,
        usage=usage,
        automatic_retries=AUTOMATIC_RETRIES,
        error_code=error_code,
        safe_error_message=safe_error_message,
        git_commit=req.git_commit,
    )


def run_blind_eval(
    req: BlindEvalRequest,
    *,
    authorize_live_call: bool,
    credential_lookup: CredentialLookup = os.environ.get,
    transport: Transport = _default_transport,
    now_fn: NowFn = _utc_now,
    perf_fn: PerfFn = perf_counter,
) -> tuple[BlindEvalReceipt, str | None]:
    """Run exactly one provider attempt; never retry or score quality."""

    started_at = now_fn()
    started_perf = perf_fn()
    try:
        envelope = build_input_envelope(req.context_bytes, req.prompt_bytes)
    except (UnicodeDecodeError, ValueError) as exc:
        return (
            _receipt(
                req=req,
                terminal_status="ERROR",
                envelope=b"",
                started_at=started_at,
                started_perf=started_perf,
                now_fn=now_fn,
                perf_fn=perf_fn,
                error_code="INVALID_UTF8_INPUT",
                safe_error_message=_safe_error_message(exc, ()),
            ),
            None,
        )

    # Critical gate: authorization precedes credential lookup and transport.
    if not authorize_live_call:
        return (
            _receipt(
                req=req,
                terminal_status="NOT_EVALUABLE",
                envelope=envelope,
                started_at=started_at,
                started_perf=started_perf,
                now_fn=now_fn,
                perf_fn=perf_fn,
                error_code="LIVE_CALL_NOT_AUTHORIZED",
                safe_error_message="live call requires explicit authorization",
            ),
            None,
        )

    if req.provider_protocol != OPENAI_COMPATIBLE_PROTOCOL:
        return (
            _receipt(
                req=req,
                terminal_status="NOT_EVALUABLE",
                envelope=envelope,
                started_at=started_at,
                started_perf=started_perf,
                now_fn=now_fn,
                perf_fn=perf_fn,
                error_code="UNSUPPORTED_PROVIDER_PROTOCOL",
                safe_error_message="provider protocol is not implemented by this bridge version",
            ),
            None,
        )

    api_key = credential_lookup(req.api_key_env)
    if not isinstance(api_key, str) or not api_key:
        return (
            _receipt(
                req=req,
                terminal_status="NOT_EVALUABLE",
                envelope=envelope,
                started_at=started_at,
                started_perf=started_perf,
                now_fn=now_fn,
                perf_fn=perf_fn,
                error_code="MISSING_CREDENTIAL",
                safe_error_message=f"credential env {req.api_key_env!r} is unavailable",
            ),
            None,
        )

    try:
        result = _invoke_openai_compatible(
            endpoint=req.endpoint,
            api_key=api_key,
            requested_model_id=req.requested_model_id,
            envelope=envelope,
            timeout_seconds=req.timeout_seconds,
            temperature=req.temperature,
            max_tokens=req.max_tokens,
            transport=transport,
        )
    except ProviderCallError as exc:
        return (
            _receipt(
                req=req,
                terminal_status="NOT_EVALUABLE",
                envelope=envelope,
                started_at=started_at,
                started_perf=started_perf,
                now_fn=now_fn,
                perf_fn=perf_fn,
                http_status=exc.http_status,
                error_code=exc.error_code,
                safe_error_message=exc.safe_message,
            ),
            None,
        )
    except Exception as exc:  # local transport failures are not quality evidence
        return (
            _receipt(
                req=req,
                terminal_status="NOT_EVALUABLE",
                envelope=envelope,
                started_at=started_at,
                started_perf=started_perf,
                now_fn=now_fn,
                perf_fn=perf_fn,
                error_code="TRANSPORT_ERROR",
                safe_error_message=_safe_error_message(exc, (api_key,)),
            ),
            None,
        )

    return (
        _receipt(
            req=req,
            terminal_status="PASS",
            envelope=envelope,
            started_at=started_at,
            started_perf=started_perf,
            now_fn=now_fn,
            perf_fn=perf_fn,
            resolved_model_id=result.resolved_model_id,
            raw_output=result.raw_output,
            http_status=result.http_status,
            provider_response_id=result.response_id,
            usage=result.usage,
        ),
        result.raw_output,
    )


def _new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"B2-BLIND-{stamp}-{uuid.uuid4().hex[:8]}"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m b2.blind_eval")
    parser.add_argument("--context-file", required=True)
    parser.add_argument("--prompt-file", required=True)
    parser.add_argument("--provider", required=True, help="metadata label only")
    parser.add_argument("--protocol", default=OPENAI_COMPATIBLE_PROTOCOL)
    parser.add_argument("--model", required=True)
    parser.add_argument("--endpoint", required=True)
    parser.add_argument("--api-key-env", required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--git-commit")
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--temperature", type=float, default=0.0)
    parser.add_argument("--max-tokens", type=int, default=8192)
    parser.add_argument("--raw-output", required=True)
    parser.add_argument("--receipt-output", required=True)
    parser.add_argument("--authorize-live-call", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    context_bytes = Path(args.context_file).read_bytes()
    prompt_bytes = Path(args.prompt_file).read_bytes()
    req = BlindEvalRequest(
        run_id=args.run_id or _new_run_id(),
        provider_label=args.provider,
        provider_protocol=args.protocol,
        requested_model_id=args.model,
        endpoint=args.endpoint,
        api_key_env=args.api_key_env,
        context_bytes=context_bytes,
        prompt_bytes=prompt_bytes,
        timeout_seconds=args.timeout,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        git_commit=args.git_commit,
    )
    receipt, raw_output = run_blind_eval(req, authorize_live_call=args.authorize_live_call)
    Path(args.receipt_output).write_text(receipt.render_json(), encoding="utf-8")
    if receipt.terminal_status == "PASS" and raw_output is not None:
        Path(args.raw_output).write_text(raw_output, encoding="utf-8")
    print(receipt.render_json(), end="")
    if receipt.terminal_status == "PASS":
        return 0
    return 2 if receipt.terminal_status == "NOT_EVALUABLE" else 3


if __name__ == "__main__":
    raise SystemExit(main())
