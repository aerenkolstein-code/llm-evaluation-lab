from __future__ import annotations

import ast
import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from b2.bm1 import (
    APPROVED_PATHS,
    AUTOMATIC_RETRIES,
    BM1AuthorizationError,
    BM1ContractError,
    BM1GlobalStop,
    BM1Runner,
    CONTROL_CASE_ID,
    FileAttemptClaimStore,
    FileRawEvidenceSink,
    GOOGLE_CREDENTIAL_REFERENCE,
    GOOGLE_ENDPOINT_ID,
    GOOGLE_PROVIDER_ID,
    GOOGLE_REQUESTED_MODEL_ID,
    GoogleInteractionsHTTPTransport,
    InMemoryAttemptClaimStore,
    InMemoryRawEvidenceSink,
    LIVE_ATTEMPT_CLAIM_POLICY,
    LIVE_AUTH_SCHEMA_VERSION,
    LiveAuthorityAnchor,
    MAX_PLANNED_ATTEMPTS,
    MAX_TOTAL_SMOKE_SPEND_USD,
    OPENAI_CREDENTIAL_REFERENCE,
    OPENAI_ENDPOINT_ID,
    OPENAI_PROVIDER_ID,
    OPENAI_REQUESTED_MODEL_ID,
    OpenAIResponsesHTTPTransport,
    RAW_BUNDLE_STORAGE_KIND,
    RUN_READY_SCHEMA_VERSION,
    build_google_request,
    build_live_authorization_fingerprint,
    build_openai_request,
    build_raw_destination_fingerprint,
    build_run_ready_receipt_fingerprint,
    expected_decision_for_case,
    normalize_google_response,
    normalize_openai_response,
    replay_scorer,
    render_case_prompt,
    validate_live_authorization,
    validate_manifest,
    validate_run_ready_receipt,
    validate_symbolic_credential_presence,
)
from b2.qa0 import sha256_json

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "cases" / "b2" / "public-safe" / "benchmark" / "bm1-live-smoke-manifest.json"
FIXTURE_PATH = ROOT / "cases" / "b2" / "public-safe" / "robustness" / "qa2-robustness-fixtures.json"
SCHEMA_PATH = ROOT / "schemas" / "bm1_live_smoke_manifest.schema.json"
FIXED_NOW = datetime(2026, 9, 5, 4, 0, 0, tzinfo=timezone.utc)
EXPIRED_NOW = datetime(2026, 9, 5, 5, 1, 0, tzinfo=timezone.utc)
EXECUTION_COMMIT = "a" * 40
EXECUTION_TREE = "b" * 40
USER_AUTH_FP = "sha256:" + "d" * 64


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def fixture_lookup() -> dict[str, dict]:
    fixture = load_json(FIXTURE_PATH)
    return {row["case_id"]: row for row in fixture["cases"]}


def refingerprint(document: dict, field: str) -> dict:
    candidate = copy.deepcopy(document)
    candidate.pop(field, None)
    candidate[field] = sha256_json(candidate)
    return candidate


def run_ready_receipt(manifest: dict, *, destination_id: str = "BM1-RAW-BUNDLE-TEST-001", **overrides: object) -> dict:
    destination = {
        "destination_id": destination_id,
        "storage_kind": RAW_BUNDLE_STORAGE_KIND,
        "destination_fingerprint": build_raw_destination_fingerprint(destination_id),
    }
    document = {
        "schema_version": RUN_READY_SCHEMA_VERSION,
        "run_ready_id": "BM1-RUN-READY-TEST-001",
        "manifest_fingerprint": manifest["manifest_fingerprint"],
        "execution_commit_sha": EXECUTION_COMMIT,
        "execution_tree_sha": EXECUTION_TREE,
        "provider_authority_fingerprint": "sha256:" + "1" * 64,
        "credential_decision_fingerprint": "sha256:" + "2" * 64,
        "raw_bundle_destination": destination,
        "authorized_attempt_ids": [row["attempt_id"] for row in manifest["attempt_plan"]],
        "runtime_limits": {
            "maximum_provider_requests": 4,
            "maximum_total_spend_usd": 0.20,
            "automatic_retries": 0,
            "timeout_seconds": 120,
            "max_input_tokens_per_attempt": 8000,
            "max_output_tokens_per_attempt": 2000,
        },
        "issued_at": "2026-09-05T03:58:00Z",
    }
    document.update(overrides)
    document["receipt_fingerprint"] = build_run_ready_receipt_fingerprint(document)
    return document


def authority_anchor(run_ready: dict, *, user_fp: str = USER_AUTH_FP) -> LiveAuthorityAnchor:
    return LiveAuthorityAnchor(
        run_ready_receipt_fingerprint=run_ready["receipt_fingerprint"],
        user_authorization_fingerprint=user_fp,
    )


def live_authorization(manifest: dict, run_ready: dict, anchor: LiveAuthorityAnchor, **overrides: object) -> dict:
    document = {
        "schema_version": LIVE_AUTH_SCHEMA_VERSION,
        "authorization_id": "BM1-LIVE-AUTH-TEST-001",
        "manifest_fingerprint": manifest["manifest_fingerprint"],
        "execution_commit_sha": EXECUTION_COMMIT,
        "execution_tree_sha": EXECUTION_TREE,
        "run_ready_receipt_fingerprint": run_ready["receipt_fingerprint"],
        "user_authorization_fingerprint": anchor.user_authorization_fingerprint,
        "raw_bundle_destination_fingerprint": run_ready["raw_bundle_destination"]["destination_fingerprint"],
        "authorized_attempt_ids": [row["attempt_id"] for row in manifest["attempt_plan"]],
        "maximum_provider_requests": 4,
        "maximum_total_spend_usd": 0.20,
        "automatic_retries": 0,
        "issued_at": "2026-09-05T03:59:00Z",
        "expires_at": "2026-09-05T05:00:00Z",
    }
    document.update(overrides)
    document["receipt_fingerprint"] = build_live_authorization_fingerprint(document)
    return document


def response_for(provider_id: str, model_id: str, decision: str, serial: int = 1) -> dict:
    final = json.dumps({"decision": decision}, separators=(",", ":"))
    if provider_id == OPENAI_PROVIDER_ID:
        return {
            "_http_status": 200,
            "id": f"resp-{serial}",
            "model": model_id,
            "status": "completed",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": final}]}],
            "usage": {"input_tokens": 100, "output_tokens": 10},
        }
    return {
        "_http_status": 200,
        "id": f"interaction-{serial}",
        "model": model_id,
        "status": "completed",
        "steps": [{"type": "model_output", "content": [{"type": "text", "text": final}]}],
        "usage": {"total_input_tokens": 100, "total_output_tokens": 10},
    }


class FakeTransport:
    is_live = False

    def __init__(self, provider_id: str, scripted: list[object] | None = None) -> None:
        self.provider_id = provider_id
        self.scripted = list(scripted or [])
        self.calls: list[dict] = []

    def call(self, *, provider_id: str, endpoint_id: str, request_body: dict, timeout_seconds: int) -> dict:
        self.calls.append({
            "provider_id": provider_id,
            "endpoint_id": endpoint_id,
            "request_body": copy.deepcopy(request_body),
            "timeout_seconds": timeout_seconds,
        })
        if provider_id != self.provider_id:
            raise AssertionError("fake provider mismatch")
        if self.scripted:
            item = self.scripted.pop(0)
            if isinstance(item, BaseException):
                raise item
            return copy.deepcopy(item)
        decision = (
            "DECLINE_CONFLICTING_ASSISTANCE"
            if "CONTRADICTS_BOUNDARY" in request_body["input"]
            else "PROVIDE_BOUNDARY_COMPATIBLE_HELP"
        )
        return response_for(provider_id, request_body["model"], decision, len(self.calls))


class FakeHTTPResponse:
    def __init__(self, payload: dict, status: int = 200) -> None:
        self.payload = json.dumps(payload).encode("utf-8")
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self, limit: int = -1) -> bytes:
        return self.payload if limit < 0 else self.payload[:limit]

    def getcode(self) -> int:
        return self.status


class CapturingOpener:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.requests = []

    def __call__(self, request, timeout: int):
        self.requests.append((request, timeout))
        return FakeHTTPResponse(self.payload)


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


class FailingSink(InMemoryRawEvidenceSink):
    def write(self, **kwargs):
        raise OSError("synthetic write failure")


class BM1ManifestTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.manifest = load_json(MANIFEST_PATH)
        cls.lookup = fixture_lookup()

    def test_manifest_binds_exact_baseline_case_roster_and_four_attempts(self):
        checked = validate_manifest(self.manifest, case_lookup=self.lookup)
        self.assertEqual(checked["implementation_baseline"]["commit_sha"], "74304a23d7e542b28dcd519f9b58d394447fc696")
        self.assertEqual([row["provider_id"] for row in checked["attempt_plan"]], ["openai", "openai", "google", "google"])
        self.assertEqual(len(checked["attempt_plan"]), MAX_PLANNED_ATTEMPTS)
        self.assertEqual(tuple(checked["implementation_scope"]["approved_paths"]), APPROVED_PATHS)
        self.assertEqual(checked["runtime_contract"]["live_attempt_claim"], LIVE_ATTEMPT_CLAIM_POLICY)
        self.assertFalse(checked["authorization"]["live_execution"])

    def test_manifest_fingerprint_tamper_is_rejected(self):
        changed = copy.deepcopy(self.manifest)
        changed["runtime_contract"]["timeout_seconds"] = 121
        with self.assertRaises(BM1ContractError):
            validate_manifest(changed, case_lookup=self.lookup)

    def test_case_prompt_decision_and_model_drift_are_rejected(self):
        for key, value in (
            ("case_fingerprint", "sha256:" + "0" * 64),
            ("prompt_fingerprint", "sha256:" + "1" * 64),
            ("expected_decision", "PROVIDE_BOUNDARY_COMPATIBLE_HELP"),
        ):
            changed = copy.deepcopy(self.manifest)
            changed["case_binding"]["cases"][0][key] = value
            changed = refingerprint(changed, "manifest_fingerprint")
            with self.subTest(key=key), self.assertRaises(BM1ContractError):
                validate_manifest(changed, case_lookup=self.lookup)
        changed = copy.deepcopy(self.manifest)
        changed["providers"][0]["requested_model_id"] = "gpt-substitute"
        changed["providers"][0]["identity_policy"]["accepted_resolved_model_ids"] = ["gpt-substitute"]
        changed["attempt_plan"][0]["requested_model_id"] = "gpt-substitute"
        changed["attempt_plan"][1]["requested_model_id"] = "gpt-substitute"
        changed = refingerprint(changed, "manifest_fingerprint")
        with self.assertRaises(BM1ContractError):
            validate_manifest(changed, case_lookup=self.lookup)

    def test_attempt_order_and_sixth_path_are_rejected(self):
        changed = copy.deepcopy(self.manifest)
        changed["attempt_plan"][0], changed["attempt_plan"][1] = changed["attempt_plan"][1], changed["attempt_plan"][0]
        changed["attempt_plan"][0]["sequence"] = 1
        changed["attempt_plan"][1]["sequence"] = 2
        changed = refingerprint(changed, "manifest_fingerprint")
        with self.assertRaises(BM1ContractError):
            validate_manifest(changed, case_lookup=self.lookup)
        changed = copy.deepcopy(self.manifest)
        changed["implementation_scope"]["approved_paths"].append("b2/not-authorized.py")
        changed = refingerprint(changed, "manifest_fingerprint")
        with self.assertRaises(BM1ContractError):
            validate_manifest(changed, case_lookup=self.lookup)

    def test_json_schema_is_strict_and_names_same_five_paths_and_claim_policy(self):
        schema = load_json(SCHEMA_PATH)
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["attempt_plan"]["minItems"], 4)
        self.assertEqual(schema["properties"]["attempt_plan"]["maxItems"], 4)
        self.assertEqual(schema["properties"]["runtime_contract"]["const"]["live_attempt_claim"], LIVE_ATTEMPT_CLAIM_POLICY)
        items = schema["properties"]["implementation_scope"]["properties"]["approved_paths"]["prefixItems"]
        self.assertEqual(tuple(item["const"] for item in items), APPROVED_PATHS)


class BM1SerializationAndIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.lookup = fixture_lookup()

    def test_e11_prompt_and_provider_request_controls_are_frozen(self):
        target = self.lookup["B2-QA2-R-CONSTRAINT-KB-001"]
        control = self.lookup[CONTROL_CASE_ID]
        self.assertEqual(expected_decision_for_case(target), "DECLINE_CONFLICTING_ASSISTANCE")
        self.assertEqual(expected_decision_for_case(control), "PROVIDE_BOUNDARY_COMPATIBLE_HELP")
        prompt = render_case_prompt(target)
        openai = build_openai_request(requested_model_id=OPENAI_REQUESTED_MODEL_ID, prompt=prompt, max_output_tokens=2000)
        self.assertEqual(openai["reasoning"], {"effort": "low"})
        self.assertNotIn("temperature", openai)
        google = build_google_request(requested_model_id=GOOGLE_REQUESTED_MODEL_ID, prompt=prompt, max_output_tokens=2000)
        self.assertEqual(google["generation_config"]["thinking_level"], "low")
        for key in ("temperature", "top_p", "top_k"):
            self.assertNotIn(key, google["generation_config"])

    def test_symbolic_credential_guard_rejects_google_dual_key(self):
        self.assertEqual(validate_symbolic_credential_presence(OPENAI_PROVIDER_ID, [OPENAI_CREDENTIAL_REFERENCE]), OPENAI_CREDENTIAL_REFERENCE)
        self.assertEqual(validate_symbolic_credential_presence(GOOGLE_PROVIDER_ID, [GOOGLE_CREDENTIAL_REFERENCE]), GOOGLE_CREDENTIAL_REFERENCE)
        with self.assertRaises(BM1AuthorizationError):
            validate_symbolic_credential_presence(GOOGLE_PROVIDER_ID, ["GEMINI_API_KEY", "GOOGLE_API_KEY"])
        with self.assertRaises(BM1AuthorizationError):
            validate_symbolic_credential_presence(GOOGLE_PROVIDER_ID, ["GOOGLE_API_KEY"])

    def test_response_normalizers_capture_identity_and_usage(self):
        openai = normalize_openai_response(response_for("openai", OPENAI_REQUESTED_MODEL_ID, "DECLINE_CONFLICTING_ASSISTANCE"))
        self.assertEqual((openai.provider_terminal_status, openai.resolved_model_id, openai.input_tokens), ("SUCCESS", OPENAI_REQUESTED_MODEL_ID, 100))
        google = normalize_google_response(response_for("google", GOOGLE_REQUESTED_MODEL_ID, "PROVIDE_BOUNDARY_COMPATIBLE_HELP"))
        self.assertEqual((google.provider_terminal_status, google.resolved_model_id, google.output_tokens), ("SUCCESS", GOOGLE_REQUESTED_MODEL_ID, 10))


class BM1RunnerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = load_json(MANIFEST_PATH)
        self.lookup = fixture_lookup()
        self.sink = InMemoryRawEvidenceSink()
        self.openai = FakeTransport("openai")
        self.google = FakeTransport("google")

    def runner(self) -> BM1Runner:
        return BM1Runner(
            manifest=self.manifest, case_lookup=self.lookup,
            transports={"openai": self.openai, "google": self.google},
            evidence_sink=self.sink, now_fn=lambda: FIXED_NOW,
        )

    def test_successful_offline_smoke_has_exactly_four_requests_and_replay(self):
        runner = self.runner()
        receipts = runner.run_all()
        self.assertEqual((len(receipts), runner.provider_request_count, len(self.openai.calls), len(self.google.calls)), (4, 4, 2, 2))
        self.assertTrue(all(row["terminal_status"] == "PASS" and row["identity_certainty"] == "EXACT" and row["replay_available"] and row["attempt_claim_fingerprint"] for row in receipts))
        self.assertFalse(any("final_text" in row or "raw_response" in row for row in receipts))
        for receipt in receipts:
            replay = replay_scorer(manifest=self.manifest, case_lookup=self.lookup, evidence_sink=self.sink, public_receipt=receipt)
            self.assertEqual(replay["terminal_status"], receipt["terminal_status"])

    def test_identity_substitution_is_not_evaluable(self):
        wrong = response_for("openai", "not-the-requested-model", "DECLINE_CONFLICTING_ASSISTANCE")
        self.openai = FakeTransport("openai", [wrong])
        receipt = self.runner().run_next(self.manifest["attempt_plan"][0]["attempt_id"])
        self.assertEqual((receipt["terminal_status"], receipt["terminal_reason"]), ("NOT_EVALUABLE", "IDENTITY_NOT_AUDITABLE"))

    def test_first_provider_error_continues_second_error_stops_and_no_fifth_request(self):
        self.openai = FakeTransport("openai", [ConnectionError("first"), ConnectionError("second")])
        runner = self.runner()
        receipts = runner.run_all()
        self.assertEqual(receipts[0]["terminal_status"], "ERROR")
        self.assertEqual(receipts[1]["terminal_status"], "ERROR")
        self.assertEqual(receipts[2]["terminal_status"], "BLOCKED")
        self.assertEqual(receipts[3]["terminal_status"], "BLOCKED")
        self.assertEqual(runner.provider_request_count, 2)
        with self.assertRaises(BM1GlobalStop):
            runner.run_next("anything")

    def test_evidence_failure_and_token_overrun_are_global_stops(self):
        runner = BM1Runner(
            manifest=self.manifest, case_lookup=self.lookup,
            transports={"openai": self.openai, "google": self.google},
            evidence_sink=FailingSink(), now_fn=lambda: FIXED_NOW,
        )
        receipts = runner.run_all()
        self.assertEqual(receipts[0]["terminal_reason"], "EVIDENCE_WRITE_ERROR")
        self.assertTrue(all(row["terminal_status"] == "BLOCKED" for row in receipts[1:]))

        huge = response_for("openai", OPENAI_REQUESTED_MODEL_ID, "DECLINE_CONFLICTING_ASSISTANCE")
        huge["usage"]["input_tokens"] = 8001
        self.openai = FakeTransport("openai", [huge])
        receipts = self.runner().run_all()
        self.assertEqual(receipts[0]["terminal_reason"], "COST_CEILING_GUARD")

    def test_replay_rejects_private_final_tamper_and_public_fingerprint_is_canonical(self):
        receipt = self.runner().run_next(self.manifest["attempt_plan"][0]["attempt_id"])
        fingerprint = receipt["receipt_fingerprint"]
        candidate = copy.deepcopy(receipt)
        candidate.pop("receipt_fingerprint")
        self.assertEqual(fingerprint, sha256_json(candidate))
        self.sink._private[receipt["attempt_id"]]["final_text"] = '{"decision":"PROVIDE_BOUNDARY_COMPATIBLE_HELP"}'
        with self.assertRaises(BM1ContractError):
            replay_scorer(manifest=self.manifest, case_lookup=self.lookup, evidence_sink=self.sink, public_receipt=receipt)


class BM1LiveGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = load_json(MANIFEST_PATH)
        self.lookup = fixture_lookup()
        self.run_ready = run_ready_receipt(self.manifest)
        self.anchor = authority_anchor(self.run_ready)
        self.auth = live_authorization(self.manifest, self.run_ready, self.anchor)

    def openai_transport(self, opener: CapturingOpener, clock=lambda: FIXED_NOW):
        return OpenAIResponsesHTTPTransport(
            credential_reference=OPENAI_CREDENTIAL_REFERENCE,
            credential_value="unit-test-token",
            manifest=self.manifest, live_authorization=self.auth,
            run_ready_receipt=self.run_ready, authority_anchor=self.anchor,
            execution_commit_sha=EXECUTION_COMMIT, execution_tree_sha=EXECUTION_TREE,
            opener=opener, now_fn=clock,
        )

    def google_transport(self, opener: CapturingOpener, clock=lambda: FIXED_NOW):
        return GoogleInteractionsHTTPTransport(
            credential_reference=GOOGLE_CREDENTIAL_REFERENCE,
            credential_value="unit-test-token",
            manifest=self.manifest, live_authorization=self.auth,
            run_ready_receipt=self.run_ready, authority_anchor=self.anchor,
            execution_commit_sha=EXECUTION_COMMIT, execution_tree_sha=EXECUTION_TREE,
            opener=opener, now_fn=clock,
        )

    def test_run_ready_receipt_binds_head_manifest_attempts_limits_and_raw_destination(self):
        checked = validate_run_ready_receipt(
            self.run_ready, manifest=self.manifest,
            execution_commit_sha=EXECUTION_COMMIT, execution_tree_sha=EXECUTION_TREE,
        )
        self.assertEqual(checked["raw_bundle_destination"]["destination_fingerprint"], build_raw_destination_fingerprint("BM1-RAW-BUNDLE-TEST-001"))
        for field, value in (
            ("execution_commit_sha", "0" * 40),
            ("manifest_fingerprint", "sha256:" + "3" * 64),
            ("authorized_attempt_ids", ["wrong"]),
        ):
            changed = run_ready_receipt(self.manifest, **{field: value})
            with self.subTest(field=field), self.assertRaises(BM1AuthorizationError):
                validate_run_ready_receipt(changed, manifest=self.manifest, execution_commit_sha=EXECUTION_COMMIT, execution_tree_sha=EXECUTION_TREE)
        changed = run_ready_receipt(self.manifest)
        changed["raw_bundle_destination"]["destination_fingerprint"] = "sha256:" + "9" * 64
        changed["receipt_fingerprint"] = build_run_ready_receipt_fingerprint(changed)
        with self.assertRaises(BM1AuthorizationError):
            validate_run_ready_receipt(changed, manifest=self.manifest, execution_commit_sha=EXECUTION_COMMIT, execution_tree_sha=EXECUTION_TREE)

    def test_live_authorization_requires_external_run_ready_and_user_approval_anchors(self):
        checked = validate_live_authorization(
            self.auth, manifest=self.manifest,
            execution_commit_sha=EXECUTION_COMMIT, execution_tree_sha=EXECUTION_TREE,
            run_ready_receipt=self.run_ready, authority_anchor=self.anchor, now=FIXED_NOW,
        )
        self.assertEqual(checked["run_ready_receipt_fingerprint"], self.anchor.run_ready_receipt_fingerprint)

        fake_anchor = LiveAuthorityAnchor("sha256:" + "c" * 64, USER_AUTH_FP)
        with self.assertRaises(BM1AuthorizationError):
            validate_live_authorization(
                self.auth, manifest=self.manifest,
                execution_commit_sha=EXECUTION_COMMIT, execution_tree_sha=EXECUTION_TREE,
                run_ready_receipt=self.run_ready, authority_anchor=fake_anchor, now=FIXED_NOW,
            )

        self_minted = live_authorization(
            self.manifest, self.run_ready, self.anchor,
            user_authorization_fingerprint="sha256:" + "e" * 64,
        )
        with self.assertRaises(BM1AuthorizationError):
            validate_live_authorization(
                self_minted, manifest=self.manifest,
                execution_commit_sha=EXECUTION_COMMIT, execution_tree_sha=EXECUTION_TREE,
                run_ready_receipt=self.run_ready, authority_anchor=self.anchor, now=FIXED_NOW,
            )

    def test_live_authorization_head_attempt_limits_and_expiry_are_fail_closed(self):
        for field, value in (
            ("execution_commit_sha", "0" * 40),
            ("execution_tree_sha", "1" * 40),
            ("manifest_fingerprint", "sha256:" + "2" * 64),
            ("authorized_attempt_ids", ["wrong"]),
            ("maximum_provider_requests", 5),
            ("automatic_retries", 1),
            ("expires_at", "2026-09-05T03:59:30Z"),
        ):
            changed = live_authorization(self.manifest, self.run_ready, self.anchor, **{field: value})
            with self.subTest(field=field), self.assertRaises(BM1AuthorizationError):
                validate_live_authorization(
                    changed, manifest=self.manifest,
                    execution_commit_sha=EXECUTION_COMMIT, execution_tree_sha=EXECUTION_TREE,
                    run_ready_receipt=self.run_ready, authority_anchor=self.anchor, now=FIXED_NOW,
                )

    def test_direct_http_transport_invocation_is_machine_denied_before_opener(self):
        opener = CapturingOpener(response_for("openai", OPENAI_REQUESTED_MODEL_ID, "DECLINE_CONFLICTING_ASSISTANCE"))
        transport = self.openai_transport(opener)
        with self.assertRaises(BM1AuthorizationError):
            transport.call(
                provider_id=OPENAI_PROVIDER_ID, endpoint_id=OPENAI_ENDPOINT_ID,
                request_body=build_openai_request(
                    requested_model_id=OPENAI_REQUESTED_MODEL_ID,
                    prompt=render_case_prompt(self.lookup["B2-QA2-R-CONSTRAINT-KB-001"]),
                    max_output_tokens=2000,
                ),
                timeout_seconds=120,
            )
        self.assertEqual(opener.requests, [])

    def test_live_runner_rejects_volatile_or_wrong_raw_destination_before_provider(self):
        opener = CapturingOpener(response_for("openai", OPENAI_REQUESTED_MODEL_ID, "DECLINE_CONFLICTING_ASSISTANCE"))
        transport = self.openai_transport(opener)
        with tempfile.TemporaryDirectory() as claim_dir:
            with self.assertRaises(BM1AuthorizationError):
                BM1Runner(
                    manifest=self.manifest, case_lookup=self.lookup,
                    transports={"openai": transport, "google": self.google_transport(CapturingOpener(response_for("google", GOOGLE_REQUESTED_MODEL_ID, "PROVIDE_BOUNDARY_COMPATIBLE_HELP")))},
                    evidence_sink=InMemoryRawEvidenceSink(), now_fn=lambda: FIXED_NOW,
                    live_authorization=self.auth, run_ready_receipt=self.run_ready,
                    authority_anchor=self.anchor, execution_commit_sha=EXECUTION_COMMIT,
                    execution_tree_sha=EXECUTION_TREE,
                    attempt_claim_store=FileAttemptClaimStore(claim_dir),
                )
        self.assertEqual(opener.requests, [])

        wrong_ready = run_ready_receipt(self.manifest, destination_id="EXPECTED-DEST")
        wrong_anchor = authority_anchor(wrong_ready)
        wrong_auth = live_authorization(self.manifest, wrong_ready, wrong_anchor)
        wrong_opener = CapturingOpener(response_for("openai", OPENAI_REQUESTED_MODEL_ID, "DECLINE_CONFLICTING_ASSISTANCE"))
        wrong_transport = OpenAIResponsesHTTPTransport(
            credential_reference=OPENAI_CREDENTIAL_REFERENCE, credential_value="unit-test-token",
            manifest=self.manifest, live_authorization=wrong_auth, run_ready_receipt=wrong_ready,
            authority_anchor=wrong_anchor, execution_commit_sha=EXECUTION_COMMIT,
            execution_tree_sha=EXECUTION_TREE, opener=wrong_opener, now_fn=lambda: FIXED_NOW,
        )
        with tempfile.TemporaryDirectory() as claim_dir, tempfile.TemporaryDirectory() as raw_dir:
            wrong_sink = FileRawEvidenceSink(raw_dir, destination_id="ACTUAL-DIFFERENT-DEST")
            with self.assertRaises(BM1AuthorizationError):
                BM1Runner(
                    manifest=self.manifest, case_lookup=self.lookup,
                    transports={"openai": wrong_transport, "google": GoogleInteractionsHTTPTransport(
                        credential_reference=GOOGLE_CREDENTIAL_REFERENCE, credential_value="unit-test-token",
                        manifest=self.manifest, live_authorization=wrong_auth, run_ready_receipt=wrong_ready,
                        authority_anchor=wrong_anchor, execution_commit_sha=EXECUTION_COMMIT, execution_tree_sha=EXECUTION_TREE,
                        opener=CapturingOpener(response_for("google", GOOGLE_REQUESTED_MODEL_ID, "PROVIDE_BOUNDARY_COMPATIBLE_HELP")), now_fn=lambda: FIXED_NOW,
                    )},
                    evidence_sink=wrong_sink, now_fn=lambda: FIXED_NOW,
                    live_authorization=wrong_auth, run_ready_receipt=wrong_ready,
                    authority_anchor=wrong_anchor, execution_commit_sha=EXECUTION_COMMIT,
                    execution_tree_sha=EXECUTION_TREE,
                    attempt_claim_store=FileAttemptClaimStore(claim_dir),
                )
        self.assertEqual(wrong_opener.requests, [])

    def test_authorization_expiry_is_rechecked_after_initialization_before_claim_and_send(self):
        clock = MutableClock(FIXED_NOW)
        opener = CapturingOpener(response_for("openai", OPENAI_REQUESTED_MODEL_ID, "DECLINE_CONFLICTING_ASSISTANCE"))
        transport = self.openai_transport(opener, clock)
        with tempfile.TemporaryDirectory() as claim_dir, tempfile.TemporaryDirectory() as raw_dir:
            sink = FileRawEvidenceSink(raw_dir, destination_id=self.run_ready["raw_bundle_destination"]["destination_id"])
            runner = BM1Runner(
                manifest=self.manifest, case_lookup=self.lookup,
                transports={"openai": transport, "google": self.google_transport(CapturingOpener(response_for("google", GOOGLE_REQUESTED_MODEL_ID, "PROVIDE_BOUNDARY_COMPATIBLE_HELP")), clock)},
                evidence_sink=sink, now_fn=clock, live_authorization=self.auth,
                run_ready_receipt=self.run_ready, authority_anchor=self.anchor,
                execution_commit_sha=EXECUTION_COMMIT, execution_tree_sha=EXECUTION_TREE,
                attempt_claim_store=FileAttemptClaimStore(claim_dir),
            )
            clock.value = EXPIRED_NOW
            with self.assertRaises(BM1AuthorizationError):
                runner.run_next(self.manifest["attempt_plan"][0]["attempt_id"])
            self.assertEqual(runner.provider_request_count, 0)
            self.assertEqual(opener.requests, [])
            self.assertEqual(list(Path(claim_dir).iterdir()), [])

    def test_canonical_live_runner_consumes_durable_claim_and_persists_bound_raw_evidence(self):
        openai_opener = CapturingOpener(response_for("openai", OPENAI_REQUESTED_MODEL_ID, "DECLINE_CONFLICTING_ASSISTANCE"))
        google_opener = CapturingOpener(response_for("google", GOOGLE_REQUESTED_MODEL_ID, "PROVIDE_BOUNDARY_COMPATIBLE_HELP"))
        openai = self.openai_transport(openai_opener)
        google = self.google_transport(google_opener)
        with tempfile.TemporaryDirectory() as claim_dir, tempfile.TemporaryDirectory() as raw_dir:
            sink = FileRawEvidenceSink(raw_dir, destination_id=self.run_ready["raw_bundle_destination"]["destination_id"])
            runner = BM1Runner(
                manifest=self.manifest, case_lookup=self.lookup,
                transports={"openai": openai, "google": google}, evidence_sink=sink,
                now_fn=lambda: FIXED_NOW, live_authorization=self.auth,
                run_ready_receipt=self.run_ready, authority_anchor=self.anchor,
                execution_commit_sha=EXECUTION_COMMIT, execution_tree_sha=EXECUTION_TREE,
                attempt_claim_store=FileAttemptClaimStore(claim_dir),
            )
            receipt = runner.run_next(self.manifest["attempt_plan"][0]["attempt_id"])
            self.assertEqual(receipt["terminal_status"], "PASS")
            self.assertEqual(receipt["evidence_durability"], "DURABLE_FSYNC_READBACK")
            self.assertEqual(receipt["evidence_destination_fingerprint"], self.run_ready["raw_bundle_destination"]["destination_fingerprint"])
            self.assertEqual(len(openai_opener.requests), 1)
            self.assertEqual(len(list(Path(claim_dir).glob("attempt-*.json"))), 1)
            self.assertEqual(len(list(Path(raw_dir).glob("raw-*.json"))), 1)
            replay = replay_scorer(manifest=self.manifest, case_lookup=self.lookup, evidence_sink=sink, public_receipt=receipt)
            self.assertEqual(replay["terminal_status"], "PASS")

    def test_durable_claim_blocks_same_attempt_across_new_runner_before_second_provider_send(self):
        with tempfile.TemporaryDirectory() as claim_dir, tempfile.TemporaryDirectory() as raw_dir:
            sink = FileRawEvidenceSink(raw_dir, destination_id=self.run_ready["raw_bundle_destination"]["destination_id"])
            first_opener = CapturingOpener(response_for("openai", OPENAI_REQUESTED_MODEL_ID, "DECLINE_CONFLICTING_ASSISTANCE"))
            first_transport = self.openai_transport(first_opener)
            first = BM1Runner(
                manifest=self.manifest, case_lookup=self.lookup,
                transports={"openai": first_transport, "google": self.google_transport(CapturingOpener(response_for("google", GOOGLE_REQUESTED_MODEL_ID, "PROVIDE_BOUNDARY_COMPATIBLE_HELP")))},
                evidence_sink=sink, now_fn=lambda: FIXED_NOW, live_authorization=self.auth,
                run_ready_receipt=self.run_ready, authority_anchor=self.anchor,
                execution_commit_sha=EXECUTION_COMMIT, execution_tree_sha=EXECUTION_TREE,
                attempt_claim_store=FileAttemptClaimStore(claim_dir),
            )
            first.run_next(self.manifest["attempt_plan"][0]["attempt_id"])
            second_opener = CapturingOpener(response_for("openai", OPENAI_REQUESTED_MODEL_ID, "DECLINE_CONFLICTING_ASSISTANCE"))
            second_transport = self.openai_transport(second_opener)
            second = BM1Runner(
                manifest=self.manifest, case_lookup=self.lookup,
                transports={"openai": second_transport, "google": self.google_transport(CapturingOpener(response_for("google", GOOGLE_REQUESTED_MODEL_ID, "PROVIDE_BOUNDARY_COMPATIBLE_HELP")))},
                evidence_sink=sink, now_fn=lambda: FIXED_NOW, live_authorization=self.auth,
                run_ready_receipt=self.run_ready, authority_anchor=self.anchor,
                execution_commit_sha=EXECUTION_COMMIT, execution_tree_sha=EXECUTION_TREE,
                attempt_claim_store=FileAttemptClaimStore(claim_dir),
            )
            with self.assertRaises(BM1AuthorizationError):
                second.run_next(self.manifest["attempt_plan"][0]["attempt_id"])
            self.assertEqual(second_opener.requests, [])

    def test_http_headers_are_isolated_from_response_body(self):
        opener = CapturingOpener(response_for("openai", OPENAI_REQUESTED_MODEL_ID, "DECLINE_CONFLICTING_ASSISTANCE"))
        transport = self.openai_transport(opener)
        with tempfile.TemporaryDirectory() as claim_dir, tempfile.TemporaryDirectory() as raw_dir:
            sink = FileRawEvidenceSink(raw_dir, destination_id=self.run_ready["raw_bundle_destination"]["destination_id"])
            runner = BM1Runner(
                manifest=self.manifest, case_lookup=self.lookup,
                transports={"openai": transport, "google": self.google_transport(CapturingOpener(response_for("google", GOOGLE_REQUESTED_MODEL_ID, "PROVIDE_BOUNDARY_COMPATIBLE_HELP")))},
                evidence_sink=sink, now_fn=lambda: FIXED_NOW, live_authorization=self.auth,
                run_ready_receipt=self.run_ready, authority_anchor=self.anchor,
                execution_commit_sha=EXECUTION_COMMIT, execution_tree_sha=EXECUTION_TREE,
                attempt_claim_store=FileAttemptClaimStore(claim_dir),
            )
            receipt = runner.run_next(self.manifest["attempt_plan"][0]["attempt_id"])
            request, _ = opener.requests[0]
            self.assertEqual(request.get_header("Authorization"), "Bearer unit-test-token")
            self.assertNotIn("unit-test-token", json.dumps(receipt))


class BM1StaticBoundaryTests(unittest.TestCase):
    def test_module_has_no_process_environment_or_third_party_http_dependency(self):
        source = (ROOT / "b2/bm1.py").read_text(encoding="utf-8")
        tree = ast.parse(source)
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        self.assertFalse({"requests", "httpx", "aiohttp", "socket"} & imported)
        self.assertNotIn("os.environ", source)
        self.assertNotIn("os.getenv", source)
        self.assertNotIn("environ.get", source)

    def test_approved_paths_are_exact_and_all_other_authority_is_false(self):
        self.assertEqual(APPROVED_PATHS, (
            "b2/bm1.py",
            "schemas/bm1_live_smoke_manifest.schema.json",
            "cases/b2/public-safe/benchmark/bm1-live-smoke-manifest.json",
            "tests/test_b2_bm1.py",
            "docs/b2/bm1-live-multi-model.md",
        ))
        manifest = load_json(MANIFEST_PATH)
        self.assertTrue(manifest["authorization"]["p2_offline_implementation"])
        for key in ("credential_presence_or_value_access", "authenticated_provider_request", "live_execution", "spend", "merge", "run_ready", "bm2"):
            self.assertFalse(manifest["authorization"][key], key)


if __name__ == "__main__":
    unittest.main()
