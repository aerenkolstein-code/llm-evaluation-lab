#!/usr/bin/env python3
"""Independent A2-S4 black-box verification for A029 P2-S4.

Behavioral evidence comes only from the installed OwnedHomeTestPort v1 process and
the public loopback /tools shell. No Companion-Mind runtime/store/action-control
module is imported and no internal persistence file is opened as an oracle.
"""
from __future__ import annotations
import argparse, hashlib, json, pathlib, subprocess, tempfile
from copy import deepcopy
from typing import Any

CONTRACT="owned-home/1"
CANDIDATE_SHA="8975db16e5d5d3bab82b01eca4d20ad3f747faea"
CANDIDATE_TREE="3a0b5b5120c15504db10f41e11a0dc5997a779ee"
SCOPE={"universe_id":"a2-s4-home","access_subject_id":"a2-s4-owner"}
SECRET="SECRET_A2S4_SENTINEL_438921"
SKILLS=["synthetic.compute","synthetic.scoped_read","synthetic.reversible_write","synthetic.consequential_send","synthetic.critical"]
TIER={
 "synthetic.compute":"P0_PURE","synthetic.scoped_read":"P1_SCOPED_READ",
 "synthetic.reversible_write":"P2_REVERSIBLE_WRITE","synthetic.consequential_send":"P3_CONSEQUENTIAL_WRITE",
 "synthetic.critical":"P4_CRITICAL"
}
TARGET={"target_id":"target-1",**SCOPE,"initial_value":0}
GRANT={"grant_id":"grant-1",**SCOPE,"resource_ids":["target-1"],"operations":["read","write"]}
SKILL_FIXTURES=[{"skill_id":s} for s in SKILLS]

def action(skill,n=1,*,request=None,session="a2s4-session",target="target-1",key=None,
           params=None,grant_id=None,script="SUCCESS",readback_mode="VERIFY",
           universe=None,subject=None,declared_tier=None,declared_side_effect=None,reversible=True):
    universe=universe or SCOPE["universe_id"]; subject=subject or SCOPE["access_subject_id"]
    if params is None:
        params=({"values":[2,3]} if skill=="synthetic.compute" else
                {"value":7} if skill=="synthetic.reversible_write" else
                {"operation":"critical"} if skill=="synthetic.critical" else {})
    if grant_id is None and skill in {"synthetic.scoped_read","synthetic.reversible_write"}:
        grant_id="grant-1"
    aid=request or f"a2s4-action-{n}"
    return {
      "action_id":aid,"idempotency_key":key or aid,"task_id":"a2s4-task",
      "request_id":aid,"session_id":session,"turn_id":f"a2s4-turn-{n}","turn_no":n,
      "universe_id":universe,"access_subject_id":subject,"skill_id":skill,"skill_version":"v1",
      "target_id":target,"parameters":params,"grant_id":grant_id,
      "observed_at":f"2026-09-18T11:{n%60:02d}:00+00:00","script":script,"readback_mode":readback_mode,
      "reversible":reversible,**({"declared_tier":declared_tier} if declared_tier is not None else {}),
      **({"declared_side_effect":declared_side_effect} if declared_side_effect is not None else {})
    }

def old_turn(n,*,request=None,text="Where is the lamp?"):
    rid=request or f"a2s4-old-{n}"
    return {"request_id":rid,"session_id":"a2s4-old-session","turn_id":f"a2s4-old-turn-{n}","turn_no":n,
            **SCOPE,"source_id":"old-source","source_version":"v1","text":text,
            "observed_at":f"2026-09-18T10:{n%60:02d}:00+00:00","budget_bytes":2048,"contract_version":CONTRACT}
OLD_FIXTURE={"source_id":"old-source","version":"v1",**SCOPE,"text":"PUBLIC SYNTHETIC inherited evidence.",
             "observed_at":"2026-09-18T10:00:00+00:00","synthetic":True,"public_safe":True}
OLD_GRANT={**SCOPE,"source_id":"old-source","version":"v1","decision":"ALLOW"}

def context_turn(n,topic,source):
    return {"request_id":f"ctx-{n}","session_id":"ctx-session","turn_id":f"ctx-turn-{n}","turn_no":n,
            **SCOPE,"source_id":source,"source_version":"v1","text":f"PUBLIC context {topic}",
            "observed_at":f"2026-09-18T10:{20+n:02d}:00+00:00","budget_bytes":4096,"contract_version":CONTRACT,
            "topic_id":topic,"premise_id":"task-v1","evidence_needs":[{"source_id":source,"route":"CURRENT"}]}
CTX_FIXTURES=[
 {"source_id":"alpha","version":"v1","revision":"r1","lifecycle":"CURRENT",**SCOPE,"text":"PUBLIC alpha",
  "observed_at":"2026-09-18T10:00:00+00:00","synthetic":True,"public_safe":True},
 {"source_id":"beta","version":"v1","revision":"r1","lifecycle":"CURRENT",**SCOPE,"text":"PUBLIC beta",
  "observed_at":"2026-09-18T10:00:00+00:00","synthetic":True,"public_safe":True}]
CTX_GRANTS=[{**SCOPE,"source_id":x,"version":"v1","decision":"ALLOW"} for x in ("alpha","beta")]

def model_turn(n,script="COMPLETE"):
    t=context_turn(n,"topic-model","alpha")
    t.update(model_intent={"preferred_profile_key":"synthetic-small","preferred_profile_version":"v1"},model_script=script)
    return t

def call(py,store,operation,*,tool_targets=None,tool_grants=None,skill_contracts=None,
         fixtures=None,grants=None,fault=None,timeout=30):
    req={"contract_version":CONTRACT,"scope":SCOPE,**operation}
    if tool_targets is not None: req["tool_targets"]=tool_targets
    if tool_grants is not None: req["tool_grants"]=tool_grants
    if skill_contracts is not None: req["skill_contracts"]=skill_contracts
    if fixtures is not None: req["fixtures"]=fixtures
    if grants is not None: req["grants"]=grants
    cmd=[py,"-I","-m","companion_mind.owned_home.testport","--store",str(store)]
    if fault: cmd += ["--fault",fault]
    p=subprocess.run(cmd,input=json.dumps(req),text=True,capture_output=True,timeout=timeout)
    parsed=json.loads(p.stdout) if p.stdout.strip() else None
    return {"returncode":p.returncode,"stdout":parsed,"stderr":p.stderr}

def result(c):
    assert c["returncode"]==0,c
    assert c["stdout"] and c["stdout"].get("ok") is True,c
    return c["stdout"]["result"]

def tool_call(py,store,op,act=None,*,grants=None,targets=None,skills=None,fault=None,extra=None):
    body={"op":op}
    if act is not None: body["action"]=act
    if extra: body.update(extra)
    return call(py,store,body,tool_targets=targets if targets is not None else [TARGET],
                tool_grants=grants if grants is not None else [GRANT],
                skill_contracts=skills,fault=fault)

def case(cases,name,fn):
    try: cases[name]={"status":"PASS","evidence":fn()}
    except Exception as exc: cases[name]={"status":"FAIL","error":f"{type(exc).__name__}: {exc}"}

def runtime_requirements(py):
    code="import importlib.metadata as m,json;r=m.metadata('companion-mind').get_all('Requires-Dist') or [];print(json.dumps([x for x in r if 'extra ==' not in x]))"
    p=subprocess.run([py,"-I","-c",code],text=True,capture_output=True,check=True)
    return json.loads(p.stdout)

def launch_shell(py,store):
    p=subprocess.Popen([py,"-I","-m","companion_mind.owned_home.shell","--store",str(store),"--port","0"],
                       stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    url=p.stdout.readline().strip()
    if not url.startswith("http://127.0.0.1:"):
        err=p.stderr.read(); p.terminate(); raise AssertionError(f"shell start failed {url!r} {err!r}")
    return p,url

def scan_safe(value:Any,forbidden=()):
    raw=json.dumps(value,sort_keys=True,ensure_ascii=False)
    assert SECRET not in raw
    low=raw.lower(); assert "chain_of_thought" not in low and "hidden_reasoning" not in low
    for x in forbidden: assert x not in raw

def ts4_01(py,root):
    regs=[]
    orders=[SKILL_FIXTURES,list(reversed(SKILL_FIXTURES)),[SKILL_FIXTURES[i] for i in (2,0,4,1,3)]]
    for i,items in enumerate(orders):
        regs.append(result(call(py,root/f"reg-{i}",{"op":"skill_registry"},skill_contracts=items)))
    assert len({r["registry_fingerprint"] for r in regs})==1
    assert regs[0]["skills"]==regs[1]["skills"]==regs[2]["skills"]
    dup=call(py,root/"dup",{"op":"skill_registry"},skill_contracts=[{"skill_id":"synthetic.compute"},{"skill_id":"synthetic.compute"}])
    assert dup["returncode"]==2 and dup["stdout"]["error"]=="DUPLICATE_SKILL_IDENTITY"
    return {"permutations":3,"registry_fingerprint":regs[0]["registry_fingerprint"],
            "skills":[x["skill_id"]+"/"+x["skill_version"] for x in regs[0]["skills"]],"duplicates":"DENY"}

def ts4_02(py,root):
    exact=result(call(py,root/"lookup",{"op":"skill_lookup","skill_id":"synthetic.reversible_write","skill_version":"v1"}))
    missing=result(call(py,root/"missing",{"op":"skill_lookup","skill_id":"synthetic.reversible_write","skill_version":"v2"}))
    assert exact["status"]=="RESOLVED" and missing["status"]=="EXACT_SKILL_UNRESOLVED"
    a=action("synthetic.reversible_write",1)
    p1=result(tool_call(py,root/"preview1","action_preview",a))
    p2=result(tool_call(py,root/"preview2","action_preview",a))
    assert p1["action_intent"]["intent_fingerprint"]==p2["action_intent"]["intent_fingerprint"]
    changed=deepcopy(a); changed["parameters"]={"value":8}
    stale=result(tool_call(py,root/"stale","action_preview",changed,
                           extra={"expected_intent":p1["action_intent"],"expected_decision":p1["permission_decision"]}))
    assert stale["permission_decision"]["decision"]=="DENY" and stale["permission_decision"]["execution_allowed"] is False
    return {"exact_skill":"RESOLVED","stale_version":"EXACT_SKILL_UNRESOLVED",
            "intent_reproducible":True,"changed_binding":"DENY","tool_executions":0}

def ts4_03(py,root):
    r=result(tool_call(py,root/"p0","tool_execute",action("synthetic.compute",1)))
    assert r["status"]=="SUCCESS" and r["permission_decision"]["decision"]=="ALLOW"
    assert r["tool_executions"]==1 and r["tool_receipt"]["pure_result"]==5
    assert r["tool_receipt"]["synthetic_reads"]==r["tool_receipt"]["synthetic_writes"]==0
    assert r["real_external_side_effects"]==r["real_credential_reads"]==r["authority_mutation_count"]==0
    return {"decision":"ALLOW","pure_result":5,"external_side_effects":0,"credential_requirement":0,"authority_mutations":0}

def ts4_04(py,root):
    ok=result(tool_call(py,root/"p1-ok","tool_execute",action("synthetic.scoped_read",1)))
    assert ok["status"]=="SUCCESS" and ok["tool_receipt"]["synthetic_reads"]==1 and ok["tool_executions"]==1
    bads=[
      [{**GRANT,"universe_id":"other-universe"}],
      [{**GRANT,"access_subject_id":"other-subject"}],
      [{**GRANT,"revoked":True}],
      [{**GRANT,"resource_ids":["other-target"]}],
      [{**GRANT,"operations":["write"]}],
    ]
    reasons=[]
    for i,gs in enumerate(bads):
        r=result(tool_call(py,root/f"p1-deny-{i}","tool_execute",action("synthetic.scoped_read",1),grants=gs))
        assert r["permission_decision"]["decision"]=="DENY" and r["tool_executions"]==0
        reasons.append(r["permission_decision"]["reason_code"])
    return {"exact_read":"ALLOW+ONE_READ","denied_variants":len(bads),"deny_reasons":reasons,"cross_scope_executions":0}

def ts4_05(py,root):
    ok=result(tool_call(py,root/"p2-ok","tool_execute",action("synthetic.reversible_write",1,params={"value":7})))
    assert ok["status"]=="SUCCESS" and ok["tool_executions"]==1
    assert ok["tool_receipt"]["readback"]["status"]=="VERIFIED"
    assert ok["tool_receipt"]["synthetic_writes"]==1 and ok["authority_mutation_count"]==0
    mismatch=result(tool_call(py,root/"p2-mm","tool_execute",action("synthetic.reversible_write",1,params={"value":8},readback_mode="MISMATCH")))
    unavailable=result(tool_call(py,root/"p2-un","tool_execute",action("synthetic.reversible_write",1,params={"value":9},readback_mode="UNAVAILABLE")))
    for r in (mismatch,unavailable):
        assert r["tool_receipt"]["outcome"]=="UNKNOWN" and r["status"]=="UNKNOWN"
        assert r["tool_receipt"]["readback"]["status"] in {"MISMATCH","UNAVAILABLE"}
    return {"success_requires":"VERIFIED","writes":1,"authority_mutations":0,
            "mismatch":"UNKNOWN","unavailable":"UNKNOWN"}

def ts4_06(py,root):
    r=result(tool_call(py,root/"p3","tool_execute",action("synthetic.consequential_send",1)))
    assert r["status"]=="REQUIRE_HUMAN" and r["permission_decision"]["decision"]=="REQUIRE_HUMAN"
    assert r["tool_executions"]==0 and r["tool_receipt"] is None
    return {"decision":"REQUIRE_HUMAN","executions":0,"synthetic_send":0,"human_override":False}

def ts4_07(py,root):
    hold=result(tool_call(py,root/"p4-hold","tool_execute",action("synthetic.critical",1,params={"operation":"critical"})))
    denied=result(tool_call(py,root/"p4-break","tool_execute",action("synthetic.critical",1,params={"operation":"break_glass"})))
    assert hold["status"]=="REQUIRE_HUMAN" and hold["tool_executions"]==0
    assert denied["status"]=="DENY" and denied["permission_decision"]["decision"]=="DENY" and denied["tool_executions"]==0
    return {"general":"REQUIRE_HUMAN","break_glass":"DENY","executions":0}

def ts4_08(py,root):
    downgrade=result(tool_call(py,root/"esc-1","tool_execute",
        action("synthetic.consequential_send",1,declared_tier="P0_PURE",declared_side_effect="NONE")))
    assert downgrade["permission_decision"]["decision"]=="DENY" and downgrade["tool_executions"]==0
    elevate=result(tool_call(py,root/"esc-2","tool_execute",
        action("synthetic.reversible_write",1,declared_tier="P4_CRITICAL",declared_side_effect="CRITICAL")))
    assert elevate["permission_decision"]["decision"]=="DENY" and elevate["tool_executions"]==0
    extra=deepcopy(action("synthetic.reversible_write",1)); extra["confidence"]=1.0
    bad=tool_call(py,root/"esc-extra","tool_execute",extra)
    assert bad["returncode"]==2
    return {"declared_tier_override":"DENY","declared_side_effect_override":"DENY",
            "extra_model_confidence":"SAFE_REFUSAL","permission_escalations":0}

def ts4_09(py,root):
    seen={}
    for i,outcome in enumerate(("SUCCESS","FAILED","PARTIAL","UNKNOWN"),1):
        r=result(tool_call(py,root/f"out-{outcome}","tool_execute",action("synthetic.compute",i,script=outcome)))
        assert r["tool_receipt"]["outcome"]==outcome and r["tool_trace"]["terminal_outcome"]==outcome
        assert r["automatic_redispatches"]==0
        seen[outcome]={"status":r["status"],"receipt":r["tool_receipt"]["outcome"]}
    assert len({x["receipt"] for x in seen.values()})==4
    return {"outcomes":seen,"silent_collapses":0,"unknown_promotions":0}

def ts4_10(py,root):
    info=result(call(py,root/"info",{"op":"info"}))
    points=set(info["tool_fault_points"])
    needed={"TOOL_AFTER_DISPATCH_INTENT","TOOL_AFTER_EFFECT"}
    assert needed.issubset(points)
    observed={}
    for i,point in enumerate(sorted(needed),1):
        store=root/f"crash-{point}"; a=action("synthetic.reversible_write",1,request=f"crash-{i}",params={"value":100+i})
        crashed=tool_call(py,store,"tool_execute",a,fault=point)
        assert crashed["returncode"]==86
        ob=result(call(py,store,{"op":"tool_observe","action_id":a["action_id"]},tool_targets=[TARGET],tool_grants=[GRANT]))
        re=result(call(py,store,{"op":"tool_resume","action_id":a["action_id"]},tool_targets=[TARGET],tool_grants=[GRANT]))
        assert ob["status"]=="UNKNOWN" and re["status"]=="UNKNOWN"
        assert ob["tool_executions"]==re["tool_executions"]==0
        assert ob["automatic_redispatches"]==re["automatic_redispatches"]==0
        assert ob["tool_receipt"]["execution_upper_bound"]==1
        if "synthetic_target" in re: assert re["synthetic_target"]["writes"] <= 1
        observed[point]={"observe":ob["status"],"resume":re["status"],
                         "writes":re.get("synthetic_target",{}).get("writes",0),"automatic_redispatches":0}
    return {"crash_points":observed,"duplicate_effects":0,"automatic_redispatches":0,"physical_power_cut_proof":False}

def ts4_11(py,root):
    store=root/"idem"; a=action("synthetic.reversible_write",1,params={"value":77})
    first=result(tool_call(py,store,"tool_execute",a))
    repeat=result(tool_call(py,store,"tool_execute",a))
    observe=result(call(py,store,{"op":"tool_observe","action_id":a["action_id"]},tool_targets=[TARGET],tool_grants=[GRANT]))
    assert repeat["tool_receipt"]==first["tool_receipt"]==observe["tool_receipt"]
    assert repeat["tool_executions"]==observe["tool_executions"]==0
    assert observe["synthetic_target"]["writes"]==1
    changed=deepcopy(a); changed["parameters"]={"value":78}
    conflict=tool_call(py,store,"tool_execute",changed)
    assert conflict["returncode"]==2 and conflict["stdout"]["error"]=="IDEMPOTENCY_CONFLICT"
    changed_key=deepcopy(a); changed_key["idempotency_key"]="other-key"
    conflict2=tool_call(py,store,"tool_execute",changed_key)
    assert conflict2["returncode"]==2 and conflict2["stdout"]["error"]=="ACTION_IDENTITY_CONFLICT"
    return {"replay_executions":0,"total_writes":1,"changed_action":"IDEMPOTENCY_CONFLICT",
            "changed_key":"ACTION_IDENTITY_CONFLICT","duplicate_dispatches":0}

def ts4_12(py,root):
    store=root/"authority"; a=action("synthetic.reversible_write",1,params={"value":42})
    r=result(tool_call(py,store,"tool_execute",a))
    assert r["authority_mutation_count"]==0 and r["action_control"]["authority"] is False
    assert r["action_control"]["mutable_execution_control_only"] is True
    assert r["action_control"]["canonical_evidence_owner"]=="A019"
    assert r["canonical_evidence"] and r["canonical_evidence"]["authority_mutation_count"]==0
    exp=result(call(py,store,{"op":"safe_export"},tool_targets=[TARGET],tool_grants=[GRANT]))["events"]
    evid=[e["tool_evidence"] for e in exp if "tool_evidence" in e]
    assert len(evid)==1 and evid[0]==r["canonical_evidence"]
    raw=json.dumps(exp,sort_keys=True)
    assert "parameters" not in raw and "42" not in raw
    return {"authority_mutations":0,"canonical_tool_evidence":1,"control_is_authority":False,"second_truth":0}

def ts4_13(py,root):
    r=result(tool_call(py,root/"trace","tool_execute",action("synthetic.reversible_write",1,params={"value":876543})))
    trace=r["tool_trace"]
    required={"skill_ref","skill_fingerprint","action_id","action_fingerprint","permission_tier","side_effect_class",
              "scope","grant_ref","permission_decision","permission_fingerprint","dispatch_state","milestones",
              "readback_status","receipt_fingerprint","terminal_outcome","retry_decision","execution_count",
              "execution_upper_bound","authority_mutation_count"}
    assert required.issubset(trace)
    scan_safe({k:r[k] for k in ("tool_trace","tool_receipt","canonical_evidence","action_control")},forbidden=["876543","parameters"])
    wrong=[{**GRANT,"universe_id":"foreign"},{**GRANT,"access_subject_id":"foreign"}]
    for i,gs in enumerate(wrong):
        d=result(tool_call(py,root/f"scope-{i}","tool_execute",action("synthetic.reversible_write",1),grants=gs))
        assert d["permission_decision"]["decision"]=="DENY" and d["tool_executions"]==0
    bad=deepcopy({"contract_version":CONTRACT,"scope":SCOPE,"op":"tool_execute","action":action("synthetic.reversible_write",1),
                  "tool_targets":[TARGET],"tool_grants":[{**GRANT,"api_key":SECRET}]})
    p=subprocess.run([py,"-I","-m","companion_mind.owned_home.testport","--store",str(root/"secret")],
                     input=json.dumps(bad),text=True,capture_output=True,timeout=20)
    out=json.loads(p.stdout); assert p.returncode==2 and SECRET not in json.dumps(out)
    return {"required_trace_fields":len(required),"cross_scope_executions":0,
            "secret_private_raw_body_leaks":0,"unsafe_secret_fixture":"SAFE_REFUSAL"}

def ts4_14(py,node,browser_verifier,root):
    p,url=launch_shell(py,root/"shell")
    try:
        run=subprocess.run([node,browser_verifier,url],text=True,capture_output=True,timeout=60)
        assert run.returncode==0,(run.stdout,run.stderr)
        browser=json.loads(run.stdout.strip().splitlines()[-1])
        assert browser["status"]=="PASS" and browser["flows"]==5
        assert browser["raw_body_storage"]==browser["secret_persistence"]==0
        assert browser["statuses"]==["SUCCESS","SUCCESS","SUCCESS","REQUIRE_HUMAN","REQUIRE_HUMAN"]
        assert browser["executions"]==[1,1,1,0,0]
    finally:
        p.terminate()
        try:p.wait(timeout=3)
        except subprocess.TimeoutExpired:p.kill()
    # Independent prior-public-seam regression, without internal or A1-test oracle.
    s1=result(call(py,root/"s1",{"op":"turn","turn":old_turn(1)},fixtures=[OLD_FIXTURE],grants=[OLD_GRANT]))
    assert s1["execution_order"].index("USER_DURABLE_RECEIPT") < s1["execution_order"].index("PROVIDER_STUB_INVOKED")
    assert s1["presentation_order"][-1]=="DISPLAY" and s1["terminal_count"]==1
    cstore=root/"s2"
    a=result(call(py,cstore,{"op":"context_turn","turn":context_turn(1,"topic-a","alpha")},fixtures=CTX_FIXTURES,grants=CTX_GRANTS))
    b=result(call(py,cstore,{"op":"topic_switch","turn":context_turn(2,"topic-b","beta")},fixtures=CTX_FIXTURES,grants=CTX_GRANTS))
    a2=result(call(py,cstore,{"op":"topic_switch","turn":context_turn(3,"topic-a","alpha")},fixtures=CTX_FIXTURES,grants=CTX_GRANTS))
    assert a["topic_id"]=="topic-a" and b["topic_id"]=="topic-b" and a2["topic_id"]=="topic-a"
    assert a["projection"]["working_set"]["source_refs"]==a2["projection"]["working_set"]["source_refs"]
    m=result(call(py,root/"s3",{"op":"model_turn","turn":model_turn(1,"UNKNOWN")},fixtures=CTX_FIXTURES,grants=CTX_GRANTS))
    assert m["model_result"]["outcome"]=="UNKNOWN" and m["model_trace"]["automatic_retries"]==0
    ev=result(call(py,root/"s3",{"op":"safe_export"},fixtures=CTX_FIXTURES,grants=CTX_GRANTS))["events"]
    assert len(ev)==2 and len({x["event_id"] for x in ev})==2
    return {"browser":browser,"s1_public":"PASS","s2_public":"PASS","s3_public":"PASS","a019_event_identity":"PASS"}

def ts4_15(py,root):
    info=result(call(py,root/"info",{"op":"info"}))
    assert info["testport"]=="OwnedHomeTestPort v1" and info["authority"]=="A019"
    assert info["offline_only"] is True and info["synthetic_only"] is True
    assert info["live_provider_enabled"] is False and info["external_connectors_enabled"] is False
    assert info["tool_gateway_version"]=="synthetic-tool-gateway/1" and info["tool_control"]=="MUTABLE_EXECUTION_ONLY"
    assert info["human_override"] is False
    invalid=call(py,root/"bad",{"op":"action_control_table"})
    assert invalid["returncode"]==2 and invalid["stdout"]["error"]=="OPERATION_NOT_IN_SLICE"
    reqs=runtime_requirements(py); assert reqs==[]
    repeats=[]
    for rno in (1,2):
        store=root/f"stress-{rno}"; ids=set(); terminals=0
        for n,skill in enumerate(("synthetic.compute","synthetic.scoped_read","synthetic.reversible_write","synthetic.compute","synthetic.scoped_read"),1):
            a=action(skill,n,request=f"stress-{rno}-{n}",session=f"stress-session-{rno}",params={"value":n} if skill=="synthetic.reversible_write" else None)
            r=result(tool_call(py,store,"tool_execute",a))
            assert r["terminal_count"]==1 and r["automatic_redispatches"]==0
            assert r["real_external_side_effects"]==r["real_credential_reads"]==r["authority_mutation_count"]==0
            ids.add(r["user_event_id"]); ids.add(r["assistant_event_id"]); terminals+=1
        events=result(call(py,store,{"op":"safe_export"},tool_targets=[TARGET],tool_grants=[GRANT]))["events"]
        actual=[e["event_id"] for e in events]
        assert len(actual)==10 and len(set(actual))==10 and set(actual)==ids
        repeats.append({"turns":5,"events":10,"terminals":terminals,"event_loss":0,"duplicate_events":0})
    return {"internal_db_oracles":0,"action_control_table_oracles":0,"runtime_internal_imports":0,
            "offline_only":True,"live_provider_enabled":False,"external_connectors_enabled":False,
            "runtime_dependencies":reqs,"real_credentials":0,"real_connectors":0,"spend":0,"repeat_runs":repeats}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--python",required=True); ap.add_argument("--node",required=True)
    ap.add_argument("--browser-verifier",required=True); ap.add_argument("--wheel",required=True)
    ap.add_argument("--candidate-sha",required=True); ap.add_argument("--candidate-tree",required=True); ap.add_argument("--output",required=True)
    a=ap.parse_args(); cases={}; infra=None
    wheel_sha=hashlib.sha256(pathlib.Path(a.wheel).read_bytes()).hexdigest()
    try:
        assert a.candidate_sha==CANDIDATE_SHA and a.candidate_tree==CANDIDATE_TREE
        with tempfile.TemporaryDirectory(prefix="a2-a029-s4-") as td:
            root=pathlib.Path(td)
            case(cases,"TS4-01",lambda:ts4_01(a.python,root)); case(cases,"TS4-02",lambda:ts4_02(a.python,root))
            case(cases,"TS4-03",lambda:ts4_03(a.python,root)); case(cases,"TS4-04",lambda:ts4_04(a.python,root))
            case(cases,"TS4-05",lambda:ts4_05(a.python,root)); case(cases,"TS4-06",lambda:ts4_06(a.python,root))
            case(cases,"TS4-07",lambda:ts4_07(a.python,root)); case(cases,"TS4-08",lambda:ts4_08(a.python,root))
            case(cases,"TS4-09",lambda:ts4_09(a.python,root)); case(cases,"TS4-10",lambda:ts4_10(a.python,root))
            case(cases,"TS4-11",lambda:ts4_11(a.python,root)); case(cases,"TS4-12",lambda:ts4_12(a.python,root))
            case(cases,"TS4-13",lambda:ts4_13(a.python,root))
            case(cases,"TS4-14",lambda:ts4_14(a.python,a.node,a.browser_verifier,root))
            case(cases,"TS4-15",lambda:ts4_15(a.python,root))
    except Exception as exc: infra=f"{type(exc).__name__}: {exc}"
    failed=[k for k,v in cases.items() if v["status"]!="PASS"]
    verdict=("A2-S4 NOT EVALUABLE" if infra is not None or len(cases)!=15 else
             "A2-S4 FAIL / REPAIR REQUIRED" if failed else "A2-S4 PASS")
    receipt={"schema_id":"a2-a029-s4-blackbox/v1","work_order":"ENG-A2-A029-S4-01",
      "candidate":{"repository":"aerenkolstein-code/Companion-Mind","pr":32,"head_sha":a.candidate_sha,
                   "tree_sha":a.candidate_tree,"wheel_sha256":wheel_sha},
      "evaluation":{"repository":"aerenkolstein-code/llm-evaluation-lab","seam":"OwnedHomeTestPort v1 + public /tools loopback",
                    "fresh_wheel_venv":True,"outside_runtime_checkout":True,"imports_runtime_internals":False,
                    "uses_internal_db_or_action_control_oracle":False,"uses_a1_behavior_results":False},
      "cases":cases,"zero_tolerance_count":len(failed),"zero_tolerance_failures":failed,"infrastructure_error":infra,
      "limitations":["offline/public-safe synthetic tool resources and grant metadata only","process-crash not physical power-cut",
                     "exact served JS in independent Node VM against real loopback HTTP; no native-browser rendering/bfcache claim",
                     "no live connector/OAuth/credential/HumanResponse/semantic-vector exercise","bounded leak scan is not universal DLP"],
      "verdict":verdict}
    pathlib.Path(a.output).write_text(json.dumps(receipt,sort_keys=True,indent=2,ensure_ascii=False),encoding="utf-8")
    print(json.dumps({"verdict":verdict,"cases":len(cases),"failed":failed,"zero_tolerance_count":len(failed),
                      "wheel_sha256":wheel_sha,"infrastructure_error":infra},sort_keys=True))
    return 0 if verdict=="A2-S4 PASS" else 1

if __name__=="__main__": raise SystemExit(main())
