"""Production orchestration for the guarded BM1 RUN-READY and live lanes.

This outer runtime owns GitHub event validation, credential *presence* checks,
storage-Authority refresh, and receipt assembly.  It deliberately owns no
network primitive: the only provider send remains inside ``BM1Runner.run_next``.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import re
import stat
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Sequence

from .bm1 import (
    BM1AuthorizationError,
    BM1Runner,
    CLAIM_STORE_STORAGE_KIND,
    FileAttemptClaimStore,
    FileRawEvidenceSink,
    GOOGLE_COMPETING_CREDENTIAL_REFERENCE,
    GOOGLE_CREDENTIAL_REFERENCE,
    GOOGLE_PROVIDER_ID,
    GoogleInteractionsHTTPTransport,
    LIVE_AUTH_SCHEMA_VERSION,
    MAX_PLANNED_ATTEMPTS,
    MAX_TOTAL_SMOKE_SPEND_USD,
    OPENAI_CREDENTIAL_REFERENCE,
    OPENAI_PROVIDER_ID,
    OpenAIResponsesHTTPTransport,
    RAW_BUNDLE_STORAGE_KIND,
    RUN_READY_SCHEMA_VERSION,
    build_live_authorization_fingerprint,
    build_run_ready_receipt_fingerprint,
    build_storage_authority_fingerprint,
    load_manifest_from_repo_root,
    validate_run_ready_receipt,
    validate_symbolic_credential_presence,
)
from .qa0 import assert_public_safe, sha256_json


WORK_ORDER = "WO-B2-BM1-RUNREADY-RECOVERY-01 v0.1"
REPOSITORY = "aerenkolstein-code/llm-evaluation-lab"
OWNER_LOGIN = "aerenkolstein-code"
CONTROL_ISSUE_NUMBER = 50
RUN_READY_WORKFLOW_PATH = ".github/workflows/b2_bm1_run_ready.yml"
LIVE_WORKFLOW_PATH = ".github/workflows/b2_bm1_live.yml"
RUN_READY_COMMENT_TYPE = "B2-BM1-RUNREADY-PREPARE/v1"
LIVE_COMMENT_TYPE = "B2-BM1-WINDOW-LIVE-APPROVAL/v1"
LIVE_AUTH_TTL_SECONDS = 3600
RUN_READY_MAX_AGE_SECONDS = 86400
PROVIDER_REVIEW_MAX_AGE_SECONDS = 86400
EXPECTED_PROVIDER_AUTHORITY_FINGERPRINT = (
    "sha256:b6c19fa563d0c5a110879546195ac7ad34aec34c51b0edac66bb5c8c0e998022"
)
GOOGLE_AUTH_STATUSES = {
    "ROTATED_NEW_AI_STUDIO_AUTH_KEY",
    "EXISTING_AI_STUDIO_KEY_TYPE_AUTH_VERIFIED",
}
_HEX40 = re.compile(r"[0-9a-f]{40}")
_SHA256 = re.compile(r"sha256:[0-9a-f]{64}")
_HMAC_SHA256 = re.compile(r"hmac-sha256:[0-9a-f]{64}")
_POSITIVE_DECIMAL = re.compile(r"[1-9][0-9]*")
_OPAQUE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")

GEMINI_AUTH_BINDING_KEY_REFERENCE = "B2_BM1_GEMINI_KEY_AUTH_BINDING_HMAC_KEY"
GEMINI_AUTH_IDENTITY_HMAC_REFERENCE = "B2_BM1_GEMINI_KEY_AUTH_IDENTITY_HMAC"


class BM1LiveOrchestrationError(BM1AuthorizationError):
    """A fail-closed error raised before this layer can enable provider traffic."""


@dataclass(frozen=True)
class GitHubEventSnapshot:
    comment_body: str
    comment_bytes: bytes
    comment_fingerprint: str
    comment_id: int
    comment_created_at: datetime
    authorization_id: str | None
    run_ready_receipt_fingerprint: str | None
    execution_commit_sha: str
    execution_tree_sha: str
    workflow_run_id: str
    workflow_path: str


@dataclass(frozen=True)
class StorageRuntime:
    raw_sink: FileRawEvidenceSink
    claim_store: FileAttemptClaimStore


@dataclass(frozen=True)
class RunReadyResult:
    receipt: Mapping[str, Any]
    public_projection: Mapping[str, Any]


def canonical_ascii_json(value: object) -> bytes:
    """Return the one accepted JSON byte representation for approval inputs."""
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("ascii")


def _reject_duplicate_keys(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise ValueError(f"non-finite JSON number: {value}")


def _strict_ascii_object(body: object, *, maximum_bytes: int = 2048) -> tuple[dict[str, Any], bytes]:
    if not isinstance(body, str):
        raise BM1LiveOrchestrationError("control comment body must be text")
    try:
        raw = body.encode("ascii")
    except UnicodeEncodeError as exc:
        raise BM1LiveOrchestrationError("control comment must be strict ASCII") from exc
    if not raw or len(raw) > maximum_bytes or any(byte < 32 or byte == 127 for byte in raw):
        raise BM1LiveOrchestrationError("control comment byte envelope is invalid")
    try:
        value = json.loads(
            raw.decode("ascii"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except (ValueError, json.JSONDecodeError) as exc:
        raise BM1LiveOrchestrationError("control comment is not strict JSON") from exc
    if not isinstance(value, dict) or canonical_ascii_json(value) != raw:
        raise BM1LiveOrchestrationError("control comment is not canonical ASCII JSON")
    return value, raw


def validate_run_ready_comment(body: object) -> tuple[dict[str, Any], bytes]:
    value, raw = _strict_ascii_object(body)
    if value != {"comment_type": RUN_READY_COMMENT_TYPE}:
        raise BM1LiveOrchestrationError("RUN-READY comment schema mismatch")
    return value, raw


def validate_live_comment(body: object) -> tuple[dict[str, Any], bytes]:
    value, raw = _strict_ascii_object(body)
    expected_keys = {
        "authorization_id",
        "comment_type",
        "confirm_four_attempts",
        "max_spend_usd",
        "run_ready_receipt_fingerprint",
    }
    if set(value) != expected_keys or value.get("comment_type") != LIVE_COMMENT_TYPE:
        raise BM1LiveOrchestrationError("live approval comment schema mismatch")
    if value.get("confirm_four_attempts") is not True:
        raise BM1LiveOrchestrationError("live approval must confirm exactly four attempts")
    if value.get("max_spend_usd") != "0.20":
        raise BM1LiveOrchestrationError("live approval spend ceiling must be exactly 0.20")
    if _OPAQUE_ID.fullmatch(str(value.get("authorization_id", ""))) is None:
        raise BM1LiveOrchestrationError("live authorization id is invalid")
    if _SHA256.fullmatch(str(value.get("run_ready_receipt_fingerprint", ""))) is None:
        raise BM1LiveOrchestrationError("live approval RUN-READY fingerprint is invalid")
    return value, raw


def _parse_utc(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise BM1LiveOrchestrationError(f"{label} is missing")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise BM1LiveOrchestrationError(f"{label} is malformed") from exc
    if parsed.tzinfo is None:
        raise BM1LiveOrchestrationError(f"{label} timezone is missing")
    return parsed.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _git_value(repo_root: Path, revision: str) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "--verify", revision],
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise BM1LiveOrchestrationError("reviewed git identity is unavailable") from exc
    value = result.stdout.strip()
    if _HEX40.fullmatch(value) is None:
        raise BM1LiveOrchestrationError("reviewed git identity is malformed")
    return value


def _read_event_file(path_value: object) -> Mapping[str, Any]:
    if not isinstance(path_value, str) or not path_value:
        raise BM1LiveOrchestrationError("trusted GitHub event file is unavailable")
    path = Path(path_value)
    try:
        if not path.is_absolute():
            raise BM1LiveOrchestrationError("trusted GitHub event file is invalid")
        file_fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(file_fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > 2_000_000:
                raise BM1LiveOrchestrationError("trusted GitHub event file is invalid")
            raw = handle.read(2_000_001)
        if len(raw) > 2_000_000:
            raise BM1LiveOrchestrationError("trusted GitHub event file is invalid")
        event = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except BM1LiveOrchestrationError:
        raise
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise BM1LiveOrchestrationError("trusted GitHub event file is unreadable") from exc
    if not isinstance(event, dict):
        raise BM1LiveOrchestrationError("trusted GitHub event root is invalid")
    return event


def _canonical_positive(value: object, label: str) -> str:
    text = str(value)
    if _POSITIVE_DECIMAL.fullmatch(text) is None:
        raise BM1LiveOrchestrationError(f"{label} is not a canonical positive decimal")
    return text


def github_event_snapshot(
    environ: Mapping[str, str], *, workflow_path: str, repo_root: str | Path,
    comment_kind: str, require_guarded_binding: bool = False,
) -> GitHubEventSnapshot:
    """Validate one actual GitHub issue-comment event and exact checked-out main."""
    if environ.get("GITHUB_ACTIONS") != "true" or environ.get("GITHUB_EVENT_NAME") != "issue_comment":
        raise BM1LiveOrchestrationError("BM1 control requires an actual GitHub issue_comment run")
    if environ.get("GITHUB_REPOSITORY") != REPOSITORY:
        raise BM1LiveOrchestrationError("BM1 control event came from the wrong repository")
    if environ.get("GITHUB_ACTOR") != OWNER_LOGIN:
        raise BM1LiveOrchestrationError("BM1 control actor is not the repository owner")
    if environ.get("GITHUB_REF") != "refs/heads/main":
        raise BM1LiveOrchestrationError("BM1 control run is not bound to main")
    if environ.get("GITHUB_RUN_ATTEMPT") != "1":
        raise BM1LiveOrchestrationError("BM1 workflow reruns are disabled")
    workflow_run_id = _canonical_positive(environ.get("GITHUB_RUN_ID", ""), "workflow run id")
    expected_workflow_ref = f"{REPOSITORY}/{workflow_path}@refs/heads/main"
    if environ.get("GITHUB_WORKFLOW_REF") != expected_workflow_ref:
        raise BM1LiveOrchestrationError("BM1 control run is not using the reviewed main workflow")

    event = _read_event_file(environ.get("GITHUB_EVENT_PATH"))
    issue = event.get("issue")
    comment = event.get("comment")
    repository = event.get("repository")
    sender = event.get("sender")
    if not all(isinstance(item, Mapping) for item in (issue, comment, repository, sender)):
        raise BM1LiveOrchestrationError("GitHub issue-comment event shape is invalid")
    if event.get("action") != "created":
        raise BM1LiveOrchestrationError("only a newly created comment can authorize BM1")
    if issue.get("number") != CONTROL_ISSUE_NUMBER or "pull_request" in issue:
        raise BM1LiveOrchestrationError("BM1 comment came from the wrong or a PR issue")
    if repository.get("full_name") != REPOSITORY or repository.get("default_branch") != "main":
        raise BM1LiveOrchestrationError("BM1 event repository/default branch is invalid")
    user = comment.get("user")
    if not isinstance(user, Mapping):
        raise BM1LiveOrchestrationError("BM1 comment user is missing")
    if (
        user.get("login") != OWNER_LOGIN
        or sender.get("login") != OWNER_LOGIN
        or comment.get("author_association") != "OWNER"
    ):
        raise BM1LiveOrchestrationError("BM1 comment is not an OWNER comment")
    comment_id_value = comment.get("id")
    if isinstance(comment_id_value, bool) or not isinstance(comment_id_value, int) or comment_id_value <= 0:
        raise BM1LiveOrchestrationError("BM1 comment id is invalid")
    comment_created_at = _parse_utc(comment.get("created_at"), "comment created_at")
    if comment_kind == "run-ready":
        parsed, comment_bytes = validate_run_ready_comment(comment.get("body"))
        authorization_id = None
        run_ready_fingerprint = None
    elif comment_kind == "live":
        parsed, comment_bytes = validate_live_comment(comment.get("body"))
        authorization_id = str(parsed["authorization_id"])
        run_ready_fingerprint = str(parsed["run_ready_receipt_fingerprint"])
        configured = environ.get("B2_BM1_EXPECTED_RUN_READY_RECEIPT_FINGERPRINT", "")
        if configured != run_ready_fingerprint:
            raise BM1LiveOrchestrationError("live approval does not name the protected RUN-READY receipt")
    else:
        raise BM1LiveOrchestrationError("unsupported BM1 control comment kind")

    root = Path(repo_root).resolve(strict=True)
    execution_commit_sha = _git_value(root, "HEAD^{commit}")
    execution_tree_sha = _git_value(root, "HEAD^{tree}")
    if environ.get("GITHUB_SHA") != execution_commit_sha:
        raise BM1LiveOrchestrationError("checked-out execution head is stale")
    comment_fingerprint = "sha256:" + hashlib.sha256(comment_bytes).hexdigest()

    if require_guarded_binding:
        guarded = {
            "B2_BM1_GUARDED_COMMENT_ID": str(comment_id_value),
            "B2_BM1_GUARDED_COMMENT_FINGERPRINT": comment_fingerprint,
            "B2_BM1_GUARDED_EXECUTION_HEAD_SHA": execution_commit_sha,
            "B2_BM1_GUARDED_EXECUTION_TREE_SHA": execution_tree_sha,
            "B2_BM1_GUARDED_WORKFLOW_RUN_ID": workflow_run_id,
        }
        if any(environ.get(name) != value for name, value in guarded.items()):
            raise BM1LiveOrchestrationError("public/private GitHub gate binding changed")

    return GitHubEventSnapshot(
        comment_body=str(comment.get("body")),
        comment_bytes=comment_bytes,
        comment_fingerprint=comment_fingerprint,
        comment_id=comment_id_value,
        comment_created_at=comment_created_at,
        authorization_id=authorization_id,
        run_ready_receipt_fingerprint=run_ready_fingerprint,
        execution_commit_sha=execution_commit_sha,
        execution_tree_sha=execution_tree_sha,
        workflow_run_id=workflow_run_id,
        workflow_path=workflow_path,
    )


class GitHubIssueCommentAuthorityVerifier:
    """BM1 AuthorityVerifier backed by the live GitHub event file and run identity."""

    def __init__(
        self, environ: Mapping[str, str], *, repo_root: str | Path,
        expected_snapshot: GitHubEventSnapshot,
    ) -> None:
        self._environ = environ
        self._repo_root = Path(repo_root)
        self._expected = expected_snapshot

    @classmethod
    def from_environment(
        cls, environ: Mapping[str, str], *, repo_root: str | Path,
    ) -> "GitHubIssueCommentAuthorityVerifier":
        snapshot = github_event_snapshot(
            environ,
            workflow_path=LIVE_WORKFLOW_PATH,
            repo_root=repo_root,
            comment_kind="live",
            require_guarded_binding=True,
        )
        return cls(environ, repo_root=repo_root, expected_snapshot=snapshot)

    def verify(
        self, *, run_ready_receipt_fingerprint: str,
        user_authorization_fingerprint: str, authorization_id: str,
    ) -> bool:
        try:
            current = github_event_snapshot(
                self._environ,
                workflow_path=LIVE_WORKFLOW_PATH,
                repo_root=self._repo_root,
                comment_kind="live",
                require_guarded_binding=True,
            )
        except Exception:
            return False
        return (
            current == self._expected
            and run_ready_receipt_fingerprint == current.run_ready_receipt_fingerprint
            and user_authorization_fingerprint == current.comment_fingerprint
            and authorization_id == current.authorization_id
        )


def validate_provider_review(
    environ: Mapping[str, str], *, now: datetime,
) -> str:
    fingerprint = environ.get("B2_BM1_PROVIDER_AUTHORITY_FINGERPRINT", "")
    if fingerprint != EXPECTED_PROVIDER_AUTHORITY_FINGERPRINT:
        raise BM1LiveOrchestrationError("provider Authority fingerprint changed")
    reviewed = _parse_utc(environ.get("B2_BM1_PROVIDER_REVIEWED_AT"), "provider reviewed_at")
    current = now.astimezone(timezone.utc)
    age = (current - reviewed).total_seconds()
    if age < -300 or age > PROVIDER_REVIEW_MAX_AGE_SECONDS:
        raise BM1LiveOrchestrationError("provider Authority review is stale")
    return fingerprint


def credential_decision(
    environ: Mapping[str, str],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Check presence/uniqueness without returning or persisting credential values."""
    present_names = [
        name for name in (
            OPENAI_CREDENTIAL_REFERENCE,
            GOOGLE_CREDENTIAL_REFERENCE,
            GOOGLE_COMPETING_CREDENTIAL_REFERENCE,
        )
        if bool(environ.get(name))
    ]
    validate_symbolic_credential_presence(
        OPENAI_PROVIDER_ID,
        [name for name in present_names if name == OPENAI_CREDENTIAL_REFERENCE],
    )
    validate_symbolic_credential_presence(
        GOOGLE_PROVIDER_ID,
        [
            name for name in present_names
            if name in {GOOGLE_CREDENTIAL_REFERENCE, GOOGLE_COMPETING_CREDENTIAL_REFERENCE}
        ],
    )
    status = environ.get("B2_BM1_GEMINI_KEY_AUTH_STATUS", "")
    attestation = environ.get("B2_BM1_GEMINI_KEY_AUTH_ATTESTATION_FINGERPRINT", "")
    if status not in GOOGLE_AUTH_STATUSES or _SHA256.fullmatch(attestation) is None:
        raise BM1LiveOrchestrationError("Gemini Auth-key evidence is missing or invalid")
    binding_key = environ.get(GEMINI_AUTH_BINDING_KEY_REFERENCE, "")
    expected_identity_hmac = environ.get(GEMINI_AUTH_IDENTITY_HMAC_REFERENCE, "")
    gemini_credential = environ.get(GOOGLE_CREDENTIAL_REFERENCE, "")
    binding_key_bytes = binding_key.encode("utf-8")
    gemini_credential_bytes = gemini_credential.encode("utf-8")
    if (
        len(binding_key_bytes) < 32
        or len(binding_key_bytes) > 4096
        or hmac.compare_digest(binding_key_bytes, gemini_credential_bytes)
        or _HMAC_SHA256.fullmatch(expected_identity_hmac) is None
    ):
        raise BM1LiveOrchestrationError("Gemini Auth-key identity binding is missing or invalid")
    actual_identity_hmac = "hmac-sha256:" + hmac.new(
        binding_key_bytes,
        gemini_credential_bytes,
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(actual_identity_hmac, expected_identity_hmac):
        raise BM1LiveOrchestrationError(
            "configured Gemini credential does not match the attested Auth-key identity"
        )
    identity_binding_fingerprint = sha256_json({
        "schema_version": "b2-bm1-gemini-auth-evidence-binding/v1",
        "google_key_auth_attestation_fingerprint": attestation,
        "google_credential_identity_hmac": expected_identity_hmac,
    })
    decision = {
        "schema_version": "b2-bm1-credential-decision/v2",
        "openai_reference": OPENAI_CREDENTIAL_REFERENCE,
        "openai_present": True,
        "google_reference": GOOGLE_CREDENTIAL_REFERENCE,
        "google_present": True,
        "google_competing_reference": GOOGLE_COMPETING_CREDENTIAL_REFERENCE,
        "google_competing_present": False,
        "google_key_auth_status": status,
        "google_key_auth_attestation_fingerprint": attestation,
        "google_key_auth_identity_binding_fingerprint": identity_binding_fingerprint,
    }
    public = {
        "openai_credential_present": True,
        "google_credential_present": True,
        "google_competing_credential_absent": True,
        "google_key_auth_status": status,
        "google_key_auth_attestation_fingerprint": attestation,
        "google_key_auth_identity_binding_fingerprint": identity_binding_fingerprint,
        "credential_decision_fingerprint": sha256_json(decision),
    }
    assert_public_safe(public)
    return decision, public


def _forbidden_storage_roots(environ: Mapping[str, str]) -> tuple[Path, ...]:
    candidates = ["/tmp", "/var/tmp", "/dev/shm"]
    candidates.extend(
        value for value in (
            environ.get("RUNNER_TEMP"),
            environ.get("GITHUB_WORKSPACE"),
        )
        if value
    )
    roots: list[Path] = []
    for value in candidates:
        try:
            roots.append(Path(value).resolve(strict=True))
        except (OSError, RuntimeError):
            continue
    return tuple(roots)


def _private_persistent_directory(
    value: object, *, label: str, environ: Mapping[str, str],
) -> Path:
    if not isinstance(value, str) or not value or any(ord(ch) < 32 or ord(ch) == 127 for ch in value):
        raise BM1LiveOrchestrationError(f"{label} storage configuration is missing")
    path = Path(value)
    try:
        info = path.lstat()
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise BM1LiveOrchestrationError(f"{label} storage is unavailable") from exc
    if (
        not path.is_absolute()
        or resolved != path
        or stat.S_ISLNK(info.st_mode)
        or not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.geteuid()
        or stat.S_IMODE(info.st_mode) != 0o700
        or any(parent.is_symlink() for parent in path.parents)
    ):
        raise BM1LiveOrchestrationError(f"{label} storage violates the private persistent boundary")
    if any(
        resolved == root
        or resolved.is_relative_to(root)
        or root.is_relative_to(resolved)
        for root in _forbidden_storage_roots(environ)
    ):
        raise BM1LiveOrchestrationError(f"{label} storage cannot use an ephemeral/workspace root")
    return resolved


def _fsync_probe(directory: Path, *, storage_kind: str) -> None:
    """Prove file+directory fsync and readback without exposing the directory."""
    token = hashlib.sha256(
        storage_kind.encode("ascii") + b"\0" + os.urandom(32)
    ).hexdigest()
    name = f".bm1-authority-probe-{token}"
    directory_fd: int | None = None
    created = False
    completed = False
    try:
        directory_fd = os.open(
            directory,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        before = directory.stat()
        opened = os.fstat(directory_fd)
        if (
            (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino)
            or not stat.S_ISDIR(opened.st_mode)
            or opened.st_uid != os.geteuid()
            or stat.S_IMODE(opened.st_mode) != 0o700
        ):
            raise BM1LiveOrchestrationError("storage Authority changed during probe")
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        file_fd = os.open(name, flags, 0o600, dir_fd=directory_fd)
        created = True
        with os.fdopen(file_fd, "wb") as handle:
            file_info = os.fstat(handle.fileno())
            if (
                not stat.S_ISREG(file_info.st_mode)
                or file_info.st_uid != os.geteuid()
                or stat.S_IMODE(file_info.st_mode) != 0o600
            ):
                raise BM1LiveOrchestrationError("storage probe file boundary is invalid")
            handle.write(b"BM1-STORAGE-PROBE/v1")
            handle.flush()
            os.fsync(handle.fileno())
        os.fsync(directory_fd)
        read_fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
        with os.fdopen(read_fd, "rb") as handle:
            if handle.read(65) != b"BM1-STORAGE-PROBE/v1":
                raise BM1LiveOrchestrationError("storage probe readback mismatch")
        completed = True
    except BM1LiveOrchestrationError:
        raise
    except OSError as exc:
        raise BM1LiveOrchestrationError("storage fsync/readback probe failed") from exc
    finally:
        if directory_fd is not None:
            cleanup_error: OSError | None = None
            if created:
                try:
                    os.unlink(name, dir_fd=directory_fd)
                    os.fsync(directory_fd)
                except OSError as exc:
                    cleanup_error = exc
            os.close(directory_fd)
            if completed and cleanup_error is not None:
                raise BM1LiveOrchestrationError(
                    "storage probe cleanup durability failed"
                ) from cleanup_error


class _RefreshingFileRawEvidenceSink(FileRawEvidenceSink):
    @property
    def storage_authority_fingerprint(self) -> str:
        _fsync_probe(self.directory, storage_kind=RAW_BUNDLE_STORAGE_KIND)
        return build_storage_authority_fingerprint(
            self.directory, storage_kind=RAW_BUNDLE_STORAGE_KIND
        )

    @storage_authority_fingerprint.setter
    def storage_authority_fingerprint(self, value: str) -> None:
        self._initial_storage_authority_fingerprint = value


class _RefreshingFileAttemptClaimStore(FileAttemptClaimStore):
    @property
    def storage_authority_fingerprint(self) -> str:
        _fsync_probe(self.directory, storage_kind=CLAIM_STORE_STORAGE_KIND)
        return build_storage_authority_fingerprint(
            self.directory, storage_kind=CLAIM_STORE_STORAGE_KIND
        )

    @storage_authority_fingerprint.setter
    def storage_authority_fingerprint(self, value: str) -> None:
        self._initial_storage_authority_fingerprint = value


def storage_runtime(environ: Mapping[str, str]) -> StorageRuntime:
    raw = _private_persistent_directory(
        environ.get("B2_BM1_RAW_BUNDLE_DIR"), label="raw bundle", environ=environ
    )
    claims = _private_persistent_directory(
        environ.get("B2_BM1_ATTEMPT_CLAIM_DIR"), label="attempt claim", environ=environ
    )
    if raw == claims or raw.is_relative_to(claims) or claims.is_relative_to(raw):
        raise BM1LiveOrchestrationError("raw and claim storage Authorities must be disjoint")
    raw_id = environ.get("B2_BM1_RAW_BUNDLE_ID", "")
    claim_id = environ.get("B2_BM1_ATTEMPT_CLAIM_STORE_ID", "")
    if _OPAQUE_ID.fullmatch(raw_id) is None or _OPAQUE_ID.fullmatch(claim_id) is None:
        raise BM1LiveOrchestrationError("storage opaque identifiers are invalid")
    sink = _RefreshingFileRawEvidenceSink(raw, destination_id=raw_id)
    store = _RefreshingFileAttemptClaimStore(claims, store_id=claim_id)
    # Trigger the first durable re-derivation/probe now. Subsequent property reads
    # repeat it at the BM1 pre-claim and pre-send gates.
    sink.storage_authority_fingerprint
    store.storage_authority_fingerprint
    return StorageRuntime(raw_sink=sink, claim_store=store)


def _write_exclusive_readback(directory: Path, name: str, value: Mapping[str, Any]) -> None:
    raw = canonical_ascii_json(value)
    directory_fd: int | None = None
    try:
        directory_fd = os.open(
            directory,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
        file_fd = os.open(name, flags, 0o600, dir_fd=directory_fd)
        with os.fdopen(file_fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.fsync(directory_fd)
        read_fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
        with os.fdopen(read_fd, "rb") as handle:
            if handle.read(len(raw) + 1) != raw:
                raise BM1LiveOrchestrationError("durable archive readback mismatch")
    except FileExistsError as exc:
        raise BM1LiveOrchestrationError("durable archive already exists") from exc
    except BM1LiveOrchestrationError:
        raise
    except OSError as exc:
        raise BM1LiveOrchestrationError("durable archive write/readback failed") from exc
    finally:
        if directory_fd is not None:
            os.close(directory_fd)


def _run_ready_archive_name(fingerprint: str) -> str:
    if _SHA256.fullmatch(fingerprint) is None:
        raise BM1LiveOrchestrationError("RUN-READY archive fingerprint is invalid")
    return f".bm1-run-ready-{fingerprint.removeprefix('sha256:')}.json"


def load_archived_run_ready(directory: Path, fingerprint: str) -> dict[str, Any]:
    name = _run_ready_archive_name(fingerprint)
    directory_fd: int | None = None
    try:
        directory_fd = os.open(
            directory,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0),
        )
        file_fd = os.open(name, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0), dir_fd=directory_fd)
        with os.fdopen(file_fd, "rb") as handle:
            info = os.fstat(handle.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size < 2 or info.st_size > 65536:
                raise BM1LiveOrchestrationError("RUN-READY archive boundary is invalid")
            raw = handle.read(65537)
        value = json.loads(
            raw.decode("ascii"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except BM1LiveOrchestrationError:
        raise
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError) as exc:
        raise BM1LiveOrchestrationError("RUN-READY archive is unavailable or invalid") from exc
    finally:
        if directory_fd is not None:
            os.close(directory_fd)
    if not isinstance(value, dict) or canonical_ascii_json(value) != raw:
        raise BM1LiveOrchestrationError("RUN-READY archive is not canonical")
    if value.get("receipt_fingerprint") != fingerprint:
        raise BM1LiveOrchestrationError("RUN-READY archive fingerprint mismatch")
    return value


def prepare_run_ready(
    environ: Mapping[str, str], *, repo_root: str | Path,
    now: datetime | None = None,
) -> RunReadyResult:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    snapshot = github_event_snapshot(
        environ,
        workflow_path=RUN_READY_WORKFLOW_PATH,
        repo_root=repo_root,
        comment_kind="run-ready",
        require_guarded_binding=True,
    )
    provider_fingerprint = validate_provider_review(environ, now=current)
    _, credential_public = credential_decision(environ)
    storage = storage_runtime(environ)
    manifest, _ = load_manifest_from_repo_root(repo_root)
    receipt: dict[str, Any] = {
        "schema_version": RUN_READY_SCHEMA_VERSION,
        "run_ready_id": f"BM1-RUNREADY-{snapshot.workflow_run_id}-{snapshot.comment_id}",
        "manifest_fingerprint": manifest["manifest_fingerprint"],
        "execution_commit_sha": snapshot.execution_commit_sha,
        "execution_tree_sha": snapshot.execution_tree_sha,
        "provider_authority_fingerprint": provider_fingerprint,
        "credential_decision_fingerprint": credential_public["credential_decision_fingerprint"],
        "raw_bundle_destination": {
            "destination_id": storage.raw_sink.destination_id,
            "storage_kind": RAW_BUNDLE_STORAGE_KIND,
            "label_fingerprint": storage.raw_sink.destination_fingerprint,
            "storage_authority_fingerprint": storage.raw_sink.storage_authority_fingerprint,
        },
        "attempt_claim_store": {
            "store_id": storage.claim_store.store_id,
            "storage_kind": CLAIM_STORE_STORAGE_KIND,
            "label_fingerprint": storage.claim_store.store_fingerprint,
            "storage_authority_fingerprint": storage.claim_store.storage_authority_fingerprint,
        },
        "authorized_attempt_ids": [row["attempt_id"] for row in manifest["attempt_plan"]],
        "runtime_limits": {
            "maximum_provider_requests": 4,
            "maximum_total_spend_usd": 0.20,
            "automatic_retries": 0,
            "timeout_seconds": 120,
            "max_input_tokens_per_attempt": 8000,
            "max_output_tokens_per_attempt": 2000,
        },
        "issued_at": _iso(current),
    }
    receipt["receipt_fingerprint"] = build_run_ready_receipt_fingerprint(receipt)
    checked = validate_run_ready_receipt(
        receipt,
        manifest=manifest,
        execution_commit_sha=snapshot.execution_commit_sha,
        execution_tree_sha=snapshot.execution_tree_sha,
    )
    _write_exclusive_readback(
        storage.raw_sink.directory,
        _run_ready_archive_name(checked["receipt_fingerprint"]),
        checked,
    )
    projection = {
        "schema_version": "b2-bm1-run-ready-preparation-result/v1",
        "status": "RUN_READY_PREPARED_NOT_LIVE_AUTHORIZED",
        "control_issue_number": CONTROL_ISSUE_NUMBER,
        "work_order": WORK_ORDER,
        "workflow_run_id": snapshot.workflow_run_id,
        "preparation_comment_id": snapshot.comment_id,
        "preparation_comment_fingerprint": snapshot.comment_fingerprint,
        "provider_authority_fingerprint": provider_fingerprint,
        **credential_public,
        "receipt": checked,
        "provider_requests": 0,
        "spend_usd": 0,
        "live_authorization_created": False,
    }
    assert_public_safe(projection)
    return RunReadyResult(receipt=checked, public_projection=projection)


def _build_live_authorization(
    *, snapshot: GitHubEventSnapshot, run_ready: Mapping[str, Any],
) -> dict[str, Any]:
    if snapshot.authorization_id is None or snapshot.run_ready_receipt_fingerprint is None:
        raise BM1LiveOrchestrationError("live event authorization binding is missing")
    issued = snapshot.comment_created_at
    authorization: dict[str, Any] = {
        "schema_version": LIVE_AUTH_SCHEMA_VERSION,
        "authorization_id": snapshot.authorization_id,
        "manifest_fingerprint": run_ready["manifest_fingerprint"],
        "execution_commit_sha": snapshot.execution_commit_sha,
        "execution_tree_sha": snapshot.execution_tree_sha,
        "run_ready_receipt_fingerprint": run_ready["receipt_fingerprint"],
        "user_authorization_fingerprint": snapshot.comment_fingerprint,
        "raw_bundle_destination_fingerprint": run_ready["raw_bundle_destination"]["label_fingerprint"],
        "raw_storage_authority_fingerprint": run_ready["raw_bundle_destination"]["storage_authority_fingerprint"],
        "attempt_claim_store_fingerprint": run_ready["attempt_claim_store"]["label_fingerprint"],
        "claim_storage_authority_fingerprint": run_ready["attempt_claim_store"]["storage_authority_fingerprint"],
        "authorized_attempt_ids": list(run_ready["authorized_attempt_ids"]),
        "maximum_provider_requests": 4,
        "maximum_total_spend_usd": 0.20,
        "automatic_retries": 0,
        "issued_at": _iso(issued),
        "expires_at": _iso(issued + timedelta(seconds=LIVE_AUTH_TTL_SECONDS)),
    }
    authorization["receipt_fingerprint"] = build_live_authorization_fingerprint(authorization)
    assert_public_safe(authorization)
    return authorization


def _live_summary(
    *, snapshot: GitHubEventSnapshot, run_ready: Mapping[str, Any],
    live_authorization: Mapping[str, Any], runner: BM1Runner,
    receipts: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "schema_version": "b2-bm1-live-run-summary/v1",
        "status": "LIVE_RUN_COMPLETED",
        "control_issue_number": CONTROL_ISSUE_NUMBER,
        "workflow_run_id": snapshot.workflow_run_id,
        "approval_comment_id": snapshot.comment_id,
        "user_authorization_fingerprint": snapshot.comment_fingerprint,
        "authorization_id": snapshot.authorization_id,
        "run_ready_receipt_fingerprint": run_ready["receipt_fingerprint"],
        "live_authorization_fingerprint": live_authorization["receipt_fingerprint"],
        "execution_commit_sha": snapshot.execution_commit_sha,
        "execution_tree_sha": snapshot.execution_tree_sha,
        "maximum_provider_requests": MAX_PLANNED_ATTEMPTS,
        "provider_requests": runner.provider_request_count,
        "maximum_total_spend_usd": MAX_TOTAL_SMOKE_SPEND_USD,
        "automatic_retries": 0,
        "fallback_or_model_substitution": 0,
        "global_stop_reason": runner.global_stop_reason,
        "attempts": [
            {
                "attempt_id": row["attempt_id"],
                "terminal_status": row["terminal_status"],
                "reason": row["terminal_reason"],
                "receipt_fingerprint": row["receipt_fingerprint"],
            }
            for row in receipts
        ],
    }
    assert_public_safe(summary)
    summary["summary_fingerprint"] = sha256_json(summary)
    return summary


def execute_live(
    environ: Mapping[str, str], *, repo_root: str | Path,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Execute the exact BM1 plan; BM1Runner.run_all delegates sends to run_next."""
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    verifier = GitHubIssueCommentAuthorityVerifier.from_environment(
        environ, repo_root=repo_root
    )
    snapshot = verifier._expected
    provider_fingerprint = validate_provider_review(environ, now=current)
    _, credential_public = credential_decision(environ)
    storage = storage_runtime(environ)
    manifest, cases = load_manifest_from_repo_root(repo_root)
    run_ready = load_archived_run_ready(
        storage.raw_sink.directory,
        str(snapshot.run_ready_receipt_fingerprint),
    )
    checked_run_ready = validate_run_ready_receipt(
        run_ready,
        manifest=manifest,
        execution_commit_sha=snapshot.execution_commit_sha,
        execution_tree_sha=snapshot.execution_tree_sha,
    )
    issued = _parse_utc(checked_run_ready["issued_at"], "RUN-READY issued_at")
    if (current - issued).total_seconds() < 0 or (current - issued).total_seconds() > RUN_READY_MAX_AGE_SECONDS:
        raise BM1LiveOrchestrationError("RUN-READY receipt is stale")
    if checked_run_ready["provider_authority_fingerprint"] != provider_fingerprint:
        raise BM1LiveOrchestrationError("provider Authority changed after RUN-READY")
    if checked_run_ready["credential_decision_fingerprint"] != credential_public["credential_decision_fingerprint"]:
        raise BM1LiveOrchestrationError("credential decision changed after RUN-READY")
    expires = snapshot.comment_created_at + timedelta(seconds=LIVE_AUTH_TTL_SECONDS)
    if current < snapshot.comment_created_at or current > expires:
        raise BM1LiveOrchestrationError("live approval comment is inactive or expired")
    live_authorization = _build_live_authorization(
        snapshot=snapshot, run_ready=checked_run_ready
    )

    openai = OpenAIResponsesHTTPTransport(
        credential_reference=OPENAI_CREDENTIAL_REFERENCE,
        credential_value=environ[OPENAI_CREDENTIAL_REFERENCE],
        manifest=manifest,
        live_authorization=live_authorization,
        run_ready_receipt=checked_run_ready,
        authority_verifier=verifier,
        execution_commit_sha=snapshot.execution_commit_sha,
        execution_tree_sha=snapshot.execution_tree_sha,
        now_fn=lambda: datetime.now(timezone.utc),
    )
    google = GoogleInteractionsHTTPTransport(
        credential_reference=GOOGLE_CREDENTIAL_REFERENCE,
        credential_value=environ[GOOGLE_CREDENTIAL_REFERENCE],
        manifest=manifest,
        live_authorization=live_authorization,
        run_ready_receipt=checked_run_ready,
        authority_verifier=verifier,
        execution_commit_sha=snapshot.execution_commit_sha,
        execution_tree_sha=snapshot.execution_tree_sha,
        now_fn=lambda: datetime.now(timezone.utc),
    )
    runner = BM1Runner(
        manifest=manifest,
        case_lookup=cases,
        transports={OPENAI_PROVIDER_ID: openai, GOOGLE_PROVIDER_ID: google},
        evidence_sink=storage.raw_sink,
        live_authorization=live_authorization,
        run_ready_receipt=checked_run_ready,
        authority_verifier=verifier,
        execution_commit_sha=snapshot.execution_commit_sha,
        execution_tree_sha=snapshot.execution_tree_sha,
        attempt_claim_store=storage.claim_store,
    )
    receipts = runner.run_all()
    summary = _live_summary(
        snapshot=snapshot,
        run_ready=checked_run_ready,
        live_authorization=live_authorization,
        runner=runner,
        receipts=receipts,
    )
    _write_exclusive_readback(
        storage.raw_sink.directory,
        f".bm1-live-summary-{summary['summary_fingerprint'].removeprefix('sha256:')}.json",
        summary,
    )
    return summary


def gate_projection(snapshot: GitHubEventSnapshot) -> dict[str, str]:
    return {
        "comment_id": str(snapshot.comment_id),
        "comment_fingerprint": snapshot.comment_fingerprint,
        "execution_head_sha": snapshot.execution_commit_sha,
        "execution_tree_sha": snapshot.execution_tree_sha,
        "workflow_run_id": snapshot.workflow_run_id,
    }


def _write_github_outputs(values: Mapping[str, object], environ: Mapping[str, str]) -> None:
    output_path = environ.get("GITHUB_OUTPUT")
    if not output_path:
        return
    lines: list[str] = []
    for key, value in values.items():
        text = str(value)
        if not re.fullmatch(r"[a-z0-9_]+", key) or "\n" in text or "\r" in text:
            raise BM1LiveOrchestrationError("GitHub output is not single-line public-safe data")
        lines.append(f"{key}={text}\n")
    with Path(output_path).open("a", encoding="utf-8", newline="\n") as handle:
        handle.writelines(lines)


def _write_public_copy(path_value: str | None, value: Mapping[str, Any]) -> None:
    if path_value is None:
        return
    path = Path(path_value)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(canonical_ascii_json(value))
        handle.flush()
        os.fsync(handle.fileno())


def _emit(value: Mapping[str, Any]) -> None:
    assert_public_safe(value)
    sys.stdout.buffer.write(canonical_ascii_json(value) + b"\n")


def _cli(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Guarded BM1 production orchestration")
    parser.add_argument("command", choices=("gate-run-ready", "gate-live", "prepare-run-ready", "execute-live"))
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--public-copy")
    args = parser.parse_args(argv)
    environment: MutableMapping[str, str] = os.environ
    root = Path(args.repo_root)
    if args.command in {"gate-run-ready", "gate-live"}:
        live = args.command == "gate-live"
        snapshot = github_event_snapshot(
            environment,
            workflow_path=LIVE_WORKFLOW_PATH if live else RUN_READY_WORKFLOW_PATH,
            repo_root=root,
            comment_kind="live" if live else "run-ready",
        )
        projection = gate_projection(snapshot)
        if live:
            projection["authorization_id"] = str(snapshot.authorization_id)
            projection["run_ready_receipt_fingerprint"] = str(snapshot.run_ready_receipt_fingerprint)
        _write_github_outputs(projection, environment)
        _emit({"schema_version": "b2-bm1-public-gate/v1", "status": "PASS", **projection})
        return 0
    if args.command == "prepare-run-ready":
        result = prepare_run_ready(environment, repo_root=root)
        receipt_bytes = canonical_ascii_json(result.receipt)
        outputs = {
            "run_ready_receipt_fingerprint": result.receipt["receipt_fingerprint"],
            "run_ready_receipt_sha256": hashlib.sha256(receipt_bytes).hexdigest(),
            "run_ready_receipt_b64": base64.b64encode(receipt_bytes).decode("ascii"),
        }
        _write_github_outputs(outputs, environment)
        _write_public_copy(args.public_copy, result.public_projection)
        _emit(result.public_projection)
        return 0
    summary = execute_live(environment, repo_root=root)
    summary_bytes = canonical_ascii_json(summary)
    _write_github_outputs(
        {
            "live_summary_fingerprint": summary["summary_fingerprint"],
            "live_summary_sha256": hashlib.sha256(summary_bytes).hexdigest(),
        },
        environment,
    )
    _write_public_copy(args.public_copy, summary)
    _emit(summary)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    try:
        return _cli(argv)
    except Exception as exc:
        print(f"BM1 orchestration STOP: {type(exc).__name__}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "BM1LiveOrchestrationError",
    "CONTROL_ISSUE_NUMBER",
    "EXPECTED_PROVIDER_AUTHORITY_FINGERPRINT",
    "GitHubEventSnapshot",
    "GitHubIssueCommentAuthorityVerifier",
    "LIVE_COMMENT_TYPE",
    "RUN_READY_COMMENT_TYPE",
    "RunReadyResult",
    "canonical_ascii_json",
    "credential_decision",
    "execute_live",
    "gate_projection",
    "github_event_snapshot",
    "load_archived_run_ready",
    "main",
    "prepare_run_ready",
    "storage_runtime",
    "validate_live_comment",
    "validate_provider_review",
    "validate_run_ready_comment",
]
