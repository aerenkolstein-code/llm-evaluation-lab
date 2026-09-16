#!/usr/bin/env python3
"""Independent A2-S1 verification for OwnedHomeTestPort v1.

The harness treats the installed TestPort process as the only behavioral seam.
It never imports Companion-Mind implementation modules and never opens runtime
files/databases as correctness oracles.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import pathlib
import subprocess
import tempfile
from typing import Any

CONTRACT = "owned-home/1"
CANDIDATE_SHA = "b57c4cb21a64992ea338ce9f6e60199d9b5254cb"
CANDIDATE_TREE = "2efaa0bacd726d5c1506a33ea39da17529559ee7"
SCOPE = {"universe_id": "a2-synthetic-home", "access_subject_id": "a2-owner"}
FIXTURE = {
    "source_id": "a2-source", "version": "v1",
    "universe_id": SCOPE["universe_id"], "access_subject_id": SCOPE["access_subject_id"],
    "text": "Synthetic public-safe evidence: the blue lantern is stored in the east room.",
    "observed_at": "2026-09-16T13:40:00+00:00", "synthetic": True, "public_safe": True,
}
GRANT = {**SCOPE, "source_id": "a2-source", "version": "v1", "decision": "ALLOW"}
DENY_GRANT = {**SCOPE, "source_id": "a2-source", "version": "v1", "decision": "DENY"}
SECRET_SENTINEL = "SHOULD_NOT_PERSIST_123456"
FORBIDDEN_SAFE_OUTPUT_KEYS = {
    "password", "passwd", "credential", "credentials", "api_key", "apikey", "access_token",
    "refresh_token", "private_key", "hidden_reasoning", "chain_of_thought", "raw", "private_archive",
}


def base_turn(n: int, *, request_id: str | None = None, text: str = "Where is the blue lantern?", budget: int = 1024) -> dict:
    rid = request_id or f"a2-req-{n}"
    return {
        "request_id": rid, "session_id": "a2-session-verify", "turn_id": f"a2-turn-{n}",
        "turn_no": n, **SCOPE, "source_id": "a2-source", "source_version": "v1",
        "text": text, "observed_at": f"2026-09-16T13:{40 + (n % 19):02d}:00+00:00",
        "budget_bytes": budget, "contract_version": CONTRACT,
    }


def call(py: str, store: pathlib.Path, op: dict, *, fixtures=None, grants=None, fault=None, timeout=20) -> dict:
    request = {"contract_version": CONTRACT, "scope": SCOPE,
               "fixtures": fixtures or [], "grants": grants or [], **op}
    cmd = [py, "-I", "-m", "companion_mind.owned_home.testport", "--store", str(store)]
    if fault:
        cmd += ["--fault", fault]
    proc = subprocess.run(cmd, input=json.dumps(request), text=True, capture_output=True, timeout=timeout)
    parsed = json.loads(proc.stdout) if proc.stdout.strip() else None
    return {"returncode": proc.returncode, "stdout": parsed, "stderr": proc.stderr}


def result(call_result: dict) -> dict:
    assert call_result["returncode"] == 0, call_result
    assert call_result["stdout"] and call_result["stdout"].get("ok") is True, call_result
    return call_result["stdout"]["result"]


def scan_safe(value: Any, *, allow_fixture_text: bool = True) -> None:
    """Bounded public-receipt scan; does not claim universal DLP."""
    if isinstance(value, dict):
        for k, v in value.items():
            if str(k).lower() in FORBIDDEN_SAFE_OUTPUT_KEYS:
                raise AssertionError(f"forbidden public-output key: {k}")
            scan_safe(v, allow_fixture_text=allow_fixture_text)
    elif isinstance(value, list):
        for v in value:
            scan_safe(v, allow_fixture_text=allow_fixture_text)
    elif isinstance(value, str):
        low = value.lower()
        assert SECRET_SENTINEL.lower() not in low
        assert "journal.sqlite" not in low and "sqlite_master" not in low
        assert "chain-of-thought" not in low and "hidden reasoning" not in low
        if not allow_fixture_text:
            assert FIXTURE["text"] not in value


def stable_ids(r: dict) -> tuple:
    keys = ("request_id", "session_id", "turn_id", "user_event_id", "assistant_event_id",
            "attempt_id", "trace_id", "task_id", "correlation_id")
    return tuple(r.get(k) for k in keys)


def zero_side_effects(r: dict) -> None:
    counters = r.get("counters", {})
    assert counters.get("provider_invocations", r.get("provider_invocations", 0)) == 0
    assert counters.get("notifications", 0) == 0
    assert counters.get("continuations", 0) == 0
    assert counters.get("external_side_effects", 0) == 0


def receipt_summary(r: dict) -> dict:
    return {
        "status": r.get("status"), "stop_reason": r.get("stop_reason"), "external_outcome": r.get("external_outcome"),
        "event_count": r.get("event_count"), "terminal_count": r.get("terminal_count"),
        "request_id": r.get("request_id"), "turn_id": r.get("turn_id"),
        "user_event_id": r.get("user_event_id"), "assistant_event_id": r.get("assistant_event_id"),
        "trace_id": r.get("trace_id"), "task_id": r.get("task_id"),
        "counters": r.get("counters"), "presentation_order": r.get("presentation_order"),
        "execution_order": r.get("execution_order"),
        "permission": r.get("projection", {}).get("permission"),
        "context": r.get("projection", {}).get("context"),
        "retrieval": r.get("projection", {}).get("retrieval"),
        "index": r.get("projection", {}).get("index"),
        "receipts": r.get("receipts"),
    }


def case(cases: dict, name: str, fn) -> None:
    try:
        evidence = fn()
        cases[name] = {"status": "PASS", "evidence": evidence}
    except Exception as exc:
        cases[name] = {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--python", required=True)
    ap.add_argument("--wheel", required=True)
    ap.add_argument("--candidate-sha", default=CANDIDATE_SHA)
    ap.add_argument("--candidate-tree", default=CANDIDATE_TREE)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    assert args.candidate_sha == CANDIDATE_SHA
    assert args.candidate_tree == CANDIDATE_TREE
    wheel_sha = hashlib.sha256(pathlib.Path(args.wheel).read_bytes()).hexdigest()
    cases: dict[str, dict] = {}
    meta: dict = {}

    with tempfile.TemporaryDirectory(prefix="a2-owned-home-final-") as td:
        root = pathlib.Path(td)

        info_call = call(args.python, root / "info", {"op": "info"})
        info = result(info_call)
        meta = info
        assert info == {
            "FTS5": True, "authority": "A019", "automatic_resume": False,
            "contract_version": CONTRACT, "external_connectors_enabled": False,
            "fault_points": ["AFTER_PROVIDER_INTENT", "AFTER_STUB_FRAME", "AFTER_USER_DURABLE", "BEFORE_DISPLAY"],
            "index_relation": "SEPARATE_FROM_A019", "live_provider_enabled": False,
            "offline_only": True, "supported_ops": ["turn", "observe", "resume", "safe_export", "wake", "rebuild", "info"],
            "synthetic_only": True, "testport": "OwnedHomeTestPort v1",
        }
        scan_safe(info)

        auth_store = root / "authorized"
        auth_turn = base_turn(1)
        auth = result(call(args.python, auth_store, {"op": "turn", "turn": auth_turn}, fixtures=[FIXTURE], grants=[GRANT]))

        def ts01():
            order = auth["execution_order"]
            assert order.index("USER_DURABLE_RECEIPT") < order.index("PROVIDER_STUB_INVOKED")
            assert auth["receipts"]["user"]["journal_offset"] == 1
            assert auth["counters"]["cognition_stub_invocations"] == 1
            assert auth["provider_invocations"] == 0
            return {"user_offset": 1, "user_before_stub": True, "provider_invocations": 0}
        case(cases, "TS1-01", ts01)

        def ts02():
            assert auth["presentation_order"] == ["USER_DURABLE_RECEIPT", "ASSISTANT_DURABLE_RECEIPT", "DISPLAY"]
            assert auth["terminal_count"] == 1 and auth["event_count"] == 2
            assert auth["receipts"]["assistant"]["journal_offset"] == 2
            assert auth["receipts"]["assistant"]["store_generation"] == auth["receipts"]["user"]["store_generation"]
            return {"presentation_order": auth["presentation_order"], "assistant_offset": 2, "terminal_count": 1}
        case(cases, "TS1-02", ts02)

        crash_store = root / "crash"
        crash_turn = base_turn(2, request_id="a2-req-crash")
        crashed = call(args.python, crash_store, {"op": "turn", "turn": crash_turn}, fixtures=[FIXTURE], grants=[GRANT], fault="AFTER_USER_DURABLE")
        observed_crash = result(call(args.python, crash_store, {"op": "observe", "request_id": "a2-req-crash"}, fixtures=[FIXTURE], grants=[GRANT]))
        resumed = result(call(args.python, crash_store, {"op": "resume", "request_id": "a2-req-crash"}, fixtures=[FIXTURE], grants=[GRANT]))
        observed_resume = result(call(args.python, crash_store, {"op": "observe", "request_id": "a2-req-crash"}, fixtures=[FIXTURE], grants=[GRANT]))
        resumed_again = result(call(args.python, crash_store, {"op": "resume", "request_id": "a2-req-crash"}, fixtures=[FIXTURE], grants=[GRANT]))
        export_crash = result(call(args.python, crash_store, {"op": "safe_export"}))

        def ts03():
            assert crashed["returncode"] == 86 and crashed["stdout"] is None
            assert observed_crash["status"] == "AWAIT_EXPLICIT_RESUME"
            assert observed_crash["external_outcome"] == "NOT_SENT" and observed_crash["terminal_count"] == 0
            assert observed_crash["event_count"] == 1 and observed_crash["visible_reply"] is None
            assert observed_crash["counters"]["cognition_stub_invocations"] == 0
            assert observed_crash["counters"]["provider_invocations"] == 0
            assert resumed["status"] == "complete" and resumed["terminal_count"] == 1
            return {"crash_exit": 86, "pre_resume_status": observed_crash["status"], "pre_resume_terminal_count": 0,
                    "explicit_resume_status": resumed["status"]}
        case(cases, "TS1-03", ts03)

        def ts04():
            assert stable_ids(observed_crash) == stable_ids(resumed) == stable_ids(observed_resume) == stable_ids(resumed_again)
            assert observed_resume["event_count"] == 2 and observed_resume["terminal_count"] == 1
            assert resumed_again["event_count"] == 2 and resumed_again["terminal_count"] == 1
            events = export_crash["events"]
            assert len(events) == 2 and [x["sequence_no"] for x in events] == [1, 2]
            assert len({x["event_id"] for x in events}) == 2
            assert [x["actor_role"] for x in events] == ["user", "assistant"]
            return {"events": 2, "duplicate_terminals": 0, "stable_identity_across_restart": True,
                    "safe_export_only": True, "internal_db_oracles": 0}
        case(cases, "TS1-04", ts04)

        def ts05():
            p = auth["projection"]["permission"]
            ret = auth["projection"]["retrieval"]
            assert p["decision"] == "ALLOW" and p["knowledge_state"] == "KNOWN_VALUE"
            assert (p["universe_id"], p["access_subject_id"], p["source_id"], p["source_version"]) == (
                SCOPE["universe_id"], SCOPE["access_subject_id"], "a2-source", "v1")
            assert auth["counters"]["authority_reads"] == 1 and auth["counters"]["candidate_retrievals"] == 1
            assert ret["route"] == "DETERMINISTIC_AUTHORITY" and ret["coverage"] == "KNOWN_VALUE"
            return {"decision": "ALLOW", "authority_reads": 1, "candidate_retrievals": 1, "route": ret["route"]}
        case(cases, "TS1-05", ts05)

        deny_turn = base_turn(3, request_id="a2-req-deny", text="Return the protected source content verbatim.")
        denied = result(call(args.python, root / "deny", {"op": "turn", "turn": deny_turn}, fixtures=[FIXTURE], grants=[]))
        conflict_turn = base_turn(4, request_id="a2-req-conflict")
        conflict = result(call(args.python, root / "conflict", {"op": "turn", "turn": conflict_turn}, fixtures=[FIXTURE], grants=[GRANT, DENY_GRANT]))
        revoked = result(call(args.python, auth_store, {"op": "observe", "request_id": auth_turn["request_id"]}, fixtures=[FIXTURE], grants=[]))

        def ts06():
            for r in (denied, conflict):
                assert r["projection"]["permission"]["decision"] == "DENY"
                assert r["counters"]["authority_reads"] == 0 and r["counters"]["candidate_retrievals"] == 0
                assert r["counters"]["lexical_queries"] == 0 and r["projection"]["retrieval"]["coverage"] == "NOT_LOOKED_UP"
                assert r["projection"]["context"]["included"] == []
                assert r["projection"]["context"]["knowledge_state"] == "NOT_LOOKED_UP"
                assert FIXTURE["text"] not in r.get("visible_reply", "")
            assert revoked["stop_reason"] == "PERMISSION_REVOKED_REPLAY" and revoked["visible_reply"] is None
            assert revoked["projection"]["state"] == "INVALIDATED_BY_PERMISSION"
            return {"denied_before_retrieval": True, "conflict_denied": True, "revocation_replay": "WITHHELD",
                    "content_leaks": 0}
        case(cases, "TS1-06", ts06)

        low_turn = base_turn(5, request_id="a2-req-low-budget", budget=64)
        low = result(call(args.python, root / "low-budget", {"op": "turn", "turn": low_turn}, fixtures=[FIXTURE], grants=[GRANT]))

        def ts07():
            ctx = auth["projection"]["context"]
            assert ctx["authority"] is False and ctx["context_fingerprint"]
            assert ctx["budget"]["silent_truncations"] == 0 and ctx["budget"]["omitted_bytes"] == 0
            assert len(ctx["included"]) == 1 and ctx["omitted"] == []
            lowctx = low["projection"]["context"]
            assert lowctx["budget"]["silent_truncations"] == 0
            assert lowctx["budget"]["limit"] == 64
            assert lowctx["budget"]["omitted_bytes"] >= 0
            if lowctx["budget"]["required"] > 64:
                assert lowctx["omitted"] or lowctx["status"] != "READY"
            scan_safe(ctx)
            return {"context_fingerprint": ctx["context_fingerprint"], "silent_truncations": 0,
                    "normal_included": len(ctx["included"]), "low_budget_status": lowctx["status"],
                    "low_budget_omitted": len(lowctx["omitted"])}
        case(cases, "TS1-07", ts07)

        rebuild_store = root / "rebuild"
        rebuild1 = result(call(args.python, rebuild_store, {"op": "rebuild", "source_id": "a2-source", "version": "v1"}, fixtures=[FIXTURE], grants=[GRANT]))
        rebuild2 = result(call(args.python, rebuild_store, {"op": "rebuild", "source_id": "a2-source", "version": "v1"}, fixtures=[FIXTURE], grants=[GRANT]))
        rebuild_deny = result(call(args.python, root / "rebuild-deny", {"op": "rebuild", "source_id": "a2-source", "version": "v1"}, fixtures=[FIXTURE], grants=[]))

        def ts08():
            i1, i2 = rebuild1["index"], rebuild2["index"]
            assert i1["derived_only"] is True and i1["authority_writes"] == 0
            assert i1["storage_relation"] == "SEPARATE_FROM_A019" and i1["index_version"] == "fts5/1"
            assert i1["index_fingerprint"] == i2["index_fingerprint"]
            assert len(i1["source_refs"]) == 1 and i1["source_refs"][0]["source_id"] == "a2-source"
            assert rebuild_deny["permission"]["decision"] == "DENY"
            assert rebuild_deny.get("index") is None or rebuild_deny["index"].get("source_refs", []) == []
            return {"physical_separation": True, "derived_only": True, "authority_writes": 0,
                    "rebuild_stable": True, "scope_denial": True, "index_fingerprint": i1["index_fingerprint"]}
        case(cases, "TS1-08", ts08)

        wake_variants = [
            ("baseline", {}), ("quiet", {"quiet_hours": True}), ("cooldown", {"cooldown_remaining": 1}),
            ("repeat", {"repeat_count": 1, "repeat_limit": 1}), ("owner", {"owner_subject_id": "a2-other"}),
            ("low-salience", {"salience": 0.1}), ("low-urgency", {"urgency": 0.1}),
        ]
        wake_results = []
        for idx, (label, patch) in enumerate(wake_variants, 1):
            cand = {"event_id": f"a2-wake-{idx}", **SCOPE, "owner_subject_id": SCOPE["access_subject_id"],
                    "observed_at": "2026-09-16T14:00:00+00:00", "salience": 1.0, "urgency": 1.0,
                    "confidence": 1.0, "quiet_hours": False, "cooldown_remaining": 0,
                    "repeat_count": 0, "repeat_limit": 1}
            cand.update(patch)
            wake_results.append((label, result(call(args.python, root / f"wake-{idx}", {"op": "wake", "candidate": cand}))))

        def ts09():
            evidence = {}
            for label, r in wake_results:
                assert r["action"] == "SILENT" and r["notifications"] == 0 and r["continuations"] == 0 and r["external_side_effects"] == 0
                assert r["decision_fingerprint"]
                evidence[label] = r["suppressed_by"]
            return {"variants": evidence, "notifications": 0, "continuations": 0, "side_effects": 0}
        case(cases, "TS1-09", ts09)

        def ts10():
            assert stable_ids(observed_crash) == stable_ids(resumed) == stable_ids(observed_resume) == stable_ids(resumed_again)
            assert observed_resume["receipts"]["user"]["disposition"] == "ALREADY_COMMITTED"
            assert observed_resume["receipts"]["assistant"]["disposition"] == "ALREADY_COMMITTED"
            return {"stable_identity": True, "explicit_id_only_resume": True, "repeat_resume_no_duplicate": True}
        case(cases, "TS1-10", ts10)

        unsafe = call(args.python, root / "unsafe", {"op": "turn", "turn": base_turn(6, request_id="a2-req-secret", text=f"api_key={SECRET_SENTINEL}")})
        invalid = call(args.python, root / "invalid", {"op": "db_read"})

        def ts11():
            assert unsafe["returncode"] == 2 and unsafe["stdout"] == {"ok": False, "error": "UNSAFE_INPUT"}
            assert invalid["returncode"] == 2 and invalid["stdout"] == {"ok": False, "error": "OPERATION_NOT_IN_SLICE"}
            scan_safe(unsafe, allow_fixture_text=False); scan_safe(invalid, allow_fixture_text=False)
            safe_export = result(call(args.python, auth_store, {"op": "safe_export"}))
            scan_safe(safe_export, allow_fixture_text=False)
            assert auth_turn["text"] not in json.dumps(safe_export)
            assert FIXTURE["text"] not in json.dumps(safe_export)
            return {"internal_db_oracles": 0, "unsafe_refusal": "UNSAFE_INPUT", "unsupported_db_op": "OPERATION_NOT_IN_SLICE",
                    "safe_export_bodies": 0, "secret_echoes": 0}
        case(cases, "TS1-11", ts11)

        def ts12():
            assert meta["testport"] == "OwnedHomeTestPort v1" and meta["authority"] == "A019"
            assert meta["offline_only"] is True and meta["synthetic_only"] is True
            assert meta["live_provider_enabled"] is False and meta["external_connectors_enabled"] is False
            assert meta["automatic_resume"] is False and meta["FTS5"] is True and meta["index_relation"] == "SEPARATE_FROM_A019"
            return {"runtime_repo": "aerenkolstein-code/Companion-Mind", "evaluation_repo": "aerenkolstein-code/llm-evaluation-lab",
                    "testport": meta["testport"], "offline_only": True, "synthetic_only": True,
                    "external_connectors_enabled": False, "FTS5": True, "index_relation": meta["index_relation"]}
        case(cases, "TS1-12", ts12)

        fresh_runs = []
        for run_no in (1, 2):
            store = root / f"fresh-{run_no}"
            ids, terminals = [], 0
            for n in range(1, 21):
                t = base_turn(100 * run_no + n, request_id=f"a2-fresh-{run_no}-{n}")
                r = result(call(args.python, store, {"op": "turn", "turn": t}, fixtures=[FIXTURE], grants=[GRANT]))
                assert r["event_count"] == 2 and r["terminal_count"] == 1
                zero_side_effects(r)
                ids.extend([r["user_event_id"], r["assistant_event_id"]]); terminals += r["terminal_count"]
            ev = result(call(args.python, store, {"op": "safe_export"}))["events"]
            assert len(ev) == 40 and [e["sequence_no"] for e in ev] == list(range(1, 41))
            assert len({e["event_id"] for e in ev}) == 40 and set(ids) == {e["event_id"] for e in ev}
            fresh_runs.append({"turns": 20, "events": 40, "terminals": terminals, "loss": 0, "duplicates": 0})

    failed = [k for k, v in cases.items() if v["status"] != "PASS"]
    zero_tolerance = []
    if failed:
        zero_tolerance.extend(failed)
    for r in (auth, denied, conflict, resumed, observed_resume):
        try: zero_side_effects(r)
        except AssertionError: zero_tolerance.append("SIDE_EFFECT")
    receipt = {
        "schema_id": "a2-a029-s1-blackbox/v1",
        "work_order": "ENG-A2-A029-S1-01",
        "candidate": {"repository": "aerenkolstein-code/Companion-Mind", "pr": 28,
                      "head_sha": args.candidate_sha, "tree_sha": args.candidate_tree,
                      "wheel_sha256": wheel_sha},
        "evaluation": {"repository": "aerenkolstein-code/llm-evaluation-lab",
                       "seam": "OwnedHomeTestPort v1", "process_only": True,
                       "uses_internal_db_oracle": False, "imports_runtime_internals": False},
        "cases": cases,
        "fresh_runs": fresh_runs,
        "zero_tolerance_count": len(set(zero_tolerance)),
        "zero_tolerance_failures": sorted(set(zero_tolerance)),
        "limitations": [
            "offline/synthetic/process-crash/TestPort scope only",
            "no physical power-cut test",
            "no live provider/Drive/OAuth/credential exercise",
            "no native-browser rendering/bfcache verification in A2",
            "secret check is bounded to declared unsafe patterns and public receipt fields",
        ],
        "verdict": "A2-S1 PASS" if not failed and not zero_tolerance else "A2-S1 FAIL / REPAIR REQUIRED",
    }
    scan_safe(receipt)
    pathlib.Path(args.output).write_text(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"verdict": receipt["verdict"], "zero_tolerance_count": receipt["zero_tolerance_count"],
                      "case_count": len(cases), "wheel_sha256": wheel_sha}, sort_keys=True))
    return 0 if receipt["verdict"] == "A2-S1 PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
