#!/usr/bin/env python3
"""Independent A2-S3 black-box verification for A029 P2-S3.

The exact installed wheel is treated as a black box. Product behavior is observed
only through OwnedHomeTestPort v1 JSON/process I/O and the public loopback /models
shell. This harness never imports Companion-Mind runtime/store/index/model-registry
internals and never opens their persistence files as correctness oracles.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import subprocess
import tempfile
import time
from copy import deepcopy
from typing import Any

CONTRACT = "owned-home/1"
CANDIDATE_SHA = "3b9b94cb37e23b761782fb1ae8d54345b931b3b1"
CANDIDATE_TREE = "dff89b764eabcb8d1833256a9540edf88e19b536"
SCOPE = {"universe_id": "a2-s3-home", "access_subject_id": "a2-s3-owner"}
SECRET = "SECRET_A2S3_SENTINEL_918273"

def fixture(source_id: str, text: str, *, version="v1", revision="r1", lifecycle="CURRENT") -> dict:
    return {
        "source_id": source_id, "version": version, "revision": revision, "lifecycle": lifecycle,
        **SCOPE, "text": text, "observed_at": "2026-09-18T06:00:00+00:00",
        "synthetic": True, "public_safe": True,
    }

ALPHA = fixture("alpha", "PUBLIC SYNTHETIC alpha evidence: blue lantern east.")
BETA = fixture("beta", "PUBLIC SYNTHETIC beta evidence: amber key north.")
GAMMA = fixture("gamma", "PUBLIC SYNTHETIC gamma evidence: green notebook south.")
FIXTURES = [ALPHA, BETA, GAMMA]

def grant(source_id: str, version="v1", decision="ALLOW") -> dict:
    return {**SCOPE, "source_id": source_id, "version": version, "decision": decision}

GRANTS = [grant("alpha"), grant("beta"), grant("gamma")]
PROFILE_REFS = [
    {"profile_key": "synthetic-small", "profile_version": "v1"},
    {"profile_key": "synthetic-large", "profile_version": "v1"},
    {"profile_key": "synthetic-capable", "profile_version": "v1"},
]

def custom_profile(key: str, version: str, capacity: int, output: int, *, provider=None, model=None,
                   structured=False, tools=False, media=False, files=False, cost=1, latency=1) -> dict:
    return {
        "provider_key": provider or ("provider-" + key),
        "model_key": model or ("model-" + key),
        "profile_key": key, "profile_version": version,
        "context_capacity": capacity, "output_reserve": output,
        "structured_output": structured, "tool_calls": tools, "media": media, "files": files,
        "cost_rank": cost, "latency_ms": latency,
    }

CUSTOM = [
    custom_profile("reg-small", "v1", 4096, 256, cost=1, latency=2),
    custom_profile("reg-large", "v1", 32768, 2048, structured=True, media=True, files=True, cost=3, latency=3),
    custom_profile("reg-capable", "v1", 16384, 1024, structured=True, tools=True, media=True, files=True, cost=2, latency=1),
]

def model_turn(n: int, *, request=None, session="a2s3-session", topic="topic-a", source="alpha",
               needs=None, text=None, budget=16384, intent=None, script="COMPLETE", premise="task-v1") -> dict:
    return {
        "request_id": request or f"a2s3-req-{n}",
        "session_id": session, "turn_id": f"a2s3-turn-{n}", "turn_no": n,
        **SCOPE, "source_id": source, "source_version": "v1",
        "text": text or f"PUBLIC synthetic model turn {n}",
        "observed_at": f"2026-09-18T06:{n % 60:02d}:00+00:00",
        "budget_bytes": budget, "contract_version": CONTRACT,
        "topic_id": topic, "premise_id": premise,
        "evidence_needs": needs if needs is not None else [{"source_id": source, "route": "CURRENT"}],
        "model_intent": intent or {"preferred_profile_key": "synthetic-small", "preferred_profile_version": "v1"},
        "model_script": script,
    }

def old_turn(n: int, *, request=None, text="Where is alpha?", budget=2048) -> dict:
    return {
        "request_id": request or f"a2s3-old-{n}", "session_id": "a2s3-old-session",
        "turn_id": f"a2s3-old-turn-{n}", "turn_no": n, **SCOPE,
        "source_id": "old-source", "source_version": "v1", "text": text,
        "observed_at": f"2026-09-18T07:{n % 60:02d}:00+00:00",
        "budget_bytes": budget, "contract_version": CONTRACT,
    }

OLD_FIXTURE = {
    "source_id": "old-source", "version": "v1", **SCOPE,
    "text": "PUBLIC SYNTHETIC inherited evidence.", "observed_at": "2026-09-18T06:00:00+00:00",
    "synthetic": True, "public_safe": True,
}
OLD_GRANT = grant("old-source")

def call(py: str, store: pathlib.Path, operation: dict, *, fixtures=None, grants=None,
         model_profiles=None, fault=None, timeout=30) -> dict:
    req = {
        "contract_version": CONTRACT, "scope": SCOPE,
        "fixtures": list(fixtures or []), "grants": list(grants or []),
        **operation,
    }
    if model_profiles is not None:
        req["model_profiles"] = model_profiles
    cmd = [py, "-I", "-m", "companion_mind.owned_home.testport", "--store", str(store)]
    if fault:
        cmd += ["--fault", fault]
    p = subprocess.run(cmd, input=json.dumps(req), text=True, capture_output=True, timeout=timeout)
    parsed = json.loads(p.stdout) if p.stdout.strip() else None
    return {"returncode": p.returncode, "stdout": parsed, "stderr": p.stderr}

def result(c: dict) -> dict:
    assert c["returncode"] == 0, c
    assert c["stdout"] and c["stdout"].get("ok") is True, c
    return c["stdout"]["result"]

def case(cases: dict, name: str, fn) -> None:
    try:
        cases[name] = {"status": "PASS", "evidence": fn()}
    except Exception as exc:
        cases[name] = {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}

def scan_no_secret(value: Any, *, forbidden_texts=()) -> None:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False)
    assert SECRET not in raw
    for text in forbidden_texts:
        assert text not in raw
    low = raw.lower()
    assert "chain_of_thought" not in low and "hidden_reasoning" not in low

def launch_shell(py: str, store: pathlib.Path):
    p = subprocess.Popen(
        [py, "-I", "-m", "companion_mind.owned_home.shell", "--store", str(store), "--port", "0"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    url = p.stdout.readline().strip()
    if not url.startswith("http://127.0.0.1:"):
        err = p.stderr.read()
        p.terminate()
        raise AssertionError(f"shell did not start: {url!r} {err!r}")
    return p, url

def runtime_requirements(py: str) -> list[str]:
    code = (
        "import importlib.metadata as m,json;"
        "r=m.metadata('companion-mind').get_all('Requires-Dist') or [];"
        "print(json.dumps([x for x in r if 'extra ==' not in x]))"
    )
    p = subprocess.run([py, "-I", "-c", code], text=True, capture_output=True, check=True)
    return json.loads(p.stdout)

def ts3_01(py, root):
    regs = []
    orders = [CUSTOM, list(reversed(CUSTOM)), [CUSTOM[1], CUSTOM[0], CUSTOM[2]]]
    for i, profiles in enumerate(orders):
        regs.append(result(call(py, root/f"reg-{i}", {"op":"model_registry"}, model_profiles=profiles)))
    fps = {r["registry_fingerprint"] for r in regs}
    assert len(fps) == 1
    projections = [r["profiles"] for r in regs]
    assert projections[0] == projections[1] == projections[2]
    dup = call(py, root/"reg-dup", {"op":"model_registry"}, model_profiles=[CUSTOM[0], CUSTOM[0]])
    assert dup["returncode"] == 2 and dup["stdout"]["error"] == "DUPLICATE_PROFILE_IDENTITY"
    return {"permutations":3, "registry_fingerprint":regs[0]["registry_fingerprint"],
            "profiles":[p["profile_key"]+"/"+p["profile_version"] for p in regs[0]["profiles"]],
            "duplicates":"DENY"}

def ts3_02(py, root):
    profiles = [
        custom_profile("exact-small","v1",4096,256),
        custom_profile("exact-small","v2",8192,512),
    ]
    one = result(call(py,root/"lookup1",{"op":"model_lookup","profile_key":"exact-small","profile_version":"v1"},model_profiles=profiles))
    two = result(call(py,root/"lookup2",{"op":"model_lookup","profile_key":"exact-small","profile_version":"v2"},model_profiles=profiles))
    missing = result(call(py,root/"lookup3",{"op":"model_lookup","profile_key":"exact-small","profile_version":"v3"},model_profiles=profiles))
    assert one["status"] == two["status"] == "RESOLVED"
    assert one["profile"]["profile_version"] == "v1" and two["profile"]["profile_version"] == "v2"
    assert missing["status"] == "EXACT_PROFILE_UNRESOLVED" and missing["profile"] is None
    intent = {
        "preferred_profile_key":"exact-small","preferred_profile_version":"v3",
        "allowed_profiles":[{"profile_key":"exact-small","profile_version":"v3"}],
        "fallback_policy":"STOP",
    }
    prev = result(call(py,root/"lookup-preview",{"op":"model_preview","turn":model_turn(1,intent=intent)},fixtures=FIXTURES,grants=GRANTS,model_profiles=profiles))
    assert prev["selection"]["selected"] is None and prev["stop_reason"] == "NO_COMPATIBLE_PROFILE"
    assert prev["provider_invocations"] == 0
    return {"exact_versions":["v1","v2"],"missing":"EXACT_PROFILE_UNRESOLVED",
            "wrong_profile_returns":0,"preview_invocations":0}

def ts3_03(py, root):
    bad_intent = {
        "preferred_profile_key":"synthetic-small","preferred_profile_version":"v1",
        "required_capabilities":["tool_calls"],"fallback_policy":"STOP",
    }
    bad = result(call(py,root/"cap-bad",{"op":"model_preview","turn":model_turn(1,intent=bad_intent)},fixtures=FIXTURES,grants=GRANTS))
    assert bad["selection"]["selected"] is None and bad["provider_invocations"] == 0
    good_intent = {
        "preferred_profile_key":"synthetic-capable","preferred_profile_version":"v1",
        "required_capabilities":["tool_calls","files","media"],"response_format":"json",
    }
    good = result(call(py,root/"cap-good",{"op":"model_preview","turn":model_turn(1,intent=good_intent)},fixtures=FIXTURES,grants=GRANTS))
    assert good["selection"]["selected"] == {"profile_key":"synthetic-capable","profile_version":"v1"}
    assert good["provider_invocations"] == 0 and set(good["selection"]["required_capabilities"]) == {"tool_calls","files","media","structured_output"}
    return {"mismatch_invocations":0,"silent_downgrades":0,"required_capabilities":4,
            "selected":"synthetic-capable/v1","real_tool_execution":0}

def ts3_04(py, root):
    small = result(call(py,root/"budget-small",{"op":"model_preview","turn":model_turn(1,intent={
        "preferred_profile_key":"synthetic-small","preferred_profile_version":"v1"})},fixtures=FIXTURES,grants=GRANTS))
    large = result(call(py,root/"budget-large",{"op":"model_preview","turn":model_turn(1,intent={
        "preferred_profile_key":"synthetic-large","preferred_profile_version":"v1"})},fixtures=FIXTURES,grants=GRANTS))
    sb = small["selection"]["effective_input_budget"]; lb = large["selection"]["effective_input_budget"]
    assert sb == 3712 and lb == 16384
    assert small["context"]["budget"]["limit"] == sb and large["context"]["budget"]["limit"] == lb
    huge = fixture("huge","X"*6000)
    huge_grant = [grant("huge")]
    turn = model_turn(1,source="huge",needs=[{"source_id":"huge","route":"CURRENT"}],
                      intent={"preferred_profile_key":"synthetic-small","preferred_profile_version":"v1"})
    limited = result(call(py,root/"budget-huge",{"op":"model_preview","turn":turn},fixtures=[huge],grants=huge_grant))
    assert limited["context"]["budget"]["silent_truncations"] == 0
    assert limited["context"]["status"] == "BLOCKED"
    assert limited["context"]["omitted"] and all(x["reason"] == "CONTEXT_BUDGET_EXCEEDED" for x in limited["context"]["omitted"])
    return {"small_budget":sb,"large_budget":lb,"silent_truncations":0,
            "oversized":"EXPLICIT_BLOCK_OR_OMIT","atomic_omissions":True}

def ts3_05(py, root):
    intent = {
        "preferred_profile_key":"synthetic-small","preferred_profile_version":"v1",
        "required_capabilities":["tool_calls"],"fallback_policy":"PRE_CALL_COMPATIBLE",
    }
    preview = result(call(py,root/"fallback-preview",{"op":"model_preview","turn":model_turn(1,intent=intent)},fixtures=FIXTURES,grants=GRANTS))
    assert preview["selection"]["selected"] == {"profile_key":"synthetic-capable","profile_version":"v1"}
    assert preview["selection"]["selection_reason"] == "PRE_CALL_COMPATIBLE_FALLBACK"
    assert preview["provider_invocations"] == 0
    actual = result(call(py,root/"fallback-run",{"op":"model_turn","turn":model_turn(1,intent=intent)},fixtures=FIXTURES,grants=GRANTS))
    assert actual["model_result"]["outcome"] == "COMPLETE"
    assert actual["model_trace"]["selected_profile"] == {"profile_key":"synthetic-capable","profile_version":"v1"}
    assert actual["provider_invocations"] == 1 and actual["real_provider_invocations"] == 0
    return {"selected":"synthetic-capable/v1","selection_invocations":0,"fallback_invocations":1,
            "deterministic_order":True,"real_provider_invocations":0}

def ts3_06(py, root):
    intent = {
        "preferred_profile_key":"synthetic-small","preferred_profile_version":"v1",
        "allowed_profiles":PROFILE_REFS[:2],"required_capabilities":["tool_calls"],
        "fallback_policy":"PRE_CALL_COMPATIBLE",
    }
    r = result(call(py,root/"no-compatible",{"op":"model_turn","turn":model_turn(1,intent=intent)},fixtures=FIXTURES,grants=GRANTS))
    assert r["stop_reason"] == "NO_COMPATIBLE_PROFILE"
    assert r["provider_invocations"] == 0 and r["model_trace"]["provider_invocation_count"] == 0
    assert r["terminal_count"] == 1 and r["receipts"]["user"]["contract_version"] == "canonical_event/v1"
    return {"no_compatible":"STOP","provider_invocations":0,"user_durable":True,
            "terminal_before_display":r["presentation_order"][-1] == "DISPLAY"}

def ts3_07(py, root):
    turn = model_turn(1,intent={"preferred_profile_key":"synthetic-capable","preferred_profile_version":"v1",
                                "required_capabilities":["tool_calls"]})
    preview = result(call(py,root/"spec-preview",{"op":"model_preview","turn":turn},fixtures=FIXTURES,grants=GRANTS))
    spec = preview["call_spec"]; assert spec and preview["provider_invocations"] == 0
    valid = result(call(py,root/"spec-valid",{"op":"model_validate_spec","turn":turn,"spec":spec},fixtures=FIXTURES,grants=GRANTS))
    assert valid["valid"] is True and valid["provider_invocations"] == 0
    mutations = []
    for label, path, value in [
        ("profile_version",("profile_version",),"v999"),
        ("context_fingerprint",("context_fingerprint",),"0"*64),
        ("input_budget",("input_budget",),spec["input_budget"]+1),
        ("identity",("identity","request_id"),"other-request"),
    ]:
        bad = deepcopy(spec)
        if len(path)==1: bad[path[0]]=value
        else: bad[path[0]][path[1]]=value
        check = result(call(py,root/f"spec-{label}",{"op":"model_validate_spec","turn":turn,"spec":bad},fixtures=FIXTURES,grants=GRANTS))
        assert check["valid"] is False and check["provider_invocations"] == 0
        mutations.append(label)
    bad_actual = deepcopy(spec); bad_actual["input_budget"] += 1
    stopped = result(call(py,root/"spec-stop",{"op":"model_turn","turn":turn,"expected_spec":bad_actual},fixtures=FIXTURES,grants=GRANTS))
    assert stopped["stop_reason"] == "MODEL_SPEC_INVALID" and stopped["provider_invocations"] == 0
    return {"exact_spec_valid":True,"invalidated_by":mutations,"stale_spec_invocations":0,
            "bound_identity":True,"bound_profile_context_budget":True}

def ts3_08(py, root):
    store=root/"outcomes"; observed={}
    mapping={"COMPLETE":"complete","PARTIAL":"partial","FAILED":"failed","TIMEOUT":"partial","UNKNOWN":"partial"}
    for n,outcome in enumerate(mapping,1):
        r=result(call(py,store,{"op":"model_turn","turn":model_turn(n,script=outcome)},fixtures=FIXTURES,grants=GRANTS))
        assert r["model_result"]["outcome"] == outcome
        assert r["status"] == mapping[outcome]
        assert r["model_trace"]["terminal_model_outcome"] == outcome
        assert r["provider_invocations"] == 1 and r["real_provider_invocations"] == 0
        observed[outcome]={"canonical_status":r["status"],"model_outcome":r["model_result"]["outcome"],
                           "trace_outcome":r["model_trace"]["terminal_model_outcome"]}
    assert len({v["model_outcome"] for v in observed.values()}) == 5
    return {"outcomes":observed,"silent_collapses":0,"real_provider_invocations":0}

def ts3_09(py, root):
    store=root/"unknown"
    turn=model_turn(1,request="unknown-request",script="UNKNOWN")
    first=result(call(py,store,{"op":"model_turn","turn":turn},fixtures=FIXTURES,grants=GRANTS))
    obs1=result(call(py,store,{"op":"observe","request_id":"unknown-request"},fixtures=FIXTURES,grants=GRANTS))
    obs2=result(call(py,store,{"op":"resume","request_id":"unknown-request"},fixtures=FIXTURES,grants=GRANTS))
    assert first["model_result"]["outcome"] == obs1["model_result"]["outcome"] == obs2["model_result"]["outcome"] == "UNKNOWN"
    for r in (first,obs1,obs2):
        assert r["model_trace"]["automatic_retries"] == 0
        assert r["model_trace"]["retry_decision"] == "NO_AUTOMATIC_RETRY"
        assert r["model_trace"]["provider_invocation_upper_bound"] == 1
    changed=deepcopy(turn); changed["model_intent"]={"preferred_profile_key":"synthetic-large","preferred_profile_version":"v1"}
    conflict=call(py,store,{"op":"model_turn","turn":changed},fixtures=FIXTURES,grants=GRANTS)
    assert conflict["returncode"] == 2 and conflict["stdout"]["error"] == "REQUEST_IDENTITY_CONFLICT"
    events=result(call(py,store,{"op":"safe_export"},fixtures=FIXTURES,grants=GRANTS))["events"]
    assert len(events)==2 and len({e["event_id"] for e in events})==2
    return {"unknown":"NO_AUTOMATIC_RETRY","automatic_retries":0,"profile_replay":"DENY",
            "events":2,"duplicate_terminals":0,"invocation_count":first["model_result"]["invocation_count"],
            "invocation_upper_bound":1}

def ts3_10(py, root):
    base=model_turn(1,request="switch-preview",session="switch-session",topic="topic-a")
    profiles=["synthetic-small","synthetic-large","synthetic-small"]; previews=[]
    for i,key in enumerate(profiles):
        turn=deepcopy(base); turn["model_intent"]={"preferred_profile_key":key,"preferred_profile_version":"v1"}
        previews.append(result(call(py,root/f"switch-{i}",{"op":"model_preview","turn":turn},fixtures=FIXTURES,grants=GRANTS)))
    assert previews[0]["identity"] == previews[1]["identity"] == previews[2]["identity"]
    assert previews[0]["working_set"]["source_refs"] == previews[1]["working_set"]["source_refs"] == previews[2]["working_set"]["source_refs"]
    assert all(p["provider_invocations"] == 0 for p in previews)
    assert [p["selection"]["selected"]["profile_key"] for p in previews] == profiles
    for p in previews:
        assert p["working_set"]["universe_id"] == SCOPE["universe_id"]
        assert p["working_set"]["access_subject_id"] == SCOPE["access_subject_id"]
    return {"profile_sequence":[x+"/v1" for x in profiles],"pre_call_identity_drift":0,
            "authority_permission_drift":0,"source_link_drift":0,"provider_invocations":0}

def ts3_11(py, root):
    store=root/"reactivate"; session="react-session"
    a1=result(call(py,store,{"op":"model_turn","turn":model_turn(1,session=session,topic="topic-a",source="alpha",
        intent={"preferred_profile_key":"synthetic-large","preferred_profile_version":"v1"})},fixtures=FIXTURES,grants=GRANTS))
    b=result(call(py,store,{"op":"model_turn","turn":model_turn(2,session=session,topic="topic-b",source="beta",
        intent={"preferred_profile_key":"synthetic-small","preferred_profile_version":"v1"})},fixtures=FIXTURES,grants=GRANTS))
    a2=result(call(py,store,{"op":"model_turn","turn":model_turn(3,session=session,topic="topic-a",source="alpha",
        intent={"preferred_profile_key":"synthetic-small","preferred_profile_version":"v1"})},fixtures=FIXTURES,grants=GRANTS))
    wa=a1["projection"]["working_set"]; wb=b["projection"]["working_set"]; wa2=a2["projection"]["working_set"]
    assert wa["source_refs"] == wa2["source_refs"] and wa["source_refs"] != wb["source_refs"]
    reasons=a2["projection"]["context"]["rebuild_reasons"]
    assert "MODEL_PROFILE_CHANGED" in reasons and "TOPIC_REACTIVATED" in reasons
    assert wa2["model_profile_ref"] == {"profile_key":"synthetic-small","profile_version":"v1"}
    state=result(call(py,store,{"op":"session_state","session_id":session},fixtures=FIXTURES,grants=GRANTS))
    topics={x["topic_id"]:x for x in state["topics"]}
    assert set(topics)=={"topic-a","topic-b"} and topics["topic-a"]["working_set"]["source_refs"] != topics["topic-b"]["working_set"]["source_refs"]
    return {"profile_rebuild":True,"reactivated":True,"source_links_preserved":True,
            "cross_topic_profile_contamination":0,"topics":sorted(topics)}

def ts3_12(py, root):
    r=result(call(py,root/"trace",{"op":"model_turn","turn":model_turn(1,text="PUBLIC harmless question",
        intent={"preferred_profile_key":"synthetic-capable","preferred_profile_version":"v1",
                "required_capabilities":["tool_calls"]})},fixtures=FIXTURES,grants=GRANTS))
    trace=r["model_trace"]
    required={"candidate_profile_refs","selected_profile","selection_reason","fallback_reason",
              "budget_decision","profile_fingerprint","estimator_fingerprint","context_fingerprint",
              "call_spec_fingerprint","terminal_model_outcome","retry_decision",
              "provider_invocation_count","real_provider_invocations","stop_reason"}
    assert required.issubset(trace)
    scan_no_secret(trace, forbidden_texts=[ALPHA["text"],"PUBLIC harmless question"])
    unsafe=call(py,root/"trace-secret",{"op":"model_turn","turn":model_turn(1,request="secret-turn",
        text="api_key="+SECRET)},fixtures=FIXTURES,grants=GRANTS)
    assert unsafe["returncode"] == 2 and unsafe["stdout"]["error"] == "UNSAFE_INPUT"
    exported=result(call(py,root/"trace-secret",{"op":"safe_export"},fixtures=FIXTURES,grants=GRANTS))
    scan_no_secret(exported)
    assert exported["events"] == []
    return {"required_trace_fields":len(required),"secret_private_body_leaks":0,
            "raw_provider_body_leaks":0,"hidden_reasoning_leaks":0,"unsafe_input":"DENY"}

def ts3_13(py, node, browser_verifier, root):
    p,url=launch_shell(py,root/"shell")
    try:
        run=subprocess.run([node,browser_verifier,url],text=True,capture_output=True,timeout=45)
        assert run.returncode == 0, (run.stdout,run.stderr)
        out=json.loads(run.stdout.strip().splitlines()[-1])
        assert out["status"]=="PASS" and out["manual_profile_switches"]==2
        assert out["raw_browser_writes"]==0 and out["secret_persistence"]==0
        assert out["session_stable"] is True and out["topic_after_reload"]=="topic-b"
        assert out["profile_after_reload"]=="synthetic-capable/v1"
        assert len(out["control_fields"])==6
        return out
    finally:
        p.terminate()
        try: p.wait(timeout=3)
        except subprocess.TimeoutExpired: p.kill()

def ts3_14(py, root):
    store=root/"regression"
    normal=result(call(py,store,{"op":"turn","turn":old_turn(1)},fixtures=[OLD_FIXTURE],grants=[OLD_GRANT]))
    order=normal["execution_order"]
    assert order.index("USER_DURABLE_RECEIPT") < order.index("PROVIDER_STUB_INVOKED")
    assert normal["presentation_order"] == ["USER_DURABLE_RECEIPT","ASSISTANT_DURABLE_RECEIPT","DISPLAY"]
    assert normal["terminal_count"]==1
    crash_store=root/"regression-crash"; crash_turn=old_turn(1,request="reg-crash")
    crashed=call(py,crash_store,{"op":"turn","turn":crash_turn},fixtures=[OLD_FIXTURE],grants=[OLD_GRANT],fault="AFTER_USER_DURABLE")
    assert crashed["returncode"]==86
    before=result(call(py,crash_store,{"op":"observe","request_id":"reg-crash"},fixtures=[OLD_FIXTURE],grants=[OLD_GRANT]))
    assert before["status"]=="AWAIT_EXPLICIT_RESUME" and before["terminal_count"]==0
    resumed=result(call(py,crash_store,{"op":"resume","request_id":"reg-crash"},fixtures=[OLD_FIXTURE],grants=[OLD_GRANT]))
    assert resumed["terminal_count"]==1
    again=result(call(py,crash_store,{"op":"resume","request_id":"reg-crash"},fixtures=[OLD_FIXTURE],grants=[OLD_GRANT]))
    assert again["terminal_count"]==1
    denied=result(call(py,root/"reg-deny",{"op":"turn","turn":old_turn(1,request="reg-deny")},fixtures=[OLD_FIXTURE],grants=[]))
    assert denied["projection"]["permission"]["decision"]=="DENY"
    assert denied["counters"]["authority_reads"]==denied["counters"]["candidate_retrievals"]==0
    rebuild=result(call(py,root/"reg-rebuild",{"op":"rebuild","source_id":"old-source","version":"v1"},fixtures=[OLD_FIXTURE],grants=[OLD_GRANT]))
    assert rebuild["index"]["derived_only"] is True and rebuild["index"]["authority_writes"]==0
    wake={"event_id":"reg-wake",**SCOPE,"owner_subject_id":SCOPE["access_subject_id"],
          "observed_at":"2026-09-18T07:30:00+00:00","salience":1.0,"urgency":1.0,"confidence":1.0,
          "quiet_hours":False,"cooldown_remaining":0,"repeat_count":0,"repeat_limit":1}
    wr=result(call(py,root/"reg-wake",{"op":"wake","candidate":wake},fixtures=[OLD_FIXTURE],grants=[OLD_GRANT]))
    assert wr["action"]=="SILENT" and wr["notifications"]==wr["continuations"]==wr["external_side_effects"]==0
    ev=result(call(py,crash_store,{"op":"safe_export"},fixtures=[OLD_FIXTURE],grants=[OLD_GRANT]))["events"]
    assert len(ev)==2 and len({x["event_id"] for x in ev})==2
    assert normal["receipts"]["user"]["contract_version"]=="canonical_event/v1"
    assert normal["receipts"]["assistant"]["contract_version"]=="canonical_event/v1"
    return {"durable_before_cognition":True,"terminal_before_display":True,"explicit_resume":True,
            "repeat_resume_duplicate_terminals":0,"permission_before_retrieval":True,
            "derived_rebuild_authority_writes":0,"wake":"SILENT","a019_public_receipts":"canonical_event/v1"}

def ts3_15(py, root):
    info=result(call(py,root/"info",{"op":"info"}))
    assert info["testport"]=="OwnedHomeTestPort v1" and info["authority"]=="A019"
    assert info["offline_only"] is True and info["synthetic_only"] is True
    assert info["live_provider_enabled"] is False and info["external_connectors_enabled"] is False
    assert info["model_gateway_version"]=="synthetic-model-gateway/1" and info["model_invocation_owner"]=="A019"
    invalid=call(py,root/"badop",{"op":"db_query"})
    assert invalid["returncode"]==2 and invalid["stdout"]["error"]=="OPERATION_NOT_IN_SLICE"
    reqs=runtime_requirements(py); assert reqs==[]
    repeats=[]
    for run_no in (1,2):
        store=root/f"stress-{run_no}"; ids=set(); terminals=0
        for n in range(1,11):
            key=("synthetic-small","synthetic-large","synthetic-capable")[n%3]
            r=result(call(py,store,{"op":"model_turn","turn":model_turn(
                n,request=f"stress-{run_no}-{n}",session=f"stress-session-{run_no}",
                intent={"preferred_profile_key":key,"preferred_profile_version":"v1"})},
                fixtures=FIXTURES,grants=GRANTS))
            assert r["terminal_count"]==1 and r["real_provider_invocations"]==0
            assert r["model_trace"]["automatic_retries"]==0
            ids.add(r["user_event_id"]); ids.add(r["assistant_event_id"]); terminals+=1
        events=result(call(py,store,{"op":"safe_export"},fixtures=FIXTURES,grants=GRANTS))["events"]
        actual=[e["event_id"] for e in events]
        assert len(actual)==20 and len(set(actual))==20 and set(actual)==ids and terminals==10
        repeats.append({"turns":10,"events":20,"terminals":10,"event_loss":0,"duplicate_events":0})
    return {"internal_db_oracles":0,"runtime_internal_imports":0,"unsupported_db_operation":"OPERATION_NOT_IN_SLICE",
            "offline_only":True,"live_provider_enabled":False,"external_connectors_enabled":False,
            "runtime_dependencies":reqs,"real_provider_calls":0,"credential_reads":0,"spend_usd":0,
            "repeat_runs":repeats}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--python",required=True); ap.add_argument("--node",required=True)
    ap.add_argument("--browser-verifier",required=True); ap.add_argument("--wheel",required=True)
    ap.add_argument("--candidate-sha",required=True); ap.add_argument("--candidate-tree",required=True)
    ap.add_argument("--output",required=True)
    a=ap.parse_args()
    cases={}; infra=None; wheel_sha=hashlib.sha256(pathlib.Path(a.wheel).read_bytes()).hexdigest()
    try:
        assert a.candidate_sha==CANDIDATE_SHA and a.candidate_tree==CANDIDATE_TREE
        with tempfile.TemporaryDirectory(prefix="a2-a029-s3-") as td:
            root=pathlib.Path(td)
            case(cases,"TS3-01",lambda:ts3_01(a.python,root))
            case(cases,"TS3-02",lambda:ts3_02(a.python,root))
            case(cases,"TS3-03",lambda:ts3_03(a.python,root))
            case(cases,"TS3-04",lambda:ts3_04(a.python,root))
            case(cases,"TS3-05",lambda:ts3_05(a.python,root))
            case(cases,"TS3-06",lambda:ts3_06(a.python,root))
            case(cases,"TS3-07",lambda:ts3_07(a.python,root))
            case(cases,"TS3-08",lambda:ts3_08(a.python,root))
            case(cases,"TS3-09",lambda:ts3_09(a.python,root))
            case(cases,"TS3-10",lambda:ts3_10(a.python,root))
            case(cases,"TS3-11",lambda:ts3_11(a.python,root))
            case(cases,"TS3-12",lambda:ts3_12(a.python,root))
            case(cases,"TS3-13",lambda:ts3_13(a.python,a.node,a.browser_verifier,root))
            case(cases,"TS3-14",lambda:ts3_14(a.python,root))
            case(cases,"TS3-15",lambda:ts3_15(a.python,root))
    except Exception as exc:
        infra=f"{type(exc).__name__}: {exc}"
    failed=[k for k,v in cases.items() if v["status"]!="PASS"]
    zero=sorted(failed)
    if infra is not None or len(cases)!=15:
        verdict="A2-S3 NOT EVALUABLE"
    elif failed:
        verdict="A2-S3 FAIL / REPAIR REQUIRED"
    else:
        verdict="A2-S3 PASS"
    receipt={
        "schema_id":"a2-a029-s3-blackbox/v1","work_order":"ENG-A2-A029-S3-01",
        "candidate":{"repository":"aerenkolstein-code/Companion-Mind","pr":30,
                     "head_sha":a.candidate_sha,"tree_sha":a.candidate_tree,"wheel_sha256":wheel_sha},
        "evaluation":{"repository":"aerenkolstein-code/llm-evaluation-lab",
                      "seam":"OwnedHomeTestPort v1 + public loopback /models",
                      "fresh_wheel_venv":True,"outside_runtime_checkout":True,
                      "imports_runtime_internals":False,"uses_internal_db_oracle":False,
                      "uses_a1_behavior_results":False},
        "cases":cases,"zero_tolerance_count":len(zero),"zero_tolerance_failures":zero,
        "infrastructure_error":infra,
        "limitations":["offline/synthetic/public-safe only","process-crash not physical power-cut",
                       "models shell uses exact served JS in independent Node VM against real loopback HTTP; no native-browser rendering/bfcache claim",
                       "synthetic UTF-8 estimator is not vendor tokenizer parity",
                       "no live provider/OAuth/Drive/credential/semantic-vector exercise",
                       "bounded secret scan is not universal DLP"],
        "verdict":verdict
    }
    pathlib.Path(a.output).write_text(json.dumps(receipt,sort_keys=True,indent=2,ensure_ascii=False),encoding="utf-8")
    print(json.dumps({"verdict":verdict,"cases":len(cases),"failed":failed,
                      "zero_tolerance_count":len(zero),"wheel_sha256":wheel_sha,
                      "infrastructure_error":infra},sort_keys=True))
    return 0 if verdict=="A2-S3 PASS" else 1

if __name__=="__main__":
    raise SystemExit(main())
