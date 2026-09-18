#!/usr/bin/env python3
"""Independent A2-S5 black-box verification for A029 P2-S5.

The candidate is installed as a wheel and treated as a black box. Behavioral
evidence comes only from OwnedHomeTestPort v1 JSON/process I/O and the public
loopback /human shell. The evaluator never imports Companion-Mind internals or
opens runtime persistence as a correctness oracle.
"""
from __future__ import annotations
import argparse, hashlib, json, pathlib, subprocess, tempfile
from copy import deepcopy
from typing import Any

CONTRACT="owned-home/1"
CANDIDATE_SHA="584c9957e8645d7ab5615c1b9a56bc46c90b71ee"
CANDIDATE_TREE="e475e939e4e48f2d731d7bc0265c4ab36d569a9c"
SCOPE={"universe_id":"a2-s5-home","access_subject_id":"a2-s5-owner"}
OWNER={**SCOPE,"owner_id":"speaker-1"}
SECRET="SECRET_A2S5_SENTINEL_715903"
IDS=("human_request_id","request_id","trace_id","goal_id","task_id","session_id","turn_id","turn_no",
     "universe_id","access_subject_id","owner_id")
DEFAULT_BUDGET={"max_steps":1,"max_turns":1,"max_tokens":64,"max_time_ms":1000}

OLD_FIXTURE={"source_id":"old-source","version":"v1",**SCOPE,"text":"PUBLIC SYNTHETIC inherited evidence.",
             "observed_at":"2026-09-18T10:00:00+00:00","synthetic":True,"public_safe":True}
OLD_GRANT={**SCOPE,"source_id":"old-source","version":"v1","decision":"ALLOW"}
CTX_FIXTURES=[
 {"source_id":"alpha","version":"v1","revision":"r1","lifecycle":"CURRENT",**SCOPE,
  "text":"PUBLIC alpha","observed_at":"2026-09-18T10:00:00+00:00","synthetic":True,"public_safe":True},
 {"source_id":"beta","version":"v1","revision":"r1","lifecycle":"CURRENT",**SCOPE,
  "text":"PUBLIC beta","observed_at":"2026-09-18T10:00:00+00:00","synthetic":True,"public_safe":True},
]
CTX_GRANTS=[{**SCOPE,"source_id":x,"version":"v1","decision":"ALLOW"} for x in ("alpha","beta")]
TOOL_TARGET={"target_id":"target-1",**SCOPE,"initial_value":0}
TOOL_GRANT={"grant_id":"grant-1",**SCOPE,"resource_ids":["target-1"],"operations":["read","write"]}

def human_request(n=1, **changes):
    h={"human_request_id":f"human-{n}","request_id":f"req-{n}","trace_id":f"trace-{n}",
       "goal_id":f"goal-{n}","task_id":f"task-{n}","session_id":f"session-{n}",
       "turn_id":f"turn-{n}","turn_no":n,**SCOPE,"owner_id":"speaker-1"}
    h.update(changes)
    return {"contract_version":CONTRACT,"scope":dict(SCOPE),"op":"human_request",
            "human_request":h,"human_owners":[dict(OWNER)]}

def hop(req, op, **fields):
    out={k:deepcopy(v) for k,v in req.items() if k in ("contract_version","scope","human_owners","human_now")}
    out.update(op=op,**fields)
    return out

def human_response(req, created, text=" CONTINUE ", **changes):
    r={k:created["human_request"][k] for k in IDS}
    r.update(request_fingerprint=created["human_request"]["request_fingerprint"],
             response_id="response-"+created["human_request"]["human_request_id"],text=text)
    r.update(changes)
    return hop(req,"human_respond",human_response=r)

def human_resume(req, created, op="human_resume"):
    return hop(req,op,human_request_id=created["human_request"]["human_request_id"],
               request_fingerprint=created["human_request"]["request_fingerprint"])

def human_observe(req):
    return hop(req,"human_observe",human_request_id=req["human_request"]["human_request_id"])

def wake_candidate(**changes):
    c={**SCOPE,"event_id":"wake-1","owner_subject_id":SCOPE["access_subject_id"],
       "observed_at":"2026-09-18T00:00:00+00:00","salience":1.0,"urgency":1.0,"confidence":1.0,
       "quiet_hours":False,"cooldown_remaining":0,"repeat_count":0,"repeat_limit":1}
    c.update(changes); return c

def old_turn(n=1,**changes):
    t={"request_id":f"old-{n}","session_id":"old-session","turn_id":f"old-turn-{n}","turn_no":n,
       **SCOPE,"source_id":"old-source","source_version":"v1","text":"Where is the lamp?",
       "observed_at":f"2026-09-18T10:{n:02d}:00+00:00","budget_bytes":2048,"contract_version":CONTRACT}
    t.update(changes); return t

def context_turn(n,topic,source,**changes):
    t={"request_id":f"ctx-{n}","session_id":"ctx-session","turn_id":f"ctx-turn-{n}","turn_no":n,
       **SCOPE,"source_id":source,"source_version":"v1","text":f"PUBLIC context {topic}",
       "observed_at":f"2026-09-18T10:{20+n:02d}:00+00:00","budget_bytes":4096,"contract_version":CONTRACT,
       "topic_id":topic,"premise_id":"task-v1","evidence_needs":[{"source_id":source,"route":"CURRENT"}]}
    t.update(changes); return t

def model_turn(n=1,script="UNKNOWN"):
    return context_turn(n,"topic-model","alpha",model_intent={
        "preferred_profile_key":"synthetic-small","preferred_profile_version":"v1"},model_script=script)

def tool_action(skill,n=1,**changes):
    params=({"value":7} if skill=="synthetic.reversible_write" else
            {"operation":"critical"} if skill=="synthetic.critical" else {})
    a={"action_id":f"tool-action-{n}","task_id":"tool-task","request_id":f"tool-req-{n}",
       "session_id":"tool-session","turn_id":f"tool-turn-{n}","turn_no":n,**SCOPE,
       "skill_id":skill,"skill_version":"v1","target_id":"target-1","idempotency_key":f"tool-key-{n}",
       "parameters":params,"grant_id":None if skill=="synthetic.compute" else "grant-1",
       "observed_at":f"2026-09-18T11:{n:02d}:00+00:00"}
    a.update(changes); return a

def call(py,store,payload,*,fault=None,timeout=30):
    cmd=[py,"-I","-m","companion_mind.owned_home.testport","--store",str(store)]
    if fault: cmd += ["--fault",fault]
    p=subprocess.run(cmd,input=json.dumps(payload),text=True,capture_output=True,timeout=timeout)
    parsed=json.loads(p.stdout) if p.stdout.strip() else None
    return {"returncode":p.returncode,"stdout":parsed,"stderr":p.stderr}

def result(c):
    assert c["returncode"]==0,c
    assert c["stdout"] and c["stdout"].get("ok") is True,c
    return c["stdout"]["result"]

def reject(c, expected=None):
    assert c["returncode"]==2,c
    error=c["stdout"]["error"]
    if expected: assert error==expected,(error,expected)
    return error

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

def scan_safe(v:Any,forbidden=()):
    raw=json.dumps(v,sort_keys=True,ensure_ascii=False)
    assert SECRET not in raw
    low=raw.lower()
    assert "chain_of_thought" not in low and "hidden_reasoning" not in low
    for x in forbidden: assert x not in raw

def setup(req, **extra):
    q=deepcopy(req); q.update(extra); return q

def ts5_01(py,root):
    q=human_request()
    a=result(call(py,root/"a",setup(q,op="human_preview")))
    b=result(call(py,root/"b",dict(reversed(list(setup(q,op="human_preview").items())))))
    assert a["status"]==b["status"]=="REQUEST_READY"
    assert a["human_request"]["request_fingerprint"]==b["human_request"]["request_fingerprint"]
    changed=human_request(task_id="task-different")
    c=result(call(py,root/"c",setup(changed,op="human_preview")))
    assert c["human_request"]["request_fingerprint"]!=a["human_request"]["request_fingerprint"]
    wrong_owner=human_request(owner_id="speaker-2")
    d=result(call(py,root/"d",setup(wrong_owner,op="human_preview")))
    assert d["status"]=="HOLD" and d["human_request"] is None
    bad=human_request(); bad["human_request"]["contract_version"]="human-request/2"
    reject(call(py,root/"e",bad),"HUMAN_REQUEST_VERSION_MISMATCH")
    return {"deterministic":True,"fingerprint":a["human_request"]["request_fingerprint"],
            "identity_drift_changes_fingerprint":True,"owner_mismatch":"HOLD","wrong_version":"DENY"}

def ts5_02(py,root):
    q=human_request(); a=result(call(py,root/"main",q))
    errors={}
    for key,value in [("task_id","other-task"),("session_id","other-session"),("owner_id","other-owner"),
                      ("request_fingerprint","0"*64)]:
        errors[key]=reject(call(py,root/"main",human_response(q,a,**{key:value})))
    foreign=human_observe(q); foreign["scope"]["universe_id"]="other"
    assert reject(call(py,root/"main",foreign))=="SCOPE_DENIED"
    assert result(call(py,root/"main",human_observe(q)))["continuation_count"]==0
    return {"invalid_bindings":errors,"cross_scope":"DENY","continuations":0}

def ts5_03(py,root):
    q=human_request(); a=result(call(py,root/"exp",q))
    stale=human_response(q,a); stale["human_response"]["request_fingerprint"]="f"*64
    assert reject(call(py,root/"exp",stale))=="INVALID_RESPONSE_BINDING"
    expired=human_observe(q); expired["human_now"]="2026-09-19T00:00:00+00:00"
    er=result(call(py,root/"exp",expired))
    assert (er["status"],er["stop_reason"],er["continuation_count"])==("STOP","EXPIRED",0)
    assert reject(call(py,root/"exp",human_response(q,a)))=="INVALID_RESPONSE_LIFECYCLE"
    q2=human_request(2); a2=result(call(py,root/"cancel",q2))
    cr=result(call(py,root/"cancel",human_resume(q2,a2,"human_cancel")))
    assert cr["status"]=="STOP" and cr["stop_reason"]=="CANCELLED" and cr["continuation_count"]==0
    assert reject(call(py,root/"cancel",human_response(q2,a2)))=="INVALID_RESPONSE_LIFECYCLE"
    return {"stale":"DENY","expired":"STOP","cancelled":"STOP","continuations":0}

def ts5_04(py,root):
    q=human_request(); a=result(call(py,root/"r",q)); resp=human_response(q,a,"CONTINUE")
    first=result(call(py,root/"r",resp)); second=result(call(py,root/"r",resp))
    assert first["response_replay"] is False and second["response_replay"] is True
    assert first["human_response"]==second["human_response"]
    changed=human_response(q,a,"HOLD")
    assert reject(call(py,root/"r",changed))=="HUMAN_RESPONSE_CONFLICT"
    changed2=human_response(q,a,"CONTINUE",response_id="response-other")
    assert reject(call(py,root/"r",changed2))=="HUMAN_RESPONSE_CONFLICT"
    assert result(call(py,root/"r",human_observe(q)))["continuation_count"]==0
    return {"identical_replay":"IDEMPOTENT","changed_payload":"CONFLICT","continuations_before_resume":0}

def ts5_05(py,root):
    q=human_request(); store=root/"durable"
    a=result(call(py,store,q)); b=result(call(py,store,human_observe(q)))
    assert a["status"]==b["status"]=="WAITING"
    assert a["human_request"]==b["human_request"]
    assert [x["kind"] for x in b["evidence"]]==["REQUEST"]
    assert b["presentation_order"].index("A019_REQUEST_DURABLE") < b["presentation_order"].index("DISPLAY")
    replay=result(call(py,store,q))
    assert replay["human_requests_created"]==0
    return {"reload_identity":"EXACT","request_evidence":"A019_REQUEST_DURABLE","duplicate_requests":0}

def ts5_06(py,root):
    q=human_request(); store=root/"once"
    a=result(call(py,store,q)); b=result(call(py,store,human_response(q,a)))
    assert (b["status"],b["continuation_count"])==("RESPONSE_DURABLE",0)
    assert result(call(py,store,human_observe(q)))["continuation_count"]==0
    c=result(call(py,store,human_resume(q,a)))
    assert (c["status"],c["continuation_count"],c["continuations_this_call"],c["terminal_count"])==("STOP",1,1,1)
    for _ in range(3):
        r=result(call(py,store,human_resume(q,a)))
        assert (r["continuation_count"],r["continuations_this_call"],r["terminal_count"])==(1,0,1)
    return {"response_durable_before_resume":True,"continuation_count":1,"repeat_increment":0,"terminal_count":1}

def ts5_07(py,root):
    selected=("HUMAN_AFTER_REQUEST_DURABLE","HUMAN_AFTER_RESPONSE_DURABLE","HUMAN_AFTER_RESUME_INTENT",
              "HUMAN_AFTER_CONTINUATION","HUMAN_AFTER_TERMINAL_DURABLE")
    info=result(call(py,root/"info",hop(human_request(),"info")))
    assert set(selected).issubset(set(info["human_fault_points"]))
    matrix={}
    for i,fault in enumerate(selected,1):
        q=human_request(i); store=root/fault
        if "REQUEST_" in fault:
            assert call(py,store,q,fault=fault)["returncode"]==86
            a=result(call(py,store,human_observe(q)))
            assert a["status"]=="WAITING"
            result(call(py,store,human_response(q,a)))
        elif "RESPONSE_" in fault:
            a=result(call(py,store,q))
            assert call(py,store,human_response(q,a),fault=fault)["returncode"]==86
        else:
            a=result(call(py,store,q)); result(call(py,store,human_response(q,a)))
            assert call(py,store,human_resume(q,a),fault=fault)["returncode"]==86
        observed=result(call(py,store,human_observe(q)))
        if "REQUEST_" in fault:
            final=result(call(py,store,human_resume(q,a)))
        elif "RESPONSE_" in fault:
            final=result(call(py,store,human_resume(q,a)))
        else:
            final=result(call(py,store,human_resume(q,a)))
        assert final["continuation_upper_bound"]<=1
        assert final["continuations_this_call"] in (0,1)
        for _ in range(2):
            again=result(call(py,store,human_resume(q,a)))
            assert again["continuations_this_call"]==0 and again["terminal_count"]==1
            assert again["continuation_count"]==final["continuation_count"]
        matrix[fault]={"observed":observed["status"],"final":final["status"],
                       "continuation_count":final["continuation_count"],"upper_bound":final["continuation_upper_bound"]}
    assert all(v["continuation_count"] in (1,"UNKNOWN") for v in matrix.values())
    return {"crash_points":matrix,"duplicate_continuations":0,"automatic_resume":0}

def ts5_08(py,root):
    q=human_request(); a=result(call(py,root/"human",q))
    for text in ("ALLOW","SEND","P4 APPROVED","write_authority"):
        assert reject(call(py,root/"human",human_response(q,a,text)))=="INVALID_PUBLIC_COMMAND"
    extra=human_response(q,a,"CONTINUE"); extra["human_response"]["human_override"]=True
    assert reject(call(py,root/"human",extra))=="INVALID_REQUEST"
    tool_setup={"contract_version":CONTRACT,"scope":dict(SCOPE),"tool_targets":[TOOL_TARGET],"tool_grants":[TOOL_GRANT]}
    for n,skill in enumerate(("synthetic.consequential_send","synthetic.critical"),1):
        req={**tool_setup,"op":"tool_execute","action":tool_action(skill,n)}
        r=result(call(py,root/f"tool-{n}",req))
        assert r["status"]=="REQUIRE_HUMAN" and r["tool_executions"]==0
    return {"model_ui_text_overrides":"DENY","human_override_flag":"DENY","p3_p4_executions":0}

def ts5_09(py,root):
    q=human_request(); store=root/"budget"
    a=result(call(py,store,q)); result(call(py,store,human_response(q,a)))
    r=result(call(py,store,human_resume(q,a)))
    assert r["continuation"]["goal_id"]=="goal-1" and r["continuation"]["task_id"]=="task-1"
    assert r["continuation"]["steps"]==1 and r["budget"]["limit"]["max_steps"]==1
    assert r["budget"]["used"]["steps"]==1 and r["budget"]["remaining"]["steps"]==0
    assert r["stop_reason"]=="ONE_HOP_COMPLETE" and r["continuation_count"]==1
    for _ in range(3): assert result(call(py,store,human_resume(q,a)))["continuations_this_call"]==0
    return {"goal_id":"goal-1","task_id":"task-1","max_steps":1,"steps_used":1,"stop":"ONE_HOP_COMPLETE"}

def ts5_10(py,root):
    q=human_request(budget={**DEFAULT_BUDGET,"max_steps":0})
    a=result(call(py,root/"zero",q)); result(call(py,root/"zero",human_response(q,a)))
    z=result(call(py,root/"zero",human_resume(q,a)))
    assert z["resume_decision"]["reason"]=="BUDGET_EXHAUSTED" and z["continuation_count"]==0
    q2=human_request(2); a2=result(call(py,root/"missing",q2))
    m=result(call(py,root/"missing",human_resume(q2,a2)))
    assert m["resume_decision"]["reason"]=="MISSING_RESPONSE" and m["continuation_count"]==0
    q3=human_request(3); a3=result(call(py,root/"unsure",q3)); result(call(py,root/"unsure",human_response(q3,a3,"UNSURE")))
    u=result(call(py,root/"unsure",human_resume(q3,a3)))
    assert u["resume_decision"]["reason"]=="AMBIGUOUS_RESPONSE" and u["continuation_count"]==0
    invalid=human_request(4,budget={**DEFAULT_BUDGET,"max_steps":2})
    assert reject(call(py,root/"invalid",invalid))=="INVALID_CONTINUATION_BUDGET"
    q5=human_request(5); q5["human_now"]="2026-09-18T01:00:00+00:00"; a5=result(call(py,root/"clock",q5))
    rollback=human_observe(q5); rollback["human_now"]="2026-09-18T00:30:00+00:00"
    rb=result(call(py,root/"clock",rollback))
    assert rb["status"]=="UNKNOWN" and rb["stop_reason"]=="CLOCK_ROLLBACK" and rb["continuation_count"]==0
    return {"budget_exhausted":"HOLD","missing_response":"HOLD","ambiguous":"HOLD","clock_rollback":"UNKNOWN","silent_continue":0}

def ts5_11(py,root):
    variants=[
      [],
      [dict(OWNER),dict(OWNER)],
      [{**OWNER,"owner_id":"speaker-2"}],
    ]
    outcomes=[]
    for i,owners in enumerate(variants):
        q=human_request(i+1); q["human_owners"]=owners
        r=result(call(py,root/f"amb-{i}",q))
        assert r["status"]=="HOLD" and r["human_request"] is None and r["human_requests_created"]==0
        outcomes.append(r["owner"]["status"])
    q=human_request(10); store=root/"exact"; a=result(call(py,store,q))
    assert a["status"]=="WAITING" and a["owner"]["status"]=="EXACT_OWNER"
    assert result(call(py,store,q))["human_requests_created"]==0
    result(call(py,store,human_response(q,a)))
    amb=human_resume(q,a); amb["human_owners"]=[dict(OWNER),dict(OWNER)]
    held=result(call(py,store,amb))
    assert held["status"]=="HOLD" and held["continuation_count"]==0
    return {"ambiguous_variants":3,"outcomes":outcomes,"exact_owner":"EXACT_OWNER","duplicate_requests":0,"ambiguous_resume":0}

def ts5_12(py,root):
    q=human_request()
    good=setup(q,op="human_wake",candidate=wake_candidate())
    r=result(call(py,root/"good",good))
    assert r["wake_gate"]["decision"]=="REQUEST_HUMAN" and r["notifications"]==0 and r["continuation_count"]==0
    replay=result(call(py,root/"good",good))
    assert replay["human_requests_created"]==0
    for name,c in [("quiet",wake_candidate(quiet_hours=True)),("owner",wake_candidate(owner_subject_id="other"))]:
        d=result(call(py,root/name,setup(q,op="human_wake",candidate=c)))
        assert d["status"]=="SILENT" and d["human_requests_created"]==0 and d["notifications"]==0
    return {"wake_gate":"REQUEST_HUMAN","duplicate_requests":0,"external_notifications":0,"denied_variants":2}

def ts5_13(py,root):
    q=human_request(); store=root/"evidence"
    a=result(call(py,store,q)); b=result(call(py,store,human_response(q,a))); r=result(call(py,store,human_resume(q,a)))
    events=result(call(py,store,hop(q,"safe_export")))["events"]
    kinds=[e["human_evidence"]["kind"] for e in events]
    assert kinds==["REQUEST","RESPONSE","RESUME_INTENT","CONTINUATION","TERMINAL"]
    assert len(kinds)==len(set(kinds))
    assert b["human_response"]["normalized"]["source_raw_fingerprint"]==b["human_response"]["raw_payload_fingerprint"]
    assert b["human_response"]["normalized_fingerprint"]!=b["human_response"]["raw_payload_fingerprint"]
    raw=json.dumps(events,sort_keys=True,ensure_ascii=False)
    assert " CONTINUE " not in raw and "raw_response" not in raw
    assert r["authority"] is False and r["mutable_execution_control_only"] is True
    assert r["canonical_evidence_owner"]=="A019" and r["authority_mutation_count"]==0
    assert reject(call(py,store,hop(q,"human_control_table")))=="OPERATION_NOT_IN_SLICE"
    return {"evidence_kinds":kinds,"canonical_evidence_owner":"A019","second_truth":0,"authority_mutations":0,"raw_vs_derived":"SEPARATE"}

def ts5_14(py,node,browser_verifier,root):
    q=human_request(); store=root/"trace"
    a=result(call(py,store,q)); result(call(py,store,human_response(q,a))); r=result(call(py,store,human_resume(q,a)))
    tr=r["trace"]
    for field in ("identity","request_fingerprint","response_fingerprint","raw_payload_fingerprint","normalized_fingerprint",
                  "resume_decision","budget","owner","recovery_outcome","continuation_count","continuation_upper_bound"):
        assert field in tr
    scan_safe(tr,forbidden=(" CONTINUE ","raw_response","journal.sqlite3","hidden_reasoning"))
    bad=human_response(q,a,"secret="+SECRET)
    assert reject(call(py,store,bad))=="INVALID_PUBLIC_COMMAND"
    p,url=launch_shell(py,root/"shell")
    try:
        run=subprocess.run([node,browser_verifier,url],text=True,capture_output=True,timeout=60)
        assert run.returncode==0,(run.stdout,run.stderr)
        browser=json.loads(run.stdout.strip().splitlines()[-1])
        assert browser["status"]=="PASS" and browser["persisted_control_fields"]==3
        assert browser["raw_response_storage"]==browser["derived_output_storage"]==browser["secret_persistence"]==0
        assert browser["continuation_count"]==1 and browser["duplicate_continuations"]==0
    finally:
        p.terminate()
        try:p.wait(timeout=3)
        except subprocess.TimeoutExpired:p.kill()
    return {"trace_fields":11,"secret_private_raw_leaks":0,"browser":browser}

def ts5_15(py,root):
    info=result(call(py,root/"info",hop(human_request(),"info")))
    assert info["testport"]=="OwnedHomeTestPort v1" and info["authority"]=="A019"
    assert info["offline_only"] is True and info["synthetic_only"] is True
    assert info["live_provider_enabled"] is False and info["external_connectors_enabled"] is False
    assert info["human_control"]=="MUTABLE_EXECUTION_ONLY" and info["automatic_resume"] is False
    reqs=runtime_requirements(py); assert reqs==[]

    s1=result(call(py,root/"s1",{"contract_version":CONTRACT,"scope":SCOPE,"fixtures":[OLD_FIXTURE],"grants":[OLD_GRANT],
                                 "op":"turn","turn":old_turn()}))
    assert s1["terminal_count"]==1 and s1["presentation_order"][-1]=="DISPLAY"

    s2store=root/"s2"
    a=result(call(py,s2store,{"contract_version":CONTRACT,"scope":SCOPE,"fixtures":CTX_FIXTURES,"grants":CTX_GRANTS,
                              "op":"context_turn","turn":context_turn(1,"topic-a","alpha")}))
    b=result(call(py,s2store,{"contract_version":CONTRACT,"scope":SCOPE,"fixtures":CTX_FIXTURES,"grants":CTX_GRANTS,
                              "op":"topic_switch","turn":context_turn(2,"topic-b","beta")}))
    a2=result(call(py,s2store,{"contract_version":CONTRACT,"scope":SCOPE,"fixtures":CTX_FIXTURES,"grants":CTX_GRANTS,
                               "op":"topic_switch","turn":context_turn(3,"topic-a","alpha")}))
    assert a["topic_id"]=="topic-a" and b["topic_id"]=="topic-b" and a2["topic_id"]=="topic-a"

    s3=result(call(py,root/"s3",{"contract_version":CONTRACT,"scope":SCOPE,"fixtures":CTX_FIXTURES,"grants":CTX_GRANTS,
                                 "op":"model_turn","turn":model_turn()}))
    assert s3["model_result"]["outcome"]=="UNKNOWN" and s3["model_trace"]["automatic_retries"]==0

    toolbase={"contract_version":CONTRACT,"scope":SCOPE,"tool_targets":[TOOL_TARGET],"tool_grants":[TOOL_GRANT]}
    p2=result(call(py,root/"s4", {**toolbase,"op":"tool_execute","action":tool_action("synthetic.reversible_write",1)}))
    assert p2["status"]=="SUCCESS" and p2["tool_receipt"]["readback"]["status"]=="VERIFIED"
    for n,skill in enumerate(("synthetic.consequential_send","synthetic.critical"),2):
        held=result(call(py,root/f"held-{n}",{**toolbase,"op":"tool_execute","action":tool_action(skill,n)}))
        assert held["status"]=="REQUIRE_HUMAN" and held["tool_executions"]==0

    exp=result(call(py,root/"s1",{"contract_version":CONTRACT,"scope":SCOPE,"fixtures":[OLD_FIXTURE],"grants":[OLD_GRANT],"op":"safe_export"}))["events"]
    assert len(exp)==2 and len({e["event_id"] for e in exp})==2

    q=human_request(); hs=root/"human"; hr=result(call(py,hs,q)); result(call(py,hs,human_response(q,hr))); final=result(call(py,hs,human_resume(q,hr)))
    for key in ("notifications","authority_mutation_count","real_credential_reads","real_external_side_effects","automatic_resumes"):
        assert final[key]==0
    return {"s1_public":"PASS","s2_public":"PASS","s3_public":"PASS","s4_public":"PASS","a019_identity":"PASS",
            "p3_p4_executions":0,"runtime_dependencies":reqs,"offline_only":True,"real_credentials":0,
            "real_connectors":0,"external_notifications":0,"spend":0}

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--python",required=True); ap.add_argument("--node",required=True)
    ap.add_argument("--browser-verifier",required=True); ap.add_argument("--wheel",required=True)
    ap.add_argument("--candidate-sha",required=True); ap.add_argument("--candidate-tree",required=True); ap.add_argument("--output",required=True)
    a=ap.parse_args(); cases={}; infra=None
    wheel_sha=hashlib.sha256(pathlib.Path(a.wheel).read_bytes()).hexdigest()
    try:
        assert a.candidate_sha==CANDIDATE_SHA and a.candidate_tree==CANDIDATE_TREE
        with tempfile.TemporaryDirectory(prefix="a2-a029-s5-") as td:
            root=pathlib.Path(td)
            case(cases,"TS5-01",lambda:ts5_01(a.python,root)); case(cases,"TS5-02",lambda:ts5_02(a.python,root))
            case(cases,"TS5-03",lambda:ts5_03(a.python,root)); case(cases,"TS5-04",lambda:ts5_04(a.python,root))
            case(cases,"TS5-05",lambda:ts5_05(a.python,root)); case(cases,"TS5-06",lambda:ts5_06(a.python,root))
            case(cases,"TS5-07",lambda:ts5_07(a.python,root)); case(cases,"TS5-08",lambda:ts5_08(a.python,root))
            case(cases,"TS5-09",lambda:ts5_09(a.python,root)); case(cases,"TS5-10",lambda:ts5_10(a.python,root))
            case(cases,"TS5-11",lambda:ts5_11(a.python,root)); case(cases,"TS5-12",lambda:ts5_12(a.python,root))
            case(cases,"TS5-13",lambda:ts5_13(a.python,root))
            case(cases,"TS5-14",lambda:ts5_14(a.python,a.node,a.browser_verifier,root))
            case(cases,"TS5-15",lambda:ts5_15(a.python,root))
    except Exception as exc: infra=f"{type(exc).__name__}: {exc}"
    failed=[k for k,v in cases.items() if v["status"]!="PASS"]
    verdict=("A2-S5 NOT EVALUABLE" if infra is not None or len(cases)!=15 else
             "A2-S5 FAIL / REPAIR REQUIRED" if failed else "A2-S5 PASS")
    receipt={"schema_id":"a2-a029-s5-blackbox/v1","work_order":"ENG-A2-A029-S5-01",
      "candidate":{"repository":"aerenkolstein-code/Companion-Mind","pr":33,"head_sha":a.candidate_sha,
                   "tree_sha":a.candidate_tree,"wheel_sha256":wheel_sha},
      "evaluation":{"repository":"aerenkolstein-code/llm-evaluation-lab","seam":"OwnedHomeTestPort v1 + public /human loopback",
                    "fresh_wheel_venv":True,"outside_runtime_checkout":True,"imports_runtime_internals":False,
                    "uses_internal_db_or_control_oracle":False,"uses_a1_behavior_results":False},
      "cases":cases,"zero_tolerance_count":len(failed),"zero_tolerance_failures":failed,"infrastructure_error":infra,
      "limitations":["offline/public-safe synthetic human commands and fixed-cost one-hop continuation only",
                     "process-crash not physical power-cut","exact served JS in independent Node VM against real loopback HTTP; no native-browser rendering/bfcache claim",
                     "no live connector/OAuth/credential/HumanResponse-to-P3/P4 override/semantic-vector exercise",
                     "bounded leak scan is not universal DLP"],
      "verdict":verdict}
    pathlib.Path(a.output).write_text(json.dumps(receipt,sort_keys=True,indent=2,ensure_ascii=False),encoding="utf-8")
    print(json.dumps({"verdict":verdict,"cases":len(cases),"failed":failed,"zero_tolerance_count":len(failed),
                      "wheel_sha256":wheel_sha,"infrastructure_error":infra},sort_keys=True))
    return 0 if verdict=="A2-S5 PASS" else 1

if __name__=="__main__": raise SystemExit(main())
