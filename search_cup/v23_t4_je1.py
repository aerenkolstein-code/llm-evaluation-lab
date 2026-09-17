"""JE1 Phase A: a locked, local-only executor over the published JE0 semantics.

Preflight/plan never call fixture_decision. A future formal replay requires a
separate Board receipt, exact clean main source, binding and one-shot run ID.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from unittest.mock import patch
import uuid

from .contracts import canonical_json, fingerprint
from .protocol_v23 import assert_content_safe, reference, seal
from .v23_judgment import JudgmentJournal, integrity_gate, validate_record
from .v23_t4_execution import (
    build_bundle, fixture_decision, validate_bundle, validate_planned_record,
)

WORK_ORDER = "WO-ENG-B1-SC-V23-T4-JE1 v0.1"
BASELINE = "c0e365360034ef5c45800563717bbffc7fc5c1b3"
EXECUTION_ID = "T4-JUDGMENT-PV-001-EXEC-V1"
BINDING = "a87a0ad172d6292cc7be52580e1ed7d85615e1298582249f892032fea83fd11d"
RUN_ID = EXECUTION_ID + ":" + BINDING + ":JE1-001"
PINS = {
    "execution_binding": BINDING,
    "parent_binding": "d8002784bd1a7b12052e204249229e95c0ef8f4cd5897b01a82d2cb96fb31222",
    "first_pass_plan": "6c732494e49d91a9c1573ec5345de7f5b3f4ecd3a6d99f8c0c4e4ed35062d508",
    "fixture_a": "2012a82562ea1dcf1860ac73ad154ee5852d65a54ea2e02ac589756ec1a5cf77",
    "fixture_b": "a27b0b251f1655d406711287f20b0315769d45e436ba2cfdface02120611e900",
    "integrity_plan": "7d88295e3ab653f1711b1fb624e7de6030741954b45ceb44c7722df4c6d400ea",
    "receipt": "614c060e4daf5bb067c4fc1c12bec4effefd274b6a27c625d340b6bef99ef1a6",
}
CLAIMS = "SYNTHETIC_PROTOCOL_VALIDATION_ONLY / NOT_BENCHMARK / NO_MODEL_QUALITY / NO_LEADERBOARD"
ZERO_COUNTERS = ("provider_calls", "search_calls", "judge_network_calls", "network_calls",
                 "follow_links", "automatic_retries", "credential_reads", "credit_consumption")


class GateError(ValueError):
    """Only fixed, public-safe reason codes are emitted; exception text is not."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pins(bundle: dict) -> dict:
    pins = {k: bundle[k]["canonical_fingerprint"] for k in
            ("execution_binding", "parent_binding", "first_pass_plan", "integrity_plan", "receipt")}
    pins.update({"fixture_a": bundle["fixture_profiles"]["t4-fixture-judge-a"]["canonical_fingerprint"],
                 "fixture_b": bundle["fixture_profiles"]["t4-fixture-judge-b"]["canonical_fingerprint"]})
    blind = bundle["blind_input"]
    return {**pins, "blind_input": fingerprint(blind),
            "candidate_pool": fingerprint(blind["candidate_pool"]),
            "rubric": fingerprint(blind["rubric"]), "evidence_packet": fingerprint(blind["evidence_packet"]),
            "roster": fingerprint(bundle["execution_roster"]),
            "aggregation": fingerprint(blind["rubric"]["aggregation"]),
            "adjudication": fingerprint(blind["adjudication"])}


def _frozen_bundle(expected_binding: str) -> dict:
    if expected_binding != BINDING:
        raise GateError("BINDING_MISMATCH")
    bundle = build_bundle()
    validate_bundle(bundle, expected_fingerprint=BINDING)
    if any(_pins(bundle)[k] != v for k, v in PINS.items()):
        raise GateError("RETAINED_PIN_MISMATCH")
    if bundle["first_pass_plan"]["run_id"] != RUN_ID:
        raise GateError("PLAN_RUN_ID_MISMATCH")
    return bundle


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _source_snapshot() -> dict:
    """Read local Git metadata and only named non-secret CI variables. No fetch."""
    def git(*args, optional=False):
        result = subprocess.run(
            ["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null",
             "-C", str(_repo_root()), *args], text=True, capture_output=True,
            env={"PATH": "/usr/local/bin:/usr/bin:/bin", "LC_ALL": "C",
                 "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null",
                 "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"},
        )
        if result.returncode and not optional:
            raise GateError("SOURCE_UNAVAILABLE")
        return result.stdout.strip() if result.returncode == 0 else None

    return {
        "head": git("rev-parse", "HEAD"), "tree": git("rev-parse", "HEAD^{tree}"),
        "branch": git("symbolic-ref", "-q", "HEAD", optional=True),
        "origin_main": git("rev-parse", "refs/remotes/origin/main", optional=True),
        "clean": git("status", "--porcelain=v1", "--untracked-files=normal") == "",
        "ci": {key: os.environ.get(key) for key in
               ("GITHUB_EVENT_NAME", "GITHUB_REF", "GITHUB_SHA", "GITHUB_RUN_ATTEMPT", "GITHUB_RUN_ID")},
    }


def _source_gate(source: dict, expected_sha: str) -> None:
    if not re.fullmatch(r"[0-9a-f]{40}", expected_sha or "") or source["head"] != expected_sha:
        raise GateError("SOURCE_SHA_MISMATCH")
    if source["branch"] != "refs/heads/main" or source["origin_main"] != expected_sha:
        raise GateError("MAIN_ONLY")
    if not source["clean"]:
        raise GateError("DIRTY_SOURCE")
    ci = source["ci"]
    # Local main may be used under the same explicit authority. In CI, every
    # supplied execution-context field must agree; partial CI context fails.
    if any(value is not None for value in ci.values()):
        if (ci["GITHUB_EVENT_NAME"] != "workflow_dispatch" or ci["GITHUB_REF"] != "refs/heads/main"
                or ci["GITHUB_SHA"] != expected_sha or not ci["GITHUB_RUN_ID"]):
            raise GateError("FORMAL_CI_CONTEXT_MISMATCH")
        if ci["GITHUB_RUN_ATTEMPT"] != "1":
            raise GateError("FORMAL_RERUN_FORBIDDEN")


def _resource_receipt(calls=0) -> dict:
    return {**dict.fromkeys(ZERO_COUNTERS, 0), "fixture_decision_calls": calls,
            "external_tools": [], "spend": {"value": 0, "currency": "USD"},
            "official_prompt_consumed": False, "hidden_registry_loaded": False,
            "scope": "LOCAL_REPLAY_NOT_GIT_OR_CI_TRANSPORT"}


def _zero_resources(resources: dict) -> bool:
    return (all(type(resources.get(k)) is int and resources[k] == 0 for k in ZERO_COUNTERS)
            and resources.get("external_tools") == []
            and resources.get("spend") == {"value": 0, "currency": "USD"}
            and resources.get("official_prompt_consumed") is False
            and resources.get("hidden_registry_loaded") is False)


def _prestart_failure(code: str) -> dict:
    return seal({"work_order": WORK_ORDER, "execution_id": EXECUTION_ID, "run_id": RUN_ID,
                 "boundary": "PRESTART", "terminal_status": "PRESTART_NOT_EVALUABLE",
                 "reason_code": code, "formal_execution_performed": False,
                 "formal_execution_complete": False, "formal_record_count": 0,
                 "human_override_count": 0, **_resource_receipt(), "claims_ceiling": CLAIMS})


def preflight(expected_binding: str) -> dict:
    """Phase A is valid on a PR, produces no formal records, grants no authority."""
    try:
        bundle = _frozen_bundle(expected_binding)
        source = _source_snapshot()
        return seal({"work_order": WORK_ORDER, "phase": "A_RUN_READY", "terminal_status": "PASS",
                     "source": source, "pins": _pins(bundle), "run_id": RUN_ID,
                     "formal_execution_allowed": False, "formal_execution_performed": False,
                     "formal_execution_complete": False, "formal_record_count": 0,
                     "human_override_count": 0, "planned_first_pass_count": 6,
                     "post_run_integrity": "NOT_RUN",
                     **_resource_receipt(), "claims_ceiling": CLAIMS})
    except (GateError, ValueError, KeyError, TypeError):
        return _prestart_failure("PREFLIGHT_PIN_OR_SOURCE_FAILURE")


def frozen_plan(expected_binding: str) -> dict:
    return _frozen_bundle(expected_binding)["first_pass_plan"]


class _DiskStore:
    """Single-writer durable snapshots; journal is authoritative over JSONL."""
    is_formal = True

    def __init__(self, root: Path):
        self.root = root
        root.mkdir(exist_ok=False)
        self._sync_directory(root.parent)

    @staticmethod
    def _sync_directory(path):
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def exists(self, name):
        return (self.root / name).exists()

    def read(self, name):
        return (self.root / name).read_bytes()

    def write(self, name, data, *, replace=False):
        target = self.root / name
        if target.exists() and not replace:
            raise GateError("ARTIFACT_OVERWRITE_FORBIDDEN")
        temporary = self.root / ("." + name + ".tmp-" + uuid.uuid4().hex)
        try:
            with temporary.open("xb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, target)
            self._sync_directory(self.root)
        finally:
            if temporary.exists():
                temporary.unlink()

    def names(self):
        return sorted(path.name for path in self.root.iterdir() if path.is_file())


def _write_json(store, name, value, *, replace=False):
    store.write(name, canonical_json(value).encode(), replace=replace)


def _manifest(store):
    lines = [hashlib.sha256(store.read(name)).hexdigest() + "  " + name
             for name in store.names() if name != "MANIFEST.sha256"]
    store.write("MANIFEST.sha256", ("\n".join(lines) + "\n").encode())


@contextmanager
def _decision_guard(resources):
    """Capability traps around the pure fixture, excluding durable local I/O.

    This is a trusted, single-threaded fixture executor, not a Python sandbox
    for hostile code. All scorer implementation and input bytes are pinned.
    """
    def denied(counter):
        def fail(*args, **kwargs):
            resources[counter] += 1
            raise GateError("FORBIDDEN_FIXTURE_CAPABILITY")
        return fail

    class NoEnvironment(dict):
        def __getitem__(self, key):
            return denied("credential_reads")()
        get = __getitem__
        def __iter__(self):
            return denied("credential_reads")()

    with ExitStack() as stack:
        for name in ("socket.socket", "socket.create_connection", "urllib.request.urlopen"):
            stack.enter_context(patch(name, side_effect=denied("network_calls")))
        for name in ("builtins.open", "pathlib.Path.open", "os.open", "os.getenv"):
            stack.enter_context(patch(name, side_effect=denied("credential_reads")))
        stack.enter_context(patch("os.environ", NoEnvironment()))
        stack.enter_context(patch("subprocess.Popen", side_effect=denied("network_calls")))
        yield


def _blind_audit(blind_bytes, source, authority):
    rendered = blind_bytes.decode("utf-8")
    tokens = ["t4-origin-", "t4-pv1-sealed-submission-", "provenance_ledger",
              "t4-fixture-judge-a", "t4-fixture-judge-b", "synthetic-not-connected",
              source["head"], authority]
    return {"blind_input_sha256": hashlib.sha256(blind_bytes).hexdigest(),
            "canonical": canonical_json(json.loads(blind_bytes)).encode() == blind_bytes,
            "provenance_absent": all(token not in rendered for token in tokens if token),
            "payload_kind": "JE0_CANONICAL_BLIND_INPUT_ONLY",
            "profile_configuration_in_payload": False, "peer_records_delivered": []}


def _integrity(bundle, start, end, entries, deliveries, leakage, resources):
    """Compute checks from actual run objects, not test receipts or expected PASS."""
    records = [e["record"] for e in entries if e.get("kind") == "FIRST_PASS"]
    plan = bundle["first_pass_plan"]["planned_records"]
    expected_pairs = [(p["judge_alias"], p["candidate_id"]) for p in plan]
    pairs = [(r["judge_alias"], r["candidate_id"]) for r in records]
    complete = len(entries) == 6 and pairs == expected_pairs
    typed = True
    try:
        journal = JudgmentJournal(canonical_json(bundle["blind_input"]),
                                  tuple(bundle["first_pass_plan"]["judges"]), canonical_json(entries))
        for record in records:
            validate_record(record, bundle["blind_input"])
            validate_planned_record(record, bundle, expected_fingerprint=BINDING)
    except (ValueError, KeyError, TypeError):
        typed = False
    pins = _pins(bundle)
    delivery_ok = len(deliveries) == 6 and all(
        d["sequence"] == i + 1 and d["record_id"] == plan[i]["record_id"]
        and d["blind_input_sha256"] == pins["blind_input"]
        and d["rubric_fingerprint"] == pins["rubric"]
        and d["evidence_packet_fingerprint"] == pins["evidence_packet"]
        and d["order_policy"] == "CANDIDATE_ID_ASC"
        and d["journal_fingerprint"] == fingerprint(entries[:i + 1])
        and d["record_fingerprint"] == records[i]["canonical_fingerprint"]
        and d["observed_peer_records"] == []
        for i, d in enumerate(deliveries)
    ) if complete else False
    unchanged = start["pins"] == pins == end.get("pins") and start["source"] == end.get("source")
    conditions = [
        complete and start["pins"]["candidate_pool"] == pins["candidate_pool"],
        delivery_ok,
        leakage.get("canonical") is True and leakage.get("provenance_absent") is True,
        _zero_resources(resources),
        complete and typed and all(r["observed_peer_records"] == [] for r in records),
        complete and typed,
        complete and typed and bundle["blind_input"]["adjudication"]["append_only"] is True,
        start["pins"]["aggregation"] == pins["aggregation"] == end.get("pins", {}).get("aggregation"),
        delivery_ok and leakage.get("payload_kind") == "JE0_CANONICAL_BLIND_INPUT_ONLY"
        and leakage.get("profile_configuration_in_payload") is False
        and resources.get("hidden_registry_loaded") is False,
        unchanged,
    ]
    actual_evidence = [
        {"start": start, "coverage": [list(pair) for pair in pairs]}, {"deliveries": deliveries}, leakage, resources,
        {"journal": entries}, {"typed_records": records, "valid": typed},
        {"journal": entries, "policy": bundle["blind_input"]["adjudication"]},
        {"start": start, "end": end}, {"deliveries": deliveries, "leakage": leakage},
        {"start": start, "end": end},
    ]
    return {f"J{i}": {"status": "PASS" if ok else "FAIL",
                       "evidence": [reference(evidence, f"je1-actual-j{i}")]}
            for i, (ok, evidence) in enumerate(zip(conditions, actual_evidence), 1)}


def _execute(store, bundle, source, authority):
    """Internal sequential engine. Tests supply an in-memory non-formal store."""
    resources = _resource_receipt()
    journal = JudgmentJournal(canonical_json(bundle["blind_input"]),
                              tuple(bundle["first_pass_plan"]["judges"]))
    deliveries = []
    blind_bytes = canonical_json(bundle["blind_input"]).encode()
    leakage = _blind_audit(blind_bytes, source, authority)
    start = {"work_order": WORK_ORDER, "execution_id": EXECUTION_ID, "run_id": RUN_ID,
             "authority_receipt_id": authority, "source": source, "pins": _pins(bundle),
             "started_at": _now(), "test_only": not store.is_formal}
    code = "NONE"
    try:
        _write_json(store, "judgment-journal.json", [])
        store.write("first-pass-records.jsonl", b"")
        _write_json(store, "input-delivery-audit.json", [])
        _write_json(store, "run-start.json", start)
        for sequence, planned in enumerate(bundle["first_pass_plan"]["planned_records"], 1):
            current = _frozen_bundle(BINDING)
            if _pins(current) != start["pins"] or _source_snapshot() != source:
                raise GateError("MIDRUN_SOURCE_OR_PACKAGE_DRIFT")
            delivered = canonical_json(current["blind_input"]).encode()
            if delivered != blind_bytes or hashlib.sha256(delivered).hexdigest() != start["pins"]["blind_input"]:
                raise GateError("BLIND_INPUT_DRIFT")
            resources["fixture_decision_calls"] += 1
            alias = planned["judge_alias"]
            with _decision_guard(resources):
                decision = fixture_decision(delivered, current["fixture_profiles"][alias], planned["candidate_id"])
            record = seal({**{k: planned[k] for k in ("run_id", "record_id", "candidate_id", "judge_alias")},
                           **decision,
                           "judge_identity": next(j for j in current["execution_roster"] if j["entrant_id"] == alias),
                           "package_fingerprint": current["blind_input"]["canonical_fingerprint"],
                           "rubric_fingerprint": fingerprint(current["blind_input"]["rubric"]),
                           "committed_at": _now()})
            validate_record(record, current["blind_input"])
            validate_planned_record(record, current, expected_fingerprint=BINDING)
            if store.read("judgment-journal.json") != journal.entries_json.encode():
                raise GateError("DURABLE_JOURNAL_DRIFT")
            updated = journal.append({"kind": "FIRST_PASS", "record": record})
            store.write("judgment-journal.json", updated.entries_json.encode(), replace=True)
            journal = updated
            entries = json.loads(journal.entries_json)
            store.write("first-pass-records.jsonl", b"".join(
                (canonical_json(e["record"]) + "\n").encode() for e in entries), replace=True)
            deliveries.append({"sequence": sequence, "record_id": record["record_id"],
                               "blind_input_sha256": hashlib.sha256(delivered).hexdigest(),
                               "rubric_fingerprint": start["pins"]["rubric"],
                               "evidence_packet_fingerprint": start["pins"]["evidence_packet"],
                               "order_policy": "CANDIDATE_ID_ASC", "observed_peer_records": [],
                               "record_fingerprint": record["canonical_fingerprint"],
                               "journal_fingerprint": fingerprint(entries)})
            _write_json(store, "input-delivery-audit.json", deliveries, replace=True)
    except Exception as error:
        code = str(error) if isinstance(error, GateError) else "REPLAY_EXCEPTION"

    started = store.exists("run-start.json")
    if not started:
        receipt = _prestart_failure("RUN_START_NOT_DURABLE")
        _write_json(store, "post-run-receipt.json", receipt)
        _manifest(store)
        return receipt
    # Read durable truth, including a commit whose fsync/write wrapper raised
    # after atomic replace. Do not replace a surviving journal with old memory.
    entries = json.loads(store.read("judgment-journal.json"))
    try:
        end = {"source": _source_snapshot(), "pins": _pins(_frozen_bundle(BINDING)), "ended_at": _now()}
    except Exception:
        end = {"source": None, "pins": {}, "ended_at": _now()}
        code = "END_PIN_UNAVAILABLE"
    checks = _integrity(bundle, start, end, entries, deliveries, leakage, resources)
    result = integrity_gate(checks)
    complete = code == "NONE" and result == "PASS" and resources["fixture_decision_calls"] == 6
    receipt = seal({"work_order": WORK_ORDER, "execution_id": EXECUTION_ID, "run_id": RUN_ID,
                    "authority_receipt_id": authority, "source_sha": source["head"], "source_tree": source["tree"],
                    "execution_binding_fingerprint": BINDING, "boundary": "STARTED",
                    "test_only": not store.is_formal,
                    "formal_execution_performed": store.is_formal,
                    "formal_execution_complete": store.is_formal and complete,
                    "formal_record_count": len(entries) if store.is_formal else 0,
                    "test_record_count": len(entries) if not store.is_formal else 0,
                    "human_override_count": sum(e["kind"] == "HUMAN_OVERRIDE" for e in entries),
                    **resources, "integrity": result,
                    "terminal_status": "PASS" if complete else "NOT_EVALUABLE",
                    "completion_status": "COMPLETE" if complete else "PARTIAL",
                    "reason_code": code, "run_identity_consumed": store.is_formal,
                    "recovery_policy": "SEPARATE_AUTHORITY_AND_NEW_SUCCESSOR_RUN_ID_NO_RETRY",
                    "claims_ceiling": CLAIMS})
    for name, value in (("leakage-audit.json", leakage), ("resource-receipt.json", resources),
                        ("integrity-checks.json", checks), ("run-end.json", end),
                        ("post-run-receipt.json", receipt)):
        _write_json(store, name, value)
    _manifest(store)
    return receipt


def replay(*, authority_receipt_id: str, expected_source_sha: str, expected_binding: str,
           run_id: str, output_dir: Path) -> dict:
    """Future Phase B only. This work order authorizes implementation, not use."""
    try:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{2,199}", authority_receipt_id or ""):
            raise GateError("AUTHORITY_RECEIPT_REQUIRED")
        assert_content_safe(authority_receipt_id)
        if run_id != RUN_ID:
            raise GateError("RUN_ID_MISMATCH")
        bundle = _frozen_bundle(expected_binding)
        source = _source_snapshot()
        _source_gate(source, expected_source_sha)
        path = Path(output_dir).absolute()
        if path.exists() or path.is_symlink():
            raise GateError("OUTPUT_DIRECTORY_REUSED")
        if not path.parent.is_dir() or path.parent.resolve().is_relative_to(_repo_root()):
            raise GateError("OUTPUT_MUST_BE_NEW_OUTSIDE_SOURCE")
        audit = _blind_audit(canonical_json(bundle["blind_input"]).encode(), source, authority_receipt_id)
        if not audit["canonical"] or not audit["provenance_absent"]:
            raise GateError("BLIND_INPUT_INVALID")
    except Exception as error:
        return _prestart_failure(str(error) if isinstance(error, GateError) else "PRESTART_CHECK_FAILED")
    try:
        store = _DiskStore(path)
        _write_json(store, "preflight.json", {"source": source, "pins": _pins(bundle),
                                            "authority_receipt_id": authority_receipt_id,
                                            "run_id": RUN_ID, "formal_record_count": 0})
        return _execute(store, bundle, source, authority_receipt_id)
    except Exception:
        # Persistent I/O failure can prevent a failure receipt being written.
        # Existing start/journal files remain authoritative and are never erased.
        started = path.joinpath("run-start.json").exists()
        return {"terminal_status": "NOT_EVALUABLE" if started else "PRESTART_NOT_EVALUABLE",
                "boundary": "STARTED" if started else "PRESTART", "completion_status": "PARTIAL",
                "run_id": RUN_ID, "formal_execution_performed": started,
                "formal_execution_complete": False, "formal_record_count": None if started else 0,
                "reason_code": "RECEIPT_PERSISTENCE_FAILURE_INSPECT_DURABLE_JOURNAL",
                "automatic_retries": 0, "recovery_requires_new_run_identity": started}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("preflight", "plan", "replay"):
        command = commands.add_parser(name)
        command.add_argument("--expected-binding", required=True)
        if name == "replay":
            command.add_argument("--authority-receipt", required=True)
            command.add_argument("--expected-source-sha", required=True)
            command.add_argument("--run-id", required=True)
            command.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.command == "replay":
        result = replay(authority_receipt_id=args.authority_receipt, expected_source_sha=args.expected_source_sha,
                        expected_binding=args.expected_binding, run_id=args.run_id, output_dir=args.output_dir)
    elif args.command == "preflight":
        result = preflight(args.expected_binding)
    else:
        try:
            result = frozen_plan(args.expected_binding)
        except (GateError, ValueError):
            result = _prestart_failure("PLAN_PIN_MISMATCH")
    print(canonical_json(result))
    return 0 if result.get("terminal_status", "PASS") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
