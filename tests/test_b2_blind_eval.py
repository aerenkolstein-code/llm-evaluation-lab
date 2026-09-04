from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch
from urllib import error, request

from b2.blind_eval import (
    AUTOMATIC_RETRIES,
    BLIND_INPUT_ENVELOPE_VERSION,
    OPENAI_COMPATIBLE_PROTOCOL,
    BlindEvalRequest,
    OutputCommitError,
    ProviderHTTPResponse,
    _NoRedirectHandler,
    _default_transport,
    build_input_envelope,
    commit_cli_outputs,
    run_blind_eval,
)


class CountingTransport:
    def __init__(self, response=None, exc=None):
        self.response = response
        self.exc = exc
        self.calls = 0
        self.last_headers = None
        self.last_payload = None

    def __call__(self, endpoint, headers, payload, timeout):
        self.calls += 1
        self.last_headers = dict(headers)
        self.last_payload = dict(payload)
        if self.exc:
            raise self.exc
        return self.response


def make_request(context=b"context", prompt=b"prompt"):
    return BlindEvalRequest(
        run_id="B2-BLIND-TEST-001",
        provider_label="fixture-provider",
        provider_protocol=OPENAI_COMPATIBLE_PROTOCOL,
        requested_model_id="fixture-model",
        endpoint="https://example.invalid/v1/chat/completions",
        api_key_env="TEST_API_KEY",
        context_bytes=context,
        prompt_bytes=prompt,
        git_commit="a" * 40,
    )


def fixed_now():
    return "2026-09-04T00:00:00Z"


def fixed_perf():
    return 100.0


def success_receipt(raw="model answer"):
    response = ProviderHTTPResponse(
        200,
        json.dumps({
            "id": "resp-123",
            "model": "fixture-model-resolved",
            "choices": [{"message": {"content": raw}}],
        }).encode(),
    )
    return run_blind_eval(
        make_request(),
        authorize_live_call=True,
        credential_lookup=lambda _: "fixture-key",
        transport=CountingTransport(response=response),
        now_fn=fixed_now,
        perf_fn=fixed_perf,
    )


class BlindEvalBridgeTests(unittest.TestCase):
    def test_authorization_precedes_credential_lookup_and_network(self):
        looked_up = []
        transport = CountingTransport()

        def lookup(name):
            looked_up.append(name)
            raise AssertionError("credential lookup must not happen")

        receipt, raw = run_blind_eval(
            make_request(),
            authorize_live_call=False,
            credential_lookup=lookup,
            transport=transport,
        )
        self.assertEqual("NOT_EVALUABLE", receipt.terminal_status)
        self.assertEqual("LIVE_CALL_NOT_AUTHORIZED", receipt.error_code)
        self.assertEqual([], looked_up)
        self.assertEqual(0, transport.calls)
        self.assertIsNone(raw)

    def test_success_is_one_attempt_with_body_free_receipt(self):
        secret = "fixture-credential-value"
        response = ProviderHTTPResponse(
            200,
            json.dumps({
                "id": "resp-123",
                "model": "fixture-model-resolved",
                "choices": [{
                    "finish_reason": "stop",
                    "message": {
                        "reasoning_content": "private reasoning body",
                        "content": "model answer",
                    },
                }],
                "usage": {"prompt_tokens": 20, "completion_tokens": 3, "total_tokens": 23},
            }).encode(),
        )
        transport = CountingTransport(response=response)
        req = make_request(context=b"private context body", prompt=b"private prompt body")
        receipt, raw = run_blind_eval(
            req,
            authorize_live_call=True,
            credential_lookup=lambda _: secret,
            transport=transport,
        )
        self.assertEqual("PASS", receipt.terminal_status)
        self.assertEqual(1, transport.calls)
        self.assertEqual(AUTOMATIC_RETRIES, receipt.automatic_retries)
        self.assertEqual(1, receipt.provider_attempts)
        self.assertEqual("model answer", raw)
        self.assertEqual("fixture-model-resolved", receipt.resolved_model_id)
        self.assertEqual("resp-123", receipt.provider_response_id)
        self.assertEqual(23, receipt.usage["total_tokens"])
        self.assertEqual("stop", receipt.finish_reason)
        self.assertTrue(receipt.response_json_parsed)
        self.assertTrue(receipt.response_schema_parsed)
        self.assertTrue(receipt.message_schema_parsed)
        self.assertTrue(receipt.reasoning_field_present)
        self.assertEqual(len(b"private reasoning body"), receipt.reasoning_bytes)
        self.assertTrue(receipt.reasoning_sha256.startswith("sha256:"))
        self.assertTrue(receipt.final_content_field_present)
        self.assertEqual(len(b"model answer"), receipt.final_content_bytes)
        self.assertEqual(receipt.raw_output_sha256, receipt.final_content_sha256)
        self.assertIsNone(receipt.quality_score)
        rendered = receipt.render_json()
        self.assertNotIn("private context body", rendered)
        self.assertNotIn("private prompt body", rendered)
        self.assertNotIn("model answer", rendered)
        self.assertNotIn("private reasoning body", rendered)
        self.assertNotIn(secret, rendered)

    def test_fake_run_receipt_is_byte_stable_with_frozen_clock(self):
        req = make_request(context="材料".encode(), prompt="问题".encode())
        response = ProviderHTTPResponse(
            200,
            json.dumps({
                "id": "fixed-response",
                "model": "fixed-model",
                "choices": [{"message": {"content": "固定答案"}}],
                "usage": {"total_tokens": 42},
            }, ensure_ascii=False).encode("utf-8"),
        )
        kwargs = dict(
            authorize_live_call=True,
            credential_lookup=lambda _: "fixture-key",
            now_fn=fixed_now,
            perf_fn=fixed_perf,
        )
        a, raw_a = run_blind_eval(req, transport=CountingTransport(response=response), **kwargs)
        b, raw_b = run_blind_eval(req, transport=CountingTransport(response=response), **kwargs)
        self.assertEqual("固定答案", raw_a)
        self.assertEqual(raw_a, raw_b)
        self.assertEqual(a.render_json(), b.render_json())

    def test_v2_receipt_fields_match_closed_json_schema(self):
        receipt, _ = success_receipt()
        document = receipt.as_dict()
        schema = json.loads(
            Path("schemas/blind_eval_receipt.schema.json").read_text(encoding="utf-8")
        )
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual("b2-blind-eval-bridge/v2", schema["properties"]["schema_version"]["const"])
        self.assertEqual(set(schema["required"]), set(document))
        self.assertEqual(set(schema["properties"]), set(document))

    def test_http_error_body_is_never_copied_to_receipt(self):
        private_echo = "private context body echoed by provider"
        response = ProviderHTTPResponse(429, json.dumps({"error": private_echo}).encode())
        transport = CountingTransport(response=response)
        receipt, raw = run_blind_eval(
            make_request(context=b"private context body"),
            authorize_live_call=True,
            credential_lookup=lambda _: "fixture-credential",
            transport=transport,
        )
        self.assertEqual("NOT_EVALUABLE", receipt.terminal_status)
        self.assertEqual("PROVIDER_HTTP_ERROR", receipt.error_code)
        self.assertEqual(429, receipt.http_status)
        self.assertEqual(1, receipt.provider_attempts)
        self.assertEqual(1, transport.calls)
        self.assertIsNone(raw)
        self.assertNotIn(private_echo, receipt.render_json())

    def test_redirect_handler_refuses_followup_request(self):
        handler = _NoRedirectHandler()
        original = request.Request(
            "https://provider.example/v1/chat/completions",
            data=b"{}",
            headers={"Authorization": "Bearer secret"},
            method="POST",
        )
        headers = Message()
        headers["Location"] = "https://attacker.invalid/collect"
        redirected = handler.redirect_request(
            original,
            None,
            302,
            "Found",
            headers,
            "https://attacker.invalid/collect",
        )
        self.assertIsNone(redirected)
        self.assertEqual("Bearer secret", original.get_header("Authorization"))

    def test_default_transport_30x_is_one_attempt_and_not_followed(self):
        class FakeOpener:
            def __init__(self):
                self.calls = 0
                self.requests = []

            def open(self, req, timeout):
                self.calls += 1
                self.requests.append(req)
                headers = Message()
                headers["Location"] = "https://attacker.invalid/collect"
                raise error.HTTPError(req.full_url, 302, "Found", headers, io.BytesIO(b"redirect"))

        fake = FakeOpener()
        captured_handlers = []

        def fake_build_opener(*handlers):
            captured_handlers.extend(handlers)
            return fake

        with patch("b2.blind_eval.request.build_opener", side_effect=fake_build_opener):
            result = _default_transport(
                "https://provider.example/v1/chat/completions",
                {"Authorization": "Bearer secret", "Content-Type": "application/json"},
                {"model": "fixture", "messages": []},
                5.0,
            )
        self.assertEqual(302, result.status)
        self.assertEqual(1, fake.calls)
        self.assertEqual(1, len(fake.requests))
        self.assertTrue(any(isinstance(handler, _NoRedirectHandler) for handler in captured_handlers))
        self.assertEqual("Bearer secret", fake.requests[0].get_header("Authorization"))

    def test_provider_controlled_metadata_is_omitted_on_echo_or_oversize(self):
        private = "private context body"
        response = ProviderHTTPResponse(
            200,
            json.dumps({
                "id": f"https://private.example/{private}",
                "model": private,
                "choices": [{"message": {"content": "answer"}}],
            }).encode(),
        )
        receipt, raw = run_blind_eval(
            make_request(context=private.encode()),
            authorize_live_call=True,
            credential_lookup=lambda _: "key",
            transport=CountingTransport(response=response),
        )
        self.assertEqual("PASS", receipt.terminal_status)
        self.assertEqual("answer", raw)
        self.assertIsNone(receipt.resolved_model_id)
        self.assertIsNone(receipt.provider_response_id)
        self.assertNotIn(private, receipt.render_json())

        oversize = "m" * 129
        response2 = ProviderHTTPResponse(
            200,
            json.dumps({
                "id": "r" * 129,
                "model": oversize,
                "choices": [{"message": {"content": "answer"}}],
            }).encode(),
        )
        receipt2, _ = run_blind_eval(
            make_request(),
            authorize_live_call=True,
            credential_lookup=lambda _: "key",
            transport=CountingTransport(response=response2),
        )
        self.assertIsNone(receipt2.resolved_model_id)
        self.assertIsNone(receipt2.provider_response_id)

    def test_nonpass_commit_removes_stale_raw(self):
        with tempfile.TemporaryDirectory() as td:
            raw_path = Path(td) / "run.raw.txt"
            receipt_path = Path(td) / "run.receipt.json"
            raw_path.write_text("stale answer", encoding="utf-8")
            receipt_path.write_text("stale receipt", encoding="utf-8")
            receipt, raw = run_blind_eval(
                make_request(), authorize_live_call=False,
                now_fn=fixed_now, perf_fn=fixed_perf,
            )
            commit_cli_outputs(
                receipt, raw,
                raw_output_path=raw_path,
                receipt_output_path=receipt_path,
            )
            self.assertFalse(raw_path.exists())
            self.assertEqual(receipt.render_json(), receipt_path.read_text(encoding="utf-8"))

    def test_output_path_alias_is_rejected_before_commit(self):
        receipt, raw = success_receipt()
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "same.txt"
            with self.assertRaises(OutputCommitError):
                commit_cli_outputs(
                    receipt, raw,
                    raw_output_path=path,
                    receipt_output_path=path,
                )
            self.assertFalse(path.exists())

    def test_raw_publication_failure_leaves_no_pass_receipt(self):
        receipt, raw = success_receipt()
        with tempfile.TemporaryDirectory() as td:
            raw_path = Path(td) / "run.raw.txt"
            receipt_path = Path(td) / "run.receipt.json"
            def fail_first_replace(src, dst):
                raise OSError("raw replace failed")
            with self.assertRaises(OutputCommitError):
                commit_cli_outputs(
                    receipt, raw,
                    raw_output_path=raw_path,
                    receipt_output_path=receipt_path,
                    replace_fn=fail_first_replace,
                )
            self.assertFalse(raw_path.exists())
            self.assertFalse(receipt_path.exists())

    def test_receipt_publication_failure_rolls_back_raw(self):
        receipt, raw = success_receipt()
        with tempfile.TemporaryDirectory() as td:
            raw_path = Path(td) / "run.raw.txt"
            receipt_path = Path(td) / "run.receipt.json"
            calls = 0
            def fail_second_replace(src, dst):
                nonlocal calls
                calls += 1
                if calls == 2:
                    raise OSError("receipt replace failed")
                return os.replace(src, dst)
            with self.assertRaises(OutputCommitError):
                commit_cli_outputs(
                    receipt, raw,
                    raw_output_path=raw_path,
                    receipt_output_path=receipt_path,
                    replace_fn=fail_second_replace,
                )
            self.assertEqual(2, calls)
            self.assertFalse(raw_path.exists())
            self.assertFalse(receipt_path.exists())

    def test_empty_output_is_not_evaluable(self):
        response = ProviderHTTPResponse(
            200,
            json.dumps({"choices": [{"message": {"content": "   "}}]}).encode(),
        )
        receipt, raw = run_blind_eval(
            make_request(),
            authorize_live_call=True,
            credential_lookup=lambda _: "key",
            transport=CountingTransport(response=response),
        )
        self.assertEqual("NOT_EVALUABLE", receipt.terminal_status)
        self.assertEqual("EMPTY_FINAL_CONTENT", receipt.error_code)
        self.assertEqual(200, receipt.http_status)
        self.assertEqual(1, receipt.provider_attempts)
        self.assertTrue(receipt.final_content_field_present)
        self.assertEqual(3, receipt.final_content_bytes)
        self.assertIsNone(receipt.final_content_sha256)
        self.assertIsNone(receipt.quality_score)
        self.assertIsNone(raw)

    def test_null_and_reasoning_only_final_are_diagnosable_without_body(self):
        private_reasoning = "private chain of thought"
        for content in (None, ""):
            response = ProviderHTTPResponse(
                200,
                json.dumps({
                    "id": "resp-reasoning-only",
                    "model": "fixture-model-resolved",
                    "choices": [{
                        "finish_reason": "length",
                        "message": {
                            "reasoning_content": private_reasoning,
                            "content": content,
                        },
                    }],
                    "usage": {
                        "prompt_tokens": 10,
                        "completion_tokens": 20,
                        "total_tokens": 30,
                    },
                }).encode(),
            )
            with self.subTest(content=content):
                receipt, raw = run_blind_eval(
                    make_request(),
                    authorize_live_call=True,
                    credential_lookup=lambda _: "fixture-key",
                    transport=CountingTransport(response=response),
                    now_fn=fixed_now,
                    perf_fn=fixed_perf,
                )
                self.assertEqual("NOT_EVALUABLE", receipt.terminal_status)
                self.assertEqual("EMPTY_FINAL_CONTENT", receipt.error_code)
                self.assertEqual("length", receipt.finish_reason)
                self.assertTrue(receipt.response_json_parsed)
                self.assertTrue(receipt.response_schema_parsed)
                self.assertTrue(receipt.message_schema_parsed)
                self.assertTrue(receipt.reasoning_field_present)
                self.assertEqual(len(private_reasoning.encode()), receipt.reasoning_bytes)
                self.assertTrue(receipt.reasoning_sha256.startswith("sha256:"))
                self.assertTrue(receipt.final_content_field_present)
                self.assertEqual(0, receipt.final_content_bytes)
                self.assertIsNone(receipt.final_content_sha256)
                self.assertIsNone(receipt.quality_score)
                self.assertIsNone(raw)
                self.assertNotIn(private_reasoning, receipt.render_json())

    def test_finish_reason_and_provider_ids_are_strictly_sanitized(self):
        private = "private locator"
        response = ProviderHTTPResponse(
            200,
            json.dumps({
                "id": f"https://private.invalid/{private}",
                "model": private,
                "choices": [{
                    "finish_reason": "unsafe reason with spaces",
                    "message": {"content": "answer"},
                }],
            }).encode(),
        )
        receipt, raw = run_blind_eval(
            make_request(), authorize_live_call=True,
            credential_lookup=lambda _: "fixture-key",
            transport=CountingTransport(response=response),
        )
        self.assertEqual("answer", raw)
        self.assertIsNone(receipt.provider_response_id)
        self.assertIsNone(receipt.resolved_model_id)
        self.assertIsNone(receipt.finish_reason)
        self.assertNotIn(private, receipt.render_json())

    def test_schema_diagnostics_distinguish_json_response_and_message(self):
        cases = (
            (b"not-json", "INVALID_PROVIDER_JSON", False, False, False),
            (b"[]", "INVALID_PROVIDER_SCHEMA", True, False, False),
            (b'{"choices":[]}', "INVALID_PROVIDER_SCHEMA", True, False, False),
            (
                b'{"choices":[{"finish_reason":"stop","message":null}]}',
                "INVALID_PROVIDER_SCHEMA", True, True, False,
            ),
        )
        for body, code, json_ok, response_ok, message_ok in cases:
            transport = CountingTransport(response=ProviderHTTPResponse(200, body))
            with self.subTest(code=code, body=body):
                receipt, raw = run_blind_eval(
                    make_request(), authorize_live_call=True,
                    credential_lookup=lambda _: "fixture-key", transport=transport,
                )
                self.assertEqual("NOT_EVALUABLE", receipt.terminal_status)
                self.assertEqual(code, receipt.error_code)
                self.assertEqual(1, receipt.provider_attempts)
                self.assertEqual(1, transport.calls)
                self.assertIs(json_ok, receipt.response_json_parsed)
                self.assertIs(response_ok, receipt.response_schema_parsed)
                self.assertIs(message_ok, receipt.message_schema_parsed)
                self.assertIsNone(raw)

    def test_transport_error_is_exactly_one_attempt_and_secret_free(self):
        transport = CountingTransport(
            exc=TimeoutError("timeout with fixture-credential-value")
        )
        receipt, raw = run_blind_eval(
            make_request(), authorize_live_call=True,
            credential_lookup=lambda _: "fixture-credential-value", transport=transport,
        )
        self.assertEqual("NOT_EVALUABLE", receipt.terminal_status)
        self.assertEqual("TRANSPORT_ERROR", receipt.error_code)
        self.assertEqual(1, transport.calls)
        self.assertEqual(1, receipt.provider_attempts)
        self.assertEqual(0, receipt.automatic_retries)
        self.assertNotIn("fixture-credential-value", receipt.render_json())
        self.assertIsNone(raw)

    def test_invalid_requested_model_fails_before_credential_and_network(self):
        req = make_request()
        object.__setattr__(req, "requested_model_id", "https://private.invalid/model")
        looked_up = []
        transport = CountingTransport()
        receipt, raw = run_blind_eval(
            req, authorize_live_call=True,
            credential_lookup=lambda name: looked_up.append(name), transport=transport,
        )
        self.assertEqual("INVALID_REQUESTED_MODEL_ID", receipt.error_code)
        self.assertIsNone(receipt.requested_model_id)
        self.assertEqual(0, receipt.provider_attempts)
        self.assertEqual([], looked_up)
        self.assertEqual(0, transport.calls)
        self.assertIsNone(raw)

    def test_missing_credential_is_not_evaluable_without_network(self):
        transport = CountingTransport()
        receipt, _ = run_blind_eval(
            make_request(),
            authorize_live_call=True,
            credential_lookup=lambda _: None,
            transport=transport,
        )
        self.assertEqual("NOT_EVALUABLE", receipt.terminal_status)
        self.assertEqual("MISSING_CREDENTIAL", receipt.error_code)
        self.assertEqual(0, transport.calls)

    def test_envelope_is_versioned_and_contains_exact_inputs(self):
        envelope = build_input_envelope(b"AAA", b"BBB").decode()
        self.assertIn(BLIND_INPUT_ENVELOPE_VERSION, envelope)
        self.assertIn("AAA", envelope)
        self.assertIn("BBB", envelope)
        self.assertLess(envelope.index("AAA"), envelope.index("BBB"))


if __name__ == "__main__":
    unittest.main()
