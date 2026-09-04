from __future__ import annotations

import copy
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from b2.blind_handoff import (
    HandoffBinding,
    HandoffError,
    SMOKE_RAW,
    build_live_result_bundle,
    build_smoke_result_bundle,
    create_challenge_ack,
    create_input_payload,
    decrypt_input_payload,
    decrypt_return_envelope,
    encrypt_return_envelope,
    generate_rsa_keypair,
    sha256_hex,
    verify_challenge_ack,
    verify_result_bundle,
)


def make_material(mode="smoke"):
    input_private, input_public = generate_rsa_keypair()
    return_private, return_public = generate_rsa_keypair()
    context = "冻结上下文".encode("utf-8")
    prompt = "冻结问题".encode("utf-8")
    binding = HandoffBinding(
        workflow_run_id="33890000000",
        execution_head_sha="a" * 40,
        bridge_main_sha="901ba05b99c413d45415c474c71b5969c155dea1",
        input_public_key_sha256=sha256_hex(input_public),
        return_public_key_sha256=sha256_hex(return_public),
        context_sha256=sha256_hex(context),
        context_bytes=len(context),
        prompt_sha256=sha256_hex(prompt),
        prompt_bytes=len(prompt),
        mode=mode,
        evaluation_run_id="B2-HANDOFF-V5-SMOKE" if mode == "smoke" else "B2-DITING-Q1-R1",
    )
    return {
        "input_private": input_private,
        "input_public": input_public,
        "return_private": return_private,
        "return_public": return_public,
        "context": context,
        "prompt": prompt,
        "challenge": bytes(range(32)),
        "ack_key": bytes(range(32, 64)),
        "binding": binding,
    }


class BlindHandoffV5Tests(unittest.TestCase):
    def test_input_round_trip_is_bound_to_all_frozen_evidence(self):
        m = make_material()
        payload = create_input_payload(
            input_public_pem=m["input_public"],
            return_public_pem=m["return_public"],
            context=m["context"],
            prompt=m["prompt"],
            challenge=m["challenge"],
            ack_key=m["ack_key"],
            binding=m["binding"],
        )
        files = decrypt_input_payload(
            input_private_pem=m["input_private"],
            payload=payload,
            expected_binding=m["binding"],
        )
        self.assertEqual(m["context"], files["context.txt"])
        self.assertEqual(m["prompt"], files["prompt.txt"])
        self.assertEqual(m["return_public"], files["return-public.pem"])
        self.assertEqual(m["challenge"], files["challenge.bin"])
        self.assertEqual(m["ack_key"], files["ack-key.bin"])

    def test_outer_binding_tamper_fails_authentication(self):
        m = make_material()
        payload = create_input_payload(
            input_public_pem=m["input_public"],
            return_public_pem=m["return_public"],
            context=m["context"],
            prompt=m["prompt"],
            challenge=m["challenge"],
            ack_key=m["ack_key"],
            binding=m["binding"],
        )
        document = json.loads(payload)
        document["binding"]["execution_head_sha"] = "b" * 40
        tampered = json.dumps(document).encode()
        tampered_binding = HandoffBinding.from_mapping(document["binding"])
        with self.assertRaises(HandoffError):
            decrypt_input_payload(
                input_private_pem=m["input_private"],
                payload=tampered,
                expected_binding=tampered_binding,
            )

    def test_frozen_input_mismatch_is_rejected_before_encryption(self):
        m = make_material()
        changed = copy.copy(m["binding"])
        object.__setattr__(changed, "context_sha256", "0" * 64)
        with self.assertRaisesRegex(HandoffError, "context_sha256"):
            create_input_payload(
                input_public_pem=m["input_public"],
                return_public_pem=m["return_public"],
                context=m["context"],
                prompt=m["prompt"],
                challenge=m["challenge"],
                ack_key=m["ack_key"],
                binding=changed,
            )

    def test_return_key_challenge_and_hmac_ack_gate(self):
        m = make_material()
        envelope = encrypt_return_envelope(
            return_public_pem=m["return_public"],
            kind="challenge-response",
            binding=m["binding"],
            plaintext=m["challenge"],
        )
        recovered = decrypt_return_envelope(
            return_private_pem=m["return_private"],
            envelope_bytes=envelope,
            expected_kind="challenge-response",
            expected_binding=m["binding"],
        )
        self.assertEqual(m["challenge"], recovered)
        ack = create_challenge_ack(
            binding=m["binding"],
            challenge_envelope=envelope,
            challenge=m["challenge"],
            ack_key=m["ack_key"],
        )
        verify_challenge_ack(
            binding=m["binding"],
            challenge_envelope=envelope,
            challenge=m["challenge"],
            ack_key=m["ack_key"],
            acknowledgement=ack,
        )
        document = json.loads(ack)
        document["status"] = "FORGED"
        with self.assertRaises(HandoffError):
            verify_challenge_ack(
                binding=m["binding"],
                challenge_envelope=envelope,
                challenge=m["challenge"],
                ack_key=m["ack_key"],
                acknowledgement=json.dumps(document).encode(),
            )

    def test_no_provider_smoke_closes_the_full_return_loop(self):
        m = make_material(mode="smoke")
        bundle = build_smoke_result_bundle(m["binding"])
        envelope = encrypt_return_envelope(
            return_public_pem=m["return_public"],
            kind="encrypted-result",
            binding=m["binding"],
            plaintext=bundle,
        )
        recovered = decrypt_return_envelope(
            return_private_pem=m["return_private"],
            envelope_bytes=envelope,
            expected_kind="encrypted-result",
            expected_binding=m["binding"],
        )
        files, receipt = verify_result_bundle(binding=m["binding"], bundle=recovered)
        self.assertEqual("HANDOFF_SMOKE_PASS", receipt["terminal_status"])
        self.assertEqual(0, receipt["provider_attempts"])
        self.assertEqual(0, receipt["automatic_retries"])
        self.assertEqual(SMOKE_RAW, files["raw-answer.txt"])

    def test_live_pass_receipt_must_match_raw_answer_and_binding(self):
        m = make_material(mode="live")
        raw = "模型原始回答".encode("utf-8")
        receipt = {
            "run_id": m["binding"].evaluation_run_id,
            "terminal_status": "PASS",
            "context_sha256": f"sha256:{m['binding'].context_sha256}",
            "prompt_sha256": f"sha256:{m['binding'].prompt_sha256}",
            "context_bytes": m["binding"].context_bytes,
            "prompt_bytes": m["binding"].prompt_bytes,
            "automatic_retries": 0,
            "git_commit": m["binding"].bridge_main_sha,
            "raw_output_sha256": f"sha256:{sha256_hex(raw)}",
            "raw_output_bytes": len(raw),
        }
        bundle = build_live_result_bundle(
            binding=m["binding"],
            receipt_bytes=(json.dumps(receipt) + "\n").encode(),
            raw_answer=raw,
            bridge_stdout=(json.dumps(receipt) + "\n").encode(),
            bridge_exit_code=b"0\n",
        )
        files, checked = verify_result_bundle(binding=m["binding"], bundle=bundle)
        self.assertEqual("PASS", checked["terminal_status"])
        self.assertEqual(raw, files["raw-answer.txt"])

        bad_receipt = dict(receipt)
        bad_receipt["raw_output_bytes"] = len(raw) + 1
        with self.assertRaisesRegex(HandoffError, "raw answer"):
            build_live_result_bundle(
                binding=m["binding"],
                receipt_bytes=(json.dumps(bad_receipt) + "\n").encode(),
                raw_answer=raw,
                bridge_stdout=(json.dumps(bad_receipt) + "\n").encode(),
                bridge_exit_code=b"0\n",
            )

    def test_result_zip_with_duplicate_member_fails_closed(self):
        m = make_material(mode="smoke")
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w") as archive:
            archive.writestr("manifest.json", b"{}")
            archive.writestr("receipt.json", b"{}")
            archive.writestr("receipt.json", b"{}")
        with self.assertRaises(HandoffError):
            verify_result_bundle(binding=m["binding"], bundle=output.getvalue())

    def test_smoke_workflow_has_no_provider_lane_or_arbitrary_pointer(self):
        workflow = Path(".github/workflows/b2_blind_handoff_v5_smoke.yml").read_text()
        self.assertNotIn("DEEPSEEK_API_KEY", workflow)
        self.assertNotIn("payload_pointer", workflow)
        self.assertNotIn("curl -L", workflow)
        self.assertIn("blind-handoff/v5/${GITHUB_RUN_ID}/${INPUT_KEY_SHA}", workflow)
        self.assertIn("provider attempts stay zero", workflow.lower())


if __name__ == "__main__":
    unittest.main()
