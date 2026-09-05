from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import subprocess
import tempfile
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


def python_heredocs(script: str) -> list[str]:
    lines = script.splitlines(keepends=True)
    blocks: list[str] = []
    index = 0
    while index < len(lines):
        if not lines[index].rstrip().endswith("<<'PY'"):
            index += 1
            continue
        index += 1
        body: list[str] = []
        while index < len(lines) and lines[index].strip() != "PY":
            body.append(lines[index])
            index += 1
        if index == len(lines):
            raise AssertionError("unterminated Python heredoc")
        blocks.append("".join(body))
        index += 1
    return blocks


def canonical_run_ready(environment: dict[str, str]) -> dict[str, object]:
    return {
        "authorization_id": environment["AUTHORIZATION_ID"],
        "automatic_retries": 0,
        "bridge_main_sha": environment["BRIDGE_MAIN_SHA"],
        "context_bytes": int(environment["EXPECTED_CONTEXT_BYTES"]),
        "context_sha256": environment["EXPECTED_CONTEXT_SHA256"],
        "evaluation_run_id": environment["EVALUATION_RUN_ID"],
        "execution_head_sha": environment["EXECUTION_HEAD_SHA"],
        "git_ref": "refs/heads/main",
        "handoff_id": environment["APPROVED_HANDOFF_ID"],
        "handoff_ttl_seconds": int(environment["HANDOFF_TTL_SECONDS"]),
        "max_provider_attempts": 1,
        "mode": "live",
        "prompt_bytes": int(environment["EXPECTED_PROMPT_BYTES"]),
        "prompt_sha256": environment["EXPECTED_PROMPT_SHA256"],
        "provider_endpoint": environment["PROVIDER_ENDPOINT"],
        "provider_label": environment["PROVIDER_LABEL"],
        "provider_max_tokens": int(environment["PROVIDER_MAX_TOKENS"]),
        "provider_protocol": environment["PROVIDER_PROTOCOL"],
        "provider_temperature": 0,
        "provider_timeout_seconds": int(environment["PROVIDER_TIMEOUT_SECONDS"]),
        "receipt_type": "R1B-RUN-READY",
        "repository": environment["GITHUB_REPOSITORY"],
        "requested_model_id": environment["REQUESTED_MODEL_ID"],
        "run_id": environment["RUN_ID"],
        "schema_version": "b2-r1b-run-ready/v2",
        "trigger_event": "workflow_dispatch",
        "workflow_path": ".github/workflows/b2_blind_handoff_v5_live.yml",
        "workflow_run_attempt": 1,
        "work_order": "WO-B2-BLIND-R1B-01 v0.1",
    }


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def bind_run_ready(
    environment: dict[str, str], receipt: dict[str, object] | None = None
) -> bytes:
    receipt_bytes = canonical_json_bytes(receipt or canonical_run_ready(environment))
    digest = hashlib.sha256(receipt_bytes).hexdigest()
    environment["RUN_READY_RECEIPT_B64"] = base64.b64encode(receipt_bytes).decode("ascii")
    environment["RUN_READY_RECEIPT_SHA256"] = digest
    environment["DISPATCH_RUN_READY_RECEIPT_SHA256"] = digest
    return receipt_bytes


def valid_preflight_environment() -> tuple[dict[str, str], bytes]:
    environment = os.environ.copy()
    environment.update({
        "EXECUTION_HEAD_SHA": "a" * 40,
        "BRIDGE_MAIN_SHA": "b" * 40,
        "AUTHORIZATION_ID": "R1B-AUTH-001",
        "RUN_ID": "B2-R1B-RUN-001",
        "APPROVED_HANDOFF_ID": "B2-R1B-HANDOFF-001",
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
        "DISPATCH_RUN_ID": "B2-R1B-RUN-001",
        "DISPATCH_EVALUATION_RUN_ID": "B2-R1B-001",
        "DISPATCH_HANDOFF_ID": "B2-R1B-HANDOFF-001",
        "DISPATCH_AUTHORIZATION_ID": "R1B-AUTH-001",
        "DISPATCH_CONFIRM_ONE_SHOT": "true",
        "GITHUB_EVENT_NAME": "workflow_dispatch",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_RUN_ID": "123456789",
        "GITHUB_SHA": "a" * 40,
        "GITHUB_REPOSITORY": "aerenkolstein-code/llm-evaluation-lab",
        "GITHUB_WORKFLOW_REF": (
            "aerenkolstein-code/llm-evaluation-lab/"
            ".github/workflows/b2_blind_handoff_v5_live.yml@refs/heads/main"
        ),
    })
    return environment, bind_run_ready(environment)


def write_claim_fault_shim(directory: Path) -> None:
    directory.mkdir(mode=0o700)
    (directory / "sitecustomize.py").write_text(
        """import os

_fault = os.environ.get("B2_R1B_TEST_LEDGER_FAULT", "")
_original_fsync = os.fsync
_original_link = os.link
_link_count = 0
_exit_after_directory_fsync = False


def _faulting_link(source, destination, *args, **kwargs):
    global _exit_after_directory_fsync, _link_count
    _link_count += 1
    if _fault == "second-index-collision" and _link_count == 2:
        destination_directory = kwargs.get("dst_dir_fd")
        collision_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        collision_flags |= getattr(os, "O_NOFOLLOW", 0)
        collision_fd = os.open(
            destination, collision_flags, 0o600, dir_fd=destination_directory
        )
        with os.fdopen(collision_fd, "wb") as collision:
            collision.write(b'{"collision":true}')
            collision.flush()
            _original_fsync(collision.fileno())
        _original_fsync(destination_directory)
        return _original_link(source, destination, *args, **kwargs)
    result = _original_link(source, destination, *args, **kwargs)
    if _fault == "crash-after-first-index" and _link_count == 1:
        _exit_after_directory_fsync = True
    return result


def _faulting_fsync(file_descriptor):
    global _exit_after_directory_fsync
    result = _original_fsync(file_descriptor)
    if _exit_after_directory_fsync:
        _exit_after_directory_fsync = False
        os._exit(91)
    return result


os.link = _faulting_link
os.fsync = _faulting_fsync
""",
        encoding="ascii",
    )


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
                "run_id",
                "evaluation_run_id",
                "handoff_id",
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

    def test_every_embedded_python_program_is_syntactically_valid(self):
        blocks = [
            block
            for script in run_scripts(self.workflow)
            for block in python_heredocs(script)
        ]
        self.assertGreaterEqual(len(blocks), 8)
        for index, block in enumerate(blocks):
            with self.subTest(program=index):
                compile(block, f"workflow-heredoc-{index}.py", "exec")

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
            "DISPATCH_RUN_READY_RECEIPT_SHA256",
            "DISPATCH_RUN_ID",
            "DISPATCH_EVALUATION_RUN_ID",
            "DISPATCH_HANDOFF_ID",
            "DISPATCH_AUTHORIZATION_ID",
            "DISPATCH_CONFIRM_ONE_SHOT",
            "B2_R1B_RUN_READY_RECEIPT_SHA256",
            "B2_R1B_AUTHORIZATION_ID",
            "B2_R1B_RUN_ID",
            "B2_R1B_HANDOFF_ID",
            "B2_R1B_EXECUTION_HEAD_SHA",
        ):
            with self.subTest(required=required):
                self.assertIn(required, self.workflow)

    def test_preflight_accepts_only_the_exact_fresh_manual_run(self):
        script = run_scripts(self.workflow)[0]
        environment, _ = valid_preflight_environment()

        result = subprocess.run(
            ["bash"], input=script, text=True, capture_output=True,
            env=environment, check=False,
        )
        self.assertEqual(0, result.returncode, result.stderr)

        adversarial = {
            "automatic event": ("GITHUB_EVENT_NAME", "push"),
            "non-main ref": ("GITHUB_REF", "refs/heads/review"),
            "rerun": ("GITHUB_RUN_ATTEMPT", "2"),
            "invalid workflow run": ("GITHUB_RUN_ID", "not-a-run"),
            "wrong head": ("GITHUB_SHA", "f" * 40),
            "stale receipt": ("DISPATCH_RUN_READY_RECEIPT_SHA256", "f" * 64),
            "wrong run ID": ("DISPATCH_RUN_ID", "B2-R1B-RUN-002"),
            "wrong evaluation ID": ("DISPATCH_EVALUATION_RUN_ID", "B2-R1B-002"),
            "wrong handoff ID": ("DISPATCH_HANDOFF_ID", "B2-R1B-HANDOFF-002"),
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

    def test_second_dispatch_cannot_rebind_a_consumed_receipt_and_authorization(self):
        scripts = run_scripts(self.workflow)
        preflight_script = scripts[0]
        claim_script = scripts[1]
        environment, receipt_bytes = valid_preflight_environment()

        with tempfile.TemporaryDirectory() as temp_root:
            root = Path(temp_root)
            claim_base = root / "claims"
            runner_temp = root / "runner-temp"
            exchange_base = root / "exchange"
            for directory in (claim_base, runner_temp, exchange_base):
                directory.mkdir(mode=0o700)
                directory.chmod(0o700)
            github_env = root / "github-env"
            github_env.write_text("", encoding="ascii")
            environment["B2_R1B_ONE_SHOT_CLAIM_BASE"] = str(claim_base)
            environment["B2_R1B_EXCHANGE_BASE"] = str(exchange_base)
            environment["RUNNER_TEMP"] = str(runner_temp)
            environment["GITHUB_ENV"] = str(github_env)

            accepted = subprocess.run(
                ["bash"], input=preflight_script, text=True, capture_output=True,
                env=environment, check=False,
            )
            self.assertEqual(0, accepted.returncode, accepted.stderr)
            consumed = subprocess.run(
                ["bash"], input=claim_script, text=True, capture_output=True,
                env=environment, check=False,
            )
            self.assertEqual(0, consumed.returncode, consumed.stderr)

            claim_files = list(claim_base.glob("*.json"))
            self.assertEqual(3, len(claim_files))
            self.assertEqual(
                1,
                len({(path.stat().st_dev, path.stat().st_ino) for path in claim_files}),
            )
            first_claim = json.loads(claim_files[0].read_bytes())
            self.assertEqual("123456789", first_claim["workflow_run_id"])
            self.assertEqual(
                hashlib.sha256(receipt_bytes).hexdigest(),
                first_claim["run_ready_receipt_sha256"],
            )

            second_dispatch = dict(environment)
            second_dispatch["GITHUB_RUN_ID"] = "123456790"
            second_dispatch["EXPECTED_WORKFLOW_RUN_ID"] = "123456790"
            second_github_env = root / "second-github-env"
            second_github_env.write_text("", encoding="ascii")
            second_dispatch["GITHUB_ENV"] = str(second_github_env)

            legacy_pair_gate = subprocess.run(
                ["bash"], input=preflight_script, text=True, capture_output=True,
                env=second_dispatch, check=False,
            )
            self.assertEqual(0, legacy_pair_gate.returncode, legacy_pair_gate.stderr)
            replay = subprocess.run(
                ["bash"], input=claim_script, text=True, capture_output=True,
                env=second_dispatch, check=False,
            )
            self.assertNotEqual(0, replay.returncode)
            self.assertIn("one-shot authorization was already consumed", replay.stderr)
            self.assertEqual(3, len(list(claim_base.glob("*.json"))))

            reused_identity = dict(environment)
            reused_identity["AUTHORIZATION_ID"] = "R1B-AUTH-002"
            reused_identity["DISPATCH_AUTHORIZATION_ID"] = "R1B-AUTH-002"
            reused_identity["GITHUB_RUN_ID"] = "123456791"
            bind_run_ready(reused_identity)
            third_github_env = root / "third-github-env"
            third_github_env.write_text("", encoding="ascii")
            reused_identity["GITHUB_ENV"] = str(third_github_env)
            fresh_authorization_preflight = subprocess.run(
                ["bash"], input=preflight_script, text=True, capture_output=True,
                env=reused_identity, check=False,
            )
            self.assertEqual(
                0, fresh_authorization_preflight.returncode,
                fresh_authorization_preflight.stderr,
            )
            run_replay = subprocess.run(
                ["bash"], input=claim_script, text=True, capture_output=True,
                env=reused_identity, check=False,
            )
            self.assertNotEqual(0, run_replay.returncode)
            self.assertIn("R1b run identity was already consumed", run_replay.stderr)
            self.assertEqual(3, len(list(claim_base.glob("*.json"))))

    def test_partial_claim_crash_and_second_index_collision_fail_closed(self):
        scripts = run_scripts(self.workflow)
        preflight_script = scripts[0]
        claim_script = scripts[1]

        for fault_mode in ("crash-after-first-index", "second-index-collision"):
            with self.subTest(fault_mode=fault_mode), tempfile.TemporaryDirectory() as temp_root:
                environment, _ = valid_preflight_environment()
                root = Path(temp_root)
                claim_base = root / "claims"
                runner_temp = root / "runner-temp"
                exchange_base = root / "exchange"
                for directory in (claim_base, runner_temp, exchange_base):
                    directory.mkdir(mode=0o700)
                    directory.chmod(0o700)
                github_env = root / "github-env"
                github_env.write_text("", encoding="ascii")
                environment["B2_R1B_ONE_SHOT_CLAIM_BASE"] = str(claim_base)
                environment["B2_R1B_EXCHANGE_BASE"] = str(exchange_base)
                environment["RUNNER_TEMP"] = str(runner_temp)
                environment["GITHUB_ENV"] = str(github_env)

                accepted = subprocess.run(
                    ["bash"], input=preflight_script, text=True, capture_output=True,
                    env=environment, check=False,
                )
                self.assertEqual(0, accepted.returncode, accepted.stderr)

                shim = root / "fault-shim"
                write_claim_fault_shim(shim)
                faulted_environment = dict(environment)
                faulted_environment["PYTHONPATH"] = str(shim)
                faulted_environment["B2_R1B_TEST_LEDGER_FAULT"] = fault_mode
                interrupted = subprocess.run(
                    ["bash"], input=claim_script, text=True, capture_output=True,
                    env=faulted_environment, check=False,
                )
                self.assertNotEqual(0, interrupted.returncode)
                if fault_mode == "crash-after-first-index":
                    self.assertEqual(91, interrupted.returncode)
                else:
                    self.assertIn("R1b run identity was already consumed", interrupted.stderr)

                partial_files = sorted(claim_base.glob("*.json"))
                expected_file_count = 2 if fault_mode == "crash-after-first-index" else 3
                self.assertEqual(expected_file_count, len(partial_files))
                self.assertTrue(any(path.name.startswith("claim-") for path in partial_files))
                self.assertTrue(
                    any(path.name.startswith("authorization-") for path in partial_files)
                )
                self.assertEqual(
                    fault_mode == "second-index-collision",
                    any(path.name.startswith("run-identity-") for path in partial_files),
                )
                self.assertEqual(
                    1 if fault_mode == "crash-after-first-index" else 2,
                    len({(path.stat().st_dev, path.stat().st_ino) for path in partial_files}),
                )

                recovered = dict(environment)
                recovered["AUTHORIZATION_ID"] = "R1B-AUTH-RECOVERY-002"
                recovered["DISPATCH_AUTHORIZATION_ID"] = "R1B-AUTH-RECOVERY-002"
                recovered["GITHUB_RUN_ID"] = "123456790"
                recovered_github_env = root / "recovered-github-env"
                recovered_github_env.write_text("", encoding="ascii")
                recovered["GITHUB_ENV"] = str(recovered_github_env)
                bind_run_ready(recovered)

                recovered_preflight = subprocess.run(
                    ["bash"], input=preflight_script, text=True, capture_output=True,
                    env=recovered, check=False,
                )
                self.assertEqual(
                    0, recovered_preflight.returncode, recovered_preflight.stderr
                )
                rejected_reuse = subprocess.run(
                    ["bash"], input=claim_script, text=True, capture_output=True,
                    env=recovered, check=False,
                )
                self.assertNotEqual(0, rejected_reuse.returncode)
                self.assertIn("R1b run identity was already consumed", rejected_reuse.stderr)

                if fault_mode == "second-index-collision":
                    unrelated = dict(environment)
                    unrelated.update({
                        "AUTHORIZATION_ID": "R1B-AUTH-UNRELATED-003",
                        "DISPATCH_AUTHORIZATION_ID": "R1B-AUTH-UNRELATED-003",
                        "RUN_ID": "B2-R1B-RUN-UNRELATED-003",
                        "DISPATCH_RUN_ID": "B2-R1B-RUN-UNRELATED-003",
                        "EVALUATION_RUN_ID": "B2-R1B-UNRELATED-003",
                        "DISPATCH_EVALUATION_RUN_ID": "B2-R1B-UNRELATED-003",
                        "APPROVED_HANDOFF_ID": "B2-R1B-HANDOFF-UNRELATED-003",
                        "DISPATCH_HANDOFF_ID": "B2-R1B-HANDOFF-UNRELATED-003",
                        "GITHUB_RUN_ID": "123456791",
                    })
                    unrelated_github_env = root / "unrelated-github-env"
                    unrelated_github_env.write_text("", encoding="ascii")
                    unrelated["GITHUB_ENV"] = str(unrelated_github_env)
                    bind_run_ready(unrelated)
                    unrelated_preflight = subprocess.run(
                        ["bash"], input=preflight_script, text=True,
                        capture_output=True, env=unrelated, check=False,
                    )
                    self.assertEqual(
                        0, unrelated_preflight.returncode, unrelated_preflight.stderr
                    )
                    quarantined = subprocess.run(
                        ["bash"], input=claim_script, text=True, capture_output=True,
                        env=unrelated, check=False,
                    )
                    self.assertNotEqual(0, quarantined.returncode)
                    self.assertIn(
                        "durable one-shot ledger contains an invalid claim",
                        quarantined.stderr,
                    )
                self.assertEqual(
                    [path.name for path in partial_files],
                    sorted(path.name for path in claim_base.glob("*.json")),
                )

        claim_position = self.workflow.index(
            "Atomically consume the durable one-shot authorization claim"
        )
        for later_gate in (
            "Check out the exact authorized execution head",
            "Create isolated run-scoped exchange roots",
            "${{ secrets.B2_R1B_PROVIDER_API_KEY }}",
            '"-m", "b2.blind_eval"',
        ):
            with self.subTest(later_gate=later_gate):
                self.assertLess(claim_position, self.workflow.index(later_gate))
        self.assertNotIn("EXPECTED_WORKFLOW_RUN_ID", self.workflow)
        self.assertNotIn("B2_R1B_WORKFLOW_RUN_ID", self.workflow)

    def test_stale_receipt_rejects_changed_provider_model_endpoint_and_runtime(self):
        script = run_scripts(self.workflow)[0]
        environment, _ = valid_preflight_environment()
        receipt_bound_adversarial = {
            "provider label": ("PROVIDER_LABEL", "provider-b"),
            "requested model": ("REQUESTED_MODEL_ID", "provider/model-v2"),
            "valid alternate endpoint": (
                "PROVIDER_ENDPOINT",
                "https://alternate.example/v1/chat/completions",
            ),
            "timeout": ("PROVIDER_TIMEOUT_SECONDS", "181"),
            "max tokens": ("PROVIDER_MAX_TOKENS", "8193"),
            "handoff ttl": ("HANDOFF_TTL_SECONDS", "3601"),
            "context digest": ("EXPECTED_CONTEXT_SHA256", "0" * 64),
            "context size": ("EXPECTED_CONTEXT_BYTES", "108231"),
            "prompt digest": ("EXPECTED_PROMPT_SHA256", "1" * 64),
            "prompt size": ("EXPECTED_PROMPT_BYTES", "2309"),
            "R1b run": ("RUN_ID", "B2-R1B-RUN-002"),
            "handoff": ("APPROVED_HANDOFF_ID", "B2-R1B-HANDOFF-002"),
            "evaluation run": ("EVALUATION_RUN_ID", "B2-R1B-002"),
            "bridge main": ("BRIDGE_MAIN_SHA", "2" * 40),
        }
        dispatch_pair = {
            "RUN_ID": "DISPATCH_RUN_ID",
            "APPROVED_HANDOFF_ID": "DISPATCH_HANDOFF_ID",
            "EVALUATION_RUN_ID": "DISPATCH_EVALUATION_RUN_ID",
        }
        for label, (name, value) in receipt_bound_adversarial.items():
            candidate = dict(environment)
            candidate[name] = value
            if name in dispatch_pair:
                candidate[dispatch_pair[name]] = value
            with self.subTest(stale_receipt_changed_parameter=label):
                rejected = subprocess.run(
                    ["bash"], input=script, text=True, capture_output=True,
                    env=candidate, check=False,
                )
                self.assertNotEqual(0, rejected.returncode)
                self.assertIn(
                    "canonical RUN-READY receipt does not match protected execution parameters",
                    rejected.stderr,
                )

    def test_complete_predeclared_run_and_handoff_identity_is_receipt_bound(self):
        script = run_scripts(self.workflow)[0]
        environment, receipt_bytes = valid_preflight_environment()
        receipt = json.loads(receipt_bytes)
        self.assertEqual("b2-r1b-run-ready/v2", receipt["schema_version"])
        self.assertEqual("B2-R1B-RUN-001", receipt["run_id"])
        self.assertEqual("B2-R1B-001", receipt["evaluation_run_id"])
        self.assertEqual("B2-R1B-HANDOFF-001", receipt["handoff_id"])

        for name, value in (
            ("RUN_ID", "B2-R1B-RUN-002"),
            ("EVALUATION_RUN_ID", "B2-R1B-002"),
            ("APPROVED_HANDOFF_ID", "B2-R1B-HANDOFF-002"),
        ):
            candidate = dict(environment)
            candidate[name] = value
            candidate[{
                "RUN_ID": "DISPATCH_RUN_ID",
                "EVALUATION_RUN_ID": "DISPATCH_EVALUATION_RUN_ID",
                "APPROVED_HANDOFF_ID": "DISPATCH_HANDOFF_ID",
            }[name]] = value
            with self.subTest(changed_protected_identity=name):
                rejected = subprocess.run(
                    ["bash"], input=script, text=True, capture_output=True,
                    env=candidate, check=False,
                )
                self.assertNotEqual(0, rejected.returncode)
                self.assertIn(
                    "canonical RUN-READY receipt does not match protected execution parameters",
                    rejected.stderr,
                )

    def test_one_shot_claim_is_atomic_durable_and_body_free(self):
        claim_step = self.workflow[
            self.workflow.index(
                "Atomically consume the durable one-shot authorization claim"
            ) : self.workflow.index("Check out the exact authorized execution head")
        ]
        for required in (
            "B2_R1B_ONE_SHOT_CLAIM_BASE",
            "b2-r1b-one-shot-claim/v1",
            "R1B-ONE-SHOT-AUTHORIZATION-CLAIM",
            "import fcntl",
            "fcntl.flock(lock_fd, fcntl.LOCK_EX)",
            "os.O_EXCL",
            "O_NOFOLLOW",
            "claim_record",
            "os.link(",
            "os.fchmod(handle.fileno(), 0o600)",
            "os.fsync(handle.fileno())",
            "os.fsync(directory_fd)",
            "dir_fd=directory_fd",
            "durable one-shot claim base overlaps an ephemeral root",
            "durable one-shot ledger contains an invalid claim",
            '"workflow_run_id": workflow_run_id',
            '"run_identity_sha256": run_identity_digest',
            '"run_ready_receipt_sha256": receipt_digest',
        ):
            with self.subTest(required=required):
                self.assertIn(required, claim_step)
        for forbidden in (
            "context.txt",
            "prompt.txt",
            "reasoning",
            "raw_answer",
            "B2_R1B_PROVIDER_API_KEY",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, claim_step)
        cleanup = self.workflow[
            self.workflow.index("Verify-clean all runner and exchange objects") :
        ]
        self.assertNotIn("B2_R1B_ONE_SHOT_CLAIM_BASE", cleanup)

    def test_tampered_receipt_rejects_stale_and_recomputed_digest(self):
        script = run_scripts(self.workflow)[0]
        environment, baseline_receipt_bytes = valid_preflight_environment()
        tampered_receipt = json.loads(baseline_receipt_bytes)
        tampered_receipt["provider_label"] = "provider-b"
        tampered_bytes = canonical_json_bytes(tampered_receipt)

        stale_digest = dict(environment)
        stale_digest["RUN_READY_RECEIPT_B64"] = base64.b64encode(tampered_bytes).decode("ascii")
        rejected = subprocess.run(
            ["bash"], input=script, text=True, capture_output=True,
            env=stale_digest, check=False,
        )
        self.assertNotEqual(0, rejected.returncode)
        self.assertIn("receipt digest does not match its bytes", rejected.stderr)

        recomputed_digest = dict(environment)
        bind_run_ready(recomputed_digest, tampered_receipt)
        rejected = subprocess.run(
            ["bash"], input=script, text=True, capture_output=True,
            env=recomputed_digest, check=False,
        )
        self.assertNotEqual(0, rejected.returncode)
        self.assertIn(
            "canonical RUN-READY receipt does not match protected execution parameters",
            rejected.stderr,
        )

    def test_receipt_rejects_noncanonical_and_duplicate_json(self):
        script = run_scripts(self.workflow)[0]
        environment, receipt_bytes = valid_preflight_environment()

        noncanonical = dict(environment)
        noncanonical_bytes = b" " + receipt_bytes
        noncanonical_digest = hashlib.sha256(noncanonical_bytes).hexdigest()
        noncanonical["RUN_READY_RECEIPT_B64"] = base64.b64encode(
            noncanonical_bytes
        ).decode("ascii")
        noncanonical["RUN_READY_RECEIPT_SHA256"] = noncanonical_digest
        noncanonical["DISPATCH_RUN_READY_RECEIPT_SHA256"] = noncanonical_digest
        rejected = subprocess.run(
            ["bash"], input=script, text=True, capture_output=True,
            env=noncanonical, check=False,
        )
        self.assertNotEqual(0, rejected.returncode)
        self.assertIn(
            "canonical RUN-READY receipt does not match protected execution parameters",
            rejected.stderr,
        )

        duplicate = dict(environment)
        first_member = '"authorization_id":"R1B-AUTH-001",'
        duplicate_bytes = receipt_bytes.decode("ascii").replace(
            first_member, first_member + first_member, 1
        ).encode("ascii")
        self.assertNotEqual(receipt_bytes, duplicate_bytes)
        duplicate_digest = hashlib.sha256(duplicate_bytes).hexdigest()
        duplicate["RUN_READY_RECEIPT_B64"] = base64.b64encode(
            duplicate_bytes
        ).decode("ascii")
        duplicate["RUN_READY_RECEIPT_SHA256"] = duplicate_digest
        duplicate["DISPATCH_RUN_READY_RECEIPT_SHA256"] = duplicate_digest
        rejected = subprocess.run(
            ["bash"], input=script, text=True, capture_output=True,
            env=duplicate, check=False,
        )
        self.assertNotEqual(0, rejected.returncode)
        self.assertIn("receipt is not strict ASCII JSON", rejected.stderr)

    def test_request_carries_the_verified_run_ready_receipt_and_digest(self):
        request_step = self.workflow[
            self.workflow.index("Generate the run-unique input key and request") :
            self.workflow.index("Wait for and accept the exact encrypted input payload")
        ]
        self.assertIn('"schema_version": "b2-r1b-live-request/v3"', request_step)
        self.assertIn('"run_ready_receipt": run_ready', request_step)
        self.assertIn('"run_ready_receipt_sha256":', request_step)
        self.assertIn('"one_shot_claim": claim', request_step)
        self.assertIn('"one_shot_claim_sha256":', request_step)
        self.assertIn("hashlib.sha256(receipt_bytes).hexdigest()", request_step)
        self.assertIn("RUN-READY receipt changed after preflight", request_step)
        for exact_identity in (
            '"run_id": run_ready["run_id"]',
            '"handoff_id": run_ready["handoff_id"]',
            '"workflow_run_id": claim["workflow_run_id"]',
            '"workflow_run_attempt": claim["workflow_run_attempt"]',
            '"evaluation_run_id": run_ready["evaluation_run_id"]',
            '"authorization_id": run_ready["authorization_id"]',
        ):
            with self.subTest(exact_identity=exact_identity):
                self.assertIn(exact_identity, request_step)
        for field in (
            "provider_label",
            "requested_model_id",
            "provider_endpoint",
            "provider_timeout_seconds",
            "provider_temperature",
            "provider_max_tokens",
            "max_provider_attempts",
            "automatic_retries",
        ):
            with self.subTest(field=field):
                self.assertIn(f'"{field}"', self.workflow)

    def test_bridge_source_is_bound_before_handoff(self):
        binding_step = self.workflow.index(
            "Bind execution head to the accepted v5.2 bridge"
        )
        handoff_step = self.workflow.index(
            "Generate the run-unique input key and request"
        )
        self.assertLess(binding_step, handoff_step)
        self.assertIn(
            'git merge-base --is-ancestor "$BOUND_BRIDGE_MAIN_SHA" "$BOUND_EXECUTION_HEAD_SHA"',
            self.workflow,
        )
        self.assertIn('$BOUND_BRIDGE_MAIN_SHA:b2/blind_eval.py', self.workflow)
        self.assertIn('$BOUND_BRIDGE_MAIN_SHA:b2/blind_handoff.py', self.workflow)

    def test_v52_possession_proof_precedes_secret_and_provider(self):
        commands = (
            "generate-input-key",
            "accept-input",
            "encrypt-challenge",
            "verify-ack",
            '"-m", "b2.blind_eval"',
            "make-live-result",
        )
        positions = [self.workflow.index(command) for command in commands]
        self.assertEqual(sorted(positions), positions)
        ack = self.workflow.index("python -m b2.blind_handoff verify-ack")
        secret = self.workflow.index("${{ secrets.B2_R1B_PROVIDER_API_KEY }}")
        provider = self.workflow.index('"-m", "b2.blind_eval"')
        authorization = self.workflow.index("--authorize-live-call")
        self.assertLess(ack, secret)
        self.assertLess(secret, provider)
        self.assertLess(provider, authorization)
        self.assertEqual(1, self.workflow.count("${{ secrets."))
        self.assertEqual(1, self.workflow.count('"-m", "b2.blind_eval"'))
        self.assertEqual(1, self.workflow.count("--authorize-live-call"))

    def test_provider_is_runtime_frozen_and_has_no_retry_wrapper(self):
        provider_step = self.workflow[
            self.workflow.index("Execute exactly one authorized provider attempt") :
            self.workflow.index("Validate the body-free bridge receipt")
        ]
        for runtime_value in (
            'run_ready["provider_label"]',
            'run_ready["provider_protocol"]',
            'run_ready["requested_model_id"]',
            'run_ready["provider_endpoint"]',
            'run_ready["provider_timeout_seconds"]',
            'run_ready["provider_temperature"]',
            'run_ready["provider_max_tokens"]',
        ):
            with self.subTest(runtime_value=runtime_value):
                self.assertIn(runtime_value, provider_step)
        for independent_environment_value in (
            "PROVIDER_LABEL",
            "PROVIDER_PROTOCOL",
            "REQUESTED_MODEL_ID",
            "PROVIDER_ENDPOINT",
            "PROVIDER_TIMEOUT_SECONDS",
            "PROVIDER_TEMPERATURE",
            "PROVIDER_MAX_TOKENS",
            "EVALUATION_RUN_ID",
            "BRIDGE_MAIN_SHA",
        ):
            with self.subTest(
                independent_environment_value=independent_environment_value
            ):
                self.assertNotIn(
                    f'os.environ["{independent_environment_value}"]', provider_step
                )
        self.assertNotRegex(provider_step, r"(?m)^\s*(for|while)\b")
        self.assertNotIn("continue-on-error", provider_step)
        self.assertNotIn("retry", provider_step.lower())
        self.assertIn('runner_root / "run-ready.json"', provider_step)
        self.assertIn(
            'create(runner_root / "run-ready.json", receipt_bytes, 0o600)',
            self.workflow,
        )
        self.assertIn(
            "provider gate lost the approved RUN-READY binding", provider_step
        )
        self.assertIn("subprocess.run(command, stdout=stdout, check=False)", provider_step)
        receipt_gate = self.workflow[
            self.workflow.index("Validate the body-free bridge receipt") :
            self.workflow.index("Encrypt and publish the complete private result evidence")
        ]
        self.assertIn(
            "bridge receipt gate lost the approved RUN-READY binding", receipt_gate
        )
        self.assertIn('run_ready["provider_label"]', receipt_gate)
        self.assertNotIn('os.environ["PROVIDER_LABEL"]', receipt_gate)
        self.assertNotIn('os.environ["REQUESTED_MODEL_ID"]', receipt_gate)
        self.assertNotIn('os.environ["PROVIDER_ENDPOINT"]', receipt_gate)
        self.assertIn("GITHUB_RUN_ATTEMPT", self.workflow)
        self.assertIn("automatic retries: `0`", self.workflow)
        self.assertNotIn("api.deepseek.com", self.workflow)
        self.assertNotIn("deepseek-v4-pro", self.workflow)

    def test_exchange_is_run_scoped_create_once_and_not_an_artifact(self):
        self.assertIn(
            'os.environ["BOUND_WORKFLOW_RUN_ID"],\n              os.environ["BOUND_WORKFLOW_RUN_ATTEMPT"],\n              os.environ["BOUND_EXECUTION_HEAD_SHA"]',
            self.workflow,
        )
        self.assertIn('"HANDOFF_ID": run_ready["handoff_id"]', self.workflow)
        self.assertNotIn("handoff_id = f\"B2-R1B-", self.workflow)
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
            "B2_R1B_RUN_READY_RECEIPT_B64",
            "B2_R1B_ONE_SHOT_CLAIM_BASE",
            "B2_R1B_RUN_ID",
            "B2_R1B_HANDOFF_ID",
            "b2-r1b-run-ready/v2",
            "b2-r1b-one-shot-claim/v1",
            "b2-r1b-live-request/v3",
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
