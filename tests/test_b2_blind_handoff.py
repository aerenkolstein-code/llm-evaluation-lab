from __future__ import annotations

import copy
import hashlib
import hmac
import io
import json
import os
import tempfile
import unittest
import zipfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

from b2.blind_handoff import (
    HandoffBinding,
    HandoffError,
    PROTOCOL_VERSION,
    SMOKE_RAW,
    _canonical_json,
    _claim_once,
    _commit_new_directory,
    _cmd_generate_input_key,
    build_live_result_bundle,
    build_smoke_result_bundle,
    cleanup_ephemeral_tree,
    create_challenge_ack,
    create_input_payload,
    decrypt_input_payload,
    decrypt_return_envelope,
    deterministic_smoke_receipt,
    encrypt_return_envelope,
    generate_rsa_keypair,
    sha256_hex,
    verify_challenge_ack,
    verify_result_bundle,
)


NOW = 1_800_000_000
_INPUT_PRIVATE, _INPUT_PUBLIC = generate_rsa_keypair()
_RETURN_PRIVATE, _RETURN_PUBLIC = generate_rsa_keypair()


def make_material(mode: str = "smoke") -> dict[str, object]:
    context = "冻结上下文".encode("utf-8")
    prompt = "冻结问题".encode("utf-8")
    binding = HandoffBinding(
        handoff_id="synthetic-handoff-33890000000-001",
        workflow_run_id="33890000000",
        execution_head_sha="a" * 40,
        bridge_main_sha="901ba05b99c413d45415c474c71b5969c155dea1",
        input_public_key_sha256=sha256_hex(_INPUT_PUBLIC),
        return_public_key_sha256=sha256_hex(_RETURN_PUBLIC),
        context_sha256=sha256_hex(context),
        context_bytes=len(context),
        prompt_sha256=sha256_hex(prompt),
        prompt_bytes=len(prompt),
        mode=mode,
        evaluation_run_id=(
            "B2-HANDOFF-V5-SMOKE" if mode == "smoke" else "B2-DITING-Q1-R1"
        ),
        issued_at_unix=NOW,
        expires_at_unix=NOW + 3600,
    )
    return {
        "input_private": _INPUT_PRIVATE,
        "input_public": _INPUT_PUBLIC,
        "return_private": _RETURN_PRIVATE,
        "return_public": _RETURN_PUBLIC,
        "context": context,
        "prompt": prompt,
        "runner_challenge": bytes(range(32)),
        "ack_key": bytes(range(32, 64)),
        "binding": binding,
    }


def make_payload(material: dict[str, object]) -> bytes:
    return create_input_payload(
        input_public_pem=material["input_public"],
        return_public_pem=material["return_public"],
        context=material["context"],
        prompt=material["prompt"],
        ack_key=material["ack_key"],
        binding=material["binding"],
        now_unix=NOW,
    )


def live_receipt(
    binding: HandoffBinding,
    *,
    status: str,
    raw: bytes | None,
    reasoning: bytes | None = None,
) -> dict[str, object]:
    final_hash = f"sha256:{sha256_hex(raw)}" if raw else None
    reasoning_hash = f"sha256:{sha256_hex(reasoning)}" if reasoning else None
    return {
        "run_id": binding.evaluation_run_id,
        "terminal_status": status,
        "context_sha256": f"sha256:{binding.context_sha256}",
        "prompt_sha256": f"sha256:{binding.prompt_sha256}",
        "context_bytes": binding.context_bytes,
        "prompt_bytes": binding.prompt_bytes,
        "provider_attempts": 1,
        "automatic_retries": 0,
        "git_commit": binding.bridge_main_sha,
        "raw_output_sha256": final_hash,
        "raw_output_bytes": len(raw) if raw else None,
        "http_status": 200,
        "requested_model_id": "fixture-model",
        "resolved_model_id": "fixture-model-resolved",
        "provider_response_id": "resp-123",
        "finish_reason": "stop" if raw else "length",
        "response_json_parsed": True,
        "response_schema_parsed": True,
        "message_schema_parsed": True,
        "reasoning_field_present": reasoning is not None,
        "reasoning_bytes": len(reasoning) if reasoning is not None else None,
        "reasoning_sha256": reasoning_hash,
        "final_content_field_present": True,
        "final_content_bytes": len(raw) if raw is not None else 0,
        "final_content_sha256": final_hash,
        "usage": {"total_tokens": 12},
        "quality_score": None,
        "error_code": None if raw else "EMPTY_FINAL_CONTENT",
    }


class BlindHandoffV5Tests(unittest.TestCase):
    def test_input_round_trip_is_bound_to_all_frozen_evidence(self):
        material = make_material()
        files = decrypt_input_payload(
            input_private_pem=material["input_private"],
            payload=make_payload(material),
            expected_binding=material["binding"],
            now_unix=NOW,
        )
        self.assertEqual(material["context"], files["context.txt"])
        self.assertEqual(material["prompt"], files["prompt.txt"])
        self.assertEqual(material["return_public"], files["return-public.pem"])
        self.assertNotIn("challenge.bin", files)
        self.assertEqual(material["ack_key"], files["ack-key.bin"])

    def test_every_identity_mismatch_is_rejected(self):
        material = make_material()
        payload = make_payload(material)
        binding = material["binding"]
        variants = {
            "workflow run": replace(binding, workflow_run_id="33890000001"),
            "execution head": replace(binding, execution_head_sha="b" * 40),
            "bridge main": replace(binding, bridge_main_sha="c" * 40),
            "input key": replace(binding, input_public_key_sha256="d" * 64),
            "return key": replace(binding, return_public_key_sha256="e" * 64),
            "context hash": replace(binding, context_sha256="f" * 64),
            "context bytes": replace(binding, context_bytes=binding.context_bytes + 1),
            "prompt hash": replace(binding, prompt_sha256="0" * 64),
            "prompt bytes": replace(binding, prompt_bytes=binding.prompt_bytes + 1),
            "mode": replace(binding, mode="live"),
            "evaluation run": replace(binding, evaluation_run_id="OTHER-RUN"),
            "handoff": replace(binding, handoff_id="synthetic-handoff-other-002"),
        }
        for label, wrong in variants.items():
            with self.subTest(label=label), self.assertRaises(HandoffError):
                decrypt_input_payload(
                    input_private_pem=material["input_private"],
                    payload=payload,
                    expected_binding=wrong,
                    now_unix=NOW,
                )

    def test_wrong_input_private_key_is_rejected(self):
        material = make_material()
        other_private, _ = generate_rsa_keypair()
        with self.assertRaises(HandoffError):
            decrypt_input_payload(
                input_private_pem=other_private,
                payload=make_payload(material),
                expected_binding=material["binding"],
                now_unix=NOW,
            )

    def test_outer_binding_tamper_fails_authentication(self):
        material = make_material()
        document = json.loads(make_payload(material))
        document["binding"]["execution_head_sha"] = "b" * 40
        tampered = json.dumps(document).encode()
        tampered_binding = HandoffBinding.from_mapping(document["binding"])
        with self.assertRaises(HandoffError):
            decrypt_input_payload(
                input_private_pem=material["input_private"],
                payload=tampered,
                expected_binding=tampered_binding,
                now_unix=NOW,
            )

    def test_frozen_input_mismatch_is_rejected_before_encryption(self):
        material = make_material()
        changed = copy.copy(material["binding"])
        object.__setattr__(changed, "context_sha256", "0" * 64)
        with self.assertRaisesRegex(HandoffError, "context_sha256"):
            create_input_payload(
                input_public_pem=material["input_public"],
                return_public_pem=material["return_public"],
                context=material["context"],
                prompt=material["prompt"],
                ack_key=material["ack_key"],
                binding=changed,
                now_unix=NOW,
            )

    def test_stale_payload_challenge_ack_and_result_are_rejected(self):
        material = make_material()
        binding = material["binding"]
        payload = make_payload(material)
        challenge_envelope = encrypt_return_envelope(
            return_public_pem=material["return_public"],
            kind="challenge-response",
            binding=binding,
            plaintext=material["runner_challenge"],
            now_unix=NOW,
        )
        ack = create_challenge_ack(
            binding=binding,
            challenge_envelope=challenge_envelope,
            challenge=material["runner_challenge"],
            ack_key=material["ack_key"],
            now_unix=NOW,
        )
        result = encrypt_return_envelope(
            return_public_pem=material["return_public"],
            kind="encrypted-result",
            binding=binding,
            plaintext=build_smoke_result_bundle(binding, now_unix=NOW),
            now_unix=NOW,
        )
        stale = binding.expires_at_unix
        with self.assertRaisesRegex(HandoffError, "stale"):
            decrypt_input_payload(
                input_private_pem=material["input_private"], payload=payload,
                expected_binding=binding, now_unix=stale,
            )
        with self.assertRaisesRegex(HandoffError, "stale"):
            verify_challenge_ack(
                binding=binding, challenge_envelope=challenge_envelope,
                challenge=material["runner_challenge"], ack_key=material["ack_key"],
                acknowledgement=ack, now_unix=stale,
            )
        with self.assertRaisesRegex(HandoffError, "stale"):
            decrypt_return_envelope(
                return_private_pem=material["return_private"], envelope_bytes=result,
                expected_kind="encrypted-result", expected_binding=binding,
                now_unix=stale,
            )

    def test_return_key_challenge_and_hmac_ack_gate(self):
        material = make_material()
        binding = material["binding"]
        envelope = encrypt_return_envelope(
            return_public_pem=material["return_public"],
            kind="challenge-response", binding=binding,
            plaintext=material["runner_challenge"], now_unix=NOW,
        )
        recovered = decrypt_return_envelope(
            return_private_pem=material["return_private"], envelope_bytes=envelope,
            expected_kind="challenge-response", expected_binding=binding,
            now_unix=NOW,
        )
        self.assertEqual(material["runner_challenge"], recovered)
        ack = create_challenge_ack(
            binding=binding, challenge_envelope=envelope,
            challenge=recovered, ack_key=material["ack_key"],
            now_unix=NOW,
        )
        verify_challenge_ack(
            binding=binding, challenge_envelope=envelope,
            challenge=material["runner_challenge"], ack_key=material["ack_key"],
            acknowledgement=ack, now_unix=NOW,
        )
        forged = json.loads(ack)
        forged["status"] = "FORGED"
        with self.assertRaises(HandoffError):
            verify_challenge_ack(
                binding=binding, challenge_envelope=envelope,
                challenge=material["runner_challenge"], ack_key=material["ack_key"],
                acknowledgement=json.dumps(forged).encode(), now_unix=NOW,
            )

    def test_ack_requires_return_private_key_not_only_preshared_material(self):
        material = make_material()
        binding = material["binding"]
        accepted = decrypt_input_payload(
            input_private_pem=material["input_private"],
            payload=make_payload(material),
            expected_binding=binding,
            now_unix=NOW,
        )
        self.assertNotIn("challenge.bin", accepted)

        runner_challenge = material["runner_challenge"]
        envelope = encrypt_return_envelope(
            return_public_pem=material["return_public"],
            kind="challenge-response",
            binding=binding,
            plaintext=runner_challenge,
            now_unix=NOW,
        )
        envelope_document = json.loads(envelope)

        # This is the exact forgery enabled by v5.1: all fields needed for the
        # acknowledgement were public or pre-shared, so no decryption was
        # necessary. v5.2 authenticates the unrevealed plaintext bytes too.
        forged_body = {
            "protocol": PROTOCOL_VERSION,
            "kind": "challenge-ack",
            "status": "VERIFIED",
            "binding": binding.as_dict(),
            "challenge_envelope_sha256": sha256_hex(envelope),
            "challenge_plaintext_sha256": envelope_document["plaintext_sha256"],
        }
        forged_body["hmac_sha256"] = hmac.new(
            material["ack_key"], _canonical_json(forged_body), hashlib.sha256
        ).hexdigest()
        with self.assertRaisesRegex(HandoffError, "HMAC mismatch"):
            verify_challenge_ack(
                binding=binding,
                challenge_envelope=envelope,
                challenge=runner_challenge,
                ack_key=material["ack_key"],
                acknowledgement=(json.dumps(forged_body) + "\n").encode(),
                now_unix=NOW,
            )

        wrong_private, _ = generate_rsa_keypair()
        with self.assertRaises(HandoffError):
            decrypt_return_envelope(
                return_private_pem=wrong_private,
                envelope_bytes=envelope,
                expected_kind="challenge-response",
                expected_binding=binding,
                now_unix=NOW,
            )

    def test_claims_are_one_time_and_replay_fails_closed(self):
        material = make_material()
        with tempfile.TemporaryDirectory() as parent:
            state = Path(parent) / "state"
            _commit_new_directory(
                state, {"binding.json": json.dumps(material["binding"].as_dict()).encode()}
            )
            _claim_once(
                state, "ack-accepted", binding=material["binding"], artifact=b"ack"
            )
            with self.assertRaisesRegex(HandoffError, "replayed|colliding"):
                _claim_once(
                    state, "ack-accepted", binding=material["binding"], artifact=b"ack"
                )

    def test_partial_state_and_path_alias_fail_closed(self):
        with tempfile.TemporaryDirectory() as parent:
            state = Path(parent) / "state"
            state.mkdir()
            (state / "partial").write_text("partial")
            with self.assertRaisesRegex(HandoffError, "already exists"):
                _commit_new_directory(state, {"complete": b"value"})
            alias = Path(parent) / "alias"
            alias.symlink_to(state, target_is_directory=True)
            with self.assertRaisesRegex(HandoffError, "symbolic link"):
                _commit_new_directory(alias, {"complete": b"value"})

    def test_key_publication_collision_rolls_back_new_partial_files(self):
        with tempfile.TemporaryDirectory() as parent:
            private = Path(parent) / "input-private.pem"
            public = Path(parent) / "input-public.pem"
            fingerprint = Path(parent) / "input-public.sha256"
            public.write_bytes(b"preexisting-public-evidence")
            args = SimpleNamespace(
                private_key=str(private),
                public_key=str(public),
                fingerprint_output=str(fingerprint),
            )
            with self.assertRaisesRegex(HandoffError, "replayed|colliding"):
                _cmd_generate_input_key(args)
            self.assertFalse(private.exists())
            self.assertEqual(b"preexisting-public-evidence", public.read_bytes())
            self.assertFalse(fingerprint.exists())

    def test_cleanup_is_verified_and_failure_is_explicit(self):
        parent = tempfile.mkdtemp()
        root = Path(parent) / "ephemeral"
        root.mkdir()
        (root / "private.tmp").write_text("synthetic")
        cleanup_ephemeral_tree(root)
        self.assertFalse(root.exists())
        os.rmdir(parent)

        with tempfile.TemporaryDirectory() as parent2:
            failed = Path(parent2) / "ephemeral"
            failed.mkdir()
            (failed / "private.tmp").write_text("synthetic")

            def reject_unlink(_path):
                raise OSError("fixture cleanup failure")

            with self.assertRaisesRegex(HandoffError, "cleanup failed"):
                cleanup_ephemeral_tree(failed, unlink_fn=reject_unlink)
            self.assertTrue(failed.exists())

    def test_no_provider_smoke_closes_the_full_return_loop(self):
        material = make_material(mode="smoke")
        binding = material["binding"]
        bundle = build_smoke_result_bundle(binding, now_unix=NOW)
        envelope = encrypt_return_envelope(
            return_public_pem=material["return_public"], kind="encrypted-result",
            binding=binding, plaintext=bundle, now_unix=NOW,
        )
        recovered = decrypt_return_envelope(
            return_private_pem=material["return_private"], envelope_bytes=envelope,
            expected_kind="encrypted-result", expected_binding=binding, now_unix=NOW,
        )
        files, receipt = verify_result_bundle(
            binding=binding, bundle=recovered, now_unix=NOW
        )
        self.assertEqual("HANDOFF_SMOKE_PASS", receipt["terminal_status"])
        self.assertEqual(0, receipt["provider_attempts"])
        self.assertEqual(0, receipt["automatic_retries"])
        self.assertEqual(SMOKE_RAW, files["raw-answer.txt"])

    def test_deterministic_smoke_proves_decryptability_and_cleanup(self):
        with tempfile.TemporaryDirectory() as parent:
            root = Path(parent) / "smoke"
            receipt = deterministic_smoke_receipt(
                work_root=root, workflow_run_id="33890000000",
                execution_head_sha="a" * 40,
                bridge_main_sha="901ba05b99c413d45415c474c71b5969c155dea1",
                now_unix=NOW,
            )
            self.assertEqual(
                "b2-blind-handoff-offline-smoke/v2", receipt["schema_version"]
            )
            self.assertEqual("HANDOFF_SMOKE_PASS", receipt["terminal_status"])
            self.assertEqual(0, receipt["provider_attempts"])
            self.assertEqual(0, receipt["credential_lookups"])
            self.assertEqual(0, receipt["automatic_retries"])
            self.assertTrue(receipt["return_decryptability_proven"])
            self.assertTrue(receipt["return_private_key_possession_proven"])
            self.assertTrue(receipt["cleanup_completed"])
            self.assertFalse(root.exists())

    def test_live_pass_receipt_matches_raw_and_diagnostic_evidence(self):
        material = make_material(mode="live")
        binding = material["binding"]
        raw = "模型原始回答".encode("utf-8")
        receipt = live_receipt(binding, status="PASS", raw=raw)
        encoded = (json.dumps(receipt) + "\n").encode()
        bundle = build_live_result_bundle(
            binding=binding, receipt_bytes=encoded, raw_answer=raw,
            bridge_stdout=encoded, bridge_exit_code=b"0\n", now_unix=NOW,
        )
        files, checked = verify_result_bundle(
            binding=binding, bundle=bundle, now_unix=NOW
        )
        self.assertEqual("PASS", checked["terminal_status"])
        self.assertEqual(raw, files["raw-answer.txt"])
        bad = dict(receipt)
        bad["raw_output_bytes"] = len(raw) + 1
        bad_encoded = (json.dumps(bad) + "\n").encode()
        with self.assertRaisesRegex(HandoffError, "raw answer"):
            build_live_result_bundle(
                binding=binding, receipt_bytes=bad_encoded, raw_answer=raw,
                bridge_stdout=bad_encoded, bridge_exit_code=b"0\n", now_unix=NOW,
            )

    def test_reasoning_only_empty_final_remains_not_evaluable(self):
        material = make_material(mode="live")
        binding = material["binding"]
        reasoning = "私有推理正文".encode("utf-8")
        receipt = live_receipt(
            binding, status="NOT_EVALUABLE", raw=None, reasoning=reasoning
        )
        encoded = (json.dumps(receipt) + "\n").encode()
        bundle = build_live_result_bundle(
            binding=binding, receipt_bytes=encoded, raw_answer=None,
            bridge_stdout=encoded, bridge_exit_code=b"2\n", now_unix=NOW,
        )
        files, checked = verify_result_bundle(
            binding=binding, bundle=bundle, now_unix=NOW
        )
        self.assertEqual("NOT_EVALUABLE", checked["terminal_status"])
        self.assertEqual("EMPTY_FINAL_CONTENT", checked["error_code"])
        self.assertIsNone(checked["quality_score"])
        self.assertNotIn("raw-answer.txt", files)
        self.assertNotIn(reasoning.decode(), encoded.decode())

    def test_private_body_field_and_unsanitized_id_are_rejected(self):
        material = make_material(mode="live")
        binding = material["binding"]
        receipt = live_receipt(binding, status="NOT_EVALUABLE", raw=None)
        for field, value in (
            ("reasoning_content", "private body"),
            ("provider_response_id", "https://private.invalid/id"),
        ):
            candidate = dict(receipt)
            candidate[field] = value
            encoded = (json.dumps(candidate) + "\n").encode()
            with self.subTest(field=field), self.assertRaises(HandoffError):
                build_live_result_bundle(
                    binding=binding, receipt_bytes=encoded, raw_answer=None,
                    bridge_stdout=encoded, bridge_exit_code=b"2\n", now_unix=NOW,
                )

    def test_result_zip_with_duplicate_member_fails_closed(self):
        material = make_material(mode="smoke")
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("manifest.json", b"{}")
            archive.writestr("receipt.json", b"{}")
            archive.writestr("receipt.json", b"{}")
        with self.assertRaises(HandoffError):
            verify_result_bundle(
                binding=material["binding"], bundle=output.getvalue(), now_unix=NOW
            )

    def test_review_workflows_cannot_call_provider(self):
        smoke_path = Path(".github/workflows/b2_blind_handoff_v5_smoke.yml")
        live_path = Path(".github/workflows/b2_blind_handoff_v5_live.yml")
        smoke_workflow = smoke_path.read_text()
        live_workflow = live_path.read_text()
        live_trigger = live_workflow.split("on:\n", 1)[1].split("\npermissions:", 1)[0]
        self.assertRegex(live_trigger, r"^  workflow_dispatch:\n")
        for forbidden_trigger in (
            "push:", "pull_request:", "schedule:", "repository_dispatch:",
            "workflow_run:",
        ):
            self.assertNotIn(forbidden_trigger, live_trigger)
        self.assertNotIn("secrets.", smoke_workflow)
        self.assertNotIn("--authorize-live-call", smoke_workflow)
        self.assertNotIn("python -m b2.blind_eval", smoke_workflow)
        self.assertNotIn("agent/b2-blind-handoff-v5-q1-20260904", smoke_workflow)
        self.assertIn("provider_attempts", smoke_workflow)
        self.assertIn("credential_lookups", smoke_workflow)

    def test_final_tree_has_no_real_run_scoped_payload_or_ack(self):
        root = Path("blind-handoff/v5")
        real_files = [] if not root.exists() else [
            path for path in root.rglob("*")
            if path.name in {"payload.json", "challenge-ack.json"}
        ]
        self.assertEqual([], real_files)

    def test_protocol_and_ci_dependency_are_documented(self):
        self.assertEqual("b2-blind-handoff/v5.2", PROTOCOL_VERSION)
        workflow = Path(".github/workflows/test.yml").read_text()
        docs = Path("docs/b2/blind-handoff-v5.md").read_text()
        self.assertIn("[blind-handoff]", workflow)
        self.assertIn("test.yml", docs)
        self.assertIn("payload has been accepted, the runner generates", docs)
        self.assertIn("unrevealed raw challenge", docs)


if __name__ == "__main__":
    unittest.main()
