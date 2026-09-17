#!/usr/bin/env python3
"""A2-S2 public TestPort probe. No Companion-Mind imports or internal store reads."""
import argparse, json, pathlib, subprocess, tempfile

CONTRACT = "owned-home/1"
SCOPE = {"universe_id": "a2s2-home", "access_subject_id": "a2s2-owner"}

def fixture(source_id, version, revision, lifecycle, text):
    return {"source_id": source_id, "version": version, "revision": revision,
            "lifecycle": lifecycle, **SCOPE, "text": text,
            "observed_at": "2026-09-17T12:00:00+00:00", "synthetic": True, "public_safe": True}

def grant(source_id, version, decision="ALLOW"):
    return {**SCOPE, "source_id": source_id, "version": version, "decision": decision}

def turn(n, topic, needs, *, premise="task-v1", budget=4096, text=None):
    return {"request_id": f"a2s2-req-{n}", "session_id": "a2s2-session", "turn_id": f"a2s2-turn-{n}",
            "turn_no": n, **SCOPE, "source_id": "alpha", "source_version": "v2",
            "text": text or f"synthetic turn {n} for {topic}",
            "observed_at": f"2026-09-17T12:{n:02d}:00+00:00", "budget_bytes": budget,
            "contract_version": CONTRACT, "topic_id": topic, "premise_id": premise,
            "evidence_needs": needs}

def call(py, store, op, fixtures=(), grants=(), fault=None):
    req = {"contract_version": CONTRACT, "scope": SCOPE, "fixtures": list(fixtures), "grants": list(grants), **op}
    cmd = [py, "-I", "-m", "companion_mind.owned_home.testport", "--store", str(store)]
    if fault: cmd += ["--fault", fault]
    p = subprocess.run(cmd, input=json.dumps(req), text=True, capture_output=True, timeout=30)
    try: out = json.loads(p.stdout) if p.stdout.strip() else None
    except Exception: out = {"raw_stdout": p.stdout}
    return {"returncode": p.returncode, "stdout": out, "stderr": p.stderr}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--python", required=True); ap.add_argument("--output", required=True); a=ap.parse_args()
    alpha_cur=fixture("alpha","v2","r2","CURRENT","Alpha current synthetic evidence: blue lantern east.")
    alpha_hist=fixture("alpha","v1","r1","HISTORY","Alpha history synthetic evidence: blue lantern west.")
    beta=fixture("beta","v1","r1","CURRENT","Beta synthetic evidence: amber key north.")
    gamma=fixture("gamma","v1","r1","CURRENT","Gamma synthetic evidence: green notebook south.")
    fixtures=[alpha_cur,alpha_hist,beta,gamma]
    grants=[grant("alpha","v1"),grant("alpha","v2"),grant("beta","v1"),grant("gamma","v1")]
    with tempfile.TemporaryDirectory(prefix="a2s2-probe-") as td:
        s=pathlib.Path(td)
        out={}
        out["info"]=call(a.python,s,{"op":"info"})
        out["a1"]=call(a.python,s,{"op":"context_turn","turn":turn(1,"topic-a",[{"source_id":"alpha","route":"CURRENT"}], text="Where is the blue lantern now?")},fixtures,grants)
        out["a2"]=call(a.python,s,{"op":"context_turn","turn":turn(2,"topic-a",[{"source_id":"alpha","route":"CURRENT"}], text="Continue alpha.")},fixtures,grants)
        out["beta"]=call(a.python,s,{"op":"topic_switch","turn":turn(3,"topic-b",[{"source_id":"beta","route":"CURRENT"}], text="Switch to beta.")},fixtures,grants)
        out["a3"]=call(a.python,s,{"op":"topic_switch","turn":turn(4,"topic-a",[{"source_id":"alpha","route":"CURRENT"}], text="Back to alpha.")},fixtures,grants)
        out["state"]=call(a.python,s,{"op":"session_state","session_id":"a2s2-session"},fixtures,grants)
        out["history"]=call(a.python,s,{"op":"context_turn","turn":turn(5,"topic-h",[{"source_id":"alpha","route":"HISTORY"}])},fixtures,grants)
        out["exact"]=call(a.python,s,{"op":"context_turn","turn":turn(6,"topic-e",[{"source_id":"alpha","route":"EXACT","version":"v1","revision":"r1"}])},fixtures,grants)
        out["missing"]=call(a.python,s,{"op":"context_turn","turn":turn(7,"topic-m",[{"source_id":"missing","route":"CURRENT"}])},fixtures,grants)
        out["denied"]=call(a.python,s,{"op":"context_turn","turn":turn(8,"topic-d",[{"source_id":"beta","route":"CURRENT"}])},fixtures,[g for g in grants if g["source_id"]!="beta"])
        out["multi"]=call(a.python,s,{"op":"context_turn","turn":turn(9,"topic-multi",[{"source_id":"alpha","route":"CURRENT"},{"source_id":"beta","route":"CURRENT"},{"source_id":"gamma","route":"CURRENT"}])},fixtures,grants)
        out["low_budget"]=call(a.python,s,{"op":"context_turn","turn":turn(10,"topic-low",[{"source_id":"alpha","route":"CURRENT"},{"source_id":"beta","route":"CURRENT"}],budget=64)},fixtures,grants)
        out["safe_export"]=call(a.python,s,{"op":"safe_export"},fixtures,grants)
        pathlib.Path(a.output).write_text(json.dumps(out,sort_keys=True,indent=2,ensure_ascii=False),encoding="utf-8")
    return 0
if __name__=="__main__": raise SystemExit(main())
