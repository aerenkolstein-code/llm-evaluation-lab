from __future__ import annotations

import os
import re
import subprocess
import unittest
from pathlib import Path


WORKFLOW_PATH = Path(".github/workflows/b2_blind_handoff_v5_live.yml")
DOC_PATH = Path("docs/b2/r1b-live-orchestration.md")


def top_level_block(document: str, key: str) -> str:
    lines = document.splitlines(keepends=True)
    marker = f"{key}:\n"
    try:
        start = lines.index(marker)
    except ValueError as exc:
        raise AssertionError(f"missing top-level {key!r} block") from exc
    end = len(lines)
    for index in range(start + 1, len(lines)):
        line = lines[index]
        if line.strip() and not line.startswith((" ", "\t")):
            end = index
            break
    return "".join(lines[start:end])


def first_level_keys(block: str) -> list[str]:
    return re.findall(r"(?m)^  ([A-Za-z_][A-Za-z0-9_-]*):(?:\s.*)?$", block)


def run_scripts(document: str) -> list[str]:
    lines = document.splitlines(keepends=True)
    scripts: list[str] = []
    index = 0
    while index < len(lines):
        if lines[index] != "        run: |\n":
            index += 1
            continue
        index += 1
        body: list[str] = []
        while index < len(lines):
            line = lines[index]
            if line.strip() and not line.startswith("          "):
                break
            body.append(line[10:] if line.startswith("          ") else line)
            index += 1
        scripts.append("".join(body))
    return scripts


class R1bLiveOrchestrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW_PATH.read_text(encoding="utf-8")
        cls.docs = DOC_PATH.read_text(encoding="utf-8")

    def test_trigger_is_exactly_manual_dispatch(self):
        trigger = top_level_block(self.workflow, "on")
        self.assertEqual(["workflow_dispatch"], first_level_keys(trigger))
        dispatch_inputs = re.findall(r"(?m)^      ([a-z][a-z0-9_]*):$", trigger)
        self.assertEqual(
            [
                "run_ready_receipt_sha256",
                "authorization_id",
                "confirm_one_shot",
            ],
            dispatch_inputs,
        )
        for forbidden in (
            "push:",
            "pull_request:",
            "schedule:",
            "repository_dispatch:",
            "workflow_run:",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, trigger)

    def test_trigger_parser_detects_each_forbidden_adversarial_trigger(self):
        trigger = top_level_block(self.workflow, "on")
        for forbidden in (
            "push",
            "pull_request",
            "schedule",
            "repository_dispatch",
            "workflow_run",
        ):
            candidate = trigger + f"  {forbidden}:\n"
            with self.subTest(forbidden=forbidden):
                self.assertIn(forbidden, first_level_keys(candidate))
                self.assertNotEqual(["workflow_dispatch"], first_level_keys(candidate))

    def test_lane_is_protected_read_only_and_private_runner_only(self):
        permissions = top_level_block(self.workflow, "permissions")
        self.assertEqual(["contents"], first_level_keys(permissions))
        self.assertIn("contents: read", permissions)
        self.assertIn("environment: b2-r1b-live", self.workflow)
        for label in ("self-hosted", "linux", "x64", "b2-r1b-private"):
            self.assertRegex(self.workflow, rf"(?m)^      - {re.escape(label)}$")
        self.assertIn("persist-credentials: false", self.workflow)
        self.assertIn("stat.S_ISGID", self.workflow)
        self.assertIn("exchange_root.chmod(0o2750)", self.workflow)
        self.assertIn('(exchange_root / "private").chmod(0o2770)', self.workflow)
        self.assertIn("os.fchmod(handle.fileno(), 0o640)", self.workflow)
        self.assertNotIn("python -m pip install", self.workflow)

    def test_every_shell_step_is_syntactically_valid(self):
        scripts = run_scripts(self.workflow)
        self.assertGreaterEqual(len(scripts), 10)
        for index, script in enumerate(scripts):
            with self.subTest(step=index):
                result = subprocess.run(
                    ["bash", "-n"],
                    input=script,
                    text=True,
                    capture_output=True,
                    check=False,
                )
                self.assertEqual(0, result.returncode, result.stderr)

    def test_fresh_preflight_and_rerun_gates_precede_exchange(self):
        preflight = self.workflow.index(
            "Validate fresh run-ready and one-shot authorization gates"
        )
        exchange = self.workflow.index("Create isolated run-scoped exchange roots")
        key = self.workflow.index("Generate the run-unique input key and request")
        self.assertLess(preflight, exchange)
        self.assertLess(exchange, key)
        for required in (
            'GITHUB_EVENT_NAME") != "workflow_dispatch"',
            'GITHUB_REF") != "refs/heads/main"',
            'GITHUB_RUN_ATTEMPT") != "1"',
            'GITHUB_SHA") != os.environ["EXECUTION_HEAD_SHA"]',
            'GITHUB_RUN_ID") != os.environ["EXPECTED_WORKFLOW_RUN_ID"]',
            "DISPATCH_RUN_READY_RECEIPT_SHA256",
            "DISPATCH_AUTHORIZATION_ID",
            "DISPATCH_CONFIRM_ONE_SHOT",
            "B2_R1B_RUN_READY_RECEIPT_SHA256",
            "B2_R1B_AUTHORIZATION_ID",
            "B2_R1B_EXECUTION_HEAD_SHA",
            "B2_R1B_WORKFLOW_RUN_ID",
        ):
            with self.subTest(required=required):
                self.assertIn(required, self.workflow)

    def test_preflight_accepts_only_the_exact_fresh_manual_run(self):
        script = run_scripts(self.workflow)[0]
        environment = os.environ.copy()
        environment.update({
            "EXECUTION_HEAD_SHA": "a" * 40,
            "BRIDGE_MAIN_SHA": "b" * 40,
            "EXPECTED_WORKFLOW_RUN_ID": "123456789",
            "RUN_READY_RECEIPT_SHA256": "c" * 64,
            "AUTHORIZATION_ID": "R1B-AUTH-001",
            "EVALUATION_RUN_ID": "B2-R1B-001",
            "EXPECTED_CONTEXT_SHA256": "d" * 64,
            "EXPECTED_CONTEXT_BYTES": "108230",
            "EXPECTED_PROMPT_SHA256": "e" * 64,
            "EXPECTED_PROMPT_BYTES": "2308",
            "PROVIDER_LABEL": "provider-a",
            "PROVIDER_PROTOCOL": "openai-compatible-chat-completions/v1",
            "REQUESTED_MODEL_ID": "provider/model-v1",
            "PROVIDER_ENDPOINT": "https://provider.example/v1/chat/completions",
            "PROVIDER_TIMEOUT_SECONDS": "180",
            "PROVIDER_TEMPERATURE": "0",
            "PROVIDER_MAX_TOKENS": "8192",
            "HANDOFF_TTL_SECONDS": "3600",
            "DISPATCH_RUN_READY_RECEIPT_SHA256": "c" * 64,
            "DISPATCH_AUTHORIZATION_ID": "R1B-AUTH-001",
            "DISPATCH_CONFIRM_ONE_SHOT": "true",
            "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_RUN_ID": "123456789",
            "GITHUB_SHA": "a" * 40,
        })

        result = subprocess.run(
            ["bash"], input=script, text=True, capture_output=True,
            env=environment, check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)

        adversarial = {
            "automatic event": ("GITHUB_EVENT_NAME", "push"),
            "non-main ref": ("GITHUB_REF", "refs/heads/review"),
            "rerun": ("GITHUB_RUN_ATTEMPT", "2"),
            "second run": ("GITHUB_RUN_ID", "123456790"),
            "wrong head": ("GITHUB_SHA", "f" * 40),
            "stale receipt": ("DISPATCH_RUN_READY_RECEIPT_SHA256", "f" * 64),
            "wrong authorization": ("DISPATCH_AUTHORIZATION_ID", "R1B-AUTH-002"),
            "missing confirmation": ("DISPATCH_CONFIRM_ONE_SHOT", "false"),
            "unsupported protocol": ("PROVIDER_PROTOCOL", "unsupported/v1"),
            "unsafe endpoint": ("PROVIDER_ENDPOINT", "http://provider.example/v1"),
            "nonzero temperature": ("PROVIDER_TEMPERATURE", "0.1"),
            "oversize ttl": ("HANDOFF_TTL_SECONDS", "21601"),
        }
        for label, (name, value) in adversarial.items():
            candidate = dict(environment)
            candidate[name] = value
            with self.subTest(label=label):
                rejected = subprocess.run(
                    ["bash"], input=script, text=True, capture_output=True,
                    env=candidate, check=False,
                )
                self.assertNotEqual(0, rejected.returncode)

    def test_bridge_source_is_bound_before_handoff(self):
        binding_step = self.workflow.index(
            "Bind execution head to the accepted v5.2 bridge"
        )
        handoff_step = self.workflow.index(
            "Generate the run-unique input key and request"
        )
        self.assertLess(binding_step, handoff_step)
        self.assertIn(
            'git merge-base --is-ancestor "$BRIDGE_MAIN_SHA" "$EXECUTION_HEAD_SHA"',
            self.workflow,
        )
        self.assertIn('$BRIDGE_MAIN_SHA:b2/blind_eval.py', self.workflow)
        self.assertIn('$BRIDGE_MAIN_SHA:b2/blind_handoff.py', self.workflow)

    def test_v52_possession_proof_precedes_secret_and_provider(self):
        commands = (
            "generate-input-key",
            "accept-input",
            "encrypt-challenge",
            "verify-ack",
            "python -m b2.blind_eval",
            "make-live-result",
        )
        positions = [self.workflow.index(command) for command in commands]
        self.assertEqual(sorted(positions), positions)
        ack = self.workflow.index("python -m b2.blind_handoff verify-ack")
        secret = self.workflow.index("${{ secrets.B2_R1B_PROVIDER_API_KEY }}")
        provider = self.workflow.index("python -m b2.blind_eval")
        authorization = self.workflow.index("--authorize-live-call")
        self.assertLess(ack, secret)
        self.assertLess(secret, provider)
        self.assertLess(provider, authorization)
        self.assertEqual(1, self.workflow.count("${{ secrets."))
        self.assertEqual(1, self.workflow.count("python -m b2.blind_eval"))
        self.assertEqual(1, self.workflow.count("--authorize-live-call"))

    def test_provider_is_runtime_frozen_and_has_no_retry_wrapper(self):
        provider_step = self.workflow[
            self.workflow.index("Execute exactly one authorized provider attempt") :
            self.workflow.index("Encrypt and publish the complete private result evidence")
        ]
        for runtime_value in (
            '"$PROVIDER_LABEL"',
            '"$PROVIDER_PROTOCOL"',
            '"$REQUESTED_MODEL_ID"',
            '"$PROVIDER_ENDPOINT"',
            '"$PROVIDER_TIMEOUT_SECONDS"',
            '"$PROVIDER_TEMPERATURE"',
            '"$PROVIDER_MAX_TOKENS"',
        ):
            with self.subTest(runtime_value=runtime_value):
                self.assertIn(runtime_value, provider_step)
        self.assertNotRegex(provider_step, r"(?m)^\s*(for|while)\b")
        self.assertNotIn("continue-on-error", provider_step)
        self.assertNotIn("retry", provider_step.lower())
        self.assertIn("GITHUB_RUN_ATTEMPT", self.workflow)
        self.assertIn("automatic retries: `0`", self.workflow)
        self.assertNotIn("api.deepseek.com", self.workflow)
        self.assertNotIn("deepseek-v4-pro", self.workflow)

    def test_exchange_is_run_scoped_create_once_and_not_an_artifact(self):
        self.assertIn(
            'os.environ["GITHUB_RUN_ID"],\n              os.environ["GITHUB_RUN_ATTEMPT"],\n              os.environ["GITHUB_SHA"]',
            self.workflow,
        )
        self.assertIn("os.O_EXCL", self.workflow)
        for name in (
            "input-public.pem",
            "request.json",
            "payload.json",
            "challenge.enc.json",
            "challenge-ack.json",
            "result.enc.json",
            "result-accepted.json",
            "result-verification-receipt.json",
            "private-cleanup-receipt.json",
        ):
            with self.subTest(name=name):
                self.assertIn(name, self.workflow)
        for forbidden in (
            "actions/upload-artifact",
            "actions/download-artifact",
            "blind-handoff/v5/${GITHUB_RUN_ID}",
            "api.github.com/repos",
            "curl ",
            "gh api",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.workflow)

    def test_private_finalization_is_exact_body_free_and_bound(self):
        for exact_key_set in (
            '{"protocol", "claim", "binding_sha256", "artifact_sha256"}',
            '"status", "mode", "terminal_status", "provider_attempts",',
            '{"status": "EPHEMERAL_CLEANUP_COMPLETE"}',
        ):
            with self.subTest(exact_key_set=exact_key_set):
                self.assertIn(exact_key_set, self.workflow)
        self.assertIn('"claim": "result-accepted"', self.workflow)
        self.assertIn('verified["provider_attempts"] != 1', self.workflow)
        self.assertIn('verified["result_envelope_sha256"] != result_hash', self.workflow)
        self.assertIn("private result receipt contains unexpected fields", self.workflow)
        self.assertIn("Validate the body-free bridge receipt", self.workflow)

    def test_cleanup_is_unconditional_and_verifies_both_roots_absent(self):
        cleanup = self.workflow.index("Verify-clean all runner and exchange objects")
        self.assertIn("if: ${{ always() }}", self.workflow[cleanup:])
        tail = self.workflow[cleanup:]
        self.assertEqual(2, tail.count("python -m b2.blind_handoff cleanup"))
        self.assertIn('test ! -e "$runner_root"', tail)
        self.assertIn('test ! -e "$exchange_root"', tail)
        self.assertNotIn("|| true", tail)
        self.assertEqual(4, tail.count("|| cleanup_failed=1"))
        self.assertIn('exit "$cleanup_failed"', tail)

    def test_public_summary_is_body_free(self):
        summary = self.workflow[
            self.workflow.index("Emit a body-free run receipt") :
            self.workflow.index("Verify-clean all runner and exchange objects")
        ]
        self.assertIn("$GITHUB_STEP_SUMMARY", summary)
        for forbidden in (
            "EXPECTED_CONTEXT_SHA256",
            "EXPECTED_PROMPT_SHA256",
            "PROVIDER_ENDPOINT",
            "REQUESTED_MODEL_ID",
            "B2_R1B_PROVIDER_API_KEY",
            "B2_R1B_EXCHANGE_BASE",
            "raw-output",
            "reasoning",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, summary)

    def test_contract_records_authority_and_hard_stops(self):
        for required in (
            "WO-B2-BLIND-R1B-01 v0.1",
            "0ba7c2572762afe38ccf6a71b012d9d8a6dae3a5",
            "f88f3f77429a52639c0fa5b5444a9d10b01235d9",
            "workflow_dispatch",
            "B2_R1B_RUN_READY_RECEIPT_SHA256",
            "B2_R1B_PROVIDER_API_KEY",
            "provider_attempts = 1",
            "automatic_retries = 0",
            "EMPTY_FINAL_CONTENT",
            "READY FOR B2-BLIND-R1B INDEPENDENT QA",
            "no live execution authority",
            "Historical Q1-R1 remains exactly",
        ):
            with self.subTest(required=required):
                self.assertIn(required, self.docs)


if __name__ == "__main__":
    unittest.main()
