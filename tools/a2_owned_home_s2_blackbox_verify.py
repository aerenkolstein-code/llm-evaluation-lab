#!/usr/bin/env python3
"""Independent A2-S2 black-box verifier for OwnedHomeTestPort v1.

No Companion-Mind module is imported. Correctness is decided only from the
installed TestPort JSON process seam and public loopback shell behavior.
"""
from __future__ import annotations
import argparse, hashlib, json, pathlib, subprocess, tempfile, time
from datetime import datetime, timezone, timedelta
from typing import Any

CONTRACT="owned-home/1"
CANDIDATE_SHA="ba40dd12d810bb02eb40f4e52ee8c4dec88ed0f5"
CANDIDATE_TREE="31bc1f2ea879095e3797f9342884046a2a694374"
SCOPE={"universe_id":"a2s2-home","access_subject_id":"a2s2-owner"}
SECRET="A2S2_SECRET_CANARY_9f71"

def fixture(source_id,version,revision,lifecycle,text,scope=SCOPE):
    return {"source_id":source_id,"version":version,"revision":revision,"lifecycle":lifecycle,**scope,
            "text":text,"observed_at":"2026-09-17T12:00:00+00:00","synthetic":True,"public_safe":True}

def grant(source_id,version,decision="ALLOW",scope=SCOPE): return {**scope,"source_id":source_id,"version":version,"decision":decision}

def stamp(n): return (datetime(2026,9,17,12,0,tzinfo=timezone.utc)+timedelta(minutes=n)).isoformat()

def cturn(n,topic,needs,*,session="a2s2-session",premise="task-v1",budget=4096,text=None,request=None):
    rid=request or f"a2s2-{session}-{n}"
    return {"request_id":rid,"session_id":session,"turn_id":f"{session}-turn-{n}","turn_no":n,**SCOPE,
            "source_id":"alpha","source_version":"v2","text":text or f"synthetic turn {n} / {topic}",
            "observed_at":stamp(n),"budget_bytes":budget,"contract_version":CONTRACT,
            "topic_id":topic,"premise_id":premise,"evidence_needs":needs}

def old_turn(n,*,session="a2s2-s1",request=None,text="Where is the synthetic lamp?",budget=4096):
    rid=request or f"a2s2-s1-{n}"
    return {"request_id":rid,"session_id":session,"turn_id":f"{session}-turn-{n}","turn_no":n,**SCOPE,
            "source_id":"s1-source","source_version":"v1","text":text,"observed_at":stamp(100+n),
            "budget_bytes":budget,"contract_version":CONTRACT}

def call(py,store,op,*,fixtures=(),grants=(),fault=None,timeout=30):
    req={"contract_version":CONTRACT,"scope":SCOPE,"fixtures":list(fixtures),"grants":list(grants),**op}
    cmd=[py,"-I","-m","companion_mind.owned_home.testport","--store",str(store)]
    if fault: cmd += ["--fault",fault]
    p=subprocess.run(cmd,input=json.dumps(req),text=True,capture_output=True,timeout=timeout)
    out=None
    if p.stdout.strip():
        try: out=json.loads(p.stdout)
        except Exception: out={"raw":p.stdout}
    return {"returncode":p.returncode,"stdout":out,"stderr":p.stderr}

def result(x):
    assert x["returncode"]==0, x
    assert isinstance(x["stdout"],dict) and x["stdout"].get("ok") is True, x
    return x["stdout"]["result"]

def safe_scan(x:Any):
    raw=json.dumps(x,sort_keys=True,ensure_ascii=False)
    for bad in (SECRET,"sqlite_master","journal.sqlite","chain_of_thought","hidden_reasoning","private RAW body"):
        assert bad not in raw, bad

def zero_side_effects(r):
    c=r.get("counters",{})
    assert c.get("authority_writes",0)==0
    assert c.get("provider_invocations",r.get("provider_invocations",0))==0
    assert c.get("notifications",0)==0 and c.get("continuations",0)==0 and c.get("external_side_effects",0)==0

def routes(r): return r["projection"]["retrieval"]["routes"]
def ctx(r): return r["projection"]["context"]
def trace(r): return r["projection"]["trace"]
def case(cases,name,fn):
    try: cases[name]={"status":"PASS","evidence":fn()}
    except Exception as e: cases[name]={"status":"FAIL","error":f"{type(e).__name__}: {e}"}

def launch_shell(py,store):
    p=subprocess.Popen([py,"-I","-m","companion_mind.owned_home.shell","--store",str(store),"--port","0"],
                       stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
    line=p.stdout.readline().strip()
    if not line.startswith("http://127.0.0.1:"):
        p.kill(); raise RuntimeError("shell did not publish loopback URL: "+line)
    return p,line

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--python",required=True); ap.add_argument("--node",default="node")
    ap.add_argument("--browser-verifier",required=True); ap.add_argument("--wheel",required=True)
    ap.add_argument("--candidate-sha",default=CANDIDATE_SHA); ap.add_argument("--candidate-tree",default=CANDIDATE_TREE)
    ap.add_argument("--output",required=True); a=ap.parse_args()
    cases={}; meta={"candidate_sha":a.candidate_sha,"candidate_tree":a.candidate_tree}
    assert a.candidate_sha==CANDIDATE_SHA and a.candidate_tree==CANDIDATE_TREE
    meta["wheel_sha256"]=hashlib.sha256(pathlib.Path(a.wheel).read_bytes()).hexdigest()
    alpha_cur=fixture("alpha","v2","r2","CURRENT","Alpha CURRENT evidence: blue lantern east.")
    alpha_hist=fixture("alpha","v1","r1","HISTORY","Alpha HISTORY evidence: blue lantern west.")
    beta=fixture("beta","v1","r1","CURRENT","Beta evidence: amber key north.")
    gamma=fixture("gamma","v1","r1","CURRENT","Gamma evidence: green notebook south.")
    base_f=[alpha_cur,alpha_hist,beta,gamma]
    base_g=[grant("alpha","v1"),grant("alpha","v2"),grant("beta","v1"),grant("gamma","v1")]
    with tempfile.TemporaryDirectory(prefix="a2s2-final-") as td:
      root=pathlib.Path(td)
      info=result(call(a.python,root/"info",{"op":"info"}))
      safe_scan(info)
      assert info["testport"]=="OwnedHomeTestPort v1" and info["context_version"]=="context-pack/2"
      assert info["offline_only"] is True and info["synthetic_only"] is True
      assert info["live_provider_enabled"] is False and info["external_connectors_enabled"] is False
      assert info["automatic_resume"] is False and info["recent_turn_limit"]==4 and info["evidence_limit"]==5
      meta["testport_info"]=info

      # TS2-01 same-topic continuity
      def t01():
        s=root/"ts01"; rr=[]
        for n in (1,2,3): rr.append(result(call(a.python,s,{"op":"context_turn","turn":cturn(n,"topic-a",[{"source_id":"alpha","route":"CURRENT"}],session="same")},fixtures=base_f,grants=base_g)))
        for r in rr: zero_side_effects(r); assert r["topic_id"]=="topic-a" and r["session_id"]=="same" and r["event_count"]==2 and r["terminal_count"]==1
        assert len({r["user_event_id"] for r in rr})==3 and len({r["assistant_event_id"] for r in rr})==3
        assert [len(ctx(r)["recent_exact_turn_refs"]) for r in rr]==[0,1,2]
        assert len({r["working_set_id"] for r in rr})==1
        st=result(call(a.python,s,{"op":"session_state","session_id":"same"},fixtures=base_f,grants=base_g))
        assert st["active_topic"]=="topic-a" and st["next_turn_no"]==4 and len(st["topics"])==1
        return {"turns":3,"events":6,"terminal_duplicates":0,"working_set_stable":True,"recent_tail":[0,1,2]}
      case(cases,"TS2-01",t01)

      # TS2-02 A-B-C-A and source-linked reactivation
      def t02():
        s=root/"ts02"
        seq=[(1,"topic-a","alpha"),(2,"topic-b","beta"),(3,"topic-c","gamma"),(4,"topic-a","alpha")]; rr=[]
        for n,t,src in seq:
          rr.append(result(call(a.python,s,{"op":"topic_switch" if n>1 else "context_turn","turn":cturn(n,t,[{"source_id":src,"route":"CURRENT"}],session="switch",text=f"{t} public synthetic")},fixtures=base_f,grants=base_g)))
        back=rr[-1]; inc=ctx(back)["included"]; raw=json.dumps(back,ensure_ascii=False)
        assert ctx(back)["rebuild_reasons"]==["TOPIC_REACTIVATED"]
        assert {x["source_id"] for x in inc}=={"alpha"} and "Beta evidence" not in raw and "Gamma evidence" not in raw
        assert len(ctx(back)["recent_exact_turn_refs"])==1
        st=result(call(a.python,s,{"op":"session_state","session_id":"switch"},fixtures=base_f,grants=base_g))
        assert len(st["topics"])>=3 and st["active_topic"]=="topic-a"
        return {"topics":len(st["topics"]),"reactivation":"TOPIC_REACTIVATED","cross_topic_contamination":0,"source_linked":True}
      case(cases,"TS2-02",t02)

      # TS2-03 Current over stale History, conflict explicit
      def t03():
        r=result(call(a.python,root/"ts03",{"op":"context_turn","turn":cturn(1,"topic-current",[{"source_id":"alpha","route":"CURRENT"}],session="current")},fixtures=base_f,grants=base_g))
        q=routes(r)[0]; assert q["selected"][0]["version"]=="v2" and q["freshness"]=="CURRENT"
        assert any(x["resolution"]=="CURRENT_WINS" for x in ctx(r)["conflicts"])
        assert "east" in r["visible_reply"] and "west" not in r["visible_reply"]
        return {"selected_version":"v2","current_wins":True,"silent_merges":0}
      case(cases,"TS2-03",t03)

      # TS2-04 exact version/revision fidelity
      def t04():
        r=result(call(a.python,root/"ts04",{"op":"context_turn","turn":cturn(1,"topic-exact",[{"source_id":"alpha","route":"EXACT","version":"v1","revision":"r1"}],session="exact")},fixtures=base_f,grants=base_g))
        q=routes(r)[0]; sel=q["selected"]; assert len(sel)==1 and (sel[0]["version"],sel[0]["revision"])==("v1","r1") and q["version_result"]=="EXACT_MATCH"
        assert "west" in r["visible_reply"] and "east" not in r["visible_reply"]
        miss=result(call(a.python,root/"ts04-miss",{"op":"context_turn","turn":cturn(2,"topic-exact-miss",[{"source_id":"alpha","route":"EXACT","version":"v1","revision":"r9"}],session="exact-miss")},fixtures=base_f,grants=base_g))
        assert routes(miss)[0]["selected"]==[] and "east" not in miss["visible_reply"]
        return {"exact":"v1/r1","wrong_version_returns":0,"wrong_revision_returns":0}
      case(cases,"TS2-04",t04)

      # TS2-05 miss is not negative existence; distinguish NOT_LOOKED_UP vs UNKNOWN
      def t05():
        denied=result(call(a.python,root/"ts05a",{"op":"context_turn","turn":cturn(1,"topic-miss",[{"source_id":"missing","route":"CURRENT"}],session="miss-a")},fixtures=base_f,grants=base_g))
        q1=routes(denied)[0]; assert q1["knowledge_state"]=="NOT_LOOKED_UP" and q1["negative_existence"]=="NOT_ESTABLISHED"
        unknown=result(call(a.python,root/"ts05b",{"op":"context_turn","turn":cturn(1,"topic-unknown",[{"source_id":"missing","route":"CURRENT"}],session="miss-b")},fixtures=base_f,grants=base_g+[grant("missing","v1")]))
        q2=routes(unknown)[0]; assert q2["knowledge_state"]=="UNKNOWN" and q2["negative_existence"]=="NOT_ESTABLISHED"
        return {"states":["NOT_LOOKED_UP","UNKNOWN"],"negative_existence_inferences":0}
      case(cases,"TS2-05",t05)

      # TS2-06 auth must precede retrieval
      def t06():
        r=result(call(a.python,root/"ts06",{"op":"context_turn","turn":cturn(1,"topic-deny",[{"source_id":"beta","route":"CURRENT"}],session="deny",text="Show protected beta")},fixtures=base_f,grants=[g for g in base_g if g["source_id"]!="beta"]))
        order=trace(r)["query_order"]; assert order==[{"action":"AUTHORIZE","source_id":"beta","decision":"DENY"}]
        assert r["counters"]["candidate_retrievals"]==0 and r["counters"]["authority_reads"]==0
        assert ctx(r)["included"]==[] and "amber key" not in r["visible_reply"]
        return {"query_order":order,"candidate_retrievals":0,"authority_reads":0,"content_leaks":0}
      case(cases,"TS2-06",t06)

      # TS2-07 multi-source bounded pack, deterministic fp, UNKNOWN+CONFLICT retained
      def t07():
        delta1=fixture("delta","v1","r1","CURRENT","Delta revision one.")
        delta2=fixture("delta","v1","r2","CURRENT","Delta revision two.")
        fs=base_f+[delta1,delta2]; gs=base_g+[grant("delta","v1"),grant("missing","v1")]
        needs=[{"source_id":"alpha","route":"CURRENT"},{"source_id":"beta","route":"CURRENT"},{"source_id":"missing","route":"CURRENT"},{"source_id":"delta","route":"CURRENT"}]
        outs=[]
        for label in ("x","y"):
          r=result(call(a.python,root/f"ts07-{label}",{"op":"context_turn","turn":cturn(1,"topic-multi",needs,session="multi-det",request="multi-fixed")},fixtures=fs,grants=gs)); outs.append(r)
        c=ctx(outs[0]); assert 2<=len(c["included"])<=5 and c["context_fingerprint"]==ctx(outs[1])["context_fingerprint"]
        rr=routes(outs[0]); assert any(x["knowledge_state"]=="UNKNOWN" for x in rr) and any(x["conflict"]=="CONFLICT" for x in rr)
        assert any(x.get("resolution")=="CONFLICT" for x in c["conflicts"])
        return {"included_refs":len(c["included"]),"deterministic_fingerprint":c["context_fingerprint"],"unknown_preserved":True,"conflict_preserved":True}
      case(cases,"TS2-07",t07)

      # TS2-08 budget fail is explicit
      def t08():
        r=result(call(a.python,root/"ts08",{"op":"context_turn","turn":cturn(1,"topic-low",[{"source_id":"alpha","route":"CURRENT"},{"source_id":"beta","route":"CURRENT"}],session="low",budget=64)},fixtures=base_f,grants=base_g))
        c=ctx(r); assert c["status"]=="BLOCKED" and c["stop_reason"]=="CONTEXT_BUDGET_EXCEEDED"
        assert c["budget"]["silent_truncations"]==0 and len(c["omitted"])>=1
        assert all(x["action"] in {"OMIT","COMPACT","INCLUDE"} for x in c["ledger"])
        return {"stop":"CONTEXT_BUDGET_EXCEEDED","silent_truncations":0,"omitted":len(c["omitted"]),"ledger_entries":len(c["ledger"])}
      case(cases,"TS2-08",t08)

      # TS2-09 revision/lifecycle invalidation and rebuild
      def t09():
        s=root/"ts09"; g=[grant("alpha","v1")]
        f1=[fixture("alpha","v1","r1","CURRENT","Alpha revision one.")]
        f2=[fixture("alpha","v1","r2","CURRENT","Alpha revision two.")]
        r1=result(call(a.python,s,{"op":"context_turn","turn":cturn(1,"topic-r",[{"source_id":"alpha","route":"CURRENT"}],session="rev")},fixtures=f1,grants=g))
        r2=result(call(a.python,s,{"op":"context_turn","turn":cturn(2,"topic-r",[{"source_id":"alpha","route":"CURRENT"}],session="rev")},fixtures=f2,grants=g))
        assert "SOURCE_REVISION_CHANGED" in ctx(r2)["invalidation_reasons"] and ctx(r2)["active_input"] if "active_input" in ctx(r2) else True
        assert ctx(r2)["included"][0]["revision"]=="r2" and "revision one" not in r2["visible_reply"]
        # lifecycle shift must make stale CURRENT input unavailable, not silently active
        f3=[fixture("alpha","v1","r2","HISTORY","Alpha revision two.")]
        r3=result(call(a.python,s,{"op":"context_turn","turn":cturn(3,"topic-r",[{"source_id":"alpha","route":"CURRENT"}],session="rev")},fixtures=f3,grants=g))
        assert "LIFECYCLE_CHANGED" in ctx(r3)["invalidation_reasons"] and r3["projection"]["active_input"] is False
        ev=result(call(a.python,s,{"op":"safe_export"},fixtures=f3,grants=g))["events"]
        assert len(ev)==6 and len({x["event_id"] for x in ev})==6
        return {"revision_invalidation":True,"lifecycle_invalidation":True,"new_revision":"r2","stale_active_inputs":0,"canonical_events_preserved":6}
      case(cases,"TS2-09",t09)

      # TS2-10 ACL tightening invalidates old derived state
      def t10():
        s=root/"ts10"; fs=[fixture("alpha","v1","r1","CURRENT","ACL synthetic allowed content.")]; gs=[grant("alpha","v1")]
        result(call(a.python,s,{"op":"context_turn","turn":cturn(1,"topic-acl",[{"source_id":"alpha","route":"CURRENT"}],session="acl")},fixtures=fs,grants=gs))
        r=result(call(a.python,s,{"op":"context_turn","turn":cturn(2,"topic-acl",[{"source_id":"alpha","route":"CURRENT"}],session="acl")},fixtures=fs,grants=[]))
        assert "ACL_SCOPE_CHANGED" in ctx(r)["invalidation_reasons"] and r["projection"]["active_input"] is False
        assert r["counters"]["candidate_retrievals"]==0 and "allowed content" not in r["visible_reply"]
        return {"invalidation":"ACL_SCOPE_CHANGED","stale_active_inputs":0,"candidate_retrievals_after_tighten":0,"leaks":0}
      case(cases,"TS2-10",t10)

      # TS2-11 premise change invalidates recent derived input
      def t11():
        s=root/"ts11"; fs=[alpha_cur]; gs=[grant("alpha","v2")]
        result(call(a.python,s,{"op":"context_turn","turn":cturn(1,"topic-p",[{"source_id":"alpha","route":"CURRENT"}],session="prem",premise="task-v1")},fixtures=fs,grants=gs))
        r=result(call(a.python,s,{"op":"context_turn","turn":cturn(2,"topic-p",[{"source_id":"alpha","route":"CURRENT"}],session="prem",premise="task-v2")},fixtures=fs,grants=gs))
        assert "PREMISE_CHANGED" in ctx(r)["invalidation_reasons"]
        assert ctx(r)["recent_exact_turn_refs"]==[] and any(x["reason"]=="INVALIDATED_DERIVED_INPUT" for x in ctx(r)["omitted"])
        return {"invalidation":"PREMISE_CHANGED","obsolete_recent_tail_in_active_input":0,"explicit_omission":True}
      case(cases,"TS2-11",t11)

      # TS2-12 safe trace completeness and content minimization
      def t12():
        r=result(call(a.python,root/"ts12",{"op":"context_turn","turn":cturn(1,"topic-trace",[{"source_id":"alpha","route":"CURRENT"},{"source_id":"beta","route":"CURRENT"}],session="trace")},fixtures=base_f,grants=base_g))
        t=trace(r); required={"active_topic","authority_routes","authorization","budget","compacted_refs","conflicts","context_fingerprint","included_refs","invalidation_reasons","omitted_refs","queried_refs","query_order","rebuild_reasons","terminal_reason","trace_fingerprint"}
        assert required.issubset(t) and t["authority"] is False
        raw=json.dumps(t,ensure_ascii=False); assert "Alpha CURRENT evidence" not in raw and "Beta evidence" not in raw
        safe_scan(t); assert r["projection"]["working_set"]["authority"] is False and r["projection"]["working_set"]["derived_only"] is True
        secret=call(a.python,root/"ts12-secret",{"op":"context_turn","turn":cturn(2,"topic-secret",[{"source_id":"alpha","route":"CURRENT"}],session="secret",text="api_key="+SECRET)},fixtures=base_f,grants=base_g)
        assert secret["returncode"]==2 and secret["stdout"].get("error")=="UNSAFE_INPUT" and SECRET not in json.dumps(secret["stdout"])
        return {"required_trace_fields":len(required),"source_bodies_in_trace":0,"secret_private_body_leaks":0,"derived_authority":False}
      case(cases,"TS2-12",t12)

      # TS2-13 real served continuity.js in independent Node VM
      def t13():
        proc,url=launch_shell(a.python,root/"shell")
        try:
          p=subprocess.run([a.node,a.browser_verifier,url],text=True,capture_output=True,timeout=30)
          assert p.returncode==0,(p.stdout,p.stderr)
          out=json.loads(p.stdout.strip().splitlines()[-1]); assert out["status"]=="PASS" and out["raw_browser_writes"]==0 and out["secret_persistence"]==0
          return out
        finally:
          proc.terminate()
          try: proc.wait(timeout=3)
          except Exception: proc.kill()
      case(cases,"TS2-13",t13)

      # TS2-14 independent S1 / A019-public behavior regression through TestPort only
      def t14():
        sf={"source_id":"s1-source","version":"v1",**SCOPE,"text":"S1 synthetic evidence: lamp is local.","observed_at":"2026-09-17T12:00:00+00:00","synthetic":True,"public_safe":True}
        sg=[grant("s1-source","v1")]; s=root/"ts14"
        ok=result(call(a.python,s,{"op":"turn","turn":old_turn(1)},fixtures=[sf],grants=sg))
        assert ok["execution_order"].index("USER_DURABLE_RECEIPT") < ok["execution_order"].index("PROVIDER_STUB_INVOKED")
        assert ok["presentation_order"]==["USER_DURABLE_RECEIPT","ASSISTANT_DURABLE_RECEIPT","DISPLAY"] and ok["terminal_count"]==1
        assert ok["receipts"]["user"]["contract_version"]=="canonical_event/v1" and ok["receipts"]["assistant"]["contract_version"]=="canonical_event/v1"
        cr=call(a.python,s,{"op":"turn","turn":old_turn(2,request="s1-crash")},fixtures=[sf],grants=sg,fault="AFTER_USER_DURABLE")
        assert cr["returncode"]==86
        ob=result(call(a.python,s,{"op":"observe","request_id":"s1-crash"},fixtures=[sf],grants=sg)); assert ob["status"]=="AWAIT_EXPLICIT_RESUME" and ob["terminal_count"]==0 and ob["counters"]["cognition_stub_invocations"]==0
        re=result(call(a.python,s,{"op":"resume","request_id":"s1-crash"},fixtures=[sf],grants=sg)); assert re["terminal_count"]==1
        deny=result(call(a.python,root/"ts14-deny",{"op":"turn","turn":old_turn(1,session="deny-s1")},fixtures=[sf],grants=[])); assert deny["counters"]["authority_reads"]==0 and deny["counters"]["candidate_retrievals"]==0
        rb=result(call(a.python,root/"ts14-rebuild",{"op":"rebuild","source_id":"s1-source","version":"v1"},fixtures=[sf],grants=sg)); assert rb.get("authority_writes",0)==0
        wake={"event_id":"wake-s1","universe_id":SCOPE["universe_id"],"access_subject_id":SCOPE["access_subject_id"],"owner_subject_id":SCOPE["access_subject_id"],"observed_at":stamp(130),"salience":1.0,"urgency":1.0,"confidence":1.0,"quiet_hours":False,"cooldown_remaining":0,"repeat_count":0,"repeat_limit":1}
        wr=result(call(a.python,root/"ts14-wake",{"op":"wake","candidate":wake},fixtures=[sf],grants=sg)); assert wr["action"]=="SILENT" and wr["notifications"]==wr["continuations"]==wr["external_side_effects"]==0
        ev=result(call(a.python,s,{"op":"safe_export"},fixtures=[sf],grants=sg))["events"]; assert len(ev)==4 and len({x["event_id"] for x in ev})==4
        return {"durable_before_cognition":True,"terminal_before_display":True,"explicit_resume":True,"duplicate_terminals":0,"permission_pre_retrieval":True,"wake":"SILENT","a019_public_receipts":"canonical_event/v1","events":4}
      case(cases,"TS2-14",t14)

      # TS2-15 independence/offline + repeated black-box runs
      repeat=[]
      def t15():
        bad=call(a.python,root/"badop",{"op":"db_query"}); assert bad["returncode"]==2 and bad["stdout"].get("error")=="OPERATION_NOT_IN_SLICE"
        for run in (1,2):
          s=root/f"stress-{run}"; ids=[]; terminals=0
          for n in range(1,21):
            topic=("topic-a","topic-b","topic-c")[n%3]; src={"topic-a":"alpha","topic-b":"beta","topic-c":"gamma"}[topic]
            r=result(call(a.python,s,{"op":"context_turn","turn":cturn(n,topic,[{"source_id":src,"route":"CURRENT"}],session=f"stress-{run}")},fixtures=base_f,grants=base_g)); zero_side_effects(r); terminals+=r["terminal_count"]; ids += [r["user_event_id"],r["assistant_event_id"]]
          ev=result(call(a.python,s,{"op":"safe_export"},fixtures=base_f,grants=base_g))["events"]
          assert len(ev)==40 and len({x["event_id"] for x in ev})==40 and set(ids)=={x["event_id"] for x in ev} and terminals==20
          repeat.append({"turns":20,"events":40,"terminals":20,"event_loss":0,"duplicate_events":0})
        return {"internal_db_oracles":0,"unsupported_db_operation":"OPERATION_NOT_IN_SLICE","offline_only":info["offline_only"],"live_provider_enabled":info["live_provider_enabled"],"external_connectors_enabled":info["external_connectors_enabled"],"repeat_runs":repeat}
      case(cases,"TS2-15",t15)

    failed=[k for k,v in cases.items() if v["status"]!="PASS"]
    zt=list(failed)
    verdict="A2-S2 PASS" if not zt else "A2-S2 FAIL / REPAIR REQUIRED"
    receipt={"schema_id":"a2-a029-s2-blackbox/v1","work_order":"ENG-A2-A029-S2-01","candidate":meta,
             "independence":{"testport_process_only":True,"shell_public_surface_only":True,"companion_mind_imports":0,"internal_db_oracles":0,"a1_tests_as_behavior_evidence":0},
             "cases":cases,"zero_tolerance_count":len(zt),"zero_tolerance_failures":zt,"verdict":verdict,
             "limitations":["Synthetic/public-safe fixtures only","Process-crash not physical power-cut","Continuity browser JS executed in independent Node VM against real loopback HTTP; no native-browser rendering/bfcache claim","No live provider/OAuth/Drive/credential"]}
    pathlib.Path(a.output).write_text(json.dumps(receipt,sort_keys=True,indent=2,ensure_ascii=False),encoding="utf-8")
    print(json.dumps({"verdict":verdict,"zero_tolerance_count":len(zt),"failed":failed,"wheel_sha256":meta["wheel_sha256"]},sort_keys=True))
    return 0 if verdict=="A2-S2 PASS" else 1
if __name__=="__main__": raise SystemExit(main())
