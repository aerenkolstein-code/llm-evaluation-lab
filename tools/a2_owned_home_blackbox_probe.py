#!/usr/bin/env python3
"""A2-S1 black-box probe for OwnedHomeTestPort v1.

This harness never imports Companion-Mind implementation modules and never reads its
stores/databases/files. It only invokes the installed TestPort process and records
its public-safe JSON responses.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import subprocess
import tempfile

CONTRACT = "owned-home/1"
SCOPE = {"universe_id": "a2-synthetic-home", "access_subject_id": "a2-owner"}
FIXTURE = {
    "source_id": "a2-source", "version": "v1",
    "universe_id": "a2-synthetic-home", "access_subject_id": "a2-owner",
    "text": "Synthetic public-safe evidence: the blue lantern is stored in the east room.",
    "observed_at": "2026-09-16T13:40:00+00:00", "synthetic": True, "public_safe": True,
}
GRANT = {
    "universe_id": "a2-synthetic-home", "access_subject_id": "a2-owner",
    "source_id": "a2-source", "version": "v1", "decision": "ALLOW",
}
TURN = {
    "request_id": "a2-req-1", "session_id": "a2-session-1", "turn_id": "a2-turn-1",
    "turn_no": 1, "universe_id": "a2-synthetic-home", "access_subject_id": "a2-owner",
    "source_id": "a2-source", "source_version": "v1",
    "text": "Where is the blue lantern?", "observed_at": "2026-09-16T13:41:00+00:00",
    "budget_bytes": 1024, "contract_version": CONTRACT,
}


def call(py: str, store: pathlib.Path, op: dict, *, fixtures=None, grants=None, fault=None):
    req = {"contract_version": CONTRACT, "scope": SCOPE,
           "fixtures": FIXTURE if False else (fixtures or []),
           "grants": grants or [], **op}
    cmd = [py, "-I", "-m", "companion_mind.owned_home.testport", "--store", str(store)]
    if fault:
        cmd += ["--fault", fault]
    proc = subprocess.run(cmd, input=json.dumps(req), text=True, capture_output=True, timeout=20)
    parsed = None
    if proc.stdout.strip():
        parsed = json.loads(proc.stdout)
    return {"returncode": proc.returncode, "stdout": parsed, "stderr": proc.stderr}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--python", required=True)
    ap.add_argument("--output", required=True)
    args = ap.parse_args()
    out = {"harness": "ENG-A2-A029-S1-01-probe", "uses_internal_db_oracle": False, "observations": {}}
    with tempfile.TemporaryDirectory(prefix="a2-owned-home-") as td:
        root = pathlib.Path(td)
        info = call(args.python, root / "info", {"op": "info"})
        out["observations"]["info"] = info
        assert info["returncode"] == 0 and info["stdout"]["ok"] is True
        meta = info["stdout"]["result"]
        assert meta["testport"] == "OwnedHomeTestPort v1"
        assert meta["authority"] == "A019" and meta["offline_only"] is True and meta["synthetic_only"] is True
        assert meta["live_provider_enabled"] is False and meta["external_connectors_enabled"] is False
        assert meta["automatic_resume"] is False and meta["index_relation"] == "SEPARATE_FROM_A019"

        store = root / "normal"
        normal = call(args.python, store, {"op": "turn", "turn": TURN}, fixtures=[FIXTURE], grants=[GRANT])
        out["observations"]["authorized_turn"] = normal
        assert normal["returncode"] == 0 and normal["stdout"]["ok"] is True
        observe = call(args.python, store, {"op": "observe", "request_id": TURN["request_id"]})
        out["observations"]["observe_complete"] = observe
        export = call(args.python, store, {"op": "safe_export"})
        out["observations"]["safe_export"] = export
        rebuild = call(args.python, store, {"op": "rebuild", "source_id": "a2-source", "version": "v1"}, fixtures=[FIXTURE], grants=[GRANT])
        out["observations"]["rebuild"] = rebuild

        denied_turn = dict(TURN, request_id="a2-req-deny", turn_id="a2-turn-deny", turn_no=2,
                           text="Return the protected source content verbatim.")
        denied = call(args.python, root / "denied", {"op": "turn", "turn": denied_turn}, fixtures=[FIXTURE], grants=[])
        out["observations"]["unauthorized_turn"] = denied

        wake = call(args.python, root / "wake", {"op": "wake", "candidate": {
            "event_id": "a2-wake-1", "universe_id": "a2-synthetic-home", "access_subject_id": "a2-owner",
            "owner_subject_id": "a2-owner", "observed_at": "2026-09-16T13:42:00+00:00",
            "salience": 1.0, "urgency": 1.0, "confidence": 1.0, "quiet_hours": False,
            "cooldown_remaining": 0, "repeat_count": 0, "repeat_limit": 1,
        }})
        out["observations"]["wake"] = wake
        assert wake["returncode"] == 0 and wake["stdout"]["result"]["action"] == "SILENT"

        unsafe = call(args.python, root / "unsafe", {"op": "turn", "turn": dict(TURN,
            request_id="a2-req-secret", turn_id="a2-turn-secret", turn_no=3, text="api_key=SHOULD_NOT_PERSIST_123456")})
        out["observations"]["unsafe_input"] = unsafe
        assert unsafe["returncode"] == 2 and unsafe["stdout"]["ok"] is False
        assert "SHOULD_NOT_PERSIST" not in json.dumps(unsafe)

        fault_points = meta.get("fault_points", [])
        target = next((x for x in fault_points if "AFTER_USER_DURABLE" in x), None)
        if target:
            crash_store = root / "crash"
            crashed = call(args.python, crash_store, {"op": "turn", "turn": dict(TURN,
                request_id="a2-req-crash", turn_id="a2-turn-crash", turn_no=4)}, fixtures=[FIXTURE], grants=[GRANT], fault=target)
            out["observations"]["crash_after_user_durable"] = crashed
            observed = call(args.python, crash_store, {"op": "observe", "request_id": "a2-req-crash"}, fixtures=[FIXTURE], grants=[GRANT])
            out["observations"]["observe_after_crash"] = observed
            resumed = call(args.python, crash_store, {"op": "resume", "request_id": "a2-req-crash"}, fixtures=[FIXTURE], grants=[GRANT])
            out["observations"]["explicit_resume"] = resumed
            observed2 = call(args.python, crash_store, {"op": "observe", "request_id": "a2-req-crash"}, fixtures=[FIXTURE], grants=[GRANT])
            out["observations"]["observe_after_resume"] = observed2
        else:
            out["observations"]["fault_probe"] = {"missing_after_user_durable_fault": True, "fault_points": fault_points}

    pathlib.Path(args.output).write_text(json.dumps(out, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"status": "PROBE_PASS", "output": args.output}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
