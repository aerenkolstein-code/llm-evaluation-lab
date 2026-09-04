"""Run-bound, fail-closed handoff for private B2 blind-evaluation inputs.

Version 5 replaces the historical fixed pointer/URL rendezvous with one exact
repository path bound to the GitHub workflow run, execution head, bridge base,
ephemeral input key, frozen inputs, return key, and execution mode.  Private
bodies are always hybrid-encrypted; only fingerprints and protocol metadata may
cross the public lane.

The same module is used on both sides of the handoff.  ``prepare-input``,
``verify-challenge``, and ``verify-result`` run in the private orchestrator.
The remaining commands run in the ephemeral GitHub Actions worker.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import io
import json
import os
import re
import tempfile
import zipfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Mapping, Sequence

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


PROTOCOL_VERSION = "b2-blind-handoff/v5"
ENCRYPTION_ALGORITHM = "RSA-OAEP-SHA256+AES-256-GCM/v1"
MIN_RSA_BITS = 3072
MAX_ENVELOPE_BYTES = 4 * 1024 * 1024
MAX_ARCHIVE_BYTES = 3 * 1024 * 1024
SMOKE_RAW = b"B2-HANDOFF-V5-SYNTHETIC-RAW\n"
_HEX64_RE = re.compile(r"^[0-9a-f]{64}$")
_COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
_RUN_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


class HandoffError(ValueError):
    """A handoff artifact is malformed, unbound, or cryptographically invalid."""


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _json_bytes(value: object) -> bytes:
    return _canonical_json(value) + b"\n"


def _strict_keys(value: Mapping[str, object], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise HandoffError(
            f"{label} keys mismatch: missing={sorted(expected - actual)!r}, "
            f"extra={sorted(actual - expected)!r}"
        )


def _require_hex64(value: object, label: str) -> str:
    if not isinstance(value, str) or _HEX64_RE.fullmatch(value) is None:
        raise HandoffError(f"{label} must be a lowercase SHA-256 hex digest")
    return value


def _require_positive_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise HandoffError(f"{label} must be a positive integer")
    return value


def _b64e(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _b64d(value: object, label: str) -> bytes:
    if not isinstance(value, str):
        raise HandoffError(f"{label} must be base64 text")
    try:
        return base64.b64decode(value, validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise HandoffError(f"{label} is not valid base64") from exc


def _load_json_bytes(value: bytes, label: str) -> dict[str, object]:
    if len(value) > MAX_ENVELOPE_BYTES:
        raise HandoffError(f"{label} exceeds the bounded size")
    try:
        document = json.loads(value.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HandoffError(f"{label} is not valid UTF-8 JSON") from exc
    if not isinstance(document, dict):
        raise HandoffError(f"{label} must be a JSON object")
    return document


def _atomic_write(path: str | Path, value: bytes, *, mode: int = 0o600) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=target.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temp_path, mode)
        os.replace(temp_path, target)
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass


@dataclass(frozen=True)
class HandoffBinding:
    workflow_run_id: str
    execution_head_sha: str
    bridge_main_sha: str
    input_public_key_sha256: str
    return_public_key_sha256: str
    context_sha256: str
    context_bytes: int
    prompt_sha256: str
    prompt_bytes: int
    mode: str
    evaluation_run_id: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)

    def validate(self) -> "HandoffBinding":
        string_fields = (
            "workflow_run_id", "execution_head_sha", "bridge_main_sha",
            "input_public_key_sha256", "return_public_key_sha256",
            "context_sha256", "prompt_sha256", "mode", "evaluation_run_id",
        )
        if any(not isinstance(getattr(self, name), str) for name in string_fields):
            raise HandoffError("binding string fields must contain strings")
        if not self.workflow_run_id.isdigit() or int(self.workflow_run_id) <= 0:
            raise HandoffError("workflow_run_id must be a positive decimal identifier")
        for label, value in (
            ("execution_head_sha", self.execution_head_sha),
            ("bridge_main_sha", self.bridge_main_sha),
        ):
            if _COMMIT_RE.fullmatch(value) is None:
                raise HandoffError(f"{label} must be a lowercase 40-hex commit")
        for label, value in (
            ("input_public_key_sha256", self.input_public_key_sha256),
            ("return_public_key_sha256", self.return_public_key_sha256),
            ("context_sha256", self.context_sha256),
            ("prompt_sha256", self.prompt_sha256),
        ):
            _require_hex64(value, label)
        _require_positive_int(self.context_bytes, "context_bytes")
        _require_positive_int(self.prompt_bytes, "prompt_bytes")
        if self.mode not in {"smoke", "live"}:
            raise HandoffError("mode must be 'smoke' or 'live'")
        if _RUN_ID_RE.fullmatch(self.evaluation_run_id) is None:
            raise HandoffError("evaluation_run_id is not a safe identifier")
        return self

    @classmethod
    def from_mapping(cls, value: object) -> "HandoffBinding":
        if not isinstance(value, Mapping):
            raise HandoffError("binding must be an object")
        expected = set(cls.__dataclass_fields__)
        _strict_keys(value, expected, "binding")
        try:
            binding = cls(**dict(value))
        except TypeError as exc:
            raise HandoffError("binding has invalid field types") from exc
        return binding.validate()


def generate_rsa_keypair(bits: int = MIN_RSA_BITS) -> tuple[bytes, bytes]:
    if bits < MIN_RSA_BITS:
        raise HandoffError(f"RSA keys must contain at least {MIN_RSA_BITS} bits")
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=bits)
    private_pem = private_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    public_pem = private_key.public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return private_pem, public_pem


def _load_public_key(value: bytes) -> rsa.RSAPublicKey:
    try:
        key = serialization.load_pem_public_key(value)
    except (TypeError, ValueError) as exc:
        raise HandoffError("public key is not valid PEM") from exc
    if not isinstance(key, rsa.RSAPublicKey) or key.key_size < MIN_RSA_BITS:
        raise HandoffError(f"public key must be RSA with at least {MIN_RSA_BITS} bits")
    return key


def _load_private_key(value: bytes) -> rsa.RSAPrivateKey:
    try:
        key = serialization.load_pem_private_key(value, password=None)
    except (TypeError, ValueError) as exc:
        raise HandoffError("private key is not valid unencrypted PEM") from exc
    if not isinstance(key, rsa.RSAPrivateKey) or key.key_size < MIN_RSA_BITS:
        raise HandoffError(f"private key must be RSA with at least {MIN_RSA_BITS} bits")
    return key


def public_pem_from_private(private_pem: bytes) -> bytes:
    return _load_private_key(private_pem).public_key().public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def _hybrid_encrypt(public_pem: bytes, plaintext: bytes, aad: bytes) -> dict[str, str]:
    public_key = _load_public_key(public_pem)
    key = os.urandom(32)
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, aad)
    wrapped_key = public_key.encrypt(
        key,
        padding.OAEP(
            mgf=padding.MGF1(algorithm=hashes.SHA256()),
            algorithm=hashes.SHA256(),
            label=None,
        ),
    )
    return {
        "wrapped_key_b64": _b64e(wrapped_key),
        "nonce_b64": _b64e(nonce),
        "ciphertext_b64": _b64e(ciphertext),
    }


def _hybrid_decrypt(
    private_pem: bytes,
    encrypted: Mapping[str, object],
    aad: bytes,
) -> bytes:
    private_key = _load_private_key(private_pem)
    wrapped_key = _b64d(encrypted.get("wrapped_key_b64"), "wrapped_key_b64")
    nonce = _b64d(encrypted.get("nonce_b64"), "nonce_b64")
    ciphertext = _b64d(encrypted.get("ciphertext_b64"), "ciphertext_b64")
    if len(nonce) != 12 or len(ciphertext) > MAX_ENVELOPE_BYTES:
        raise HandoffError("encrypted payload has invalid bounded lengths")
    try:
        key = private_key.decrypt(
            wrapped_key,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None,
            ),
        )
        if len(key) != 32:
            raise HandoffError("unwrapped AES key has invalid length")
        return AESGCM(key).decrypt(nonce, ciphertext, aad)
    except HandoffError:
        raise
    except Exception as exc:
        raise HandoffError("encrypted payload authentication failed") from exc


def _zip_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o600 << 16
    return info


def _build_archive(kind: str, binding: HandoffBinding, files: Mapping[str, bytes]) -> bytes:
    if "manifest.json" in files or not files:
        raise HandoffError("archive files are invalid")
    inventory = {
        name: {"sha256": sha256_hex(value), "bytes": len(value)}
        for name, value in sorted(files.items())
    }
    manifest = {
        "protocol": PROTOCOL_VERSION,
        "kind": kind,
        "binding": binding.as_dict(),
        "files": inventory,
    }
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(_zip_info("manifest.json"), _json_bytes(manifest))
        for name, value in sorted(files.items()):
            if Path(name).name != name or name in {"", ".", ".."}:
                raise HandoffError("archive file names must be flat and safe")
            archive.writestr(_zip_info(name), value)
    result = output.getvalue()
    if len(result) > MAX_ARCHIVE_BYTES:
        raise HandoffError("archive exceeds the bounded size")
    return result


def _read_archive(
    value: bytes,
    *,
    expected_kind: str,
    expected_binding: HandoffBinding,
    expected_names: set[str],
) -> dict[str, bytes]:
    if len(value) > MAX_ARCHIVE_BYTES:
        raise HandoffError("archive exceeds the bounded size")
    try:
        with zipfile.ZipFile(io.BytesIO(value)) as archive:
            infos = archive.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                raise HandoffError("archive contains duplicate names")
            if set(names) != {"manifest.json", *expected_names}:
                raise HandoffError("archive member set mismatch")
            if (
                any(info.file_size > MAX_ARCHIVE_BYTES for info in infos)
                or sum(info.file_size for info in infos) > MAX_ARCHIVE_BYTES
            ):
                raise HandoffError("archive member exceeds the bounded size")
            files = {name: archive.read(name) for name in names}
    except (zipfile.BadZipFile, RuntimeError) as exc:
        raise HandoffError("decrypted payload is not a valid ZIP archive") from exc

    manifest = _load_json_bytes(files.pop("manifest.json"), "archive manifest")
    _strict_keys(manifest, {"protocol", "kind", "binding", "files"}, "archive manifest")
    if manifest["protocol"] != PROTOCOL_VERSION or manifest["kind"] != expected_kind:
        raise HandoffError("archive protocol or kind mismatch")
    if HandoffBinding.from_mapping(manifest["binding"]) != expected_binding:
        raise HandoffError("archive binding mismatch")
    inventory = manifest["files"]
    if not isinstance(inventory, Mapping) or set(inventory) != expected_names:
        raise HandoffError("archive inventory mismatch")
    for name, data in files.items():
        entry = inventory[name]
        if not isinstance(entry, Mapping):
            raise HandoffError("archive inventory entry must be an object")
        _strict_keys(entry, {"sha256", "bytes"}, f"archive inventory {name}")
        if entry["sha256"] != sha256_hex(data) or entry["bytes"] != len(data):
            raise HandoffError(f"archive member fingerprint mismatch: {name}")
    return files


def _input_header(binding: HandoffBinding) -> dict[str, object]:
    return {
        "protocol": PROTOCOL_VERSION,
        "kind": "encrypted-input",
        "algorithm": ENCRYPTION_ALGORITHM,
        "binding": binding.as_dict(),
    }


def create_input_payload(
    *,
    input_public_pem: bytes,
    return_public_pem: bytes,
    context: bytes,
    prompt: bytes,
    challenge: bytes,
    ack_key: bytes,
    binding: HandoffBinding,
) -> bytes:
    binding.validate()
    _load_public_key(input_public_pem)
    _load_public_key(return_public_pem)
    checks = {
        "input_public_key_sha256": sha256_hex(input_public_pem),
        "return_public_key_sha256": sha256_hex(return_public_pem),
        "context_sha256": sha256_hex(context),
        "context_bytes": len(context),
        "prompt_sha256": sha256_hex(prompt),
        "prompt_bytes": len(prompt),
    }
    for name, actual in checks.items():
        if getattr(binding, name) != actual:
            raise HandoffError(f"binding does not match {name}")
    if len(challenge) != 32 or len(ack_key) != 32:
        raise HandoffError("challenge and acknowledgement key must each be 32 bytes")
    archive = _build_archive(
        "input-package",
        binding,
        {
            "ack-key.bin": ack_key,
            "challenge.bin": challenge,
            "context.txt": context,
            "prompt.txt": prompt,
            "return-public.pem": return_public_pem,
        },
    )
    header = _input_header(binding)
    envelope = {**header, **_hybrid_encrypt(input_public_pem, archive, _canonical_json(header))}
    return _json_bytes(envelope)


def decrypt_input_payload(
    *,
    input_private_pem: bytes,
    payload: bytes,
    expected_binding: HandoffBinding,
) -> dict[str, bytes]:
    envelope = _load_json_bytes(payload, "input envelope")
    expected_keys = {
        "protocol", "kind", "algorithm", "binding",
        "wrapped_key_b64", "nonce_b64", "ciphertext_b64",
    }
    _strict_keys(envelope, expected_keys, "input envelope")
    binding = HandoffBinding.from_mapping(envelope["binding"])
    if binding != expected_binding:
        raise HandoffError("input envelope binding mismatch")
    header = _input_header(binding)
    for name, expected in header.items():
        if envelope[name] != expected:
            raise HandoffError(f"input envelope {name} mismatch")
    input_public_pem = public_pem_from_private(input_private_pem)
    if sha256_hex(input_public_pem) != binding.input_public_key_sha256:
        raise HandoffError("ephemeral input private key does not match binding")
    archive = _hybrid_decrypt(input_private_pem, envelope, _canonical_json(header))
    files = _read_archive(
        archive,
        expected_kind="input-package",
        expected_binding=binding,
        expected_names={
            "ack-key.bin", "challenge.bin", "context.txt", "prompt.txt",
            "return-public.pem",
        },
    )
    if len(files["challenge.bin"]) != 32 or len(files["ack-key.bin"]) != 32:
        raise HandoffError("private challenge material has invalid length")
    if sha256_hex(files["return-public.pem"]) != binding.return_public_key_sha256:
        raise HandoffError("return public key fingerprint mismatch")
    if (
        len(files["context.txt"]) != binding.context_bytes
        or sha256_hex(files["context.txt"]) != binding.context_sha256
        or len(files["prompt.txt"]) != binding.prompt_bytes
        or sha256_hex(files["prompt.txt"]) != binding.prompt_sha256
    ):
        raise HandoffError("decrypted frozen-input fingerprint mismatch")
    return files


def _return_header(
    *, kind: str, binding: HandoffBinding, plaintext: bytes,
) -> dict[str, object]:
    if kind not in {"challenge-response", "encrypted-result"}:
        raise HandoffError("unsupported return-envelope kind")
    return {
        "protocol": PROTOCOL_VERSION,
        "kind": kind,
        "algorithm": ENCRYPTION_ALGORITHM,
        "binding": binding.as_dict(),
        "plaintext_sha256": sha256_hex(plaintext),
        "plaintext_bytes": len(plaintext),
    }


def encrypt_return_envelope(
    *, return_public_pem: bytes, kind: str, binding: HandoffBinding, plaintext: bytes,
) -> bytes:
    binding.validate()
    if sha256_hex(return_public_pem) != binding.return_public_key_sha256:
        raise HandoffError("return public key does not match binding")
    header = _return_header(kind=kind, binding=binding, plaintext=plaintext)
    return _json_bytes({
        **header,
        **_hybrid_encrypt(return_public_pem, plaintext, _canonical_json(header)),
    })


def decrypt_return_envelope(
    *,
    return_private_pem: bytes,
    envelope_bytes: bytes,
    expected_kind: str,
    expected_binding: HandoffBinding,
) -> bytes:
    envelope = _load_json_bytes(envelope_bytes, "return envelope")
    expected_keys = {
        "protocol", "kind", "algorithm", "binding", "plaintext_sha256",
        "plaintext_bytes", "wrapped_key_b64", "nonce_b64", "ciphertext_b64",
    }
    _strict_keys(envelope, expected_keys, "return envelope")
    binding = HandoffBinding.from_mapping(envelope["binding"])
    if binding != expected_binding:
        raise HandoffError("return envelope binding mismatch")
    return_public_pem = public_pem_from_private(return_private_pem)
    if sha256_hex(return_public_pem) != binding.return_public_key_sha256:
        raise HandoffError("return private key does not match binding")
    if envelope["protocol"] != PROTOCOL_VERSION:
        raise HandoffError("return envelope protocol mismatch")
    if envelope["kind"] != expected_kind:
        raise HandoffError("return envelope kind mismatch")
    if envelope["algorithm"] != ENCRYPTION_ALGORITHM:
        raise HandoffError("return envelope algorithm mismatch")
    plaintext_sha256 = _require_hex64(envelope["plaintext_sha256"], "plaintext_sha256")
    plaintext_bytes = _require_positive_int(envelope["plaintext_bytes"], "plaintext_bytes")
    header = {
        "protocol": envelope["protocol"],
        "kind": envelope["kind"],
        "algorithm": envelope["algorithm"],
        "binding": binding.as_dict(),
        "plaintext_sha256": plaintext_sha256,
        "plaintext_bytes": plaintext_bytes,
    }
    plaintext = _hybrid_decrypt(return_private_pem, envelope, _canonical_json(header))
    if len(plaintext) != plaintext_bytes or sha256_hex(plaintext) != plaintext_sha256:
        raise HandoffError("return plaintext fingerprint mismatch")
    return plaintext


def create_challenge_ack(
    *,
    binding: HandoffBinding,
    challenge_envelope: bytes,
    challenge: bytes,
    ack_key: bytes,
) -> bytes:
    if len(challenge) != 32 or len(ack_key) != 32:
        raise HandoffError("challenge acknowledgement material has invalid length")
    body: dict[str, object] = {
        "protocol": PROTOCOL_VERSION,
        "kind": "challenge-ack",
        "status": "VERIFIED",
        "binding": binding.as_dict(),
        "challenge_envelope_sha256": sha256_hex(challenge_envelope),
        "challenge_plaintext_sha256": sha256_hex(challenge),
    }
    body["hmac_sha256"] = hmac.new(ack_key, _canonical_json(body), hashlib.sha256).hexdigest()
    return _json_bytes(body)


def verify_challenge_ack(
    *,
    binding: HandoffBinding,
    challenge_envelope: bytes,
    challenge: bytes,
    ack_key: bytes,
    acknowledgement: bytes,
) -> None:
    document = _load_json_bytes(acknowledgement, "challenge acknowledgement")
    expected_keys = {
        "protocol", "kind", "status", "binding", "challenge_envelope_sha256",
        "challenge_plaintext_sha256", "hmac_sha256",
    }
    _strict_keys(document, expected_keys, "challenge acknowledgement")
    supplied_mac = _require_hex64(document.pop("hmac_sha256"), "hmac_sha256")
    expected_mac = hmac.new(ack_key, _canonical_json(document), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(supplied_mac, expected_mac):
        raise HandoffError("challenge acknowledgement HMAC mismatch")
    if (
        document["protocol"] != PROTOCOL_VERSION
        or document["kind"] != "challenge-ack"
        or document["status"] != "VERIFIED"
        or HandoffBinding.from_mapping(document["binding"]) != binding
        or document["challenge_envelope_sha256"] != sha256_hex(challenge_envelope)
        or document["challenge_plaintext_sha256"] != sha256_hex(challenge)
    ):
        raise HandoffError("challenge acknowledgement binding mismatch")


def _validate_live_receipt(
    receipt_bytes: bytes,
    raw_answer: bytes | None,
    binding: HandoffBinding,
) -> dict[str, object]:
    receipt = _load_json_bytes(receipt_bytes, "blind-eval receipt")
    required = {
        "run_id", "terminal_status", "context_sha256", "prompt_sha256",
        "context_bytes", "prompt_bytes", "automatic_retries", "git_commit",
        "raw_output_sha256", "raw_output_bytes",
    }
    if not required.issubset(receipt):
        raise HandoffError("blind-eval receipt is missing required evidence fields")
    if (
        receipt["run_id"] != binding.evaluation_run_id
        or receipt["context_sha256"] != f"sha256:{binding.context_sha256}"
        or receipt["prompt_sha256"] != f"sha256:{binding.prompt_sha256}"
        or receipt["context_bytes"] != binding.context_bytes
        or receipt["prompt_bytes"] != binding.prompt_bytes
        or receipt["automatic_retries"] != 0
        or receipt["git_commit"] != binding.bridge_main_sha
    ):
        raise HandoffError("blind-eval receipt does not match handoff binding")
    status = receipt["terminal_status"]
    if status == "PASS":
        if raw_answer is None:
            raise HandoffError("PASS receipt has no raw answer")
        if (
            receipt["raw_output_sha256"] != f"sha256:{sha256_hex(raw_answer)}"
            or receipt["raw_output_bytes"] != len(raw_answer)
        ):
            raise HandoffError("raw answer does not match PASS receipt")
    elif status in {"NOT_EVALUABLE", "ERROR"}:
        if raw_answer is not None:
            raise HandoffError("non-PASS receipt must not include a raw answer")
        if receipt["raw_output_sha256"] is not None or receipt["raw_output_bytes"] is not None:
            raise HandoffError("non-PASS receipt carries raw-output evidence")
    else:
        raise HandoffError("blind-eval receipt has invalid terminal status")
    return receipt


def build_smoke_result_bundle(binding: HandoffBinding) -> bytes:
    if binding.mode != "smoke":
        raise HandoffError("smoke result requires a smoke binding")
    receipt = {
        "schema_version": "b2-blind-handoff-smoke/v1",
        "terminal_status": "HANDOFF_SMOKE_PASS",
        "provider_attempts": 0,
        "automatic_retries": 0,
        "context_sha256": binding.context_sha256,
        "context_bytes": binding.context_bytes,
        "prompt_sha256": binding.prompt_sha256,
        "prompt_bytes": binding.prompt_bytes,
        "raw_output_sha256": sha256_hex(SMOKE_RAW),
        "raw_output_bytes": len(SMOKE_RAW),
        "binding_sha256": sha256_hex(_canonical_json(binding.as_dict())),
    }
    return _build_archive(
        "result-package",
        binding,
        {
            "bridge-exit-code.txt": b"0\n",
            "raw-answer.txt": SMOKE_RAW,
            "receipt.json": _json_bytes(receipt),
        },
    )


def build_live_result_bundle(
    *,
    binding: HandoffBinding,
    receipt_bytes: bytes,
    raw_answer: bytes | None,
    bridge_stdout: bytes,
    bridge_exit_code: bytes,
) -> bytes:
    if binding.mode != "live":
        raise HandoffError("live result requires a live binding")
    receipt = _validate_live_receipt(receipt_bytes, raw_answer, binding)
    stdout_receipt = _load_json_bytes(bridge_stdout, "bridge stdout")
    if stdout_receipt != receipt:
        raise HandoffError("bridge stdout and committed receipt disagree")
    try:
        exit_code = int(bridge_exit_code.decode("ascii").strip())
    except (UnicodeDecodeError, ValueError) as exc:
        raise HandoffError("bridge exit code is invalid") from exc
    if exit_code not in {0, 2, 3}:
        raise HandoffError("bridge exit code is outside the protocol")
    expected_exit_code = {"PASS": 0, "NOT_EVALUABLE": 2, "ERROR": 3}[
        receipt["terminal_status"]
    ]
    if exit_code != expected_exit_code:
        raise HandoffError("bridge exit code disagrees with receipt terminal status")
    files = {
        "bridge-exit-code.txt": f"{exit_code}\n".encode("ascii"),
        "bridge-stdout.json": bridge_stdout,
        "receipt.json": receipt_bytes,
    }
    if raw_answer is not None:
        files["raw-answer.txt"] = raw_answer
    return _build_archive("result-package", binding, files)


def verify_result_bundle(
    *, binding: HandoffBinding, bundle: bytes,
) -> tuple[dict[str, bytes], dict[str, object]]:
    expected_names = {"bridge-exit-code.txt", "bridge-stdout.json", "receipt.json"}
    if binding.mode == "smoke":
        expected_names = {"bridge-exit-code.txt", "raw-answer.txt", "receipt.json"}
    else:
        # Inspect only the member names to decide whether PASS includes raw.
        try:
            with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
                if "raw-answer.txt" in archive.namelist():
                    expected_names.add("raw-answer.txt")
        except zipfile.BadZipFile as exc:
            raise HandoffError("result bundle is not a valid ZIP archive") from exc
    files = _read_archive(
        bundle,
        expected_kind="result-package",
        expected_binding=binding,
        expected_names=expected_names,
    )
    receipt = _load_json_bytes(files["receipt.json"], "result receipt")
    if binding.mode == "smoke":
        required = {
            "schema_version", "terminal_status", "provider_attempts",
            "automatic_retries", "context_sha256", "context_bytes",
            "prompt_sha256", "prompt_bytes", "raw_output_sha256",
            "raw_output_bytes", "binding_sha256",
        }
        _strict_keys(receipt, required, "smoke receipt")
        if (
            receipt["terminal_status"] != "HANDOFF_SMOKE_PASS"
            or receipt["provider_attempts"] != 0
            or receipt["automatic_retries"] != 0
            or files["raw-answer.txt"] != SMOKE_RAW
            or receipt["raw_output_sha256"] != sha256_hex(SMOKE_RAW)
            or receipt["raw_output_bytes"] != len(SMOKE_RAW)
            or receipt["context_sha256"] != binding.context_sha256
            or receipt["context_bytes"] != binding.context_bytes
            or receipt["prompt_sha256"] != binding.prompt_sha256
            or receipt["prompt_bytes"] != binding.prompt_bytes
            or receipt["binding_sha256"] != sha256_hex(_canonical_json(binding.as_dict()))
        ):
            raise HandoffError("smoke result evidence mismatch")
    else:
        receipt = _validate_live_receipt(files["receipt.json"], files.get("raw-answer.txt"), binding)
    return files, receipt


def _binding_from_file(path: str | Path) -> HandoffBinding:
    return HandoffBinding.from_mapping(
        _load_json_bytes(Path(path).read_bytes(), "binding file")
    )


def _state_binding(state_dir: str | Path) -> HandoffBinding:
    return _binding_from_file(Path(state_dir) / "binding.json")


def _expected_binding_from_args(args: argparse.Namespace, return_key_hash: str) -> HandoffBinding:
    return HandoffBinding(
        workflow_run_id=args.workflow_run_id,
        execution_head_sha=args.execution_head_sha,
        bridge_main_sha=args.bridge_main_sha,
        input_public_key_sha256=args.input_public_key_sha256,
        return_public_key_sha256=return_key_hash,
        context_sha256=args.context_sha256,
        context_bytes=args.context_bytes,
        prompt_sha256=args.prompt_sha256,
        prompt_bytes=args.prompt_bytes,
        mode=args.mode,
        evaluation_run_id=args.evaluation_run_id,
    ).validate()


def _add_binding_args(parser: argparse.ArgumentParser, *, include_input_key_hash: bool) -> None:
    parser.add_argument("--workflow-run-id", required=True)
    parser.add_argument("--execution-head-sha", required=True)
    parser.add_argument("--bridge-main-sha", required=True)
    if include_input_key_hash:
        parser.add_argument("--input-public-key-sha256", required=True)
    parser.add_argument("--context-sha256", required=True)
    parser.add_argument("--context-bytes", required=True, type=int)
    parser.add_argument("--prompt-sha256", required=True)
    parser.add_argument("--prompt-bytes", required=True, type=int)
    parser.add_argument("--mode", required=True, choices=("smoke", "live"))
    parser.add_argument("--evaluation-run-id", required=True)


def _cmd_generate_input_key(args: argparse.Namespace) -> dict[str, object]:
    private_pem, public_pem = generate_rsa_keypair()
    _atomic_write(args.private_key, private_pem)
    _atomic_write(args.public_key, public_pem, mode=0o644)
    fingerprint = sha256_hex(public_pem)
    _atomic_write(args.fingerprint_output, f"{fingerprint}\n".encode("ascii"), mode=0o644)
    return {"status": "INPUT_KEY_READY", "input_public_key_sha256": fingerprint}


def _cmd_prepare_input(args: argparse.Namespace) -> dict[str, object]:
    state = Path(args.state_dir)
    input_public = Path(args.input_public_key).read_bytes()
    context = Path(args.context_file).read_bytes()
    prompt = Path(args.prompt_file).read_bytes()
    if sha256_hex(input_public) != args.input_public_key_sha256:
        raise HandoffError("downloaded input public key fingerprint mismatch")
    return_private, return_public = generate_rsa_keypair()
    binding = _expected_binding_from_args(args, sha256_hex(return_public))
    if (
        sha256_hex(context) != binding.context_sha256
        or len(context) != binding.context_bytes
        or sha256_hex(prompt) != binding.prompt_sha256
        or len(prompt) != binding.prompt_bytes
    ):
        raise HandoffError("private frozen inputs do not match the authorized binding")
    challenge, ack_key = os.urandom(32), os.urandom(32)
    payload = create_input_payload(
        input_public_pem=input_public,
        return_public_pem=return_public,
        context=context,
        prompt=prompt,
        challenge=challenge,
        ack_key=ack_key,
        binding=binding,
    )
    for name, value in {
        "binding.json": _json_bytes(binding.as_dict()),
        "return-private.pem": return_private,
        "return-public.pem": return_public,
        "challenge.bin": challenge,
        "ack-key.bin": ack_key,
    }.items():
        _atomic_write(state / name, value)
    _atomic_write(args.payload_output, payload, mode=0o644)
    return {
        "status": "ENCRYPTED_INPUT_READY",
        "binding_sha256": sha256_hex(_canonical_json(binding.as_dict())),
        "payload_sha256": sha256_hex(payload),
    }


def _cmd_accept_input(args: argparse.Namespace) -> dict[str, object]:
    private_pem = Path(args.input_private_key).read_bytes()
    input_public_hash = sha256_hex(public_pem_from_private(private_pem))
    payload_document = _load_json_bytes(Path(args.payload).read_bytes(), "input envelope")
    payload_binding = HandoffBinding.from_mapping(payload_document.get("binding"))
    expected = _expected_binding_from_args(args, payload_binding.return_public_key_sha256)
    if expected.input_public_key_sha256 != input_public_hash:
        raise HandoffError("runner input key fingerprint does not match expected binding")
    files = decrypt_input_payload(
        input_private_pem=private_pem,
        payload=Path(args.payload).read_bytes(),
        expected_binding=expected,
    )
    state = Path(args.state_dir)
    for name, value in {
        "binding.json": _json_bytes(expected.as_dict()),
        "context.txt": files["context.txt"],
        "prompt.txt": files["prompt.txt"],
        "return-public.pem": files["return-public.pem"],
        "challenge.bin": files["challenge.bin"],
        "ack-key.bin": files["ack-key.bin"],
    }.items():
        _atomic_write(state / name, value)
    return {
        "status": "FROZEN_INPUT_ACCEPTED",
        "context_sha256": expected.context_sha256,
        "context_bytes": expected.context_bytes,
        "prompt_sha256": expected.prompt_sha256,
        "prompt_bytes": expected.prompt_bytes,
    }


def _cmd_encrypt_challenge(args: argparse.Namespace) -> dict[str, object]:
    state = Path(args.state_dir)
    binding = _state_binding(state)
    challenge = state.joinpath("challenge.bin").read_bytes()
    envelope = encrypt_return_envelope(
        return_public_pem=state.joinpath("return-public.pem").read_bytes(),
        kind="challenge-response",
        binding=binding,
        plaintext=challenge,
    )
    _atomic_write(args.output, envelope, mode=0o644)
    return {"status": "CHALLENGE_ENCRYPTED", "envelope_sha256": sha256_hex(envelope)}


def _cmd_verify_challenge(args: argparse.Namespace) -> dict[str, object]:
    state = Path(args.state_dir)
    binding = _state_binding(state)
    envelope = Path(args.challenge_envelope).read_bytes()
    challenge = state.joinpath("challenge.bin").read_bytes()
    actual = decrypt_return_envelope(
        return_private_pem=state.joinpath("return-private.pem").read_bytes(),
        envelope_bytes=envelope,
        expected_kind="challenge-response",
        expected_binding=binding,
    )
    if not hmac.compare_digest(actual, challenge):
        raise HandoffError("challenge round-trip plaintext mismatch")
    ack = create_challenge_ack(
        binding=binding,
        challenge_envelope=envelope,
        challenge=challenge,
        ack_key=state.joinpath("ack-key.bin").read_bytes(),
    )
    _atomic_write(args.ack_output, ack, mode=0o644)
    return {"status": "RETURN_KEY_PROVEN", "ack_sha256": sha256_hex(ack)}


def _cmd_verify_ack(args: argparse.Namespace) -> dict[str, object]:
    state = Path(args.state_dir)
    verify_challenge_ack(
        binding=_state_binding(state),
        challenge_envelope=Path(args.challenge_envelope).read_bytes(),
        challenge=state.joinpath("challenge.bin").read_bytes(),
        ack_key=state.joinpath("ack-key.bin").read_bytes(),
        acknowledgement=Path(args.acknowledgement).read_bytes(),
    )
    return {"status": "PROVIDER_GATE_OPEN"}


def _cmd_make_smoke_result(args: argparse.Namespace) -> dict[str, object]:
    state = Path(args.state_dir)
    binding = _state_binding(state)
    bundle = build_smoke_result_bundle(binding)
    envelope = encrypt_return_envelope(
        return_public_pem=state.joinpath("return-public.pem").read_bytes(),
        kind="encrypted-result",
        binding=binding,
        plaintext=bundle,
    )
    _atomic_write(args.output, envelope, mode=0o644)
    return {
        "status": "SMOKE_RESULT_ENCRYPTED",
        "provider_attempts": 0,
        "result_sha256": sha256_hex(envelope),
    }


def _cmd_make_live_result(args: argparse.Namespace) -> dict[str, object]:
    state = Path(args.state_dir)
    binding = _state_binding(state)
    raw_path = Path(args.raw_answer)
    raw = raw_path.read_bytes() if raw_path.exists() else None
    bundle = build_live_result_bundle(
        binding=binding,
        receipt_bytes=Path(args.receipt).read_bytes(),
        raw_answer=raw,
        bridge_stdout=Path(args.bridge_stdout).read_bytes(),
        bridge_exit_code=Path(args.bridge_exit_code).read_bytes(),
    )
    envelope = encrypt_return_envelope(
        return_public_pem=state.joinpath("return-public.pem").read_bytes(),
        kind="encrypted-result",
        binding=binding,
        plaintext=bundle,
    )
    _atomic_write(args.output, envelope, mode=0o644)
    return {"status": "LIVE_RESULT_ENCRYPTED", "result_sha256": sha256_hex(envelope)}


def _cmd_verify_result(args: argparse.Namespace) -> dict[str, object]:
    state = Path(args.state_dir)
    binding = _state_binding(state)
    envelope = Path(args.result_envelope).read_bytes()
    bundle = decrypt_return_envelope(
        return_private_pem=state.joinpath("return-private.pem").read_bytes(),
        envelope_bytes=envelope,
        expected_kind="encrypted-result",
        expected_binding=binding,
    )
    files, receipt = verify_result_bundle(binding=binding, bundle=bundle)
    output = Path(args.output_dir)
    for name, value in files.items():
        _atomic_write(output / name, value)
    return {
        "status": "RESULT_VERIFIED",
        "mode": binding.mode,
        "terminal_status": receipt["terminal_status"],
        "provider_attempts": receipt.get("provider_attempts"),
        "result_envelope_sha256": sha256_hex(envelope),
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m b2.blind_handoff")
    commands = parser.add_subparsers(dest="command", required=True)

    key = commands.add_parser("generate-input-key")
    key.add_argument("--private-key", required=True)
    key.add_argument("--public-key", required=True)
    key.add_argument("--fingerprint-output", required=True)
    key.set_defaults(handler=_cmd_generate_input_key)

    prepare = commands.add_parser("prepare-input")
    prepare.add_argument("--input-public-key", required=True)
    prepare.add_argument("--context-file", required=True)
    prepare.add_argument("--prompt-file", required=True)
    prepare.add_argument("--state-dir", required=True)
    prepare.add_argument("--payload-output", required=True)
    _add_binding_args(prepare, include_input_key_hash=True)
    prepare.set_defaults(handler=_cmd_prepare_input)

    accept = commands.add_parser("accept-input")
    accept.add_argument("--input-private-key", required=True)
    accept.add_argument("--payload", required=True)
    accept.add_argument("--state-dir", required=True)
    _add_binding_args(accept, include_input_key_hash=True)
    accept.set_defaults(handler=_cmd_accept_input)

    challenge = commands.add_parser("encrypt-challenge")
    challenge.add_argument("--state-dir", required=True)
    challenge.add_argument("--output", required=True)
    challenge.set_defaults(handler=_cmd_encrypt_challenge)

    verify_challenge = commands.add_parser("verify-challenge")
    verify_challenge.add_argument("--state-dir", required=True)
    verify_challenge.add_argument("--challenge-envelope", required=True)
    verify_challenge.add_argument("--ack-output", required=True)
    verify_challenge.set_defaults(handler=_cmd_verify_challenge)

    verify_ack = commands.add_parser("verify-ack")
    verify_ack.add_argument("--state-dir", required=True)
    verify_ack.add_argument("--challenge-envelope", required=True)
    verify_ack.add_argument("--acknowledgement", required=True)
    verify_ack.set_defaults(handler=_cmd_verify_ack)

    smoke = commands.add_parser("make-smoke-result")
    smoke.add_argument("--state-dir", required=True)
    smoke.add_argument("--output", required=True)
    smoke.set_defaults(handler=_cmd_make_smoke_result)

    live = commands.add_parser("make-live-result")
    live.add_argument("--state-dir", required=True)
    live.add_argument("--receipt", required=True)
    live.add_argument("--raw-answer", required=True)
    live.add_argument("--bridge-stdout", required=True)
    live.add_argument("--bridge-exit-code", required=True)
    live.add_argument("--output", required=True)
    live.set_defaults(handler=_cmd_make_live_result)

    result = commands.add_parser("verify-result")
    result.add_argument("--state-dir", required=True)
    result.add_argument("--result-envelope", required=True)
    result.add_argument("--output-dir", required=True)
    result.set_defaults(handler=_cmd_verify_result)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        report = args.handler(args)
    except (HandoffError, OSError) as exc:
        raise SystemExit(f"blind-handoff failed closed: {exc}") from exc
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
