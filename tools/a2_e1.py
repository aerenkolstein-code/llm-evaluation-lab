#!/usr/bin/env python3
"""Independent A2 E1 consumer; only the pinned A1 JSON CLI is executed.

No Companion-Mind import, fixture factory, conformance runner, or storage read.
All case data below is synthetic. This is not a Canonical Event schema/validator.
"""

from __future__ import annotations

import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
import tempfile

A1_HEAD = "36c138f53912821732683d40cf994cc776cd1fc9"
CONTRACT = "63ac8d7de8eb35915cc291b0f7ea67c33b366922"
STATES = ("UNKNOWN", "KNOWN_EMPTY", "N_A", "NOT_LOOKED_UP")
STAMP = "2026-01-02T03:04:05Z"
SENTINELS = ("A2_SYNTHETIC_CREDENTIAL_ZEBRA_71", "A2_SYNTHETIC_CREDENTIAL_OTTER_92")
ZERO_METRICS = ("event_loss", "sequence_disorder", "duplicate_amplification",
                "destructive_correction", "synthetic_sentinel_leak",
                "semantic_collapse", "payload_status_drift")


def encode(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value):
    return hashlib.sha256(encode(value)).hexdigest()


def order_key(event):
    return tuple(event[k] for k in
                 ("session_id", "sequence_no", "turn_id", "actor_role", "event_id"))


def event(case, seq=0, *, role="user", session=None, adapter="A019"):
    kind, observation = {"A018": ("browser_sidecar", "observed"),
                         "A019": ("owned_client", "observed"),
                         "A020": ("historical_backfill", "imported")}[adapter]
    return {
        "event_id": f"a2-{case}-{role}", "session_id": session or f"a2-session-{case}",
        "turn_id": f"a2-turn-{case}", "sequence_no": seq, "actor_role": role,
        "message_id": f"a2-message-{case}-{role}", "persona_id": "a2-persona-fixed",
        "relationship_id": "a2-relationship-fixed", "provider": "offline-a2",
        "model": "synthetic-model-one", "observed_at": STAMP, "created_at": STAMP,
        "content_type": "text/plain", "content_payload": {"text": f"synthetic {case} 雪"},
        "status": "complete", "source_ref": {"source_kind": kind,
        "observation_type": observation, "source_id": f"a2-source-{case}"},
        "attachment_ref": [], "correction_id": None, "correction_of": None,
        "redaction_state": "none", "metadata": {"adapter": adapter,
        "knowledge": {"observability": {"state": STATES[seq % 4]}}},
    }


def turn(case, seq=0, *, outcome="complete", session=None, frames=None):
    user = event(case, seq, session=session)
    assistant = event(case, seq + 1, role="assistant", session=user["session_id"])
    assistant["content_payload"] = {"text": ""}
    if frames is None:
        frames = [] if outcome == "failed" else [f"visible {case} 雪\n", "second frame\n"]
    return {"op": "turn", "user": user, "assistant_template": assistant,
            "attempt_id": f"a2-attempt-{case}",
            "script": {"frames": frames, "outcome": outcome}}


def git(path, *args):
    return subprocess.check_output(["git", "-C", str(path), *args], text=True).strip()


class Seam:
    """Subprocess boundary. Never open any file below the SUT's store/replica."""

    def __init__(self, checkout, root):
        self.checkout, self.root = Path(checkout).resolve(), Path(root).resolve()
        self.records = []

    def call(self, case, request, *, fault=None, raw=None):
        target = self.root / case
        target.mkdir(parents=True, exist_ok=True)
        cmd = [sys.executable, "-B", "-m", "companion_mind.journal", "--store",
               str(target / "local"), "--replica", str(target / "remote")]
        if fault:
            cmd += ["--fault", fault]
        # A minimal child environment carries no provider credentials/configuration.
        env = {"PATH": os.defpath, "PYTHONPATH": str(self.checkout),
               "PYTHONDONTWRITEBYTECODE": "1", "PYTHONIOENCODING": "utf-8",
               "LC_ALL": "C.UTF-8"}
        supplied = raw if raw is not None else encode(request).decode("utf-8")
        completed = subprocess.run(cmd, input=supplied, text=True, encoding="utf-8",
                                   capture_output=True, env=env, cwd=target, timeout=30)
        try:
            body = json.loads(completed.stdout)
        except (ValueError, TypeError):
            body = None
        record = {"index": len(self.records) + 1, "case": case,
                  "operation": request.get("op") if isinstance(request, dict) else None,
                  "fault": fault, "request_sha256": hashlib.sha256(supplied.encode()).hexdigest(),
                  "returncode": completed.returncode, "response": body,
                  "stdout_sha256": hashlib.sha256(completed.stdout.encode()).hexdigest(),
                  "stderr_sha256": hashlib.sha256(completed.stderr.encode()).hexdigest(),
                  "stderr_empty": not completed.stderr,
                  "sentinel_leaks": sum((completed.stdout + completed.stderr).count(s)
                                        for s in SENTINELS)}
        # Persist sanitized evidence even if a zero-tolerance leak is discovered.
        serialized = json.dumps(record, ensure_ascii=False)
        for value in SENTINELS:
            serialized = serialized.replace(value, "[SYNTHETIC_SENTINEL_REDACTED]")
        self.records.append(json.loads(serialized))
        return completed.returncode, body


def expected_turn(request, *, fault=None):
    """Input-derived semantic oracle; no SUT response is an expected value."""
    user = deepcopy(request["user"])
    if fault == "F1":
        return [user]
    assistant = deepcopy(request["assistant_template"])
    script = request["script"]
    frames = script["frames"]
    status = script["outcome"] if frames else "failed"
    external = {"complete": "SUCCESS", "partial": "UNKNOWN", "failed": "FAILED"}[status]
    evidence, error = "OBSERVED", "STUB_FAILED" if status == "failed" else None
    if fault == "F2":
        frames, status, external = [], "failed", "UNKNOWN"
        evidence, error = "RECOVERY_INTERRUPTED", "NO_VISIBLE_OUTPUT"
    elif fault == "F3":
        frames, status, external = frames[:1], "partial", "UNKNOWN"
        evidence = "RECOVERY_INTERRUPTED"
    assistant["content_payload"] = {"text": "".join(frames)}
    assistant["status"] = status
    extension = {"attempt_id": request["attempt_id"], "external_outcome": external,
                 "terminal_evidence": evidence}
    if error:
        extension["error_class"] = error
    assistant["metadata"].setdefault("extensions", {})["a019_attempt"] = extension
    return [user, assistant]


def event_metrics(expected, observed):
    """Count observable deviations without accepting the SUT's own verdict/hash."""
    wanted = {e["event_id"]: e for e in expected}
    seen = {e["event_id"]: e for e in observed}
    counts = Counter(e["event_id"] for e in observed)
    keys = [order_key(e) for e in observed]
    shared = wanted.keys() & seen.keys()
    return {
        "event_loss": len(wanted.keys() - seen.keys()),
        "sequence_disorder": sum(a > b for a, b in zip(keys, keys[1:])),
        "duplicate_amplification": sum(n - 1 for n in counts.values()) + len(seen.keys() - wanted.keys()),
        "destructive_correction": sum(k not in seen or digest(wanted[k]) != digest(seen[k])
                                       for k in wanted if k in {e["correction_of"] for e in expected}),
        "synthetic_sentinel_leak": sum(encode(observed).count(s.encode()) for s in SENTINELS),
        "semantic_collapse": sum(digest(wanted[k]["metadata"].get("knowledge", {})) !=
                                 digest(seen[k]["metadata"].get("knowledge", {})) for k in shared),
        "payload_status_drift": sum(digest(wanted[k]) != digest(seen[k]) for k in shared),
    }


def verdict(checks, missing):
    if any(not item["passed"] for item in checks):
        return "FAIL"
    if missing:
        return "NOT_EVALUABLE"
    return "PASS" if checks else "BLOCKED"


class MissingObservation(Exception):
    pass


class Evaluation:
    def __init__(self, seam):
        self.seam = seam
        self.checks, self.missing = [], []
        self.metrics = Counter({key: 0 for key in ZERO_METRICS})
        self.sections = {}

    def check(self, case, invariant, condition, **details):
        self.checks.append({"case": case, "invariant": invariant,
                            "passed": bool(condition), **details})

    def ok(self, case, request):
        rc, body = self.seam.call(case, request)
        shape = (rc == 0 and isinstance(body, dict) and body.get("ok") is True
                 and "result" in body)
        self.check(case, "success_response_contract", shape,
                   operation=request["op"], observed_returncode=rc)
        if not shape:
            raise MissingObservation(f"{case}:{request['op']}:no-success-result")
        return body["result"]

    def error(self, case, request, code=None, *, raw=None):
        rc, body = self.seam.call(case, request, raw=raw)
        shape = (rc == 2 and isinstance(body, dict) and body.get("ok") is False
                 and isinstance(body.get("error"), str)
                 and re.fullmatch(r"[A-Z][A-Z0-9_]*", body["error"]) is not None)
        self.check(case, "safe_rejection", shape and (code is None or body["error"] == code),
                   operation=request.get("op"), expected_code=code,
                   observed_code=body.get("error") if isinstance(body, dict) else None,
                   observed_returncode=rc)
        return body

    def receipt(self, case, receipt, expected):
        self.check(case, "durable_receipt_identity", receipt.get("event_id") == expected["event_id"])
        self.check(case, "durable_receipt_fingerprint", receipt.get("fingerprint") == digest(expected))
        self.check(case, "durable_receipt_contract", receipt.get("contract_commit") == CONTRACT
                   and receipt.get("contract_version") == "canonical_event/v1")

    def export(self, case, expected, *, tag="canonical"):
        result = self.ok(case, {"op": "export", "order": "canonical"})
        observed = result["events"]
        metrics = event_metrics(expected, observed)
        self.metrics.update(metrics)
        wanted = sorted(expected, key=order_key)
        self.check(case, f"{tag}:full_event_oracle", digest(wanted) == digest(observed),
                   expected_sha256=digest(wanted), observed_sha256=digest(observed), metrics=metrics)
        self.check(case, f"{tag}:reported_fingerprint", result["fingerprint"] == digest(observed))
        return observed

    def reopen(self, case, expected, repeats=3):
        fingerprints, invocations = [], []
        for index in range(repeats):
            recovery = self.ok(case, {"op": "recover"})
            self.check(case, "recovery_no_provider", recovery.get("provider_invocations") == 0)
            self.check(case, "recovery_completed", recovery.get("local_recovery_complete") is True)
            invocations.append(recovery.get("provider_invocations"))
            fingerprints.append(digest(self.export(case, expected, tag=f"restart-{index + 1}")))
        self.check(case, "restart_determinism", len(set(fingerprints)) == 1)
        return {"fresh_process_reopens": repeats, "fingerprints": fingerprints,
                "provider_invocations": invocations}

    def replica(self, case, expected):
        local = self.export(case, expected, tag="replica-local")
        receipt = self.ok(case, {"op": "drain"})
        complete = receipt.get("completion") == "READBACK_VERIFIED"
        self.check(case, "replica_completion", complete)
        if not complete:
            raise MissingObservation(f"{case}:replica-completion-unverified")
        self.check(case, "replica_envelope", receipt.get("expected_events") == len(expected)
                   and receipt.get("verified_events") == len(expected)
                   and receipt.get("journal_high_water") == len(expected))
        self.check(case, "replica_transport", receipt.get("transport_evidence") == "OFFLINE_DRIVE_STUB")
        # The drain envelope is physical high-water order. Canonical agreement
        # is independently recomputed below, never inferred from this receipt.
        self.check(case, "replica_physical_envelope_fingerprint", receipt.get("ordered_fingerprint") == digest(expected))
        readback = self.ok(case, {"op": "readback"})
        self.check(case, "replica_readback_transport", readback.get("transport_evidence") == "OFFLINE_DRIVE_STUB")
        observed = sorted(readback["events"], key=order_key)
        self.metrics.update(event_metrics(expected, observed))
        self.check(case, "replica_exact_canonical_agreement", digest(observed) == digest(local))
        expected_hashes = {e["event_id"]: digest(e) for e in expected}
        self.check(case, "replica_per_event_receipts",
                   {r["event_id"]: r["fingerprint"] for r in receipt["receipts"]} == expected_hashes)
        ids = {r["event_id"]: r["remote_id"] for r in receipt["receipts"]}
        repeat = self.ok(case, {"op": "drain"})
        stable_ids = (repeat.get("completion") == "READBACK_VERIFIED"
                      and {r["event_id"]: r["remote_id"] for r in repeat["receipts"]} == ids)
        self.check(case, "replica_repeat_no_new_remote_ids", stable_ids)
        self.check(case, "replica_remote_ids_unique", len(set(ids.values())) == len(expected))
        return {"completion": receipt["completion"], "events": len(expected),
                "journal_high_water": receipt["journal_high_water"],
                "canonical_fingerprint": digest(local), "physical_envelope_fingerprint": receipt.get("ordered_fingerprint"),
                "repeated_remote_ids_stable": stable_ids,
                "transport_evidence": receipt["transport_evidence"]}

    def smoke(self):
        case = "smoke"
        info = self.ok(case, {"op": "info"})
        self.check(case, "info_pin", info.get("contract_commit") == CONTRACT
                   and info.get("contract_version") == "canonical_event/v1"
                   and info.get("offline_only") is True and info.get("recovery_complete") is True)
        self.error(case, {"op": "operation_does_not_exist"})
        self.error(case, {}, raw="{")
        invalid = event("invalid")
        del invalid["message_id"]
        self.error(case, {"op": "append", "event": invalid})
        expected = []
        for i, outcome in enumerate(("complete", "partial", "failed")):
            req = turn(f"smoke-{outcome}", i * 2, session="a2-smoke", outcome=outcome)
            receipt = self.ok(case, req)
            pair = expected_turn(req)
            expected.extend(pair)
            self.receipt(case, receipt["user"], pair[0])
            self.receipt(case, receipt["assistant"], pair[1])
            self.check(case, "user_before_provider", receipt.get("trace", [])[:3] ==
                       ["USER_DURABLE_RECEIPT", "PROVIDER_INTENT_DURABLE", "PROVIDER_STUB_INVOKED"])
            self.check(case, "terminal_before_ack", receipt.get("trace", [])[-2:] ==
                       ["ASSISTANT_DURABLE", "CLIENT_COMPLETION_ACK"])
            self.check(case, "single_stub_invocation", receipt.get("provider_invocations") == 1)
            repeated = self.ok(case, req)
            self.check(case, "same_attempt_no_reinvoke", repeated.get("provider_invocations") == 0)
            self.check(case, "same_attempt_original_receipt",
                       all(repeated["assistant"][k] == receipt["assistant"][k] for k in
                           ("event_id", "journal_offset", "fingerprint", "commit_generation", "store_generation")))
            conflict = deepcopy(req)
            conflict["script"]["frames"] = ["conflicting callback"]
            self.error(case, conflict)
        self.export(case, expected)
        restart = self.reopen(case, expected)
        replica = self.replica(case, expected)
        return {"info": info, "expected_events": len(expected), "restart": restart, "replica": replica}

    def ordering_and_correction(self):
        case, expected = "ordering-correction", []
        # Arrival order differs from canonical order and includes a declared gap.
        for name, seq, adapter in (("late", 9, "A019"), ("early", 1, "A020"), ("middle", 5, "A018")):
            item = event(name, seq, session="a2-permuted", adapter=adapter)
            item["content_type"] = "application/json"
            item["content_payload"] = {"array": [None, False, 0, "雪", {"count": 2}], "number": 0}
            item["attachment_ref"] = [{"attachment_id": f"synthetic-{name}",
                 "media_type": "image/png", "source_ref": "synthetic:diagram", "sha256": "a" * 64}]
            receipt = self.ok(case, {"op": "ingest", "adapter": adapter, "event": item})
            self.receipt(case, receipt, item)
            duplicate = self.ok(case, {"op": "append", "event": item})
            self.check(case, "append_duplicate_original_receipt", duplicate.get("disposition") == "ALREADY_COMMITTED"
                       and all(duplicate[k] == receipt[k] for k in
                               ("event_id", "fingerprint", "journal_offset", "commit_generation", "store_generation")))
            conflict = deepcopy(item)
            conflict["content_payload"]["number"] = 1
            self.error(case, {"op": "append", "event": conflict}, "IDENTITY_CONFLICT")
            collision = deepcopy(item)
            collision["event_id"] += "-collision"
            self.error(case, {"op": "append", "event": collision}, "SEQUENCE_CONFLICT")
            expected.append(item)
        physical = self.ok(case, {"op": "export", "order": "journal"})["events"]
        self.check(case, "physical_arrival_order", digest(physical) == digest(expected))
        canonical = self.export(case, expected)
        self.check(case, "explicit_gaps_preserved", [e["sequence_no"] for e in canonical] == [1, 5, 9])
        for name, target in (("correction", expected[0]), ("revert", None)):
            target = target or expected[-1]
            item = event(name, len(expected) + 10, session="a2-permuted")
            item["source_ref"].update(source_kind="correction", observation_type="corrected")
            item["correction_id"], item["correction_of"] = f"a2-{name}", target["event_id"]
            item["metadata"]["extensions"] = {"correction_action": name}
            self.ok(case, {"op": "correct", "event": item})
            expected.append(item)
        missing = deepcopy(expected[-1])
        missing.update(event_id="a2-missing-correction", correction_id="a2-missing-edge",
                       correction_of="nonexistent-event", sequence_no=20)
        self.error(case, {"op": "correct", "event": missing})
        self.error(case, {"op": "delete", "event_id": expected[0]["event_id"]})
        observed = self.export(case, expected)
        self.check(case, "original_preserved_after_correction", observed[2] == expected[0])
        return {"arrival_sequences": [9, 1, 5], "canonical_sequences": [1, 5, 9],
                "graph": [[e["event_id"], e["correction_of"]] for e in expected],
                "restart": self.reopen(case, expected), "replica": self.replica(case, expected)}

    def batch(self, run):
        case, expected, requests = f"batch-{run}", [], []
        before = len(self.seam.records)
        ack_count = 0
        for index in range(120):
            outcome = "complete" if index < 100 else "partial" if index < 110 else "failed"
            req = turn(f"batch-{index:03}", 2 * index, session="a2-batch-fixed", outcome=outcome)
            # Alternate models/providers while keeping stable identities unchanged.
            for side in ("user", "assistant_template"):
                req[side]["provider"] = f"offline-provider-{index % 2}"
                req[side]["model"] = f"synthetic-model-{index % 3}"
                req[side]["metadata"]["knowledge"] = {state.lower(): {"state": state} for state in STATES}
            requests.append(req)
            pair = expected_turn(req)
            receipt = self.ok(case, req)
            for actor, item in zip(("user", "assistant"), pair):
                self.receipt(case, receipt[actor], item)
                ack_count += 1
            self.check(case, "batch_single_stub_invocation", receipt.get("provider_invocations") == 1)
            self.check(case, "batch_user_before_provider", receipt.get("trace", [])[:3] ==
                       ["USER_DURABLE_RECEIPT", "PROVIDER_INTENT_DURABLE", "PROVIDER_STUB_INVOKED"])
            duplicate = self.ok(case, req)
            self.check(case, "batch_duplicate_no_stub_invocation", duplicate.get("provider_invocations") == 0)
            expected.extend(pair)
        observed = self.export(case, expected)
        statuses = Counter(e["status"] for e in observed if e["actor_role"] == "assistant")
        self.check(case, "120_turn_distribution", statuses == {"complete": 100, "partial": 10, "failed": 10})
        restart = self.reopen(case, expected)
        replica = self.replica(case, expected)
        return {"run": run, "fresh_store": True, "turns": 120, "acknowledged_events": ack_count,
                "canonical_events": len(observed), "terminal_outcomes": dict(statuses),
                "case_manifest_sha256": digest(requests), "expected_fingerprint": digest(sorted(expected, key=order_key)),
                "normalized_fingerprint": digest(observed), "metrics": event_metrics(expected, observed),
                "restart": restart, "replica": replica,
                "ledger_range": [before + 1, len(self.seam.records)]}

    def fault(self, point):
        case = f"fault-{point}"
        req = turn(case, frames=["durable visible frame\n", "not-yet-visible frame\n"])
        item = event(case)
        if point in ("F7", "F8"):
            self.ok(case, {"op": "append", "event": item})
            operation, expected = {"op": "drain"}, [item]
        elif point in ("F6", "APPEND_BEFORE_COMMIT"):
            operation = {"op": "append", "event": item}
            expected = [] if point == "APPEND_BEFORE_COMMIT" else [item]
        else:
            operation, expected = req, expected_turn(req, fault=point)
        rc, body = self.seam.call(case, operation, fault=point)
        self.check(case, "hard_process_exit", rc == 86 and body is None,
                   point=point, returncode=rc)
        if rc != 86:
            self.missing.append(f"{point}:sanctioned-hard-exit-unavailable")
        recovery = self.ok(case, {"op": "recover"})
        self.check(case, "unclean_shutdown_observed", recovery.get("previous_clean_shutdown") is False)
        self.check(case, "fault_recovery_zero_invocations", recovery.get("provider_invocations") == 0)
        self.export(case, expected)
        restart = self.reopen(case, expected)
        if point == "F1":
            attempts = self.ok(case, {"op": "attempts"})
            self.check(case, "not_sent_no_phantom_completion", len(attempts) == 1
                       and attempts[0]["external_outcome"] == "NOT_SENT"
                       and attempts[0]["phase"] == "USER_DURABLE")
            resumed = self.ok(case, req)
            self.check(case, "explicit_resume_once", resumed.get("provider_invocations") == 1)
            expected = expected_turn(req)
            self.export(case, expected, tag="explicit-resume")
        elif point in ("F2", "F3", "F4", "F5"):
            duplicate = self.ok(case, req)
            self.check(case, "post_fault_no_reinvoke", duplicate.get("provider_invocations") == 0)
            self.export(case, expected, tag="post-fault-duplicate")
            attempts = self.ok(case, {"op": "attempts"})
            external = "UNKNOWN" if point in ("F2", "F3") else "SUCCESS"
            self.check(case, "external_outcome_preserved", len(attempts) == 1
                       and attempts[0]["external_outcome"] == external)
        elif point == "APPEND_BEFORE_COMMIT":
            self.check(case, "atomic_no_phantom_outbox", self.ok(case, {"op": "replica_state"}) == [])
            self.ok(case, operation)
            expected = [item]
            self.export(case, expected, tag="atomic-explicit-retry")
        replica = self.replica(case, expected)
        return {"point": point, "hard_exit": rc, "events_after_initial_recovery": len(expected_turn(req, fault=point))
                if point in ("F1", "F2", "F3", "F4", "F5") else (0 if point == "APPEND_BEFORE_COMMIT" else 1),
                "expected_initial_assistant_status": None if point not in ("F2", "F3", "F4", "F5")
                else expected_turn(req, fault=point)[1]["status"], "recovery_provider_invocations": recovery.get("provider_invocations"),
                "restart": restart, "replica": replica}

    def replica_errors(self):
        case, item = "replica-errors", event("replica-errors")
        self.ok(case, {"op": "append", "event": item})
        outcomes = []
        for option in ("fail", "corrupt_read"):
            result = self.ok(case, {"op": "drain", option: True})
            self.check(case, "replica_error_not_verified", result.get("completion") == "INCOMPLETE"
                       and result.get("ordered_fingerprint") is None)
            self.export(case, [item], tag=option)
            outcomes.append({"injection": option, "completion": result.get("completion")})
        first = self.replica(case, [item])
        # The old receipt is only an envelope; a later append requires a new drain.
        second = event("replica-later", 1, session=item["session_id"])
        self.ok(case, {"op": "append", "event": second})
        pending = self.ok(case, {"op": "replica_state"})
        later = self.replica(case, [item, second])
        return {"incomplete_cases": outcomes, "first_envelope": first, "later_envelope": later,
                "pending_state_sha256": digest(pending)}

    def boundaries(self):
        case, expected = "boundaries", []
        for index, state in enumerate(STATES):
            item = event(f"state-{state}", index, session="a2-states")
            item["metadata"]["knowledge"] = {"fact": {"state": state}}
            self.ok(case, {"op": "append", "event": item})
            expected.append(item)
            bad = deepcopy(item)
            bad["event_id"] += "-value"
            bad["sequence_no"] += 100
            bad["metadata"]["knowledge"]["fact"]["value"] = False
            self.error(case, {"op": "append", "event": bad})
        for index, (adapter, kind, observation) in enumerate((
                ("A018", "browser_sidecar", "observed"),
                ("A019", "owned_client", "observed"),
                ("A020", "historical_backfill", "imported"))):
            item = event(f"adapter-{adapter}", index, session="a2-adapters", adapter=adapter)
            self.ok(case, {"op": "ingest", "adapter": adapter, "event": item})
            expected.append(item)
            self.error(case, {"op": "ingest", "adapter": "A018" if adapter != "A018" else "A020", "event": item})
            bad = deepcopy(item)
            bad.update(event_id=f"a2-mislabeled-{adapter}", sequence_no=index + 10)
            bad["source_ref"]["observation_type"] = "observed" if observation == "imported" else "imported"
            self.error(case, {"op": "ingest", "adapter": adapter, "event": bad})
        for observation in ("inferred", "projected"):
            item = event(f"derived-{observation}", session=f"a2-{observation}")
            item["source_ref"].update(source_kind="derived", observation_type=observation)
            item["metadata"].pop("adapter")
            self.ok(case, {"op": "append", "event": item})
            expected.append(item)
            bad = deepcopy(item)
            bad["source_ref"]["observation_type"] = "observed"
            self.error(case, {"op": "append", "event": bad})
        # Authority files are A2-owned external synthetic controls, not SUT storage.
        authority_file = self.seam.root / "synthetic-authority-control.json"
        original = encode({"persona_current": "fixed", "relationship_current": "unchanged"})
        authority_file.write_bytes(original)
        for key in ("persona_current", "relationship_current", "persona_biography",
                    "relationship_milestone", "relationship_upgrade", "authority_write",
                    "biography_write", "current_state_write"):
            bad = event(f"authority-{key}")
            bad["metadata"]["extensions"] = {key: {"requested": "upgrade"}}
            self.error(case, {"op": "append", "event": bad})
        for operation in ("current", "memory", "persona", "relationship", "authority_write"):
            self.error(case, {"op": operation, "path": str(authority_file), "value": "mutated"})
        observed = self.export(case, expected)
        self.check(case, "no_negative_current_inference", all("absent_fact" not in e["metadata"].get("knowledge", {})
                                                             for e in observed))
        self.check(case, "external_authority_control_unchanged", authority_file.read_bytes() == original)
        return {"states": list(STATES), "adapters": ["A018", "A019", "A020"],
                "authority_negative": "unsupported-ops-and-mutation-metadata-rejected",
                "authority_control_sha256": hashlib.sha256(original).hexdigest(),
                "absence_semantics": "no negative Current assertion exposed",
                "restart": self.reopen(case, expected), "replica": self.replica(case, expected)}

    def retry_and_template_boundary(self):
        case = "retry-template-boundary"
        req = turn(case, outcome="failed")
        bad = deepcopy(req)
        bad["assistant_template"]["persona_id"] = "another-persona"
        self.error(case, bad)
        self.export(case, [], tag="invalid-template-no-user-commit")
        self.ok(case, req)
        expected = expected_turn(req)
        retry = deepcopy(req)
        retry["attempt_id"] += "-retry"
        retry["assistant_template"]["event_id"] += "-retry"
        retry["assistant_template"]["sequence_no"] += 1
        retry["script"] = {"frames": ["explicit retry visible output"], "outcome": "complete"}
        receipt = self.ok(case, retry)
        expected.append(expected_turn(retry)[1])
        self.check(case, "explicit_new_attempt_once", receipt.get("provider_invocations") == 1)
        self.export(case, expected)
        self.reopen(case, expected)
        return {"events": len(expected), "prior_failed_evidence_preserved": True,
                "new_attempt_terminal_status": "complete", "replica": self.replica(case, expected)}

    def secrets(self):
        case, expected = "secrets", []
        item = event("secret-structured")
        item["content_payload"] = {"password": SENTINELS[0], "nested": [{"api_key": SENTINELS[1]}]}
        self.ok(case, {"op": "append", "event": item})
        scrubbed = deepcopy(item)
        scrubbed["content_payload"] = {"password": "[SECRET_REDACTED]",
                                        "nested": [{"api_key": "[SECRET_REDACTED]"}]}
        scrubbed["redaction_state"] = "redacted"
        expected.append(scrubbed)
        envelope = event("secret-envelope")
        envelope["event_id"] = "Bearer " + SENTINELS[0]
        self.error(case, {"op": "append", "event": envelope})
        req = turn("secret-split", frames=["password=" + SENTINELS[1][:12], SENTINELS[1][12:]])
        self.ok(case, req)
        pair = expected_turn(req)
        pair[1]["content_payload"] = {"text": "[SECRET_REDACTED]"}
        pair[1]["redaction_state"] = "redacted"
        expected.extend(pair)
        self.export(case, expected)
        self.ok(case, {"op": "attempts"})
        self.ok(case, {"op": "replica_state"})
        restart = self.reopen(case, expected)
        replica = self.replica(case, expected)
        return {"sentinel_inventory_sha256": digest(SENTINELS),
                "surfaces": ["CLI stdout/stderr", "canonical export", "recover", "replica_state", "readback", "A2 evidence"],
                "storage_internals": "not inspected; A1 conformance responsibility",
                "restart": restart, "replica": replica}

    def run_group(self, name, function):
        before = len(self.checks)
        try:
            value = function()
        except (MissingObservation, KeyError, TypeError, ValueError, subprocess.TimeoutExpired) as exc:
            self.missing.append(f"{name}:{type(exc).__name__}")
            value = {"missing_observation": type(exc).__name__}
        self.sections[name] = {"receipt": value,
                               "checks": len(self.checks) - before,
                               "failed_checks": sum(not c["passed"] for c in self.checks[before:])}
        print(json.dumps({"section": name, "checks": self.sections[name]["checks"],
                          "failed": self.sections[name]["failed_checks"]}), flush=True)


def preflight(checkout, remote_receipt):
    """Only allowed public contract/manifest files and git metadata are read."""
    root = Path(checkout).resolve()
    if git(root, "rev-parse", "HEAD") != A1_HEAD or git(root, "status", "--porcelain"):
        raise MissingObservation("A1 candidate pin/clean-checkout drift")
    authority_files = ("docs/contracts/canonical_event_v1.md", "schemas/canonical_event_v1.schema.json",
                       "companion_mind/contracts/canonical_event_v1.py")
    fingerprints = {}
    for path in authority_files:
        actual = (root / path).read_bytes()
        baseline = subprocess.check_output(["git", "-C", str(root), "show", f"{CONTRACT}:{path}"])
        if actual != baseline:
            raise MissingObservation(f"CONTRACT_CHANGE_REQUIRED:{path}")
        fingerprints[path] = hashlib.sha256(actual).hexdigest()
    manifest_file = root / "examples/a019_e1_manifest.json"
    manifest = json.loads(manifest_file.read_text())
    if (manifest.get("contract_commit") != CONTRACT or manifest.get("fresh_runs") != 2
            or manifest.get("turns_per_run") != 120
            or manifest.get("terminal_outcomes") != {"complete": 100, "partial": 10, "failed": 10}
            or manifest.get("canonical_events_per_run") != 240
            or manifest.get("faults") != [f"F{i}" for i in range(1, 9)]
            or manifest.get("additional_atomic_fault") != "APPEND_BEFORE_COMMIT"
            or manifest.get("repeated_reopens") != 3):
        raise MissingObservation("sanctioned-manifest-drift")
    proof = json.loads(Path(remote_receipt).read_text())
    if (proof.get("a1_pr_state") != "open" or proof.get("a1_pr_draft") is not True
            or proof.get("a1_head") != A1_HEAD or proof.get("contract_commit") != CONTRACT
            or proof.get("a1_ci_run_id") != 34992621405 or proof.get("a1_ci_conclusion") != "success"
            or proof.get("a1_ci_head") != A1_HEAD):
        raise MissingObservation("remote-preflight-receipt-does-not-match-work-order")
    observed = datetime.fromisoformat(proof["observed_at"].replace("Z", "+00:00"))
    age = (datetime.now(timezone.utc) - observed).total_seconds()
    if not 0 <= age <= 3600:
        raise MissingObservation("remote-preflight-receipt-not-fresh-within-one-hour")
    return {"remote_observation": proof, "contract_files_sha256": fingerprints,
            "a1_manifest_sha256": hashlib.sha256(manifest_file.read_bytes()).hexdigest(),
            "handoff_sha256": hashlib.sha256((root / "docs/journal/a2-handoff.md").read_bytes()).hexdigest(),
            "a1_tree": git(root, "rev-parse", "HEAD^{tree}"), "a1_clean": True}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--a1-checkout", required=True, type=Path)
    parser.add_argument("--preflight-receipt", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)
    repo = Path(__file__).resolve().parents[1]
    args.output_dir.mkdir(parents=True, exist_ok=False)
    started = datetime.now(timezone.utc).isoformat()
    try:
        intake = preflight(args.a1_checkout, args.preflight_receipt)
        if git(repo, "status", "--porcelain"):
            raise MissingObservation("A2 runner must execute from a clean committed checkout")
    except (MissingObservation, KeyError, ValueError, OSError, subprocess.CalledProcessError) as exc:
        result = {"verdict": "BLOCKED", "reason": str(exc), "a1_execution_started": False}
        (args.output_dir / "receipt.json").write_bytes(encode(result) + b"\n")
        print(json.dumps(result))
        return 2
    harness_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    catalog_path = repo / "cases/a2/e1-case-catalog.json"
    catalog = json.loads(catalog_path.read_text())
    with tempfile.TemporaryDirectory(prefix="a2-e1-evaluation-") as scratch:
        evaluation = Evaluation(Seam(args.a1_checkout, scratch))
        evaluation.run_group("smoke", evaluation.smoke)
        evaluation.run_group("ordering_correction", evaluation.ordering_and_correction)
        evaluation.run_group("batch_1", lambda: evaluation.batch(1))
        evaluation.run_group("batch_2", lambda: evaluation.batch(2))
        for fault in [f"F{i}" for i in range(1, 9)] + ["APPEND_BEFORE_COMMIT"]:
            evaluation.run_group(fault, lambda fault=fault: evaluation.fault(fault))
        evaluation.run_group("replica_errors", evaluation.replica_errors)
        evaluation.run_group("boundaries", evaluation.boundaries)
        evaluation.run_group("retry_template_boundary", evaluation.retry_and_template_boundary)
        evaluation.run_group("secrets", evaluation.secrets)
        # Revalidate all required groups and the exact code/contract after execution.
        for name in catalog["required_sections"]:
            if name not in evaluation.sections or evaluation.sections[name]["checks"] == 0:
                evaluation.missing.append(f"required-section:{name}")
        first = evaluation.sections["batch_1"]["receipt"]
        second = evaluation.sections["batch_2"]["receipt"]
        for field in ("case_manifest_sha256", "normalized_fingerprint", "expected_fingerprint", "metrics", "terminal_outcomes"):
            if field not in first or field not in second:
                evaluation.missing.append(f"dual-run:{field}")
            else:
                evaluation.check("dual-run", f"independent_fresh_{field}", first[field] == second[field])
        output_leaks = sum(r["sentinel_leaks"] for r in evaluation.seam.records)
        evaluation.metrics["synthetic_sentinel_leak"] += output_leaks
        evaluation.check("privacy", "zero_raw_stdout_stderr_sentinel_leaks", output_leaks == 0)
        evaluation.check("scope", "A1_checkout_unchanged", git(args.a1_checkout, "rev-parse", "HEAD") == A1_HEAD
                         and not git(args.a1_checkout, "status", "--porcelain"))
        evaluation.check("scope", "A2_harness_unchanged", hashlib.sha256(Path(__file__).read_bytes()).hexdigest() == harness_hash)
        normalized = {"a1_head": A1_HEAD, "contract_commit": CONTRACT,
                      "catalog_sha256": digest(catalog), "metrics": dict(evaluation.metrics),
                      "batch_fingerprints": [first.get("normalized_fingerprint"), second.get("normalized_fingerprint")],
                      "checks": [{k: c[k] for k in ("case", "invariant", "passed")} for c in evaluation.checks],
                      "missing": evaluation.missing}
        result = {
            "receipt_version": "a2-e1-independent/1", "work_order": "ENG-A2-E1-01",
            "verdict": verdict(evaluation.checks, evaluation.missing), "acceptance_ceiling": "A2 ONLY; Board E1 decision required; STOP",
            "a1_head": A1_HEAD, "contract_commit": CONTRACT, "contract_version": "canonical_event/v1",
            "a2_execution_head": git(repo, "rev-parse", "HEAD"), "a2_execution_tree": git(repo, "rev-parse", "HEAD^{tree}"),
            "harness_sha256": harness_hash, "case_catalog_sha256": digest(catalog), "intake": intake,
            "environment": {"python": platform.python_version(), "implementation": platform.python_implementation(),
                            "platform": platform.platform(), "machine": platform.machine(),
                            "transport": "OFFLINE_DRIVE_STUB", "child_environment": "explicit minimal allowlist, no credentials",
                            "runtime_dependencies": "Python standard library; A1 executed via PYTHONPATH", "store_substrate": "POSIX local temporary directory"},
            "started_at": started, "finished_at": datetime.now(timezone.utc).isoformat(),
            "normalized_result_fingerprint": digest(normalized), "zero_tolerance_metrics": dict(evaluation.metrics),
            "metric_counting": "deviations over all checked snapshots; zero means no deviation in any snapshot",
            "sections": evaluation.sections, "checks": evaluation.checks, "missing_evidence": evaluation.missing,
            "failed_checks": [c for c in evaluation.checks if not c["passed"]],
            "operations": len(evaluation.seam.records), "live_provider_calls": 0, "real_remote_integrations": 0,
            "limits": ["process crashes on this POSIX substrate, not physical power loss",
                       "observable CLI evidence only; no Journal database/WAL/outbox-internal inspection",
                       "A1 conformance is distinct reference evidence, never the A2 oracle",
                       "redaction covers these synthetic labeled credentials, not universal secret detection",
                       "unsupported authority operations and unchanged external controls are bounded negative evidence",
                       "remote preflight is a connector observation, not an atomic GitHub execution lock"]}
        ledger = b"".join(encode(r) + b"\n" for r in evaluation.seam.records)
        result["ledger_sha256"] = hashlib.sha256(ledger).hexdigest()
        result["evidence_sentinel_leaks"] = sum((ledger + encode(result)).count(s.encode()) for s in SENTINELS)
        if result["evidence_sentinel_leaks"]:
            result["verdict"] = "FAIL"
        (args.output_dir / "observations.jsonl").write_bytes(ledger)
        (args.output_dir / "receipt.json").write_bytes(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False).encode() + b"\n")
        (args.output_dir / "normalized-result.json").write_bytes(encode(normalized) + b"\n")
        seal = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(args.output_dir.iterdir()) if path.is_file()}
        (args.output_dir / "SHA256SUMS.json").write_bytes(encode(seal) + b"\n")
        print(json.dumps({"verdict": result["verdict"], "operations": result["operations"],
                          "checks": len(evaluation.checks), "failed_checks": len(result["failed_checks"]),
                          "missing": evaluation.missing, "normalized_result_fingerprint": digest(normalized)}))
        return 0 if result["verdict"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
