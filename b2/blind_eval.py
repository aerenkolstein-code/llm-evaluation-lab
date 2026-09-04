"""Generic B2 blind-evaluation bridge.

The bridge sends two byte-frozen UTF-8 inputs (long context + prompt) through
one explicitly authorized provider request and returns the raw answer separately
from a sanitized, body-free receipt. It never scores model quality, calls tools
or search, follows provider redirects, or retries a provider automatically.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import tempfile
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Callable, Mapping, Sequence
from urllib import error, request

BLIND_EVAL_PROTOCOL_VERSION = "b2-blind-eval-bridge/v2"
BLIND_INPUT_ENVELOPE_VERSION = "b2-blind-input-envelope/v1"
OPENAI_COMPATIBLE_PROTOCOL = "openai-compatible-chat-completions/v1"
AUTOMATIC_RETRIES = 0
TERMINAL_STATUSES = {"PASS", "NOT_EVALUABLE", "ERROR"}
_PROVIDER_MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+\-]{0,127}$")
_PROVIDER_RESPONSE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-]{0,127}$")
_PROVIDER_FINISH_REASON_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:\-]{0,63}$")


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


def _safe_provider_metadata(value: object, *, kind: str) -> str | None:
    """Keep only short ASCII token-like provider metadata; omit everything else.

    These fields are provider-controlled and therefore cannot be copied verbatim
    into a public-safe receipt. Model identifiers may contain one provider/model
    slash; response IDs are deliberately stricter. URLs and locator-like values
    are rejected even when they otherwise fit the character class.
    """

    if not isinstance(value, str):
        return None
    candidate = value.strip()
    if not candidate or "://" in candidate:
        return None
    patterns = {
        "model": _PROVIDER_MODEL_RE,
        "response_id": _PROVIDER_RESPONSE_ID_RE,
        "finish_reason": _PROVIDER_FINISH_REASON_RE,
    }
    try:
        pattern = patterns[kind]
    except KeyError as exc:
        raise ValueError(f"unsupported provider metadata kind: {kind}") from exc
    if pattern.fullmatch(candidate) is None:
        return None
    return candidate


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
    observation: "ProviderObservation"


@dataclass(frozen=True)
class ProviderObservation:
    """Body-free facts observed from one provider response.

    The object deliberately retains only booleans, counts, hashes, bounded
    token-like identifiers, and usage integers. Provider message bodies never
    cross this boundary.
    """

    http_status: int | None = None
    response_json_parsed: bool | None = None
    response_schema_parsed: bool | None = None
    message_schema_parsed: bool | None = None
    resolved_model_id: str | None = None
    response_id: str | None = None
    finish_reason: str | None = None
    reasoning_field_present: bool | None = None
    reasoning_bytes: int | None = None
    reasoning_sha256: str | None = None
    final_content_field_present: bool | None = None
    final_content_bytes: int | None = None
    final_content_sha256: str | None = None
    usage: Mapping[str, int] | None = None


@dataclass(frozen=True)
class BlindEvalReceipt:
    schema_version: str
    run_id: str
    terminal_status: str
    protocol_version: str
    envelope_version: str
    provider_label: str
    provider_protocol: str
    requested_model_id: str | None
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
    response_json_parsed: bool | None
    response_schema_parsed: bool | None
    message_schema_parsed: bool | None
    finish_reason: str | None
    reasoning_field_present: bool | None
    reasoning_bytes: int | None
    reasoning_sha256: str | None
    final_content_field_present: bool | None
    final_content_bytes: int | None
    final_content_sha256: str | None
    usage: Mapping[str, int] | None
    provider_attempts: int
    automatic_retries: int
    quality_score: float | None
    error_code: str | None
    safe_error_message: str | None
    git_commit: str | None

    def as_dict(self) -> dict[str, object]:
        document = asdict(self)
        if document["terminal_status"] not in TERMINAL_STATUSES:
            raise ValueError("invalid terminal status")
        if document["provider_attempts"] not in {0, 1}:
            raise ValueError("provider attempts must be zero or one")
        if document["automatic_retries"] != 0:
            raise ValueError("automatic retries must remain zero")
        if document["quality_score"] is not None:
            raise ValueError("the bridge must not emit a model-quality score")
        if self.terminal_status == "PASS":
            if (
                self.provider_attempts != 1
                or self.raw_output_sha256 is None
                or self.raw_output_bytes is None
                or self.final_content_sha256 != self.raw_output_sha256
                or self.final_content_bytes != self.raw_output_bytes
            ):
                raise ValueError("PASS requires one attempt and matching final evidence")
        elif self.raw_output_sha256 is not None or self.raw_output_bytes is not None:
            raise ValueError("non-PASS receipt must not carry raw-output evidence")
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
        observation: ProviderObservation | None = None,
    ) -> None:
        super().__init__(safe_message)
        self.error_code = error_code
        self.safe_message = safe_message
        self.observation = observation or ProviderObservation()


class OutputCommitError(RuntimeError):
    """Private output pair could not be committed without ambiguity."""


class _NoRedirectHandler(request.HTTPRedirectHandler):
    """Fail closed on all redirects; never construct a follow-up request."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: ANN001
        return None


Transport = Callable[[str, Mapping[str, str], Mapping[str, object], float], ProviderHTTPResponse]
CredentialLookup = Callable[[str], str | None]
NowFn = Callable[[], str]
PerfFn = Callable[[], float]
ReplaceFn = Callable[[str, str], object]


def _default_transport(
    endpoint: str,
    headers: Mapping[str, str],
    payload: Mapping[str, object],
    timeout_seconds: float,
) -> ProviderHTTPResponse:
    """Make one POST attempt with redirects disabled."""

    encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(endpoint, data=encoded, headers=dict(headers), method="POST")
    opener = request.build_opener(_NoRedirectHandler())
    try:
        with opener.open(req, timeout=timeout_seconds) as response:
            return ProviderHTTPResponse(response.status, response.read())
    except error.HTTPError as exc:
        # A 30x arrives here because _NoRedirectHandler refuses to create a
        # second request. The response body remains private and is never copied
        # into the receipt by _invoke_openai_compatible.
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
            if (
                isinstance(raw, int)
                and not isinstance(raw, bool)
                and 0 <= raw <= 2**63 - 1
            ):
                normalized[target] = raw
                break
    return normalized or None


def _content_evidence(
    value: object,
    *,
    field_present: bool,
) -> tuple[str | None, int | None, str | None]:
    """Return extracted text plus body-free byte/hash evidence.

    A missing field is distinguishable from an explicit null or empty value.
    Hashes are retained only for semantically non-empty text. The text itself
    is returned only to the private caller and is never placed in a receipt.
    """

    if not field_present:
        return None, None, None
    text = _extract_text_content(value)
    if text is None:
        return None, 0, None
    encoded = text.encode("utf-8")
    digest = _sha256_bytes(encoded) if text.strip() else None
    return text, len(encoded), digest


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
    initial_observation = ProviderObservation(http_status=response.status)
    if response.status < 200 or response.status >= 300:
        raise ProviderCallError(
            error_code="PROVIDER_HTTP_ERROR",
            safe_message=f"provider returned HTTP {response.status}",
            observation=initial_observation,
        )

    try:
        document = json.loads(response.body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderCallError(
            error_code="INVALID_PROVIDER_JSON",
            safe_message="provider response is not valid UTF-8 JSON",
            observation=ProviderObservation(
                http_status=response.status,
                response_json_parsed=False,
                response_schema_parsed=False,
                message_schema_parsed=False,
            ),
        ) from exc
    if not isinstance(document, Mapping):
        raise ProviderCallError(
            error_code="INVALID_PROVIDER_SCHEMA",
            safe_message="provider response JSON must be an object",
            observation=ProviderObservation(
                http_status=response.status,
                response_json_parsed=True,
                response_schema_parsed=False,
                message_schema_parsed=False,
            ),
        )

    resolved_model_id = _safe_provider_metadata(document.get("model"), kind="model")
    response_id = _safe_provider_metadata(document.get("id"), kind="response_id")
    usage = _extract_usage(document.get("usage"))

    choices = document.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
        raise ProviderCallError(
            error_code="INVALID_PROVIDER_SCHEMA",
            safe_message="provider response has no choices[0]",
            observation=ProviderObservation(
                http_status=response.status,
                response_json_parsed=True,
                response_schema_parsed=False,
                message_schema_parsed=False,
                resolved_model_id=resolved_model_id,
                response_id=response_id,
                usage=usage,
            ),
        )
    choice = choices[0]
    finish_reason = _safe_provider_metadata(
        choice.get("finish_reason"), kind="finish_reason"
    )
    message = choice.get("message")
    if not isinstance(message, Mapping):
        raise ProviderCallError(
            error_code="INVALID_PROVIDER_SCHEMA",
            safe_message="provider response has no choices[0].message",
            observation=ProviderObservation(
                http_status=response.status,
                response_json_parsed=True,
                response_schema_parsed=True,
                message_schema_parsed=False,
                resolved_model_id=resolved_model_id,
                response_id=response_id,
                finish_reason=finish_reason,
                usage=usage,
            ),
        )

    reasoning_keys = ("reasoning_content", "reasoning", "analysis")
    reasoning_key = next((key for key in reasoning_keys if key in message), None)
    _reasoning, reasoning_bytes, reasoning_sha256 = _content_evidence(
        message.get(reasoning_key) if reasoning_key is not None else None,
        field_present=reasoning_key is not None,
    )
    content, final_bytes, final_sha256 = _content_evidence(
        message.get("content"),
        field_present="content" in message,
    )
    observation = ProviderObservation(
        http_status=response.status,
        response_json_parsed=True,
        response_schema_parsed=True,
        message_schema_parsed=True,
        resolved_model_id=resolved_model_id,
        response_id=response_id,
        finish_reason=finish_reason,
        reasoning_field_present=reasoning_key is not None,
        reasoning_bytes=reasoning_bytes,
        reasoning_sha256=reasoning_sha256,
        final_content_field_present="content" in message,
        final_content_bytes=final_bytes,
        final_content_sha256=final_sha256,
        usage=usage,
    )
    if content is None or not content.strip():
        raise ProviderCallError(
            error_code="EMPTY_FINAL_CONTENT",
            safe_message="provider returned empty final content",
            observation=observation,
        )

    return ProviderResult(
        raw_output=content,
        observation=observation,
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
    raw_output: str | None = None,
    provider_attempts: int = 0,
    observation: ProviderObservation | None = None,
    error_code: str | None = None,
    safe_error_message: str | None = None,
) -> BlindEvalReceipt:
    completed_at = now_fn()
    raw_bytes = raw_output.encode("utf-8") if raw_output is not None else None
    observed = observation or ProviderObservation()
    return BlindEvalReceipt(
        schema_version=BLIND_EVAL_PROTOCOL_VERSION,
        run_id=req.run_id,
        terminal_status=terminal_status,
        protocol_version=BLIND_EVAL_PROTOCOL_VERSION,
        envelope_version=BLIND_INPUT_ENVELOPE_VERSION,
        provider_label=req.provider_label,
        provider_protocol=req.provider_protocol,
        requested_model_id=_safe_provider_metadata(req.requested_model_id, kind="model"),
        resolved_model_id=observed.resolved_model_id,
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
        http_status=observed.http_status,
        provider_response_id=observed.response_id,
        response_json_parsed=observed.response_json_parsed,
        response_schema_parsed=observed.response_schema_parsed,
        message_schema_parsed=observed.message_schema_parsed,
        finish_reason=observed.finish_reason,
        reasoning_field_present=observed.reasoning_field_present,
        reasoning_bytes=observed.reasoning_bytes,
        reasoning_sha256=observed.reasoning_sha256,
        final_content_field_present=observed.final_content_field_present,
        final_content_bytes=observed.final_content_bytes,
        final_content_sha256=observed.final_content_sha256,
        usage=observed.usage,
        provider_attempts=provider_attempts,
        automatic_retries=AUTOMATIC_RETRIES,
        quality_score=None,
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

    if _safe_provider_metadata(req.requested_model_id, kind="model") != req.requested_model_id:
        return (
            _receipt(
                req=req,
                terminal_status="NOT_EVALUABLE",
                envelope=envelope,
                started_at=started_at,
                started_perf=started_perf,
                now_fn=now_fn,
                perf_fn=perf_fn,
                error_code="INVALID_REQUESTED_MODEL_ID",
                safe_error_message="requested model ID violates the strict token policy",
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
                safe_error_message="configured provider credential is unavailable",
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
                provider_attempts=1,
                observation=exc.observation,
                error_code=exc.error_code,
                safe_error_message=exc.safe_message,
            ),
            None,
        )
    except Exception as exc:
        return (
            _receipt(
                req=req,
                terminal_status="NOT_EVALUABLE",
                envelope=envelope,
                started_at=started_at,
                started_perf=started_perf,
                now_fn=now_fn,
                perf_fn=perf_fn,
                provider_attempts=1,
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
            raw_output=result.raw_output,
            provider_attempts=1,
            observation=result.observation,
        ),
        result.raw_output,
    )


def _new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"B2-BLIND-{stamp}-{uuid.uuid4().hex[:8]}"


def _output_paths(raw_output: str | Path, receipt_output: str | Path) -> tuple[Path, Path]:
    raw_path = Path(raw_output).expanduser().resolve(strict=False)
    receipt_path = Path(receipt_output).expanduser().resolve(strict=False)
    if raw_path == receipt_path:
        raise OutputCommitError("raw-output and receipt-output must resolve to distinct paths")
    if raw_path.exists() and receipt_path.exists():
        try:
            if os.path.samefile(raw_path, receipt_path):
                raise OutputCommitError("raw-output and receipt-output alias the same file")
        except OSError:
            pass
    return raw_path, receipt_path


def _remove_if_exists(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        return


def _stage_bytes(path: Path, data: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        return temp_path
    except Exception:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass
        raise


def commit_cli_outputs(
    receipt: BlindEvalReceipt,
    raw_output: str | None,
    *,
    raw_output_path: str | Path,
    receipt_output_path: str | Path,
    replace_fn: ReplaceFn = os.replace,
) -> None:
    """Commit one unambiguous output pair or leave neither target stale.

    Both target paths are cleared before a new pair is committed. PASS stages
    both files before publishing either target, publishes raw first and receipt
    last, and rolls back the raw target if receipt publication fails. Non-PASS
    publishes only the receipt and guarantees the raw target is absent.
    """

    raw_path, receipt_path = _output_paths(raw_output_path, receipt_output_path)
    if receipt.terminal_status == "PASS" and raw_output is None:
        raise OutputCommitError("PASS receipt requires a raw output body")
    if receipt.terminal_status != "PASS" and raw_output is not None:
        raise OutputCommitError("non-PASS receipt must not carry a raw output body")

    raw_temp: Path | None = None
    receipt_temp: Path | None = None
    try:
        if receipt.terminal_status == "PASS":
            raw_temp = _stage_bytes(raw_path, raw_output.encode("utf-8"))
        receipt_temp = _stage_bytes(receipt_path, receipt.render_json().encode("utf-8"))

        # Clear any prior run pair only after staging succeeded.
        _remove_if_exists(raw_path)
        _remove_if_exists(receipt_path)

        if receipt.terminal_status == "PASS":
            replace_fn(str(raw_temp), str(raw_path))
            raw_temp = None
            try:
                replace_fn(str(receipt_temp), str(receipt_path))
                receipt_temp = None
            except Exception:
                # Never leave a current PASS raw artifact without its matching
                # sanitized receipt. A failed pair publication is no evidence.
                _remove_if_exists(raw_path)
                _remove_if_exists(receipt_path)
                raise
        else:
            replace_fn(str(receipt_temp), str(receipt_path))
            receipt_temp = None
    except Exception as exc:
        _remove_if_exists(raw_path)
        _remove_if_exists(receipt_path)
        raise OutputCommitError(_safe_error_message(exc, ())) from exc
    finally:
        for temp_path in (raw_temp, receipt_temp):
            if temp_path is not None:
                try:
                    temp_path.unlink()
                except FileNotFoundError:
                    pass


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
    try:
        _output_paths(args.raw_output, args.receipt_output)
    except OutputCommitError as exc:
        raise SystemExit(f"blind-eval output path error: {exc}") from exc

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
    try:
        commit_cli_outputs(
            receipt,
            raw_output,
            raw_output_path=args.raw_output,
            receipt_output_path=args.receipt_output,
        )
    except OutputCommitError as exc:
        raise SystemExit(f"blind-eval output commit failed: {exc}") from exc

    print(receipt.render_json(), end="")
    if receipt.terminal_status == "PASS":
        return 0
    return 2 if receipt.terminal_status == "NOT_EVALUABLE" else 3


if __name__ == "__main__":
    raise SystemExit(main())
