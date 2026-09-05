from __future__ import annotations

import ast
import copy
import json
import os
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

from b2 import bm1_live
from b2.bm1 import (
    BM1AuthorizationError,
    BM1GlobalStop,
    BM1Runner,
    CLAIM_STORE_STORAGE_KIND,
    InMemoryRawEvidenceSink,
    RAW_BUNDLE_STORAGE_KIND,
    build_manifest_fingerprint,
    build_run_ready_receipt_fingerprint,
    build_storage_authority_fingerprint,
    load_manifest_from_repo_root,
    validate_manifest,
    validate_run_ready_receipt,
)


RUN_READY_WORKFLOW = Path(".github/workflows/b2_bm1_run_ready.yml")
LIVE_WORKFLOW = Path(".github/workflows/b2_bm1_live.yml")
MODULE_PATH = Path("b2/bm1_live.py")
DOC_PATH = Path("docs/b2/bm1-live-orchestration.md")
ATT_FINGERPRINT = "sha256:" + "a" * 64
RUN_READY_FINGERPRINT = "sha256:" + "b" * 64
FIXED_NOW = datetime(2026, 9, 5, 21, 20, tzinfo=timezone.utc)


def top_level_block(document: str, key: str) -> str:
    lines = document.splitlines(keepends=True)
    marker = f"{key}:\n"
    start = lines.index(marker)
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].strip() and not lines[index].startswith((" ", "\t")):
            end = index
            break
    return "".join(lines[start:end])


def job_block(document: str, job: str) -> str:
    lines = document.splitlines(keepends=True)
    marker = f"  {job}:\n"
    start = lines.index(marker)
    end = len(lines)
    for index in range(start + 1, len(lines)):
        if lines[index].startswith("  ") and not lines[index].startswith("    ") and lines[index].strip():
            end = index
            break
    return "".join(lines[start:end])


def git_value(revision: str) -> str:
    return subprocess.run(
        ["git", "rev-parse", "--verify", revision],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


class EventHarness:
    def __init__(self, directory: Path, *, live: bool) -> None:
        self.path = directory / "event.json"
        self.live = live
        self.comment = (
            {
                "authorization_id": "BM1-LIVE-AUTH-001",
                "comment_type": bm1_live.LIVE_COMMENT_TYPE,
                "confirm_four_attempts": True,
                "max_spend_usd": "0.20",
                "run_ready_receipt_fingerprint": RUN_READY_FINGERPRINT,
            }
            if live
            else {"comment_type": bm1_live.RUN_READY_COMMENT_TYPE}
        )
        self.event = {
            "action": "created",
            "issue": {"number": 50},
            "comment": {
                "id": 987654321,
                "body": bm1_live.canonical_ascii_json(self.comment).decode("ascii"),
                "created_at": "2026-09-05T21:20:00Z",
                "author_association": "OWNER",
                "user": {"login": "aerenkolstein-code"},
            },
            "repository": {
                "full_name": "aerenkolstein-code/llm-evaluation-lab",
                "default_branch": "main",
            },
            "sender": {"login": "aerenkolstein-code"},
        }
        self.write()

    def write(self) -> None:
        self.path.write_text(json.dumps(self.event), encoding="utf-8")

    def environment(self) -> dict[str, str]:
        workflow = bm1_live.LIVE_WORKFLOW_PATH if self.live else bm1_live.RUN_READY_WORKFLOW_PATH
        environment = {
            "GITHUB_ACTIONS": "true",
            "GITHUB_EVENT_NAME": "issue_comment",
            "GITHUB_REPOSITORY": "aerenkolstein-code/llm-evaluation-lab",
            "GITHUB_ACTOR": "aerenkolstein-code",
            "GITHUB_REF": "refs/heads/main",
            "GITHUB_RUN_ATTEMPT": "1",
            "GITHUB_RUN_ID": "123456789",
            "GITHUB_WORKFLOW_REF": (
                "aerenkolstein-code/llm-evaluation-lab/"
                f"{workflow}@refs/heads/main"
            ),
            "GITHUB_EVENT_PATH": str(self.path),
            "GITHUB_SHA": git_value("HEAD^{commit}"),
        }
        if self.live:
            environment["B2_BM1_EXPECTED_RUN_READY_RECEIPT_FINGERPRINT"] = RUN_READY_FINGERPRINT
        return environment


def add_guarded_binding(environment: dict[str, str], snapshot: bm1_live.GitHubEventSnapshot) -> None:
    environment.update({
        "B2_BM1_GUARDED_COMMENT_ID": str(snapshot.comment_id),
        "B2_BM1_GUARDED_COMMENT_FINGERPRINT": snapshot.comment_fingerprint,
        "B2_BM1_GUARDED_EXECUTION_HEAD_SHA": snapshot.execution_commit_sha,
        "B2_BM1_GUARDED_EXECUTION_TREE_SHA": snapshot.execution_tree_sha,
        "B2_BM1_GUARDED_WORKFLOW_RUN_ID": snapshot.workflow_run_id,
    })


def add_private_configuration(
    environment: dict[str, str], raw: Path, claims: Path,
) -> None:
    environment.update({
        "B2_BM1_PROVIDER_AUTHORITY_FINGERPRINT": (
            bm1_live.EXPECTED_PROVIDER_AUTHORITY_FINGERPRINT
        ),
        "B2_BM1_PROVIDER_REVIEWED_AT": FIXED_NOW.isoformat().replace("+00:00", "Z"),
        "B2_BM1_GEMINI_KEY_AUTH_STATUS": "ROTATED_NEW_AI_STUDIO_AUTH_KEY",
        "B2_BM1_GEMINI_KEY_AUTH_ATTESTATION_FINGERPRINT": ATT_FINGERPRINT,
        "B2_BM1_RAW_BUNDLE_ID": "BM1-RAW-PERSISTENT-001",
        "B2_BM1_ATTEMPT_CLAIM_STORE_ID": "BM1-CLAIMS-PERSISTENT-001",
        "B2_BM1_RAW_BUNDLE_DIR": str(raw),
        "B2_BM1_ATTEMPT_CLAIM_DIR": str(claims),
        "OPENAI_API_KEY": "synthetic-openai-test-value",
        "GEMINI_API_KEY": "synthetic-gemini-test-value",
        "GOOGLE_API_KEY": "",
    })


class OfflineTransport:
    is_live = False

    def __init__(self, provider_id: str, *, failures: int = 0) -> None:
        self.provider_id = provider_id
        self.failures = failures
        self.calls = 0

    def call(self, *, provider_id, endpoint_id, request_body, timeout_seconds):
        self.calls += 1
        if self.calls <= self.failures:
            raise ConnectionError("synthetic no-network provider-local failure")
        decision = (
            "DECLINE_CONFLICTING_ASSISTANCE"
            if "CONTRADICTS_BOUNDARY" in request_body["input"]
            else "PROVIDE_BOUNDARY_COMPATIBLE_HELP"
        )
        final = json.dumps({"decision": decision}, separators=(",", ":"))
        if provider_id == "openai":
            return {
                "_http_status": 200,
                "id": f"response-{self.calls}",
                "model": request_body["model"],
                "status": "completed",
                "output": [{"type": "message", "content": [{"type": "output_text", "text": final}]}],
                "usage": {"input_tokens": 100, "output_tokens": 10},
            }
        return {
            "_http_status": 200,
            "id": f"interaction-{self.calls}",
            "model": request_body["model"],
            "status": "completed",
            "steps": [{"type": "model_output", "content": [{"type": "text", "text": final}]}],
            "usage": {"total_input_tokens": 100, "total_output_tokens": 10},
        }


class WorkflowContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.run_ready = RUN_READY_WORKFLOW.read_text(encoding="utf-8")
        cls.live = LIVE_WORKFLOW.read_text(encoding="utf-8")
        cls.module = MODULE_PATH.read_text(encoding="utf-8")

    def test_only_created_issue_comment_can_trigger_either_workflow(self):
        for document in (self.run_ready, self.live):
            trigger = top_level_block(document, "on")
            self.assertIn("issue_comment:", trigger)
            self.assertIn("types: [created]", trigger)
            for forbidden in (
                "workflow_dispatch", "push:", "pull_request:", "schedule:",
                "repository_dispatch", "workflow_run",
            ):
                self.assertNotIn(forbidden, trigger)

    def test_public_gate_is_exact_issue_owner_non_pr_main_and_first_attempt(self):
        for document in (self.run_ready, self.live):
            gate = job_block(document, "public-gate")
            for required in (
                "github.event.issue.number == 50",
                "github.event.issue.pull_request == null",
                "github.actor == 'aerenkolstein-code'",
                "github.event.comment.user.login == 'aerenkolstein-code'",
                "github.event.comment.author_association == 'OWNER'",
                "github.event.action == 'created'",
                "github.event.repository.default_branch == 'main'",
                "github.ref == 'refs/heads/main'",
                "github.run_attempt == 1",
                "ref: refs/heads/main",
            ):
                self.assertIn(required, gate)
            self.assertNotIn("secrets.", gate)

    def test_private_lane_is_dedicated_and_public_gate_precedes_it(self):
        for document, job in (
            (self.run_ready, "private-run-ready"),
            (self.live, "private-live"),
        ):
            private = job_block(document, job)
            self.assertIn("needs: public-gate", private)
            self.assertIn("- self-hosted", private)
            self.assertIn("- b2-bm1-private", private)
            self.assertIn("environment: b2-bm1-live", private)

    def test_issue_number_is_literal_in_workflows_module_tests_and_docs(self):
        self.assertEqual(50, bm1_live.CONTROL_ISSUE_NUMBER)
        for path in (RUN_READY_WORKFLOW, LIVE_WORKFLOW, MODULE_PATH, Path(__file__), DOC_PATH):
            self.assertIn("50", path.read_text(encoding="utf-8"))

    def test_run_ready_lane_has_no_live_or_provider_execution_command(self):
        private = job_block(self.run_ready, "private-run-ready")
        self.assertIn("prepare-run-ready", private)
        self.assertNotIn("execute-live", private)
        self.assertNotIn("B2-BM1-WINDOW-LIVE-APPROVAL", self.run_ready)
        self.assertNotIn("urlopen", self.run_ready)
        self.assertNotIn("curl ", self.run_ready)

    def test_live_lane_requires_the_exact_archived_run_ready_fingerprint(self):
        self.assertIn("B2_BM1_RUN_READY_RECEIPT_FINGERPRINT", self.live)
        self.assertIn("run_ready_receipt_fingerprint", self.live)
        self.assertIn("execute-live", self.live)

    def test_wrapper_imports_reviewed_surfaces_and_no_network_primitive(self):
        tree = ast.parse(self.module)
        imported = {
            alias.name
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module == "bm1"
            for alias in node.names
        }
        self.assertTrue({
            "OpenAIResponsesHTTPTransport",
            "GoogleInteractionsHTTPTransport",
            "FileRawEvidenceSink",
            "FileAttemptClaimStore",
            "BM1Runner",
        }.issubset(imported))
        imported_roots = {
            alias.name.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        }
        self.assertTrue(imported_roots.isdisjoint({"requests", "httpx", "socket", "urllib"}))
        forbidden_attributes = {"urlopen", "Request", "HTTPConnection", "HTTPSConnection"}
        self.assertFalse({
            node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)
        } & forbidden_attributes)
        self.assertNotIn("https://api.openai.com", self.module)
        self.assertNotIn("generativelanguage.googleapis.com", self.module)
        self.assertIn("runner.run_all()", self.module)

    def test_workflow_only_places_credentials_and_private_paths_in_private_jobs(self):
        for document, private_job in (
            (self.run_ready, "private-run-ready"),
            (self.live, "private-live"),
        ):
            gate = job_block(document, "public-gate")
            private = job_block(document, private_job)
            for name in ("OPENAI_API_KEY", "GEMINI_API_KEY", "GOOGLE_API_KEY"):
                self.assertNotIn(name, gate)
                self.assertIn(name, private)
            self.assertNotIn("B2_BM1_RAW_BUNDLE_DIR", gate)
            self.assertIn("B2_BM1_RAW_BUNDLE_DIR", private)

    def test_ordinary_push_pull_request_ci_and_docs_have_no_bm1_live_path(self):
        ordinary_ci = Path(".github/workflows/test.yml").read_text(encoding="utf-8")
        for forbidden in (
            "b2.bm1_live",
            "OPENAI_API_KEY",
            "GEMINI_API_KEY",
            "B2_BM1_RAW_BUNDLE_DIR",
            "execute-live",
        ):
            self.assertNotIn(forbidden, ordinary_ci)
        for document in (self.run_ready, self.live):
            trigger = top_level_block(document, "on")
            self.assertNotIn("push:", trigger)
            self.assertNotIn("pull_request:", trigger)


class CanonicalCommentTests(unittest.TestCase):
    def test_run_ready_comment_accepts_only_one_exact_object(self):
        body = '{"comment_type":"B2-BM1-RUNREADY-PREPARE/v1"}'
        parsed, raw = bm1_live.validate_run_ready_comment(body)
        self.assertEqual({"comment_type": bm1_live.RUN_READY_COMMENT_TYPE}, parsed)
        self.assertEqual(body.encode("ascii"), raw)
        for bad in (
            body + "\n",
            '{ "comment_type":"B2-BM1-RUNREADY-PREPARE/v1"}',
            '{"comment_type":"B2-BM1-RUNREADY-PREPARE/v1","extra":1}',
            '{"comment_type":"B2-BM1-RUNREADY-PREPARE/v1","comment_type":"B2-BM1-RUNREADY-PREPARE/v1"}',
            '{"comment_type":"B2-BM1-RUNREADY-PREPARE/v1","n":NaN}',
            '{"comment_type":"B2-BM1-RUNREADY-PREPARE/v1","note":"é"}',
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(BM1AuthorizationError):
                    bm1_live.validate_run_ready_comment(bad)

    def test_live_comment_binds_exact_receipt_auth_four_attempts_and_ceiling(self):
        value = {
            "authorization_id": "BM1-LIVE-AUTH-001",
            "comment_type": bm1_live.LIVE_COMMENT_TYPE,
            "confirm_four_attempts": True,
            "max_spend_usd": "0.20",
            "run_ready_receipt_fingerprint": RUN_READY_FINGERPRINT,
        }
        body = bm1_live.canonical_ascii_json(value).decode("ascii")
        self.assertEqual(value, bm1_live.validate_live_comment(body)[0])
        mutations = (
            {**value, "confirm_four_attempts": False},
            {**value, "max_spend_usd": "0.2"},
            {**value, "max_spend_usd": 0.2},
            {**value, "run_ready_receipt_fingerprint": "sha256:" + "c" * 64},
            {**value, "authorization_id": "bad/id"},
            {**value, "extra": True},
        )
        for mutation in mutations:
            if mutation["run_ready_receipt_fingerprint"] != RUN_READY_FINGERPRINT:
                # A different well-formed fingerprint is syntactically valid; the
                # event gate rejects it against protected state instead.
                continue
            with self.subTest(mutation=mutation):
                with self.assertRaises(BM1AuthorizationError):
                    bm1_live.validate_live_comment(
                        bm1_live.canonical_ascii_json(mutation).decode("ascii")
                    )


class GitHubAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def snapshot(self, harness: EventHarness, environment: dict[str, str]):
        return bm1_live.github_event_snapshot(
            environment,
            workflow_path=(
                bm1_live.LIVE_WORKFLOW_PATH
                if harness.live
                else bm1_live.RUN_READY_WORKFLOW_PATH
            ),
            repo_root=Path.cwd(),
            comment_kind="live" if harness.live else "run-ready",
        )

    def test_valid_actual_event_binds_comment_issue_owner_head_tree_and_run(self):
        harness = EventHarness(self.directory, live=True)
        environment = harness.environment()
        snapshot = self.snapshot(harness, environment)
        self.assertEqual(50, bm1_live.CONTROL_ISSUE_NUMBER)
        self.assertEqual(987654321, snapshot.comment_id)
        self.assertEqual(git_value("HEAD^{commit}"), snapshot.execution_commit_sha)
        self.assertEqual(git_value("HEAD^{tree}"), snapshot.execution_tree_sha)
        self.assertEqual("123456789", snapshot.workflow_run_id)
        self.assertEqual(RUN_READY_FINGERPRINT, snapshot.run_ready_receipt_fingerprint)

    def test_event_gate_rejects_each_wrong_authority_dimension(self):
        changes = {
            "wrong issue": lambda h, e: h.event["issue"].update(number=49),
            "pull request": lambda h, e: h.event["issue"].update(pull_request={"url": "x"}),
            "edited": lambda h, e: h.event.update(action="edited"),
            "deleted": lambda h, e: h.event.update(action="deleted"),
            "wrong comment user": lambda h, e: h.event["comment"]["user"].update(login="other"),
            "wrong sender": lambda h, e: h.event["sender"].update(login="other"),
            "not owner": lambda h, e: h.event["comment"].update(author_association="MEMBER"),
            "wrong default": lambda h, e: h.event["repository"].update(default_branch="dev"),
            "wrong actor": lambda h, e: e.update(GITHUB_ACTOR="other"),
            "wrong ref": lambda h, e: e.update(GITHUB_REF="refs/heads/dev"),
            "wrong head": lambda h, e: e.update(GITHUB_SHA="0" * 40),
            "rerun": lambda h, e: e.update(GITHUB_RUN_ATTEMPT="2"),
            "wrong workflow": lambda h, e: e.update(GITHUB_WORKFLOW_REF="wrong"),
            "not actions": lambda h, e: e.update(GITHUB_ACTIONS="false"),
        }
        for label, change in changes.items():
            harness = EventHarness(self.directory, live=True)
            environment = harness.environment()
            change(harness, environment)
            harness.write()
            with self.subTest(label=label):
                with self.assertRaises(BM1AuthorizationError):
                    self.snapshot(harness, environment)

    def test_live_event_rejects_different_protected_run_ready(self):
        harness = EventHarness(self.directory, live=True)
        environment = harness.environment()
        environment["B2_BM1_EXPECTED_RUN_READY_RECEIPT_FINGERPRINT"] = "sha256:" + "c" * 64
        with self.assertRaises(BM1AuthorizationError):
            self.snapshot(harness, environment)

    def test_external_verifier_reloads_event_and_rejects_local_candidate_or_tamper(self):
        harness = EventHarness(self.directory, live=True)
        environment = harness.environment()
        snapshot = self.snapshot(harness, environment)
        add_guarded_binding(environment, snapshot)
        verifier = bm1_live.GitHubIssueCommentAuthorityVerifier.from_environment(
            environment, repo_root=Path.cwd()
        )
        self.assertTrue(verifier.verify(
            run_ready_receipt_fingerprint=RUN_READY_FINGERPRINT,
            user_authorization_fingerprint=snapshot.comment_fingerprint,
            authorization_id="BM1-LIVE-AUTH-001",
        ))
        self.assertFalse(verifier.verify(
            run_ready_receipt_fingerprint="sha256:" + "d" * 64,
            user_authorization_fingerprint=snapshot.comment_fingerprint,
            authorization_id="BM1-LIVE-AUTH-001",
        ))
        self.assertFalse(verifier.verify(
            run_ready_receipt_fingerprint=RUN_READY_FINGERPRINT,
            user_authorization_fingerprint=snapshot.comment_fingerprint,
            authorization_id="BM1-LIVE-AUTH-DIFFERENT",
        ))
        harness.event["comment"]["body"] = bm1_live.canonical_ascii_json({
            **harness.comment,
            "authorization_id": "BM1-LOCALLY-MINTED-002",
        }).decode("ascii")
        harness.write()
        self.assertFalse(verifier.verify(
            run_ready_receipt_fingerprint=RUN_READY_FINGERPRINT,
            user_authorization_fingerprint=snapshot.comment_fingerprint,
            authorization_id="BM1-LIVE-AUTH-001",
        ))

    def test_verifier_cannot_be_created_without_trusted_event_file_and_guard_outputs(self):
        harness = EventHarness(self.directory, live=True)
        environment = harness.environment()
        with self.assertRaises(BM1AuthorizationError):
            bm1_live.GitHubIssueCommentAuthorityVerifier.from_environment(
                environment, repo_root=Path.cwd()
            )
        environment["GITHUB_EVENT_PATH"] = str(self.directory / "locally-missing.json")
        with self.assertRaises(BM1AuthorizationError):
            bm1_live.GitHubIssueCommentAuthorityVerifier.from_environment(
                environment, repo_root=Path.cwd()
            )


class CredentialAndProviderTests(unittest.TestCase):
    def base(self) -> dict[str, str]:
        return {
            "OPENAI_API_KEY": "openai-test-value",
            "GEMINI_API_KEY": "gemini-test-value",
            "GOOGLE_API_KEY": "",
            "B2_BM1_GEMINI_KEY_AUTH_STATUS": "ROTATED_NEW_AI_STUDIO_AUTH_KEY",
            "B2_BM1_GEMINI_KEY_AUTH_ATTESTATION_FINGERPRINT": ATT_FINGERPRINT,
        }

    def test_presence_only_decision_is_public_safe_and_value_free(self):
        environment = self.base()
        _, public = bm1_live.credential_decision(environment)
        encoded = json.dumps(public, sort_keys=True)
        self.assertNotIn(environment["OPENAI_API_KEY"], encoded)
        self.assertNotIn(environment["GEMINI_API_KEY"], encoded)
        self.assertTrue(public["openai_credential_present"])
        self.assertTrue(public["google_competing_credential_absent"])

    def test_missing_or_ambiguous_credentials_fail_closed(self):
        mutations = (
            {"OPENAI_API_KEY": ""},
            {"GEMINI_API_KEY": ""},
            {"GOOGLE_API_KEY": "competing-test-value"},
        )
        for mutation in mutations:
            environment = self.base()
            environment.update(mutation)
            with self.subTest(mutation=mutation):
                with self.assertRaises(BM1AuthorizationError):
                    bm1_live.credential_decision(environment)

    def test_auth_key_status_requires_explicit_public_safe_attestation(self):
        for mutation in (
            {"B2_BM1_GEMINI_KEY_AUTH_STATUS": "INFERRED_FROM_PREFIX"},
            {"B2_BM1_GEMINI_KEY_AUTH_ATTESTATION_FINGERPRINT": ""},
            {"B2_BM1_GEMINI_KEY_AUTH_ATTESTATION_FINGERPRINT": "sha256:bad"},
        ):
            environment = self.base()
            environment.update(mutation)
            with self.subTest(mutation=mutation):
                with self.assertRaises(BM1AuthorizationError):
                    bm1_live.credential_decision(environment)

    def test_provider_review_requires_exact_fingerprint_and_fresh_timestamp(self):
        environment = {
            "B2_BM1_PROVIDER_AUTHORITY_FINGERPRINT": bm1_live.EXPECTED_PROVIDER_AUTHORITY_FINGERPRINT,
            "B2_BM1_PROVIDER_REVIEWED_AT": FIXED_NOW.isoformat(),
        }
        self.assertEqual(
            bm1_live.EXPECTED_PROVIDER_AUTHORITY_FINGERPRINT,
            bm1_live.validate_provider_review(environment, now=FIXED_NOW),
        )
        for mutation in (
            {"B2_BM1_PROVIDER_AUTHORITY_FINGERPRINT": "sha256:" + "e" * 64},
            {"B2_BM1_PROVIDER_REVIEWED_AT": (FIXED_NOW - timedelta(days=2)).isoformat()},
            {"B2_BM1_PROVIDER_REVIEWED_AT": (FIXED_NOW + timedelta(hours=1)).isoformat()},
        ):
            changed = dict(environment)
            changed.update(mutation)
            with self.subTest(mutation=mutation):
                with self.assertRaises(BM1AuthorizationError):
                    bm1_live.validate_provider_review(changed, now=FIXED_NOW)


class StorageAuthorityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.raw = self.base / "raw"
        self.claims = self.base / "claims"
        self.raw.mkdir(mode=0o700)
        self.claims.mkdir(mode=0o700)
        os.chmod(self.raw, 0o700)
        os.chmod(self.claims, 0o700)
        self.environment = {
            "B2_BM1_RAW_BUNDLE_DIR": str(self.raw),
            "B2_BM1_ATTEMPT_CLAIM_DIR": str(self.claims),
            "B2_BM1_RAW_BUNDLE_ID": "BM1-RAW-TEST-001",
            "B2_BM1_ATTEMPT_CLAIM_STORE_ID": "BM1-CLAIM-TEST-001",
        }

    def tearDown(self) -> None:
        self.temp.cleanup()

    def runtime(self):
        with mock.patch("b2.bm1_live._forbidden_storage_roots", return_value=()):
            return bm1_live.storage_runtime(self.environment)

    def test_actual_authority_binds_kind_resolved_path_device_and_inode(self):
        runtime = self.runtime()
        self.assertEqual(
            build_storage_authority_fingerprint(self.raw, storage_kind=RAW_BUNDLE_STORAGE_KIND),
            runtime.raw_sink.storage_authority_fingerprint,
        )
        self.assertEqual(
            build_storage_authority_fingerprint(self.claims, storage_kind=CLAIM_STORE_STORAGE_KIND),
            runtime.claim_store.storage_authority_fingerprint,
        )

    def test_default_policy_rejects_new_temporary_substitutes(self):
        with self.assertRaises(BM1AuthorizationError):
            bm1_live.storage_runtime(self.environment)

    def test_missing_world_readable_overlapping_and_symlink_storage_fail(self):
        missing = dict(self.environment, B2_BM1_RAW_BUNDLE_DIR=str(self.base / "missing"))
        with mock.patch("b2.bm1_live._forbidden_storage_roots", return_value=()):
            with self.assertRaises(BM1AuthorizationError):
                bm1_live.storage_runtime(missing)
        os.chmod(self.raw, 0o755)
        with mock.patch("b2.bm1_live._forbidden_storage_roots", return_value=()):
            with self.assertRaises(BM1AuthorizationError):
                bm1_live.storage_runtime(self.environment)
        os.chmod(self.raw, 0o700)
        overlapping = dict(self.environment, B2_BM1_ATTEMPT_CLAIM_DIR=str(self.raw))
        with mock.patch("b2.bm1_live._forbidden_storage_roots", return_value=()):
            with self.assertRaises(BM1AuthorizationError):
                bm1_live.storage_runtime(overlapping)
        link = self.base / "raw-link"
        link.symlink_to(self.raw, target_is_directory=True)
        linked = dict(self.environment, B2_BM1_RAW_BUNDLE_DIR=str(link))
        with mock.patch("b2.bm1_live._forbidden_storage_roots", return_value=()):
            with self.assertRaises(BM1AuthorizationError):
                bm1_live.storage_runtime(linked)

    def test_same_label_different_directory_has_different_actual_authority(self):
        first = self.runtime()
        raw_two = self.base / "raw-two"
        claims_two = self.base / "claims-two"
        raw_two.mkdir(mode=0o700)
        claims_two.mkdir(mode=0o700)
        os.chmod(raw_two, 0o700)
        os.chmod(claims_two, 0o700)
        second_environment = dict(
            self.environment,
            B2_BM1_RAW_BUNDLE_DIR=str(raw_two),
            B2_BM1_ATTEMPT_CLAIM_DIR=str(claims_two),
        )
        with mock.patch("b2.bm1_live._forbidden_storage_roots", return_value=()):
            second = bm1_live.storage_runtime(second_environment)
        self.assertEqual(first.raw_sink.destination_fingerprint, second.raw_sink.destination_fingerprint)
        self.assertNotEqual(
            first.raw_sink.storage_authority_fingerprint,
            second.raw_sink.storage_authority_fingerprint,
        )

    def test_inode_replacement_is_seen_on_next_authority_read(self):
        runtime = self.runtime()
        before = runtime.raw_sink.storage_authority_fingerprint
        old = self.base / "raw-old"
        self.raw.rename(old)
        self.raw.mkdir(mode=0o700)
        os.chmod(self.raw, 0o700)
        after = runtime.raw_sink.storage_authority_fingerprint
        self.assertNotEqual(before, after)

    def test_fsync_failure_fails_closed(self):
        runtime = self.runtime()
        with mock.patch("b2.bm1_live.os.fsync", side_effect=OSError("synthetic")):
            with self.assertRaises(BM1AuthorizationError):
                runtime.claim_store.storage_authority_fingerprint


class RunReadyPreparationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.base = Path(self.temp.name)
        self.raw = self.base / "raw"
        self.claims = self.base / "claims"
        self.raw.mkdir(mode=0o700)
        self.claims.mkdir(mode=0o700)
        os.chmod(self.raw, 0o700)
        os.chmod(self.claims, 0o700)
        self.harness = EventHarness(self.base, live=False)
        self.environment = self.harness.environment()
        snapshot = bm1_live.github_event_snapshot(
            self.environment,
            workflow_path=bm1_live.RUN_READY_WORKFLOW_PATH,
            repo_root=Path.cwd(),
            comment_kind="run-ready",
        )
        add_guarded_binding(self.environment, snapshot)
        add_private_configuration(self.environment, self.raw, self.claims)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def prepare(self):
        with mock.patch("b2.bm1_live._forbidden_storage_roots", return_value=()):
            return bm1_live.prepare_run_ready(
                self.environment, repo_root=Path.cwd(), now=FIXED_NOW
            )

    def test_preparation_emits_valid_public_receipt_archives_and_stops_without_live(self):
        with mock.patch("b2.bm1_live.OpenAIResponsesHTTPTransport") as openai, mock.patch(
            "b2.bm1_live.GoogleInteractionsHTTPTransport"
        ) as google:
            result = self.prepare()
        openai.assert_not_called()
        google.assert_not_called()
        manifest, _ = load_manifest_from_repo_root(Path.cwd())
        checked = validate_run_ready_receipt(
            result.receipt,
            manifest=manifest,
            execution_commit_sha=git_value("HEAD^{commit}"),
            execution_tree_sha=git_value("HEAD^{tree}"),
        )
        self.assertEqual(4, len(checked["authorized_attempt_ids"]))
        self.assertEqual(0, result.public_projection["provider_requests"])
        self.assertEqual(0, result.public_projection["spend_usd"])
        self.assertFalse(result.public_projection["live_authorization_created"])
        archived = bm1_live.load_archived_run_ready(
            self.raw, checked["receipt_fingerprint"]
        )
        self.assertEqual(checked, archived)

    def test_public_projection_contains_no_secret_value_or_private_path(self):
        result = self.prepare()
        encoded = bm1_live.canonical_ascii_json(result.public_projection).decode("ascii")
        for forbidden in (
            self.environment["OPENAI_API_KEY"],
            self.environment["GEMINI_API_KEY"],
            str(self.raw),
            str(self.claims),
        ):
            self.assertNotIn(forbidden, encoded)

    def test_changed_head_provider_credential_or_storage_is_rejected(self):
        result = self.prepare()
        manifest, _ = load_manifest_from_repo_root(Path.cwd())
        with self.assertRaises(BM1AuthorizationError):
            validate_run_ready_receipt(
                result.receipt,
                manifest=manifest,
                execution_commit_sha="0" * 40,
                execution_tree_sha=git_value("HEAD^{tree}"),
            )
        changed_provider = dict(self.environment)
        changed_provider["B2_BM1_PROVIDER_AUTHORITY_FINGERPRINT"] = "sha256:" + "f" * 64
        with self.assertRaises(BM1AuthorizationError):
            bm1_live.validate_provider_review(changed_provider, now=FIXED_NOW)
        changed_credential = dict(self.environment)
        changed_credential["B2_BM1_GEMINI_KEY_AUTH_ATTESTATION_FINGERPRINT"] = "sha256:" + "c" * 64
        _, public = bm1_live.credential_decision(changed_credential)
        self.assertNotEqual(
            result.receipt["credential_decision_fingerprint"],
            public["credential_decision_fingerprint"],
        )
        replacement = self.base / "raw-replacement"
        replacement.mkdir(mode=0o700)
        os.chmod(replacement, 0o700)
        self.assertNotEqual(
            result.receipt["raw_bundle_destination"]["storage_authority_fingerprint"],
            build_storage_authority_fingerprint(
                replacement, storage_kind=RAW_BUNDLE_STORAGE_KIND
            ),
        )

    def test_attempt_order_and_runtime_limits_remain_the_frozen_core_contract(self):
        result = self.prepare()
        self.assertEqual([
            "BM1-A01-OPENAI-TARGET",
            "BM1-A02-OPENAI-CONTROL",
            "BM1-A03-GOOGLE-TARGET",
            "BM1-A04-GOOGLE-CONTROL",
        ], result.receipt["authorized_attempt_ids"])
        self.assertEqual({
            "maximum_provider_requests": 4,
            "maximum_total_spend_usd": 0.2,
            "automatic_retries": 0,
            "timeout_seconds": 120,
            "max_input_tokens_per_attempt": 8000,
            "max_output_tokens_per_attempt": 2000,
        }, result.receipt["runtime_limits"])

        manifest, _ = load_manifest_from_repo_root(Path.cwd())
        changed_order = copy.deepcopy(result.receipt)
        changed_order["authorized_attempt_ids"] = list(reversed(
            changed_order["authorized_attempt_ids"]
        ))
        changed_order["receipt_fingerprint"] = build_run_ready_receipt_fingerprint(
            changed_order
        )
        with self.assertRaises(BM1AuthorizationError):
            validate_run_ready_receipt(
                changed_order,
                manifest=manifest,
                execution_commit_sha=git_value("HEAD^{commit}"),
                execution_tree_sha=git_value("HEAD^{tree}"),
            )

        changed_limits = copy.deepcopy(result.receipt)
        changed_limits["runtime_limits"]["automatic_retries"] = 1
        changed_limits["receipt_fingerprint"] = build_run_ready_receipt_fingerprint(
            changed_limits
        )
        with self.assertRaises(BM1AuthorizationError):
            validate_run_ready_receipt(
                changed_limits,
                manifest=manifest,
                execution_commit_sha=git_value("HEAD^{commit}"),
                execution_tree_sha=git_value("HEAD^{tree}"),
            )

    def test_wrong_manifest_retry_and_fallback_drift_fail_closed(self):
        manifest, cases = load_manifest_from_repo_root(Path.cwd())
        mutations = (
            ("automatic_retries", 1),
            ("fallback_or_model_substitution", 1),
            ("planned_provider_attempts", 5),
        )
        for field, value in mutations:
            changed = copy.deepcopy(manifest)
            changed["runtime_contract"][field] = value
            changed["manifest_fingerprint"] = build_manifest_fingerprint(changed)
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    validate_manifest(changed, case_lookup=cases)

        result = self.prepare()
        changed_receipt = copy.deepcopy(result.receipt)
        changed_receipt["manifest_fingerprint"] = "sha256:" + "0" * 64
        changed_receipt["receipt_fingerprint"] = build_run_ready_receipt_fingerprint(
            changed_receipt
        )
        with self.assertRaises(BM1AuthorizationError):
            validate_run_ready_receipt(
                changed_receipt,
                manifest=manifest,
                execution_commit_sha=git_value("HEAD^{commit}"),
                execution_tree_sha=git_value("HEAD^{tree}"),
            )

    def test_archive_rejects_tamper_and_wrong_fingerprint(self):
        result = self.prepare()
        fingerprint = result.receipt["receipt_fingerprint"]
        archive = self.raw / f".bm1-run-ready-{fingerprint.removeprefix('sha256:')}.json"
        archive.write_text("{}", encoding="ascii")
        with self.assertRaises(BM1AuthorizationError):
            bm1_live.load_archived_run_ready(self.raw, fingerprint)
        with self.assertRaises(BM1AuthorizationError):
            bm1_live.load_archived_run_ready(self.raw, "sha256:" + "d" * 64)


class FrozenExecutionSemanticsTests(unittest.TestCase):
    def runner(self, *, openai_failures: int = 0):
        manifest, cases = load_manifest_from_repo_root(Path.cwd())
        openai = OfflineTransport("openai", failures=openai_failures)
        google = OfflineTransport("google")
        runner = BM1Runner(
            manifest=manifest,
            case_lookup=cases,
            transports={"openai": openai, "google": google},
            evidence_sink=InMemoryRawEvidenceSink(),
            now_fn=lambda: FIXED_NOW,
        )
        return runner, openai, google

    def test_exact_four_no_retry_and_fifth_request_are_core_enforced_offline(self):
        runner, openai, google = self.runner()
        receipts = runner.run_all()
        self.assertEqual(4, runner.provider_request_count)
        self.assertEqual((2, 2), (openai.calls, google.calls))
        self.assertTrue(all(row["terminal_status"] == "PASS" for row in receipts))
        with self.assertRaises(BM1GlobalStop):
            runner.run_next("BM1-A05-FORBIDDEN")

    def test_two_provider_local_errors_stop_remaining_without_retry_or_fallback(self):
        runner, openai, google = self.runner(openai_failures=2)
        receipts = runner.run_all()
        self.assertEqual(["ERROR", "ERROR", "BLOCKED", "BLOCKED"], [
            row["terminal_status"] for row in receipts
        ])
        self.assertEqual(2, runner.provider_request_count)
        self.assertEqual(2, openai.calls)
        self.assertEqual(0, google.calls)

    def test_public_live_summary_is_body_secret_and_path_free(self):
        runner, _, _ = self.runner()
        receipts = runner.run_all()
        snapshot = bm1_live.GitHubEventSnapshot(
            comment_body="not-projected",
            comment_bytes=b"not-projected",
            comment_fingerprint="sha256:" + "1" * 64,
            comment_id=123,
            comment_created_at=FIXED_NOW,
            authorization_id="BM1-AUTH-SUMMARY-001",
            run_ready_receipt_fingerprint="sha256:" + "2" * 64,
            execution_commit_sha="3" * 40,
            execution_tree_sha="4" * 40,
            workflow_run_id="123456",
            workflow_path=bm1_live.LIVE_WORKFLOW_PATH,
        )
        summary = bm1_live._live_summary(
            snapshot=snapshot,
            run_ready={"receipt_fingerprint": "sha256:" + "2" * 64},
            live_authorization={"receipt_fingerprint": "sha256:" + "5" * 64},
            runner=runner,
            receipts=receipts,
        )
        encoded = bm1_live.canonical_ascii_json(summary).decode("ascii").lower()
        for forbidden in (
            "not-projected",
            "authorization: bearer",
            "request_body",
            "raw_response",
            "response_body",
            "final_text",
            "reasoning_body",
            "/tmp/",
        ):
            self.assertNotIn(forbidden, encoded)


class ChangedPathEnvelopeTests(unittest.TestCase):
    def test_work_order_envelope_is_exactly_five_new_paths(self):
        expected = {
            ".github/workflows/b2_bm1_run_ready.yml",
            ".github/workflows/b2_bm1_live.yml",
            "b2/bm1_live.py",
            "tests/test_b2_bm1_live_orchestration.py",
            "docs/b2/bm1-live-orchestration.md",
        }
        self.assertEqual(expected, {
            str(RUN_READY_WORKFLOW), str(LIVE_WORKFLOW), str(MODULE_PATH),
            str(Path(__file__).resolve().relative_to(Path.cwd().resolve())), str(DOC_PATH),
        })
        for path in expected:
            self.assertTrue(Path(path).is_file())


if __name__ == "__main__":
    unittest.main()
