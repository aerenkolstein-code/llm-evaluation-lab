from __future__ import annotations

import ast
import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import b2.bm1 as bm1_mod
from b2.bm1 import (
    APPROVED_PATHS,
    AUTOMATIC_RETRIES,
    BM1AuthorizationError,
    BM1ContractError,
    BM1GlobalStop,
    BM1Runner,
    CLAIM_STORE_STORAGE_KIND,
    CONTROL_CASE_ID,
    FileAttemptClaimStore,
    FileRawEvidenceSink,
    GOOGLE_CREDENTIAL_REFERENCE,
    GOOGLE_PROVIDER_ID,
    GOOGLE_REQUESTED_MODEL_ID,
    GoogleInteractionsHTTPTransport,
    InMemoryRawEvidenceSink,
    LIVE_ATTEMPT_CLAIM_POLICY,
    LIVE_AUTH_SCHEMA_VERSION,
    MAX_PLANNED_ATTEMPTS,
    MAX_TOTAL_SMOKE_SPEND_USD,
    OPENAI_CREDENTIAL_REFERENCE,
    OPENAI_PROVIDER_ID,
    OPENAI_REQUESTED_MODEL_ID,
    OpenAIResponsesHTTPTransport,
    RAW_BUNDLE_STORAGE_KIND,
    RUN_READY_SCHEMA_VERSION,
    build_claim_store_fingerprint,
    build_google_request,
    build_live_authorization_fingerprint,
    build_openai_request,
    build_raw_destination_fingerprint,
    build_run_ready_receipt_fingerprint,
    build_storage_authority_fingerprint,
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
AUTHORIZATION_ID = "BM1-LIVE-AUTH-TEST-001"
RAW_DEST_ID = "BM1-RAW-BUNDLE-TEST-001"
CLAIM_STORE_ID = "BM1-CLAIM-STORE-TEST-001"


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


def run_ready_receipt(
    manifest: dict, *, raw_dir: str | Path, claim_dir: str | Path,
    destination_id: str = RAW_DEST_ID, store_id: str = CLAIM_STORE_ID,
    **overrides: object,
) -> dict:
    raw_binding = {
        "destination_id": destination_id,
        "storage_kind": RAW_BUNDLE_STORAGE_KIND,
        "label_fingerprint": build_raw_destination_fingerprint(destination_id),
        "storage_authority_fingerprint": build_storage_authority_fingerprint(
            raw_dir, storage_kind=RAW_BUNDLE_STORAGE_KIND,
        ),
    }
    claim_binding = {
        "store_id": store_id,
        "storage_kind": CLAIM_STORE_STORAGE_KIND,
        "label_fingerprint": build_claim_store_fingerprint(store_id),
        "storage_authority_fingerprint": build_storage_authority_fingerprint(
            claim_dir, storage_kind=CLAIM_STORE_STORAGE_KIND,
        ),
    }
    document = {
        "schema_version": RUN_READY_SCHEMA_VERSION,
        "run_ready_id": "BM1-RUN-READY-TEST-001",
        "manifest_fingerprint": manifest["manifest_fingerprint"],
        "execution_commit_sha": EXECUTION_COMMIT,
        "execution_tree_sha": EXECUTION_TREE,
        "provider_authority_fingerprint": "sha256:" + "1" * 64,
        "credential_decision_fingerprint": "sha256:" + "2" * 64,
        "raw_bundle_destination": raw_binding,
        "attempt_claim_store": claim_binding,
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


def live_authorization(
    manifest: dict, run_ready: dict, *, user_fp: str = USER_AUTH_FP,
    authorization_id: str = AUTHORIZATION_ID, **overrides: object,
) -> dict:
    raw_binding = run_ready["raw_bundle_destination"]
    claim_binding = run_ready["attempt_claim_store"]
    document = {
        "schema_version": LIVE_AUTH_SCHEMA_VERSION,
        "authorization_id": authorization_id,
        "manifest_fingerprint": manifest["manifest_fingerprint"],
        "execution_commit_sha": EXECUTION_COMMIT,
        "execution_tree_sha": EXECUTION_TREE,
        "run_ready_receipt_fingerprint": run_ready["receipt_fingerprint"],
        "user_authorization_fingerprint": user_fp,
        "raw_bundle_destination_fingerprint": raw_binding["label_fingerprint"],
        "raw_storage_authority_fingerprint": raw_binding["storage_authority_fingerprint"],
        "attempt_claim_store_fingerprint": claim_binding["label_fingerprint"],
        "claim_storage_authority_fingerprint": claim_binding["storage_authority_fingerprint"],
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


class FixedAuthorityVerifier:
    """Test double for an independently provisioned outer-runtime Authority."""

    def __init__(self, run_ready_fp: str, user_fp: str, authorization_id: str) -> None:
        self.expected = (run_ready_fp, user_fp, authorization_id)
        self.calls: list[tuple[str, str, str]] = []

    def verify(
        self, *, run_ready_receipt_fingerprint: str,
        user_authorization_fingerprint: str, authorization_id: str,
    ) -> bool:
        observed = (
            run_ready_receipt_fingerprint,
            user_authorization_fingerprint,
            authorization_id,
        )
        self.calls.append(observed)
        return observed == self.expected


class RejectAllVerifier:
    def verify(self, **kwargs) -> bool:
        return False


def response_for(provider_id: str, model_id: str, decision: str, serial: int = 1) -> dict:
    final = json.dumps({"decision": decision}, separators=(",", ":"))
    if provider_id == OPENAI_PROVIDER_ID:
        return {
            "_http_status": 200, "id": f"resp-{serial}", "model": model_id,
            "status": "completed",
            "output": [{"type": "message", "content": [{"type": "output_text", "text": final}]}],
            "usage": {"input_tokens": 100, "output_tokens": 10},
        }
    return {
        "_http_status": 200, "id": f"interaction-{serial}", "model": model_id,
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
            "provider_id": provider_id, "endpoint_id": endpoint_id,
            "request_body": copy.deepcopy(request_body), "timeout_seconds": timeout_seconds,
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

    def test_manifest_fingerprint_case_model_order_and_sixth_path_tamper_rejected(self):
        changed = copy.deepcopy(self.manifest)
        changed["runtime_contract"]["timeout_seconds"] = 121
        with self.assertRaises(BM1ContractError):
            validate_manifest(changed, case_lookup=self.lookup)

        changed = copy.deepcopy(self.manifest)
        changed["case_binding"]["cases"][0]["case_fingerprint"] = "sha256:" + "0" * 64
        changed = refingerprint(changed, "manifest_fingerprint")
        with self.assertRaises(BM1ContractError):
            validate_manifest(changed, case_lookup=self.lookup)

        changed = copy.deepcopy(self.manifest)
        changed["providers"][0]["requested_model_id"] = "gpt-substitute"
        changed["providers"][0]["identity_policy"]["accepted_resolved_model_ids"] = ["gpt-substitute"]
        changed["attempt_plan"][0]["requested_model_id"] = "gpt-substitute"
        changed["attempt_plan"][1]["requested_model_id"] = "gpt-substitute"
        changed = refingerprint(changed, "manifest_fingerprint")
        with self.assertRaises(BM1ContractError):
            validate_manifest(changed, case_lookup=self.lookup)

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

    def test_e11_prompt_provider_controls_and_symbolic_credentials_are_frozen(self):
        target = self.lookup["B2-QA2-R-CONSTRAINT-KB-001"]
        control = self.lookup[CONTROL_CASE_ID]
        self.assertEqual(expected_decision_for_case(target), "DECLINE_CONFLICTING_ASSISTANCE")
        self.assertEqual(expected_decision_for_case(control), "PROVIDE_BOUNDARY_COMPATIBLE_HELP")
        prompt = render_case_prompt(target)
        openai = build_openai_request(requested_model_id=OPENAI_REQUESTED_MODEL_ID, prompt=prompt, max_output_tokens=2000)
        google = build_google_request(requested_model_id=GOOGLE_REQUESTED_MODEL_ID, prompt=prompt, max_output_tokens=2000)
        self.assertEqual(openai["reasoning"], {"effort": "low"})
        self.assertNotIn("temperature", openai)
        self.assertEqual(google["generation_config"]["thinking_level"], "low")
        for key in ("temperature", "top_p", "top_k"):
            self.assertNotIn(key, google["generation_config"])
        self.assertEqual(validate_symbolic_credential_presence(OPENAI_PROVIDER_ID, [OPENAI_CREDENTIAL_REFERENCE]), OPENAI_CREDENTIAL_REFERENCE)
        self.assertEqual(validate_symbolic_credential_presence(GOOGLE_PROVIDER_ID, [GOOGLE_CREDENTIAL_REFERENCE]), GOOGLE_CREDENTIAL_REFERENCE)
        with self.assertRaises(BM1AuthorizationError):
            validate_symbolic_credential_presence(GOOGLE_PROVIDER_ID, ["GEMINI_API_KEY", "GOOGLE_API_KEY"])

    def test_response_normalizers_capture_identity_and_usage(self):
        openai = normalize_openai_response(response_for("openai", OPENAI_REQUESTED_MODEL_ID, "DECLINE_CONFLICTING_ASSISTANCE"))
        google = normalize_google_response(response_for("google", GOOGLE_REQUESTED_MODEL_ID, "PROVIDE_BOUNDARY_COMPATIBLE_HELP"))
        self.assertEqual((openai.provider_terminal_status, openai.resolved_model_id, openai.input_tokens), ("SUCCESS", OPENAI_REQUESTED_MODEL_ID, 100))
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

    def test_identity_substitution_first_second_error_and_no_fifth_request(self):
        wrong = response_for("openai", "not-the-requested-model", "DECLINE_CONFLICTING_ASSISTANCE")
        self.openai = FakeTransport("openai", [wrong])
        receipt = self.runner().run_next(self.manifest["attempt_plan"][0]["attempt_id"])
        self.assertEqual((receipt["terminal_status"], receipt["terminal_reason"]), ("NOT_EVALUABLE", "IDENTITY_NOT_AUDITABLE"))

        self.openai = FakeTransport("openai", [ConnectionError("first"), ConnectionError("second")])
        runner = self.runner()
        receipts = runner.run_all()
        self.assertEqual([row["terminal_status"] for row in receipts], ["ERROR", "ERROR", "BLOCKED", "BLOCKED"])
        self.assertEqual(runner.provider_request_count, 2)
        with self.assertRaises(BM1GlobalStop):
            runner.run_next("anything")

    def test_evidence_failure_token_overrun_replay_tamper_and_public_fingerprint(self):
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
        self.assertEqual(self.runner().run_all()[0]["terminal_reason"], "COST_CEILING_GUARD")

        self.openai = FakeTransport("openai")
        receipt = self.runner().run_next(self.manifest["attempt_plan"][0]["attempt_id"])
        candidate = copy.deepcopy(receipt)
        fingerprint = candidate.pop("receipt_fingerprint")
        self.assertEqual(fingerprint, sha256_json(candidate))
        self.sink._private[receipt["attempt_id"]]["final_text"] = '{"decision":"PROVIDE_BOUNDARY_COMPATIBLE_HELP"}'
        with self.assertRaises(BM1ContractError):
            replay_scorer(manifest=self.manifest, case_lookup=self.lookup, evidence_sink=self.sink, public_receipt=receipt)


class BM1LiveGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self.manifest = load_json(MANIFEST_PATH)
        self.lookup = fixture_lookup()
        self.raw_temp = tempfile.TemporaryDirectory()
        self.claim_temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.raw_temp.cleanup)
        self.addCleanup(self.claim_temp.cleanup)
        self.raw_dir = self.raw_temp.name
        self.claim_dir = self.claim_temp.name
        self.run_ready = run_ready_receipt(
            self.manifest, raw_dir=self.raw_dir, claim_dir=self.claim_dir,
        )
        self.verifier = FixedAuthorityVerifier(
            self.run_ready["receipt_fingerprint"], USER_AUTH_FP, AUTHORIZATION_ID,
        )
        self.auth = live_authorization(self.manifest, self.run_ready)

    def raw_sink(self, directory: str | Path | None = None) -> FileRawEvidenceSink:
        return FileRawEvidenceSink(
            directory or self.raw_dir,
            destination_id=self.run_ready["raw_bundle_destination"]["destination_id"],
        )

    def claim_store(self, directory: str | Path | None = None) -> FileAttemptClaimStore:
        return FileAttemptClaimStore(
            directory or self.claim_dir,
            store_id=self.run_ready["attempt_claim_store"]["store_id"],
        )

    def openai_transport(self, opener: CapturingOpener, clock=lambda: FIXED_NOW, verifier=None):
        return OpenAIResponsesHTTPTransport(
            credential_reference=OPENAI_CREDENTIAL_REFERENCE, credential_value="unit-test-token",
            manifest=self.manifest, live_authorization=self.auth,
            run_ready_receipt=self.run_ready,
            authority_verifier=verifier or self.verifier,
            execution_commit_sha=EXECUTION_COMMIT, execution_tree_sha=EXECUTION_TREE,
            opener=opener, now_fn=clock,
        )

    def google_transport(self, opener: CapturingOpener, clock=lambda: FIXED_NOW, verifier=None):
        return GoogleInteractionsHTTPTransport(
            credential_reference=GOOGLE_CREDENTIAL_REFERENCE, credential_value="unit-test-token",
            manifest=self.manifest, live_authorization=self.auth,
            run_ready_receipt=self.run_ready,
            authority_verifier=verifier or self.verifier,
            execution_commit_sha=EXECUTION_COMMIT, execution_tree_sha=EXECUTION_TREE,
            opener=opener, now_fn=clock,
        )

    def runner(self, openai_opener: CapturingOpener, google_opener: CapturingOpener, *, clock=lambda: FIXED_NOW, sink=None, claim_store=None, verifier=None) -> BM1Runner:
        verifier = verifier or self.verifier
        return BM1Runner(
            manifest=self.manifest, case_lookup=self.lookup,
            transports={
                "openai": self.openai_transport(openai_opener, clock, verifier),
                "google": self.google_transport(google_opener, clock, verifier),
            },
            evidence_sink=sink or self.raw_sink(), now_fn=clock,
            live_authorization=self.auth, run_ready_receipt=self.run_ready,
            authority_verifier=verifier,
            execution_commit_sha=EXECUTION_COMMIT, execution_tree_sha=EXECUTION_TREE,
            attempt_claim_store=claim_store or self.claim_store(),
        )

    def test_run_ready_binds_exact_raw_and_claim_storage_authority(self):
        checked = validate_run_ready_receipt(
            self.run_ready, manifest=self.manifest,
            execution_commit_sha=EXECUTION_COMMIT, execution_tree_sha=EXECUTION_TREE,
        )
        self.assertEqual(checked["raw_bundle_destination"]["storage_authority_fingerprint"], build_storage_authority_fingerprint(self.raw_dir, storage_kind=RAW_BUNDLE_STORAGE_KIND))
        self.assertEqual(checked["attempt_claim_store"]["storage_authority_fingerprint"], build_storage_authority_fingerprint(self.claim_dir, storage_kind=CLAIM_STORE_STORAGE_KIND))
        changed = copy.deepcopy(self.run_ready)
        changed["attempt_claim_store"]["storage_authority_fingerprint"] = "sha256:" + "9" * 64
        changed["receipt_fingerprint"] = build_run_ready_receipt_fingerprint(changed)
        # Structurally valid but no longer matches an actual RUN-READY object trusted by our verifier.
        self.assertNotEqual(changed["receipt_fingerprint"], self.run_ready["receipt_fingerprint"])

    def test_external_verifier_rejects_fully_self_consistent_self_minted_triplet(self):
        with tempfile.TemporaryDirectory() as raw2, tempfile.TemporaryDirectory() as claim2:
            minted_rr = run_ready_receipt(self.manifest, raw_dir=raw2, claim_dir=claim2, destination_id="MINTED-RAW", store_id="MINTED-CLAIMS")
            minted_auth = live_authorization(self.manifest, minted_rr, user_fp="sha256:" + "e" * 64, authorization_id="MINTED-AUTH")
            with self.assertRaises(BM1AuthorizationError):
                validate_live_authorization(
                    minted_auth, manifest=self.manifest,
                    execution_commit_sha=EXECUTION_COMMIT, execution_tree_sha=EXECUTION_TREE,
                    run_ready_receipt=minted_rr, authority_verifier=self.verifier, now=FIXED_NOW,
                )
            with self.assertRaises(BM1AuthorizationError):
                OpenAIResponsesHTTPTransport(
                    credential_reference=OPENAI_CREDENTIAL_REFERENCE,
                    credential_value="unit-test-token", manifest=self.manifest,
                    live_authorization=minted_auth, run_ready_receipt=minted_rr,
                    authority_verifier=self.verifier,
                    execution_commit_sha=EXECUTION_COMMIT, execution_tree_sha=EXECUTION_TREE,
                    opener=CapturingOpener(response_for("openai", OPENAI_REQUESTED_MODEL_ID, "DECLINE_CONFLICTING_ASSISTANCE")),
                    now_fn=lambda: FIXED_NOW,
                )

    def test_missing_or_rejecting_external_verifier_fails_closed(self):
        with self.assertRaises(BM1AuthorizationError):
            validate_live_authorization(
                self.auth, manifest=self.manifest,
                execution_commit_sha=EXECUTION_COMMIT, execution_tree_sha=EXECUTION_TREE,
                run_ready_receipt=self.run_ready, authority_verifier=RejectAllVerifier(), now=FIXED_NOW,
            )

    def test_direct_transport_and_forged_prepared_capability_cannot_reach_opener(self):
        openai_opener = CapturingOpener(response_for("openai", OPENAI_REQUESTED_MODEL_ID, "DECLINE_CONFLICTING_ASSISTANCE"))
        google_opener = CapturingOpener(response_for("google", GOOGLE_REQUESTED_MODEL_ID, "PROVIDE_BOUNDARY_COMPATIBLE_HELP"))
        runner = self.runner(openai_opener, google_opener)
        transport = runner.transports["openai"]
        body = build_openai_request(
            requested_model_id=OPENAI_REQUESTED_MODEL_ID,
            prompt=render_case_prompt(self.lookup["B2-QA2-R-CONSTRAINT-KB-001"]),
            max_output_tokens=2000,
        )
        with self.assertRaises(BM1AuthorizationError):
            transport.call(provider_id="openai", endpoint_id="responses-api:/responses", request_body=body, timeout_seconds=120)
        forged = bm1_mod._PreparedLiveCall(
            attempt_id=self.manifest["attempt_plan"][0]["attempt_id"],
            trial_id=self.manifest["attempt_plan"][0]["trial_id"], sequence=1,
            provider_id="openai", endpoint_id="responses-api:/responses",
            requested_model_id=OPENAI_REQUESTED_MODEL_ID,
            case_id=self.manifest["attempt_plan"][0]["case_id"],
            request_fingerprint=sha256_json(body), claim_fingerprint="sha256:" + "f" * 64,
            live_authorization_fingerprint=self.auth["receipt_fingerprint"],
            run_ready_receipt_fingerprint=self.run_ready["receipt_fingerprint"],
            user_authorization_fingerprint=USER_AUTH_FP,
            raw_bundle_destination_fingerprint=self.run_ready["raw_bundle_destination"]["label_fingerprint"],
            raw_storage_authority_fingerprint=self.run_ready["raw_bundle_destination"]["storage_authority_fingerprint"],
            claim_store_fingerprint=self.run_ready["attempt_claim_store"]["label_fingerprint"],
            claim_storage_authority_fingerprint=self.run_ready["attempt_claim_store"]["storage_authority_fingerprint"],
            request_ordinal=1,
        )
        runner.provider_request_count = 1
        with self.assertRaises(BM1AuthorizationError):
            runner._send_live(transport=transport, capability=forged, request_body=body, timeout_seconds=120)
        self.assertEqual(openai_opener.requests, [])
        self.assertEqual(list(Path(self.claim_dir).iterdir()), [])

    def test_registered_capability_binds_exact_request_and_durable_claim(self):
        openai_opener = CapturingOpener(response_for("openai", OPENAI_REQUESTED_MODEL_ID, "DECLINE_CONFLICTING_ASSISTANCE"))
        google_opener = CapturingOpener(response_for("google", GOOGLE_REQUESTED_MODEL_ID, "PROVIDE_BOUNDARY_COMPATIBLE_HELP"))
        runner = self.runner(openai_opener, google_opener)
        attempt = self.manifest["attempt_plan"][0]
        provider = self.manifest["providers"][0]
        body = bm1_mod.build_provider_request(provider, render_case_prompt(self.lookup[attempt["case_id"]]))
        claim, capability = runner._claim_and_prepare(attempt, runner.transports["openai"], body)
        self.assertTrue(runner.attempt_claim_store.verify_claim(claim=claim))
        runner.provider_request_count = 1
        tampered = copy.deepcopy(body)
        tampered["model"] = "tampered"
        with self.assertRaises(BM1AuthorizationError):
            runner._send_live(transport=runner.transports["openai"], capability=capability, request_body=tampered, timeout_seconds=120)
        self.assertEqual(openai_opener.requests, [])
        # The exact registered capability was consumed fail-closed; it cannot be reused.
        with self.assertRaises(BM1AuthorizationError):
            runner._send_live(transport=runner.transports["openai"], capability=capability, request_body=body, timeout_seconds=120)
        self.assertEqual(openai_opener.requests, [])

    def test_wrong_raw_directory_with_correct_label_is_rejected_before_provider(self):
        openai_opener = CapturingOpener(response_for("openai", OPENAI_REQUESTED_MODEL_ID, "DECLINE_CONFLICTING_ASSISTANCE"))
        google_opener = CapturingOpener(response_for("google", GOOGLE_REQUESTED_MODEL_ID, "PROVIDE_BOUNDARY_COMPATIBLE_HELP"))
        with tempfile.TemporaryDirectory() as wrong_raw:
            wrong_sink = FileRawEvidenceSink(wrong_raw, destination_id=RAW_DEST_ID)
            self.assertEqual(wrong_sink.destination_fingerprint, self.run_ready["raw_bundle_destination"]["label_fingerprint"])
            self.assertNotEqual(wrong_sink.storage_authority_fingerprint, self.run_ready["raw_bundle_destination"]["storage_authority_fingerprint"])
            with self.assertRaises(BM1AuthorizationError):
                self.runner(openai_opener, google_opener, sink=wrong_sink)
        self.assertEqual(openai_opener.requests, [])

    def test_fresh_claim_directory_with_correct_label_cannot_replay(self):
        first_openai = CapturingOpener(response_for("openai", OPENAI_REQUESTED_MODEL_ID, "DECLINE_CONFLICTING_ASSISTANCE"))
        first_google = CapturingOpener(response_for("google", GOOGLE_REQUESTED_MODEL_ID, "PROVIDE_BOUNDARY_COMPATIBLE_HELP"))
        first = self.runner(first_openai, first_google)
        first.run_next(self.manifest["attempt_plan"][0]["attempt_id"])
        self.assertEqual(len(first_openai.requests), 1)

        second_openai = CapturingOpener(response_for("openai", OPENAI_REQUESTED_MODEL_ID, "DECLINE_CONFLICTING_ASSISTANCE"))
        second_google = CapturingOpener(response_for("google", GOOGLE_REQUESTED_MODEL_ID, "PROVIDE_BOUNDARY_COMPATIBLE_HELP"))
        with tempfile.TemporaryDirectory() as fresh_claim:
            fresh_store = FileAttemptClaimStore(fresh_claim, store_id=CLAIM_STORE_ID)
            self.assertEqual(fresh_store.store_fingerprint, self.run_ready["attempt_claim_store"]["label_fingerprint"])
            self.assertNotEqual(fresh_store.storage_authority_fingerprint, self.run_ready["attempt_claim_store"]["storage_authority_fingerprint"])
            with self.assertRaises(BM1AuthorizationError):
                self.runner(second_openai, second_google, claim_store=fresh_store)
        self.assertEqual(second_openai.requests, [])

    def test_same_exact_claim_store_blocks_restart_duplicate_before_second_send(self):
        first_openai = CapturingOpener(response_for("openai", OPENAI_REQUESTED_MODEL_ID, "DECLINE_CONFLICTING_ASSISTANCE"))
        first = self.runner(first_openai, CapturingOpener(response_for("google", GOOGLE_REQUESTED_MODEL_ID, "PROVIDE_BOUNDARY_COMPATIBLE_HELP")))
        first.run_next(self.manifest["attempt_plan"][0]["attempt_id"])
        second_openai = CapturingOpener(response_for("openai", OPENAI_REQUESTED_MODEL_ID, "DECLINE_CONFLICTING_ASSISTANCE"))
        second = self.runner(second_openai, CapturingOpener(response_for("google", GOOGLE_REQUESTED_MODEL_ID, "PROVIDE_BOUNDARY_COMPATIBLE_HELP")))
        with self.assertRaises(BM1AuthorizationError):
            second.run_next(self.manifest["attempt_plan"][0]["attempt_id"])
        self.assertEqual(second_openai.requests, [])

    def test_authorization_expiry_rechecked_before_claim_and_network(self):
        clock = MutableClock(FIXED_NOW)
        openai_opener = CapturingOpener(response_for("openai", OPENAI_REQUESTED_MODEL_ID, "DECLINE_CONFLICTING_ASSISTANCE"))
        google_opener = CapturingOpener(response_for("google", GOOGLE_REQUESTED_MODEL_ID, "PROVIDE_BOUNDARY_COMPATIBLE_HELP"))
        runner = self.runner(openai_opener, google_opener, clock=clock)
        clock.value = EXPIRED_NOW
        with self.assertRaises(BM1AuthorizationError):
            runner.run_next(self.manifest["attempt_plan"][0]["attempt_id"])
        self.assertEqual(runner.provider_request_count, 0)
        self.assertEqual(openai_opener.requests, [])
        self.assertEqual(list(Path(self.claim_dir).iterdir()), [])

    def test_canonical_live_runner_persists_storage_bound_evidence_and_header_isolation(self):
        openai_opener = CapturingOpener(response_for("openai", OPENAI_REQUESTED_MODEL_ID, "DECLINE_CONFLICTING_ASSISTANCE"))
        google_opener = CapturingOpener(response_for("google", GOOGLE_REQUESTED_MODEL_ID, "PROVIDE_BOUNDARY_COMPATIBLE_HELP"))
        runner = self.runner(openai_opener, google_opener)
        receipt = runner.run_next(self.manifest["attempt_plan"][0]["attempt_id"])
        self.assertEqual(receipt["terminal_status"], "PASS")
        self.assertEqual(receipt["evidence_durability"], "DURABLE_FSYNC_READBACK")
        self.assertEqual(receipt["evidence_destination_fingerprint"], self.run_ready["raw_bundle_destination"]["label_fingerprint"])
        self.assertEqual(receipt["evidence_storage_authority_fingerprint"], self.run_ready["raw_bundle_destination"]["storage_authority_fingerprint"])
        self.assertEqual(len(openai_opener.requests), 1)
        self.assertEqual(len(list(Path(self.claim_dir).glob("attempt-*.json"))), 1)
        self.assertEqual(len(list(Path(self.raw_dir).glob("raw-*.json"))), 1)
        request, _ = openai_opener.requests[0]
        self.assertEqual(request.get_header("Authorization"), "Bearer unit-test-token")
        self.assertNotIn("unit-test-token", json.dumps(receipt))
        replay = replay_scorer(manifest=self.manifest, case_lookup=self.lookup, evidence_sink=self.raw_sink(), public_receipt=receipt)
        self.assertEqual(replay["terminal_status"], "PASS")


class BM1StaticBoundaryTests(unittest.TestCase):
    def test_module_has_no_process_environment_third_party_http_or_self_mintable_anchor(self):
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
        self.assertNotIn("class LiveAuthorityAnchor", source)
        self.assertNotIn("def _send_prepared", source)

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
