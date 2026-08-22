"""P2 adapter contract tests; all provider and search transports are offline."""

from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from search_cup.contracts import CandidateCard, CompetitionSpec, SearchResult
from search_cup.demo import DEFAULT_CANDIDATE, DEFAULT_COMPETITION
from search_cup.p2_smoke import (
    PROVIDER_DEFINITIONS,
    P2_SMOKE_ENVELOPE_FINGERPRINT,
    P2_SMOKE_INSTRUCTION_FINGERPRINT,
    run_p2_smoke,
)
from search_cup.provider_adapters import (
    P2_SMOKE_QUERY,
    ProviderHTTPResponse,
    SEARCH_WEB_DESCRIPTION,
    SEARCH_WEB_PARAMETERS,
)
from search_cup.tools import FakeSearchBackend


def _submission(definition) -> dict[str, object]:
    candidate = CandidateCard.load(DEFAULT_CANDIDATE)
    competition = CompetitionSpec.load(DEFAULT_COMPETITION)
    result_url = "https://docs.python.org/3/library/dataclasses.html"
    return {
        "entrant": {
            "entrant_id": definition.entrant_id,
            "provider": definition.provider,
            "exact_model_id": definition.default_model,
            "endpoint_mode": definition.endpoint_mode,
            "sampling": dict(definition.sampling),
        },
        "candidate_fingerprint": candidate.fingerprint,
        "competition_fingerprint": competition.fingerprint,
        "leads": [
            {
                "company": "Python Software Foundation",
                "role": "Documentation verification smoke (not a job)",
                "source_url": result_url,
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
                "evidence_urls": [result_url],
                "claimed_novel": False,
            }
        ],
        "apply_now_urls": [],
        "search_strategy_summary": "One non-official contract-smoke query.",
        "rejected_or_downgraded": [],
        "uncertainties": ["This smoke is not a job-search evaluation."],
        "search_calls": 1,
    }


class ScriptedTransport:
    def __init__(self, definition, captured: list[dict[str, object]]) -> None:
        self.definition = definition
        self.captured = captured
        self.calls = 0

    def __call__(self, endpoint, headers, payload, timeout):
        self.calls += 1
        self.captured.append(
            {
                "provider": self.definition.provider,
                "call": self.calls,
                "endpoint": endpoint,
                "headers": dict(headers),
                "payload": dict(payload),
                "timeout": timeout,
            }
        )
        if self.definition.protocol == "gemini-generate-content":
            if self.calls == 1:
                document = {
                    "responseId": "gemini-tool",
                    "modelVersion": self.definition.default_model + "-resolved",
                    "candidates": [
                        {
                            "content": {
                                "role": "model",
                                "parts": [
                                    {
                                        "functionCall": {
                                            "name": "search_web",
                                            "args": {"query": P2_SMOKE_QUERY},
                                        }
                                    }
                                ],
                            }
                        }
                    ],
                }
            else:
                document = {
                    "responseId": "gemini-final",
                    "modelVersion": self.definition.default_model + "-resolved",
                    "candidates": [
                        {
                            "content": {
                                "role": "model",
                                "parts": [
                                    {"text": json.dumps(_submission(self.definition))}
                                ],
                            }
                        }
                    ],
                }
        elif self.calls == 1:
            document = {
                "id": self.definition.provider.lower() + "-tool",
                "model": self.definition.default_model + "-resolved",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call-search-web",
                                    "type": "function",
                                    "function": {
                                        "name": "search_web",
                                        "arguments": json.dumps(
                                            {"query": P2_SMOKE_QUERY}
                                        ),
                                    },
                                }
                            ],
                        }
                    }
                ],
            }
        else:
            document = {
                "id": self.definition.provider.lower() + "-final",
                "model": self.definition.default_model + "-resolved",
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": json.dumps(_submission(self.definition)),
                        }
                    }
                ],
            }
        return ProviderHTTPResponse(200, json.dumps(document).encode("utf-8"))


class P2ProviderAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.keys = {
            "OPENAI_API_KEY": "openai-test-secret",
            "GEMINI_API_KEY": "gemini-test-secret",
            "DEEPSEEK_API_KEY": "deepseek-test-secret",
            "GLM_API_KEY": "glm-test-secret",
        }

    @staticmethod
    def search_backend(_definition):
        return FakeSearchBackend(
            {
                P2_SMOKE_QUERY: (
                    SearchResult(
                        title="dataclasses — Data Classes",
                        url="https://docs.python.org/3/library/dataclasses.html",
                        snippet="Official Python documentation.",
                    ),
                )
            }
        )

    def test_four_adapters_share_contract_and_pass_sequential_smoke(self) -> None:
        captured: list[dict[str, object]] = []

        def transports(definition):
            return ScriptedTransport(definition, captured)

        with patch.dict(os.environ, self.keys, clear=False):
            artifact, green = run_p2_smoke(
                transport_factory=transports,
                search_backend_factory=self.search_backend,
            )

        self.assertTrue(green)
        self.assertEqual("GREEN", artifact["gate"])
        self.assertEqual(4, len(artifact["outcomes"]))
        self.assertEqual(
            {"OpenAI", "Gemini", "DeepSeek", "GLM"},
            {outcome["provider"] for outcome in artifact["outcomes"]},
        )
        for outcome in artifact["outcomes"]:
            self.assertEqual("PASS", outcome["status"])
            self.assertIsNone(outcome["quality_score"])
            self.assertEqual(2, outcome["api_attempts"])
            self.assertEqual(0, outcome["automatic_retries"])
            self.assertEqual(1, outcome["search_calls"])
            self.assertEqual(1, len(outcome["search_traces"]))
            self.assertTrue(outcome["submission_sha256"])
            self.assertTrue(outcome["resolved_model_id"].endswith("-resolved"))
        self.assertFalse(artifact["official_prompt_consumed"])
        self.assertFalse(artifact["hidden_registry_loaded"])
        self.assertFalse(artifact["judge_invoked"])
        self.assertEqual(P2_SMOKE_ENVELOPE_FINGERPRINT, artifact["smoke_envelope_fingerprint"])
        self.assertEqual(P2_SMOKE_INSTRUCTION_FINGERPRINT, artifact["smoke_instruction_fingerprint"])

        first_requests = [item for item in captured if item["call"] == 1]
        self.assertEqual(4, len(first_requests))
        for item in first_requests:
            payload = item["payload"]
            if item["provider"] == "Gemini":
                declaration = payload["tools"][0]["functionDeclarations"][0]
                self.assertEqual("search_web", declaration["name"])
                self.assertEqual(SEARCH_WEB_DESCRIPTION, declaration["description"])
                self.assertEqual(dict(SEARCH_WEB_PARAMETERS), declaration["parameters"])
            else:
                function = payload["tools"][0]["function"]
                self.assertEqual("search_web", function["name"])
                self.assertEqual(SEARCH_WEB_DESCRIPTION, function["description"])
                self.assertEqual(dict(SEARCH_WEB_PARAMETERS), function["parameters"])

        final_requests = [item for item in captured if item["call"] == 2]
        self.assertEqual(4, len(final_requests))
        provider_neutral_contracts: list[str] = []
        for item in final_requests:
            payload = item["payload"]
            if item["provider"] == "Gemini":
                instruction_text = payload["contents"][-1]["parts"][-1]["text"]
            else:
                instruction_text = payload["messages"][-1]["content"]
            instruction = json.loads(instruction_text)
            required_output = instruction["required_output"]
            self.assertEqual(
                sorted(required_output),
                sorted(instruction["required_top_level_keys"]),
            )
            self.assertEqual(
                "https://docs.python.org/3/library/dataclasses.html",
                required_output["leads"][0]["source_url"],
            )
            self.assertEqual(
                ["https://docs.python.org/3/library/dataclasses.html"],
                required_output["leads"][0]["evidence_urls"],
            )
            self.assertEqual(1, required_output["search_calls"])
            neutralized = json.loads(json.dumps(instruction))
            neutralized["required_output"]["entrant"] = "ENTRANT_METADATA"
            provider_neutral_contracts.append(
                json.dumps(neutralized, ensure_ascii=False, sort_keys=True)
            )
        self.assertEqual(1, len(set(provider_neutral_contracts)))

        serialized = json.dumps(artifact, ensure_ascii=False, sort_keys=True)
        for secret in self.keys.values():
            self.assertNotIn(secret, serialized)

    def test_missing_keys_are_typed_not_evaluable_without_calls(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            artifact, green = run_p2_smoke(
                search_backend_factory=self.search_backend,
            )
        self.assertFalse(green)
        self.assertEqual("NOT_EVALUABLE", artifact["gate"])
        for outcome in artifact["outcomes"]:
            self.assertEqual("NOT_EVALUABLE", outcome["status"])
            self.assertEqual("MISSING_API_KEY", outcome["failure"]["error_code"])
            self.assertIsNone(outcome["quality_score"])
            self.assertEqual(0, outcome["api_attempts"])
            self.assertEqual(0, outcome["search_calls"])

    def test_http_failure_is_not_retried_or_scored(self) -> None:
        def transport_factory(_definition):
            def fail(_endpoint, _headers, _payload, _timeout):
                body = json.dumps(
                    {"error": {"code": "rate_limit", "message": "try later"}}
                ).encode("utf-8")
                return ProviderHTTPResponse(429, body)

            return fail

        with patch.dict(os.environ, self.keys, clear=False):
            artifact, green = run_p2_smoke(
                transport_factory=transport_factory,
                search_backend_factory=self.search_backend,
            )
        self.assertFalse(green)
        for outcome in artifact["outcomes"]:
            self.assertEqual("NOT_EVALUABLE", outcome["status"])
            self.assertEqual("rate_limit", outcome["failure"]["error_code"])
            self.assertEqual(1, outcome["api_attempts"])
            self.assertEqual(0, outcome["automatic_retries"])
            self.assertEqual(0, outcome["search_calls"])
            self.assertIsNone(outcome["quality_score"])


if __name__ == "__main__":
    unittest.main()
