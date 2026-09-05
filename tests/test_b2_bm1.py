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
    APPROVED_PATHS, BM1AuthorizationError, BM1ContractError, BM1GlobalStop, BM1Runner,
    CLAIM_STORE_STORAGE_KIND, CONTROL_CASE_ID, FileAttemptClaimStore, FileRawEvidenceSink,
    GOOGLE_CREDENTIAL_REFERENCE, GOOGLE_PROVIDER_ID, GOOGLE_REQUESTED_MODEL_ID,
    GoogleInteractionsHTTPTransport, InMemoryRawEvidenceSink, LIVE_ATTEMPT_CLAIM_POLICY,
    LIVE_AUTH_SCHEMA_VERSION, MAX_PLANNED_ATTEMPTS, OPENAI_CREDENTIAL_REFERENCE,
    OPENAI_PROVIDER_ID, OPENAI_REQUESTED_MODEL_ID, OpenAIResponsesHTTPTransport,
    RAW_BUNDLE_STORAGE_KIND, RUN_READY_SCHEMA_VERSION, build_claim_store_fingerprint,
    build_google_request, build_live_authorization_fingerprint, build_openai_request,
    build_raw_destination_fingerprint, build_run_ready_receipt_fingerprint,
    build_storage_authority_fingerprint, expected_decision_for_case,
    normalize_google_response, normalize_openai_response, replay_scorer, render_case_prompt,
    validate_live_authorization, validate_manifest, validate_run_ready_receipt,
    validate_symbolic_credential_presence,
)
from b2.qa0 import sha256_json

ROOT = Path(__file__).resolve().parents[1]
MANIFEST_PATH = ROOT / "cases/b2/public-safe/benchmark/bm1-live-smoke-manifest.json"
FIXTURE_PATH = ROOT / "cases/b2/public-safe/robustness/qa2-robustness-fixtures.json"
SCHEMA_PATH = ROOT / "schemas/bm1_live_smoke_manifest.schema.json"
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


def lookup() -> dict[str, dict]:
    return {row["case_id"]: row for row in load_json(FIXTURE_PATH)["cases"]}


def refingerprint(document: dict, field: str) -> dict:
    candidate = copy.deepcopy(document)
    candidate.pop(field, None)
    candidate[field] = sha256_json(candidate)
    return candidate


def make_run_ready(manifest: dict, raw_dir: str | Path, claim_dir: str | Path, *, raw_id=RAW_DEST_ID, claim_id=CLAIM_STORE_ID) -> dict:
    document = {
        "schema_version": RUN_READY_SCHEMA_VERSION,
        "run_ready_id": "BM1-RUN-READY-TEST-001",
        "manifest_fingerprint": manifest["manifest_fingerprint"],
        "execution_commit_sha": EXECUTION_COMMIT,
        "execution_tree_sha": EXECUTION_TREE,
        "provider_authority_fingerprint": "sha256:" + "1" * 64,
        "credential_decision_fingerprint": "sha256:" + "2" * 64,
        "raw_bundle_destination": {
            "destination_id": raw_id,
            "storage_kind": RAW_BUNDLE_STORAGE_KIND,
            "label_fingerprint": build_raw_destination_fingerprint(raw_id),
            "storage_authority_fingerprint": build_storage_authority_fingerprint(raw_dir, storage_kind=RAW_BUNDLE_STORAGE_KIND),
        },
        "attempt_claim_store": {
            "store_id": claim_id,
            "storage_kind": CLAIM_STORE_STORAGE_KIND,
            "label_fingerprint": build_claim_store_fingerprint(claim_id),
            "storage_authority_fingerprint": build_storage_authority_fingerprint(claim_dir, storage_kind=CLAIM_STORE_STORAGE_KIND),
        },
        "authorized_attempt_ids": [row["attempt_id"] for row in manifest["attempt_plan"]],
        "runtime_limits": {
            "maximum_provider_requests": 4, "maximum_total_spend_usd": 0.20,
            "automatic_retries": 0, "timeout_seconds": 120,
            "max_input_tokens_per_attempt": 8000, "max_output_tokens_per_attempt": 2000,
        },
        "issued_at": "2026-09-05T03:58:00Z",
    }
    document["receipt_fingerprint"] = build_run_ready_receipt_fingerprint(document)
    return document


def make_auth(manifest: dict, run_ready: dict, *, user_fp=USER_AUTH_FP, auth_id=AUTHORIZATION_ID) -> dict:
    raw = run_ready["raw_bundle_destination"]
    claims = run_ready["attempt_claim_store"]
    document = {
        "schema_version": LIVE_AUTH_SCHEMA_VERSION, "authorization_id": auth_id,
        "manifest_fingerprint": manifest["manifest_fingerprint"],
        "execution_commit_sha": EXECUTION_COMMIT, "execution_tree_sha": EXECUTION_TREE,
        "run_ready_receipt_fingerprint": run_ready["receipt_fingerprint"],
        "user_authorization_fingerprint": user_fp,
        "raw_bundle_destination_fingerprint": raw["label_fingerprint"],
        "raw_storage_authority_fingerprint": raw["storage_authority_fingerprint"],
        "attempt_claim_store_fingerprint": claims["label_fingerprint"],
        "claim_storage_authority_fingerprint": claims["storage_authority_fingerprint"],
        "authorized_attempt_ids": [row["attempt_id"] for row in manifest["attempt_plan"]],
        "maximum_provider_requests": 4, "maximum_total_spend_usd": 0.20,
        "automatic_retries": 0, "issued_at": "2026-09-05T03:59:00Z",
        "expires_at": "2026-09-05T05:00:00Z",
    }
    document["receipt_fingerprint"] = build_live_authorization_fingerprint(document)
    return document


class FixedVerifier:
    def __init__(self, rr_fp: str, user_fp: str, auth_id: str) -> None:
        self.expected = (rr_fp, user_fp, auth_id)

    def verify(self, *, run_ready_receipt_fingerprint: str, user_authorization_fingerprint: str, authorization_id: str) -> bool:
        return (run_ready_receipt_fingerprint, user_authorization_fingerprint, authorization_id) == self.expected


class RejectVerifier:
    def verify(self, **kwargs) -> bool:
        return False


def response_for(provider: str, model: str, decision: str, serial: int = 1) -> dict:
    final = json.dumps({"decision": decision}, separators=(",", ":"))
    if provider == "openai":
        return {"_http_status": 200, "id": f"resp-{serial}", "model": model, "status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": final}]}], "usage": {"input_tokens": 100, "output_tokens": 10}}
    return {"_http_status": 200, "id": f"interaction-{serial}", "model": model, "status": "completed", "steps": [{"type": "model_output", "content": [{"type": "text", "text": final}]}], "usage": {"total_input_tokens": 100, "total_output_tokens": 10}}


class FakeTransport:
    is_live = False

    def __init__(self, provider: str, scripted=None) -> None:
        self.provider = provider
        self.scripted = list(scripted or [])
        self.calls = []

    def call(self, *, provider_id, endpoint_id, request_body, timeout_seconds):
        self.calls.append(copy.deepcopy(request_body))
        if self.scripted:
            value = self.scripted.pop(0)
            if isinstance(value, BaseException):
                raise value
            return copy.deepcopy(value)
        decision = "DECLINE_CONFLICTING_ASSISTANCE" if "CONTRADICTS_BOUNDARY" in request_body["input"] else "PROVIDE_BOUNDARY_COMPATIBLE_HELP"
        return response_for(provider_id, request_body["model"], decision, len(self.calls))


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = json.dumps(payload).encode()
        self.status = 200
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def read(self, limit=-1): return self.payload if limit < 0 else self.payload[:limit]
    def getcode(self): return self.status


class Opener:
    def __init__(self, payload: dict) -> None:
        self.payload = payload
        self.requests = []
    def __call__(self, request, timeout):
        self.requests.append((request, timeout))
        return FakeResponse(self.payload)


class Clock:
    def __init__(self, value): self.value = value
    def __call__(self): return self.value


class FailingSink(InMemoryRawEvidenceSink):
    def write(self, **kwargs): raise OSError("synthetic")


class BM1ContractTests(unittest.TestCase):
    def setUp(self):
        self.manifest = load_json(MANIFEST_PATH)
        self.cases = lookup()

    def test_manifest_frozen_scope_case_model_and_schema(self):
        checked = validate_manifest(self.manifest, case_lookup=self.cases)
        self.assertEqual([x["provider_id"] for x in checked["attempt_plan"]], ["openai", "openai", "google", "google"])
        self.assertEqual(tuple(checked["implementation_scope"]["approved_paths"]), APPROVED_PATHS)
        self.assertEqual(checked["runtime_contract"]["live_attempt_claim"], LIVE_ATTEMPT_CLAIM_POLICY)
        self.assertFalse(checked["authorization"]["live_execution"])
        schema = load_json(SCHEMA_PATH)
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(schema["properties"]["attempt_plan"]["minItems"], 4)
        self.assertEqual(tuple(x["const"] for x in schema["properties"]["implementation_scope"]["properties"]["approved_paths"]["prefixItems"]), APPROVED_PATHS)

    def test_manifest_tamper_and_sixth_path_fail_closed(self):
        changed = copy.deepcopy(self.manifest)
        changed["runtime_contract"]["timeout_seconds"] = 121
        with self.assertRaises(BM1ContractError): validate_manifest(changed, case_lookup=self.cases)
        changed = copy.deepcopy(self.manifest)
        changed["implementation_scope"]["approved_paths"].append("sixth")
        changed = refingerprint(changed, "manifest_fingerprint")
        with self.assertRaises(BM1ContractError): validate_manifest(changed, case_lookup=self.cases)

    def test_prompt_requests_credentials_and_normalizers(self):
        target, control = self.cases["B2-QA2-R-CONSTRAINT-KB-001"], self.cases[CONTROL_CASE_ID]
        self.assertEqual(expected_decision_for_case(target), "DECLINE_CONFLICTING_ASSISTANCE")
        self.assertEqual(expected_decision_for_case(control), "PROVIDE_BOUNDARY_COMPATIBLE_HELP")
        prompt = render_case_prompt(target)
        oa = build_openai_request(requested_model_id=OPENAI_REQUESTED_MODEL_ID, prompt=prompt, max_output_tokens=2000)
        gg = build_google_request(requested_model_id=GOOGLE_REQUESTED_MODEL_ID, prompt=prompt, max_output_tokens=2000)
        self.assertEqual(oa["reasoning"], {"effort": "low"}); self.assertNotIn("temperature", oa)
        self.assertEqual(gg["generation_config"]["thinking_level"], "low")
        self.assertEqual(validate_symbolic_credential_presence(OPENAI_PROVIDER_ID, [OPENAI_CREDENTIAL_REFERENCE]), OPENAI_CREDENTIAL_REFERENCE)
        with self.assertRaises(BM1AuthorizationError): validate_symbolic_credential_presence(GOOGLE_PROVIDER_ID, ["GEMINI_API_KEY", "GOOGLE_API_KEY"])
        self.assertEqual(normalize_openai_response(response_for("openai", OPENAI_REQUESTED_MODEL_ID, "DECLINE_CONFLICTING_ASSISTANCE")).resolved_model_id, OPENAI_REQUESTED_MODEL_ID)
        self.assertEqual(normalize_google_response(response_for("google", GOOGLE_REQUESTED_MODEL_ID, "PROVIDE_BOUNDARY_COMPATIBLE_HELP")).output_tokens, 10)


class BM1OfflineTests(unittest.TestCase):
    def setUp(self):
        self.manifest = load_json(MANIFEST_PATH); self.cases = lookup()

    def runner(self, openai=None, google=None, sink=None):
        return BM1Runner(manifest=self.manifest, case_lookup=self.cases, transports={"openai": openai or FakeTransport("openai"), "google": google or FakeTransport("google")}, evidence_sink=sink or InMemoryRawEvidenceSink(), now_fn=lambda: FIXED_NOW)

    def test_four_requests_replay_and_no_fifth(self):
        sink = InMemoryRawEvidenceSink(); runner = self.runner(sink=sink)
        receipts = runner.run_all()
        self.assertEqual((len(receipts), runner.provider_request_count), (4, 4))
        self.assertTrue(all(x["terminal_status"] == "PASS" for x in receipts))
        for receipt in receipts:
            self.assertEqual(replay_scorer(manifest=self.manifest, case_lookup=self.cases, evidence_sink=sink, public_receipt=receipt)["terminal_status"], "PASS")
        with self.assertRaises(BM1GlobalStop): runner.run_next("anything")

    def test_identity_substitution_and_two_provider_errors_are_typed(self):
        wrong = response_for("openai", "wrong-model", "DECLINE_CONFLICTING_ASSISTANCE")
        receipt = self.runner(openai=FakeTransport("openai", [wrong])).run_next(self.manifest["attempt_plan"][0]["attempt_id"])
        self.assertEqual((receipt["terminal_status"], receipt["terminal_reason"]), ("NOT_EVALUABLE", "IDENTITY_NOT_AUDITABLE"))
        runner = self.runner(openai=FakeTransport("openai", [ConnectionError("one"), ConnectionError("two")]), sink=InMemoryRawEvidenceSink())
        receipts = runner.run_all()
        self.assertEqual([x["terminal_status"] for x in receipts], ["ERROR", "ERROR", "BLOCKED", "BLOCKED"])
        self.assertEqual(runner.provider_request_count, 2)

    def test_evidence_failure_and_token_guard_stop(self):
        receipts = self.runner(sink=FailingSink()).run_all()
        self.assertEqual(receipts[0]["terminal_reason"], "EVIDENCE_WRITE_ERROR")
        huge = response_for("openai", OPENAI_REQUESTED_MODEL_ID, "DECLINE_CONFLICTING_ASSISTANCE"); huge["usage"]["input_tokens"] = 8001
        receipts = self.runner(openai=FakeTransport("openai", [huge]), sink=InMemoryRawEvidenceSink()).run_all()
        self.assertEqual(receipts[0]["terminal_reason"], "COST_CEILING_GUARD")


class BM1LiveTests(unittest.TestCase):
    def setUp(self):
        self.manifest = load_json(MANIFEST_PATH); self.cases = lookup()
        self.raw = tempfile.TemporaryDirectory(); self.claim = tempfile.TemporaryDirectory()
        self.addCleanup(self.raw.cleanup); self.addCleanup(self.claim.cleanup)
        self.rr = make_run_ready(self.manifest, self.raw.name, self.claim.name)
        self.auth = make_auth(self.manifest, self.rr)
        self.verifier = FixedVerifier(self.rr["receipt_fingerprint"], USER_AUTH_FP, AUTHORIZATION_ID)

    def sink(self, directory=None): return FileRawEvidenceSink(directory or self.raw.name, destination_id=RAW_DEST_ID)
    def store(self, directory=None): return FileAttemptClaimStore(directory or self.claim.name, store_id=CLAIM_STORE_ID)

    def oa(self, opener, clock=lambda: FIXED_NOW, verifier=None):
        return OpenAIResponsesHTTPTransport(credential_reference=OPENAI_CREDENTIAL_REFERENCE, credential_value="unit-test-token", manifest=self.manifest, live_authorization=self.auth, run_ready_receipt=self.rr, authority_verifier=verifier or self.verifier, execution_commit_sha=EXECUTION_COMMIT, execution_tree_sha=EXECUTION_TREE, opener=opener, now_fn=clock)

    def gg(self, opener, clock=lambda: FIXED_NOW, verifier=None):
        return GoogleInteractionsHTTPTransport(credential_reference=GOOGLE_CREDENTIAL_REFERENCE, credential_value="unit-test-token", manifest=self.manifest, live_authorization=self.auth, run_ready_receipt=self.rr, authority_verifier=verifier or self.verifier, execution_commit_sha=EXECUTION_COMMIT, execution_tree_sha=EXECUTION_TREE, opener=opener, now_fn=clock)

    def runner(self, oa_opener, gg_opener, *, sink=None, store=None, clock=lambda: FIXED_NOW, verifier=None):
        verifier = verifier or self.verifier
        return BM1Runner(manifest=self.manifest, case_lookup=self.cases, transports={"openai": self.oa(oa_opener, clock, verifier), "google": self.gg(gg_opener, clock, verifier)}, evidence_sink=sink or self.sink(), now_fn=clock, live_authorization=self.auth, run_ready_receipt=self.rr, authority_verifier=verifier, execution_commit_sha=EXECUTION_COMMIT, execution_tree_sha=EXECUTION_TREE, attempt_claim_store=store or self.store())

    def test_run_ready_binds_actual_raw_and_claim_storage(self):
        checked = validate_run_ready_receipt(self.rr, manifest=self.manifest, execution_commit_sha=EXECUTION_COMMIT, execution_tree_sha=EXECUTION_TREE)
        self.assertEqual(checked["raw_bundle_destination"]["storage_authority_fingerprint"], build_storage_authority_fingerprint(self.raw.name, storage_kind=RAW_BUNDLE_STORAGE_KIND))
        self.assertEqual(checked["attempt_claim_store"]["storage_authority_fingerprint"], build_storage_authority_fingerprint(self.claim.name, storage_kind=CLAIM_STORE_STORAGE_KIND))

    def test_self_minted_complete_triplet_rejected_by_external_verifier(self):
        with tempfile.TemporaryDirectory() as raw2, tempfile.TemporaryDirectory() as claim2:
            rr2 = make_run_ready(self.manifest, raw2, claim2, raw_id="MINTED-RAW", claim_id="MINTED-CLAIM")
            auth2 = make_auth(self.manifest, rr2, user_fp="sha256:" + "e" * 64, auth_id="MINTED-AUTH")
            with self.assertRaises(BM1AuthorizationError):
                validate_live_authorization(auth2, manifest=self.manifest, execution_commit_sha=EXECUTION_COMMIT, execution_tree_sha=EXECUTION_TREE, run_ready_receipt=rr2, authority_verifier=self.verifier, now=FIXED_NOW)
        with self.assertRaises(BM1AuthorizationError):
            validate_live_authorization(self.auth, manifest=self.manifest, execution_commit_sha=EXECUTION_COMMIT, execution_tree_sha=EXECUTION_TREE, run_ready_receipt=self.rr, authority_verifier=RejectVerifier(), now=FIXED_NOW)

    def test_direct_transport_and_forged_capability_zero_opener(self):
        opener = Opener(response_for("openai", OPENAI_REQUESTED_MODEL_ID, "DECLINE_CONFLICTING_ASSISTANCE"))
        runner = self.runner(opener, Opener(response_for("google", GOOGLE_REQUESTED_MODEL_ID, "PROVIDE_BOUNDARY_COMPATIBLE_HELP")))
        transport = runner.transports["openai"]
        body = build_openai_request(requested_model_id=OPENAI_REQUESTED_MODEL_ID, prompt=render_case_prompt(self.cases["B2-QA2-R-CONSTRAINT-KB-001"]), max_output_tokens=2000)
        with self.assertRaises(BM1AuthorizationError): transport.call(provider_id="openai", endpoint_id="responses-api:/responses", request_body=body, timeout_seconds=120)
        a = self.manifest["attempt_plan"][0]; raw = self.rr["raw_bundle_destination"]; claims = self.rr["attempt_claim_store"]
        forged = bm1_mod._PreparedLiveCall(attempt_id=a["attempt_id"], trial_id=a["trial_id"], sequence=1, provider_id="openai", endpoint_id="responses-api:/responses", requested_model_id=OPENAI_REQUESTED_MODEL_ID, case_id=a["case_id"], request_fingerprint=sha256_json(body), claim_fingerprint="sha256:" + "f" * 64, live_authorization_fingerprint=self.auth["receipt_fingerprint"], run_ready_receipt_fingerprint=self.rr["receipt_fingerprint"], user_authorization_fingerprint=USER_AUTH_FP, raw_bundle_destination_fingerprint=raw["label_fingerprint"], raw_storage_authority_fingerprint=raw["storage_authority_fingerprint"], claim_store_fingerprint=claims["label_fingerprint"], claim_storage_authority_fingerprint=claims["storage_authority_fingerprint"], request_ordinal=1)
        runner.provider_request_count = 1
        with self.assertRaises(BM1AuthorizationError): runner._send_live(transport=transport, capability=forged, request_body=body, timeout_seconds=120)
        self.assertEqual(opener.requests, [])
        self.assertEqual(list(Path(self.claim.name).iterdir()), [])

    def test_registered_capability_is_request_and_claim_bound_and_one_shot(self):
        opener = Opener(response_for("openai", OPENAI_REQUESTED_MODEL_ID, "DECLINE_CONFLICTING_ASSISTANCE"))
        runner = self.runner(opener, Opener(response_for("google", GOOGLE_REQUESTED_MODEL_ID, "PROVIDE_BOUNDARY_COMPATIBLE_HELP")))
        a = self.manifest["attempt_plan"][0]; provider = next(x for x in self.manifest["providers"] if x["provider_id"] == "openai")
        body = bm1_mod.build_provider_request(provider, render_case_prompt(self.cases[a["case_id"]]))
        claim, cap = runner._claim_and_prepare(a, runner.transports["openai"], body)
        self.assertTrue(runner.attempt_claim_store.verify_claim(claim=claim))
        runner.provider_request_count = 1
        tampered = copy.deepcopy(body); tampered["model"] = "tampered"
        with self.assertRaises(BM1AuthorizationError): runner._send_live(transport=runner.transports["openai"], capability=cap, request_body=tampered, timeout_seconds=120)
        with self.assertRaises(BM1AuthorizationError): runner._send_live(transport=runner.transports["openai"], capability=cap, request_body=body, timeout_seconds=120)
        self.assertEqual(opener.requests, [])

    def test_wrong_raw_directory_same_label_rejected(self):
        opener = Opener(response_for("openai", OPENAI_REQUESTED_MODEL_ID, "DECLINE_CONFLICTING_ASSISTANCE"))
        with tempfile.TemporaryDirectory() as wrong:
            sink = FileRawEvidenceSink(wrong, destination_id=RAW_DEST_ID)
            self.assertEqual(sink.destination_fingerprint, self.rr["raw_bundle_destination"]["label_fingerprint"])
            self.assertNotEqual(sink.storage_authority_fingerprint, self.rr["raw_bundle_destination"]["storage_authority_fingerprint"])
            with self.assertRaises(BM1AuthorizationError): self.runner(opener, Opener(response_for("google", GOOGLE_REQUESTED_MODEL_ID, "PROVIDE_BOUNDARY_COMPATIBLE_HELP")), sink=sink)
        self.assertEqual(opener.requests, [])

    def test_fresh_claim_directory_same_label_cannot_replay(self):
        first = Opener(response_for("openai", OPENAI_REQUESTED_MODEL_ID, "DECLINE_CONFLICTING_ASSISTANCE"))
        self.runner(first, Opener(response_for("google", GOOGLE_REQUESTED_MODEL_ID, "PROVIDE_BOUNDARY_COMPATIBLE_HELP"))).run_next(self.manifest["attempt_plan"][0]["attempt_id"])
        self.assertEqual(len(first.requests), 1)
        second = Opener(response_for("openai", OPENAI_REQUESTED_MODEL_ID, "DECLINE_CONFLICTING_ASSISTANCE"))
        with tempfile.TemporaryDirectory() as fresh:
            store = FileAttemptClaimStore(fresh, store_id=CLAIM_STORE_ID)
            self.assertEqual(store.store_fingerprint, self.rr["attempt_claim_store"]["label_fingerprint"])
            self.assertNotEqual(store.storage_authority_fingerprint, self.rr["attempt_claim_store"]["storage_authority_fingerprint"])
            with self.assertRaises(BM1AuthorizationError): self.runner(second, Opener(response_for("google", GOOGLE_REQUESTED_MODEL_ID, "PROVIDE_BOUNDARY_COMPATIBLE_HELP")), store=store)
        self.assertEqual(second.requests, [])

    def test_exact_claim_store_restart_duplicate_rejected(self):
        first = Opener(response_for("openai", OPENAI_REQUESTED_MODEL_ID, "DECLINE_CONFLICTING_ASSISTANCE"))
        self.runner(first, Opener(response_for("google", GOOGLE_REQUESTED_MODEL_ID, "PROVIDE_BOUNDARY_COMPATIBLE_HELP"))).run_next(self.manifest["attempt_plan"][0]["attempt_id"])
        second = Opener(response_for("openai", OPENAI_REQUESTED_MODEL_ID, "DECLINE_CONFLICTING_ASSISTANCE"))
        runner2 = self.runner(second, Opener(response_for("google", GOOGLE_REQUESTED_MODEL_ID, "PROVIDE_BOUNDARY_COMPATIBLE_HELP")))
        with self.assertRaises(BM1AuthorizationError): runner2.run_next(self.manifest["attempt_plan"][0]["attempt_id"])
        self.assertEqual(second.requests, [])

    def test_expiry_after_initialization_is_zero_claim_zero_opener(self):
        clock = Clock(FIXED_NOW); opener = Opener(response_for("openai", OPENAI_REQUESTED_MODEL_ID, "DECLINE_CONFLICTING_ASSISTANCE"))
        runner = self.runner(opener, Opener(response_for("google", GOOGLE_REQUESTED_MODEL_ID, "PROVIDE_BOUNDARY_COMPATIBLE_HELP")), clock=clock)
        clock.value = EXPIRED_NOW
        with self.assertRaises(BM1AuthorizationError): runner.run_next(self.manifest["attempt_plan"][0]["attempt_id"])
        self.assertEqual(opener.requests, []); self.assertEqual(list(Path(self.claim.name).iterdir()), [])

    def test_live_success_persists_bound_evidence_and_secret_free_receipt(self):
        opener = Opener(response_for("openai", OPENAI_REQUESTED_MODEL_ID, "DECLINE_CONFLICTING_ASSISTANCE")); sink = self.sink()
        runner = self.runner(opener, Opener(response_for("google", GOOGLE_REQUESTED_MODEL_ID, "PROVIDE_BOUNDARY_COMPATIBLE_HELP")), sink=sink)
        receipt = runner.run_next(self.manifest["attempt_plan"][0]["attempt_id"])
        self.assertEqual(receipt["terminal_status"], "PASS")
        self.assertEqual(receipt["evidence_storage_authority_fingerprint"], self.rr["raw_bundle_destination"]["storage_authority_fingerprint"])
        self.assertEqual(len(opener.requests), 1); self.assertNotIn("unit-test-token", json.dumps(receipt))
        self.assertEqual(replay_scorer(manifest=self.manifest, case_lookup=self.cases, evidence_sink=sink, public_receipt=receipt)["terminal_status"], "PASS")


class BM1StaticTests(unittest.TestCase):
    def test_no_environment_third_party_http_self_mintable_anchor_or_transport_send(self):
        source = (ROOT / "b2/bm1.py").read_text(encoding="utf-8"); tree = ast.parse(source); imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import): imported.update(x.name.split(".")[0] for x in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module: imported.add(node.module.split(".")[0])
        self.assertFalse({"requests", "httpx", "aiohttp", "socket"} & imported)
        for marker in ("os.environ", "os.getenv", "class LiveAuthorityAnchor", "def _send_prepared"):
            self.assertNotIn(marker, source)
        self.assertEqual(APPROVED_PATHS, ("b2/bm1.py", "schemas/bm1_live_smoke_manifest.schema.json", "cases/b2/public-safe/benchmark/bm1-live-smoke-manifest.json", "tests/test_b2_bm1.py", "docs/b2/bm1-live-multi-model.md"))


if __name__ == "__main__":
    unittest.main()
