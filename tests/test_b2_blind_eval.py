from __future__ import annotations

import json
import unittest

from b2.blind_eval import (
    AUTOMATIC_RETRIES,
    BLIND_INPUT_ENVELOPE_VERSION,
    OPENAI_COMPATIBLE_PROTOCOL,
    BlindEvalRequest,
    ProviderHTTPResponse,
    build_input_envelope,
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
        secret = "sk-super-secret-value"
        response = ProviderHTTPResponse(
            200,
            json.dumps(
                {
                    "id": "resp-123",
                    "model": "fixture-model-resolved",
                    "choices": [{"message": {"content": "model answer"}}],
                    "usage": {"prompt_tokens": 20, "completion_tokens": 3, "total_tokens": 23},
                }
            ).encode(),
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
        self.assertEqual("model answer", raw)
        self.assertEqual("fixture-model-resolved", receipt.resolved_model_id)
        self.assertEqual("resp-123", receipt.provider_response_id)
        self.assertEqual(23, receipt.usage["total_tokens"])
        rendered = receipt.render_json()
        self.assertNotIn("private context body", rendered)
        self.assertNotIn("private prompt body", rendered)
        self.assertNotIn("model answer", rendered)
        self.assertNotIn(secret, rendered)
        self.assertTrue(receipt.context_sha256.startswith("sha256:"))
        self.assertTrue(receipt.prompt_sha256.startswith("sha256:"))
        self.assertTrue(receipt.raw_output_sha256.startswith("sha256:"))

    def test_fingerprints_are_stable_for_same_bytes(self):
        req = make_request(context="材料".encode(), prompt="问题".encode())
        response = ProviderHTTPResponse(
            200,
            json.dumps({"choices": [{"message": {"content": "答"}}]}).encode(),
        )
        a, _ = run_blind_eval(
            req,
            authorize_live_call=True,
            credential_lookup=lambda _: "key",
            transport=CountingTransport(response=response),
        )
        b, _ = run_blind_eval(
            req,
            authorize_live_call=True,
            credential_lookup=lambda _: "key",
            transport=CountingTransport(response=response),
        )
        self.assertEqual(a.context_sha256, b.context_sha256)
        self.assertEqual(a.prompt_sha256, b.prompt_sha256)
        self.assertEqual(a.input_envelope_sha256, b.input_envelope_sha256)
        self.assertEqual(a.raw_output_sha256, b.raw_output_sha256)

    def test_http_error_is_not_evaluable_and_not_retried(self):
        secret = "sk-do-not-leak-this"
        response = ProviderHTTPResponse(429, json.dumps({"error": f"quota rejected {secret}"}).encode())
        transport = CountingTransport(response=response)
        receipt, raw = run_blind_eval(
            make_request(),
            authorize_live_call=True,
            credential_lookup=lambda _: secret,
            transport=transport,
        )
        self.assertEqual("NOT_EVALUABLE", receipt.terminal_status)
        self.assertEqual(429, receipt.http_status)
        self.assertEqual(1, transport.calls)
        self.assertEqual(0, receipt.automatic_retries)
        self.assertIsNone(raw)
        self.assertNotIn(secret, receipt.render_json())
        self.assertIn("[SECRET_REDACTED]", receipt.safe_error_message)

    def test_network_error_is_not_evaluable_and_not_retried(self):
        transport = CountingTransport(exc=OSError("network down"))
        receipt, _ = run_blind_eval(
            make_request(),
            authorize_live_call=True,
            credential_lookup=lambda _: "key",
            transport=transport,
        )
        self.assertEqual("NOT_EVALUABLE", receipt.terminal_status)
        self.assertEqual(1, transport.calls)
        self.assertEqual("PROVIDER_OR_TRANSPORT_ERROR", receipt.error_code)

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
