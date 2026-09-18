from __future__ import annotations

import ast
import copy
import json
import tempfile
import os
import sys
import subprocess
import unittest
from unittest import mock
from datetime import datetime, timezone
from pathlib import Path

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


def harden_test_directory(path, *, extra_aces="", protected=True, owner=None):
    """Test-only fixture provisioning; production never repairs store ACLs."""
    if sys.platform != "win32":
        os.chmod(path, 0o700)
        return
    import ctypes as c
    from ctypes import wintypes as w
    from b2.bm1 import _windows_storage
    backend = _windows_storage()
    sid = backend.runner_sid()
    descriptor = c.c_void_p()
    sddl = f"O:{owner or sid}D:{'P' if protected else ''}(A;;FA;;;{sid}){extra_aces}"
    backend._require(backend.advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        sddl, 1, c.byref(descriptor), None))
    owner_reader = backend._api(backend.advapi, "GetSecurityDescriptorOwner",
                               [c.c_void_p, c.POINTER(c.c_void_p), c.POINTER(w.BOOL)], w.BOOL)
    acl_reader = backend._api(backend.advapi, "GetSecurityDescriptorDacl",
                             [c.c_void_p, c.POINTER(w.BOOL), c.POINTER(c.c_void_p), c.POINTER(w.BOOL)], w.BOOL)
    setter = backend._api(backend.advapi, "SetNamedSecurityInfoW",
                         [w.LPWSTR, c.c_int, w.DWORD, c.c_void_p, c.c_void_p, c.c_void_p, c.c_void_p], w.DWORD)
    try:
        owner_pointer, acl = c.c_void_p(), c.c_void_p()
        present, defaulted = w.BOOL(), w.BOOL()
        backend._require(owner_reader(descriptor, c.byref(owner_pointer), c.byref(defaulted)))
        backend._require(acl_reader(descriptor, c.byref(present), c.byref(acl), c.byref(defaulted)))
        backend._require(setter(str(path), 1, 5 | (0x80000000 if protected else 0x20000000),
                                owner_pointer, None, acl, None) == 0)
    finally:
        backend.kernel.LocalFree(descriptor)


class PrivateTemporaryDirectory(tempfile.TemporaryDirectory):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = str(Path(self.name).resolve())
        harden_test_directory(self.name)

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


class ExpiringClaimStore(FileAttemptClaimStore):
    def __init__(self, directory, *, store_id, clock):
        super().__init__(directory, store_id=store_id)
        self.clock = clock

    def claim(self, *, claim):
        checked = super().claim(claim=claim)
        self.clock.value = EXPIRED_NOW
        return checked


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
        self.raw = PrivateTemporaryDirectory(); self.claim = PrivateTemporaryDirectory()
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
        with PrivateTemporaryDirectory() as raw2, PrivateTemporaryDirectory() as claim2:
            rr2 = make_run_ready(self.manifest, raw2, claim2, raw_id="MINTED-RAW", claim_id="MINTED-CLAIM")
            auth2 = make_auth(self.manifest, rr2, user_fp="sha256:" + "e" * 64, auth_id="MINTED-AUTH")
            with self.assertRaises(BM1AuthorizationError):
                validate_live_authorization(auth2, manifest=self.manifest, execution_commit_sha=EXECUTION_COMMIT, execution_tree_sha=EXECUTION_TREE, run_ready_receipt=rr2, authority_verifier=self.verifier, now=FIXED_NOW)
        with self.assertRaises(BM1AuthorizationError):
            validate_live_authorization(self.auth, manifest=self.manifest, execution_commit_sha=EXECUTION_COMMIT, execution_tree_sha=EXECUTION_TREE, run_ready_receipt=self.rr, authority_verifier=RejectVerifier(), now=FIXED_NOW)

    def test_direct_transport_and_separate_network_helpers_are_fail_closed(self):
        opener = Opener(response_for("openai", OPENAI_REQUESTED_MODEL_ID, "DECLINE_CONFLICTING_ASSISTANCE"))
        runner = self.runner(opener, Opener(response_for("google", GOOGLE_REQUESTED_MODEL_ID, "PROVIDE_BOUNDARY_COMPATIBLE_HELP")))
        transport = runner.transports["openai"]
        body = build_openai_request(requested_model_id=OPENAI_REQUESTED_MODEL_ID, prompt=render_case_prompt(self.cases["B2-QA2-R-CONSTRAINT-KB-001"]), max_output_tokens=2000)
        with self.assertRaises(BM1AuthorizationError): transport.call(provider_id="openai", endpoint_id="responses-api:/responses", request_body=body, timeout_seconds=120)
        for name in ("_claim_and_prepare", "_consume_capability", "_send_live"):
            self.assertFalse(hasattr(runner, name))
        self.assertEqual(opener.requests, [])
        self.assertEqual(list(Path(self.claim.name).iterdir()), [])

    def test_post_claim_expiry_emits_bound_terminal_receipt_and_blocks_replay(self):
        clock = Clock(FIXED_NOW)
        opener = Opener(response_for("openai", OPENAI_REQUESTED_MODEL_ID, "DECLINE_CONFLICTING_ASSISTANCE"))
        store = ExpiringClaimStore(
            self.claim.name, store_id=CLAIM_STORE_ID, clock=clock,
        )
        runner = self.runner(
            opener,
            Opener(response_for("google", GOOGLE_REQUESTED_MODEL_ID, "PROVIDE_BOUNDARY_COMPATIBLE_HELP")),
            store=store, clock=clock,
        )
        attempt_id = self.manifest["attempt_plan"][0]["attempt_id"]
        with self.assertRaises(BM1AuthorizationError):
            runner.run_next(attempt_id)

        claim_files = list(Path(self.claim.name).glob("attempt-*.json"))
        self.assertEqual(len(claim_files), 1)
        claim = load_json(claim_files[0])
        self.assertTrue(store.verify_claim(claim=claim))
        self.assertEqual(len(runner.receipts), 1)
        receipt = runner.receipts[0]
        self.assertEqual(
            (receipt["terminal_status"], receipt["terminal_reason"]),
            ("ERROR", "LIVE_AUTHORIZATION_STOP"),
        )
        self.assertEqual(receipt["provider_terminal_status"], "RUNTIME_ERROR")
        self.assertIsNone(receipt["provider_http_status"])
        self.assertEqual(receipt["attempt_claim_fingerprint"], claim["claim_fingerprint"])
        unsigned_receipt = copy.deepcopy(receipt)
        unsigned_receipt.pop("receipt_fingerprint")
        self.assertEqual(receipt["receipt_fingerprint"], sha256_json(unsigned_receipt))
        self.assertEqual(runner.provider_request_count, 0)
        self.assertEqual(runner.global_stop_reason, "LIVE_AUTHORIZATION_STOP")
        self.assertEqual(opener.requests, [])

        with self.assertRaises(BM1GlobalStop):
            runner.run_next(attempt_id)
        clock.value = FIXED_NOW
        replay_opener = Opener(response_for("openai", OPENAI_REQUESTED_MODEL_ID, "DECLINE_CONFLICTING_ASSISTANCE"))
        replay_runner = self.runner(
            replay_opener,
            Opener(response_for("google", GOOGLE_REQUESTED_MODEL_ID, "PROVIDE_BOUNDARY_COMPATIBLE_HELP")),
            store=self.store(), clock=clock,
        )
        with self.assertRaises(BM1AuthorizationError):
            replay_runner.run_next(attempt_id)
        self.assertEqual(replay_opener.requests, [])

    def test_wrong_raw_directory_same_label_rejected(self):
        opener = Opener(response_for("openai", OPENAI_REQUESTED_MODEL_ID, "DECLINE_CONFLICTING_ASSISTANCE"))
        with PrivateTemporaryDirectory() as wrong:
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
        with PrivateTemporaryDirectory() as fresh:
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


    def test_duplicate_claim_rejected_in_a_fresh_process(self):
        opener = Opener(response_for("openai", OPENAI_REQUESTED_MODEL_ID, "DECLINE_CONFLICTING_ASSISTANCE"))
        self.runner(opener, Opener({})).run_next(self.manifest["attempt_plan"][0]["attempt_id"])
        claim = next(Path(self.claim.name).glob("attempt-*.json")).read_text(encoding="utf-8")
        code = (
            "import json,sys; from b2.bm1 import FileAttemptClaimStore,BM1AuthorizationError; "
            "store=FileAttemptClaimStore(sys.argv[1],store_id=sys.argv[2]); "
            "claim=json.loads(sys.stdin.read())\n"
            "try: store.claim(claim=claim)\n"
            "except BM1AuthorizationError: sys.exit(0)\n"
            "sys.exit(7)\n"
        )
        completed = subprocess.run([sys.executable, "-c", code, self.claim.name, CLAIM_STORE_ID],
                                   input=claim, text=True, capture_output=True)
        self.assertEqual(completed.returncode, 0, "fresh-process duplicate denial failed")
        self.assertEqual(completed.stdout, "")

    def test_post_claim_directory_drift_blocks_before_provider_send(self):
        from b2 import bm1_live
        selected = "windows" if sys.platform == "win32" else "linux"
        env = {"B2_BM1_RUNNER_OS": selected, "B2_BM1_GUARDED_RUNNER_OS": selected,
               "B2_BM1_LANE_OS": selected, "RUNNER_ARCH": "X64",
               "RUNNER_OS": "Windows" if selected == "windows" else "Linux",
               "B2_BM1_RAW_BUNDLE_DIR": self.raw.name, "B2_BM1_ATTEMPT_CLAIM_DIR": self.claim.name,
               "B2_BM1_RAW_BUNDLE_ID": RAW_DEST_ID, "B2_BM1_ATTEMPT_CLAIM_STORE_ID": CLAIM_STORE_ID}
        with mock.patch.object(bm1_live, "_forbidden_storage_roots", return_value=()):
            runtime = bm1_live.storage_runtime(env)
            opener = Opener({})
            runner = self.runner(opener, Opener({}), sink=runtime.raw_sink, store=runtime.claim_store)
            original_claim = runtime.claim_store.claim
            old = Path(self.raw.name).with_name(Path(self.raw.name).name + "-replaced")
            def replace_after_claim(**kwargs):
                result = original_claim(**kwargs)
                Path(self.raw.name).rename(old)
                Path(self.raw.name).mkdir(mode=0o700)
                harden_test_directory(self.raw.name)
                return result
            try:
                with mock.patch.object(runtime.claim_store, "claim", side_effect=replace_after_claim):
                    with self.assertRaises(BM1AuthorizationError):
                        runner.run_next(self.manifest["attempt_plan"][0]["attempt_id"])
                self.assertEqual(opener.requests, [])
                self.assertEqual(runner.provider_request_count, 0)
                self.assertEqual(runner.receipts[0]["terminal_reason"], "LIVE_AUTHORIZATION_STOP")
            finally:
                if old.exists():
                    import shutil
                    shutil.rmtree(old)

    @unittest.skipUnless(sys.platform == "win32", "native Windows ACL drift")
    def test_post_claim_approved_acl_drift_blocks_before_provider_send(self):
        from b2 import bm1_live
        sink = bm1_live._RefreshingFileRawEvidenceSink(self.raw.name, destination_id=RAW_DEST_ID)
        store = bm1_live._RefreshingFileAttemptClaimStore(self.claim.name, store_id=CLAIM_STORE_ID)
        opener = Opener({})
        runner = self.runner(opener, Opener({}), sink=sink, store=store)
        original = store.claim
        def drift(**kwargs):
            result = original(**kwargs)
            harden_test_directory(self.raw.name, extra_aces="(A;;FA;;;SY)")
            return result
        with mock.patch.object(store, "claim", side_effect=drift):
            with self.assertRaises(BM1AuthorizationError):
                runner.run_next(self.manifest["attempt_plan"][0]["attempt_id"])
        self.assertEqual(opener.requests, [])
        self.assertEqual(runner.provider_request_count, 0)
        self.assertEqual(runner.receipts[0]["terminal_reason"], "LIVE_AUTHORIZATION_STOP")


class DurableFilePortabilityTests(unittest.TestCase):
    def test_exclusive_raw_roundtrip_rejects_overwrite(self):
        with PrivateTemporaryDirectory() as root:
            sink = FileRawEvidenceSink(root, destination_id=RAW_DEST_ID)
            values = dict(attempt_id="portable", request_body={"synthetic": "unicode-测试"},
                          raw_response={"value": 1}, final_text="private synthetic", error_class=None)
            receipt = sink.write(**values)
            self.assertEqual(sink.read_for_replay(attempt_id="portable")["raw_response"], {"value": 1})
            with self.assertRaises(BM1ContractError):
                sink.write(**values)
            self.assertNotIn(root, json.dumps(receipt))
            self.assertNotIn("private synthetic", json.dumps(receipt))
            if sys.platform == "linux":
                self.assertEqual(next(Path(root).glob("raw-*.json")).stat().st_mode & 0o777, 0o600)

    @unittest.skipUnless(sys.platform == "linux", "Linux fingerprint and fsync contract")
    def test_linux_authority_tuple_unchanged_and_fsync_covers_file_and_directory(self):
        from b2 import bm1
        import hashlib
        import stat
        with PrivateTemporaryDirectory() as root:
            path = Path(root).resolve()
            info = path.stat()
            expected = sha256_json({"storage_kind": RAW_BUNDLE_STORAGE_KIND,
                "resolved_path_fingerprint": "sha256:" + hashlib.sha256(str(path).encode()).hexdigest(),
                "device": info.st_dev, "inode": info.st_ino})
            self.assertEqual(build_storage_authority_fingerprint(root, storage_kind=RAW_BUNDLE_STORAGE_KIND), expected)
            synced = []
            original = os.fsync
            def capture(fd):
                synced.append(stat.S_ISDIR(os.fstat(fd).st_mode))
                return original(fd)
            with mock.patch.object(bm1.os, "fsync", side_effect=capture):
                bm1._durable_exclusive_write(path / "synthetic", b"durable data")
            self.assertEqual(synced, [False, True])

    @unittest.skipUnless(sys.platform == "win32", "native Windows NTFS backend")
    def test_windows_create_new_write_through_flush_close_reopen_readback(self):
        from b2.bm1 import _windows_storage
        backend = _windows_storage()
        with PrivateTemporaryDirectory() as root:
            events = []
            create, flush = backend.kernel.CreateFileW, backend.kernel.FlushFileBuffers
            def opening(*args):
                if args[4] == 1:
                    self.assertTrue(args[5] & 0x80000000)
                    self.assertTrue(args[3])
                    events.append("create-new-write-through")
                elif str(args[0]).endswith("synthetic.bin"):
                    events.append("reopen")
                return create(*args)
            def flushing(handle):
                events.append("flush")
                return flush(handle)
            with mock.patch.object(backend.kernel, "CreateFileW", side_effect=opening), mock.patch.object(
                    backend.kernel, "FlushFileBuffers", side_effect=flushing):
                backend.exclusive_write(Path(root) / "synthetic.bin", b"synthetic durable data")
            self.assertEqual(events, ["create-new-write-through", "flush", "reopen"])
            with self.assertRaises(FileExistsError):
                backend.exclusive_write(Path(root) / "synthetic.bin", b"cannot overwrite")

    @unittest.skipUnless(sys.platform == "win32", "native Windows NTFS backend")
    def test_windows_flush_failure_and_readback_corruption_fail_closed_with_tombstone(self):
        from b2.bm1 import _windows_storage
        backend = _windows_storage()
        with PrivateTemporaryDirectory() as root:
            path = Path(root) / "failed-flush"
            with mock.patch.object(backend.kernel, "FlushFileBuffers", return_value=0):
                with self.assertRaises(BM1AuthorizationError):
                    backend.exclusive_write(path, b"synthetic")
            with self.assertRaises(FileExistsError):
                backend.exclusive_write(path, b"retry forbidden")
            with mock.patch.object(backend, "_read", return_value=(b"corrupted", {})):
                with self.assertRaises(BM1AuthorizationError):
                    backend.exclusive_write(Path(root) / "bad-readback", b"synthetic")


class BM1StaticTests(unittest.TestCase):
    def test_no_environment_third_party_http_self_mintable_anchor_or_transport_send(self):
        source = (ROOT / "b2/bm1.py").read_text(encoding="utf-8"); tree = ast.parse(source); imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import): imported.update(x.name.split(".")[0] for x in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module: imported.add(node.module.split(".")[0])
        self.assertFalse({"requests", "httpx", "aiohttp", "socket"} & imported)
        for marker in (
            "os.environ", "os.getenv", "class LiveAuthorityAnchor",
            "class _PreparedLiveCall", "def _claim_and_prepare",
            "def _consume_capability", "def _send_live", "def _send_prepared",
        ):
            self.assertNotIn(marker, source)
        parents = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parents[child] = parent
        opener_call_owners = []
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_opener"
            ):
                continue
            owner = parents.get(node)
            while owner is not None and not isinstance(owner, (ast.FunctionDef, ast.AsyncFunctionDef)):
                owner = parents.get(owner)
            opener_call_owners.append(None if owner is None else owner.name)
        self.assertEqual(opener_call_owners, ["run_next"])
        self.assertEqual(APPROVED_PATHS, ("b2/bm1.py", "schemas/bm1_live_smoke_manifest.schema.json", "cases/b2/public-safe/benchmark/bm1-live-smoke-manifest.json", "tests/test_b2_bm1.py", "docs/b2/bm1-live-multi-model.md"))


if __name__ == "__main__":
    unittest.main()
