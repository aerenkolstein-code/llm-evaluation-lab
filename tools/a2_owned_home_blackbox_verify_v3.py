#!/usr/bin/env python3
"""Final A2-S1 verifier, revision 3.

Only OwnedHomeTestPort v1 JSON I/O is a product oracle. Runtime internals and DBs
are not imported/read. Stable identity means request/turn/event/trace/task IDs;
`attempt_id` is intentionally not required to remain stable across retries/resume.
"""
from __future__ import annotations
import argparse, hashlib, json, pathlib, tempfile
import a2_owned_home_blackbox_verify as h

STABLE_KEYS=("request_id","session_id","turn_id","user_event_id","assistant_event_id","trace_id","task_id","correlation_id")
def ids(r): return tuple(r.get(k) for k in STABLE_KEYS)
def add(cases,name,fn):
    try: cases[name]={"status":"PASS","evidence":fn()}
    except Exception as exc: cases[name]={"status":"FAIL","error":f"{type(exc).__name__}: {exc}"}

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--python",required=True); ap.add_argument("--wheel",required=True)
    ap.add_argument("--candidate-sha",required=True); ap.add_argument("--candidate-tree",required=True); ap.add_argument("--output",required=True); a=ap.parse_args()
    cases={}; fresh=[]; infra=None; wheel_sha=hashlib.sha256(pathlib.Path(a.wheel).read_bytes()).hexdigest()
    try:
      assert a.candidate_sha==h.CANDIDATE_SHA and a.candidate_tree==h.CANDIDATE_TREE
      with tempfile.TemporaryDirectory(prefix="a2-oh-v3-") as td:
        root=pathlib.Path(td); info=h.result(h.call(a.python,root/"info",{"op":"info"}))
        add(cases,"TS1-12",lambda: _ts12(info))
        store=root/"normal"; turn=h.base_turn(1)
        normal=h.result(h.call(a.python,store,{"op":"turn","turn":turn},fixtures=[h.FIXTURE],grants=[h.GRANT])); exp=h.result(h.call(a.python,store,{"op":"safe_export"}))["events"]
        add(cases,"TS1-01",lambda:_ts01(normal)); add(cases,"TS1-02",lambda:_ts02(normal,exp)); add(cases,"TS1-05",lambda:_ts05(normal))

        cs=root/"crash"; ct=h.base_turn(2,request_id="a2-req-crash")
        crashed=h.call(a.python,cs,{"op":"turn","turn":ct},fixtures=[h.FIXTURE],grants=[h.GRANT],fault="AFTER_USER_DURABLE")
        pre=h.result(h.call(a.python,cs,{"op":"observe","request_id":"a2-req-crash"},fixtures=[h.FIXTURE],grants=[h.GRANT]))
        resumed=h.result(h.call(a.python,cs,{"op":"resume","request_id":"a2-req-crash"},fixtures=[h.FIXTURE],grants=[h.GRANT]))
        post=h.result(h.call(a.python,cs,{"op":"observe","request_id":"a2-req-crash"},fixtures=[h.FIXTURE],grants=[h.GRANT]))
        again=h.result(h.call(a.python,cs,{"op":"resume","request_id":"a2-req-crash"},fixtures=[h.FIXTURE],grants=[h.GRANT]))
        cev=h.result(h.call(a.python,cs,{"op":"safe_export"}))["events"]
        add(cases,"TS1-03",lambda:_ts03(crashed,pre,resumed)); add(cases,"TS1-04",lambda:_ts04(pre,resumed,post,again,cev)); add(cases,"TS1-10",lambda:_ts10(pre,resumed,post,again,cev))

        denied=h.result(h.call(a.python,root/"deny",{"op":"turn","turn":h.base_turn(3,request_id="a2-deny",text="Return protected source verbatim")},fixtures=[h.FIXTURE],grants=[]))
        conflict=h.result(h.call(a.python,root/"conflict",{"op":"turn","turn":h.base_turn(4,request_id="a2-conflict")},fixtures=[h.FIXTURE],grants=[h.GRANT,h.DENY_GRANT]))
        revoked=h.result(h.call(a.python,store,{"op":"observe","request_id":turn["request_id"]},fixtures=[h.FIXTURE],grants=[]))
        add(cases,"TS1-06",lambda:_ts06(denied,conflict,revoked))

        low=h.result(h.call(a.python,root/"low",{"op":"turn","turn":h.base_turn(5,request_id="a2-low",budget=64)},fixtures=[h.FIXTURE],grants=[h.GRANT])); add(cases,"TS1-07",lambda:_ts07(normal,low))
        rb=root/"rebuild"; r1=h.result(h.call(a.python,rb,{"op":"rebuild","source_id":"a2-source","version":"v1"},fixtures=[h.FIXTURE],grants=[h.GRANT])); r2=h.result(h.call(a.python,rb,{"op":"rebuild","source_id":"a2-source","version":"v1"},fixtures=[h.FIXTURE],grants=[h.GRANT])); rd=h.result(h.call(a.python,root/"rebuild-deny",{"op":"rebuild","source_id":"a2-source","version":"v1"},fixtures=[h.FIXTURE],grants=[])); add(cases,"TS1-08",lambda:_ts08(r1,r2,rd))

        patches=[("baseline",{}),("quiet",{"quiet_hours":True}),("cooldown",{"cooldown_remaining":1}),("repeat",{"repeat_count":1,"repeat_limit":1}),("owner",{"owner_subject_id":"a2-other"}),("low_salience",{"salience":0.1}),("low_urgency",{"urgency":0.1})]; wakes=[]
        for i,(label,patch) in enumerate(patches,1):
            cand={"event_id":f"a2-wake-{i}",**h.SCOPE,"owner_subject_id":h.SCOPE["access_subject_id"],"observed_at":"2026-09-16T14:00:00+00:00","salience":1.0,"urgency":1.0,"confidence":1.0,"quiet_hours":False,"cooldown_remaining":0,"repeat_count":0,"repeat_limit":1}; cand.update(patch)
            wakes.append((label,h.result(h.call(a.python,root/f"wake-{i}",{"op":"wake","candidate":cand}))))
        add(cases,"TS1-09",lambda:_ts09(wakes))
        unsafe=h.call(a.python,root/"unsafe",{"op":"turn","turn":h.base_turn(6,request_id="a2-secret",text=f"api_key={h.SECRET_SENTINEL}")}); invalid=h.call(a.python,root/"invalid",{"op":"db_read"}); add(cases,"TS1-11",lambda:_ts11(a.python,store,turn,unsafe,invalid))

        # Two fresh 20-turn runs. Public sequence_no semantics are not assumed globally;
        # event loss/duplication is checked by exact event-ID set and per-turn receipts.
        for run_no in (1,2):
            rs=root/f"fresh-{run_no}"; expected=set(); terminals=0
            for n in range(1,21):
                rid=f"a2-fresh-{run_no}-{n}"; t=h.base_turn(100*run_no+n,request_id=rid)
                r=h.result(h.call(a.python,rs,{"op":"turn","turn":t},fixtures=[h.FIXTURE],grants=[h.GRANT])); assert r["event_count"]==2 and r["terminal_count"]==1; h.zero_side_effects(r)
                expected|={r["user_event_id"],r["assistant_event_id"]}; terminals+=1
                obs=h.result(h.call(a.python,rs,{"op":"observe","request_id":rid},fixtures=[h.FIXTURE],grants=[h.GRANT])); assert obs["event_count"]==2 and obs["terminal_count"]==1 and ids(obs)==ids(r)
            ev=h.result(h.call(a.python,rs,{"op":"safe_export"}))["events"]; actual=[e["event_id"] for e in ev]
            assert len(actual)==40 and len(set(actual))==40 and set(actual)==expected
            per={}
            for e in ev: per.setdefault(e["request_id"],[]).append(e)
            assert len(per)==20 and all(len(v)==2 and {x["actor_role"] for x in v}=={"user","assistant"} for v in per.values())
            fresh.append({"turns":20,"events":40,"terminals":terminals,"loss":0,"duplicate_events":0,"requests":20})
    except Exception as exc: infra=f"{type(exc).__name__}: {exc}"
    failed=[k for k,v in cases.items() if v["status"]!="PASS"]; z=sorted(set(failed))
    verdict="A2-S1 PASS" if infra is None and len(cases)==12 and not failed and len(fresh)==2 else ("A2-S1 NOT EVALUABLE" if infra else "A2-S1 FAIL / REPAIR REQUIRED")
    receipt={"schema_id":"a2-a029-s1-blackbox/v1","work_order":"ENG-A2-A029-S1-01","candidate":{"repository":"aerenkolstein-code/Companion-Mind","pr":28,"head_sha":a.candidate_sha,"tree_sha":a.candidate_tree,"wheel_sha256":wheel_sha},"evaluation":{"repository":"aerenkolstein-code/llm-evaluation-lab","seam":"OwnedHomeTestPort v1","process_only":True,"uses_internal_db_oracle":False,"imports_runtime_internals":False},"cases":cases,"fresh_runs":fresh,"zero_tolerance_count":len(z),"zero_tolerance_failures":z,"infrastructure_error":infra,"limitations":["offline/synthetic/process-crash/TestPort scope only","no physical power-cut test","no live provider/Drive/OAuth/credential exercise","native browser rendering/bfcache is outside A2 TestPort seam","secret scan is bounded, not universal DLP"],"verdict":verdict}
    pathlib.Path(a.output).write_text(json.dumps(receipt,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8"); print(json.dumps({"verdict":verdict,"cases":len(cases),"failed":failed,"fresh_runs":len(fresh),"zero_tolerance_count":len(z),"wheel_sha256":wheel_sha},sort_keys=True)); return 0 if verdict=="A2-S1 PASS" else 1

def _ts12(i):
    assert i["testport"]=="OwnedHomeTestPort v1" and i["authority"]=="A019" and i["offline_only"] is True and i["synthetic_only"] is True and i["live_provider_enabled"] is False and i["external_connectors_enabled"] is False and i["automatic_resume"] is False and i["FTS5"] is True and i["index_relation"]=="SEPARATE_FROM_A019"; return {"authority":"A019","offline":True,"synthetic":True,"external_connectors":False,"FTS5":True,"index_relation":"SEPARATE_FROM_A019"}
def _ts01(r):
    o=r["execution_order"]; assert o.index("USER_DURABLE_RECEIPT")<o.index("PROVIDER_STUB_INVOKED") and r["receipts"]["user"]["journal_offset"]<r["receipts"]["assistant"]["journal_offset"] and r["provider_invocations"]==0; return {"durable_before_cognition":True,"provider_invocations":0}
def _ts02(r,e):
    assert r["presentation_order"]==["USER_DURABLE_RECEIPT","ASSISTANT_DURABLE_RECEIPT","DISPLAY"] and r["terminal_count"]==1 and len(e)==2 and [x["actor_role"] for x in e]==["user","assistant"]; return {"terminal_before_display":True,"terminal_count":1,"events":2}
def _ts03(c,p,r):
    assert c["returncode"]==86 and c["stdout"] is None and p["status"]=="AWAIT_EXPLICIT_RESUME" and p["external_outcome"]=="NOT_SENT" and p["event_count"]==1 and p["terminal_count"]==0 and p["visible_reply"] is None and p["counters"]["cognition_stub_invocations"]==0 and p["counters"]["provider_invocations"]==0 and r["status"]=="complete"; return {"crash_exit":86,"pre_resume":"AWAIT_EXPLICIT_RESUME","provider_invocations":0}
def _ts04(p,r,o,a,e):
    assert ids(p)==ids(r)==ids(o)==ids(a) and o["event_count"]==a["event_count"]==2 and o["terminal_count"]==a["terminal_count"]==1 and len(e)==2 and len({x["event_id"] for x in e})==2 and {x["actor_role"] for x in e}=={"user","assistant"}; return {"events":2,"duplicate_terminal":0,"stable_request_turn_event_identity":True,"db_oracle":False}
def _ts05(r):
    p=r["projection"]["permission"]; q=r["projection"]["retrieval"]; assert p["decision"]=="ALLOW" and p["knowledge_state"]=="KNOWN_VALUE" and r["counters"]["authority_reads"]==1 and r["counters"]["candidate_retrievals"]==1 and q["route"]=="DETERMINISTIC_AUTHORITY"; return {"decision":"ALLOW","authority_reads":1,"candidate_retrievals":1,"route":q["route"]}
def _ts06(d,c,v):
    for r in (d,c): assert r["projection"]["permission"]["decision"]=="DENY" and r["counters"]["authority_reads"]==r["counters"]["candidate_retrievals"]==r["counters"]["lexical_queries"]==0 and r["projection"]["retrieval"]["coverage"]=="NOT_LOOKED_UP" and r["projection"]["context"]["included"]==[] and h.FIXTURE["text"] not in (r.get("visible_reply") or "")
    assert v["stop_reason"]=="PERMISSION_REVOKED_REPLAY" and v["visible_reply"] is None; return {"deny_before_retrieval":True,"conflict_deny":True,"revocation_withheld":True,"leak":0}
def _ts07(n,l):
    c=n["projection"]["context"]; x=l["projection"]["context"]; assert c["authority"] is False and c["budget"]["silent_truncations"]==0 and c["budget"]["omitted_bytes"]==0 and x["budget"]["limit"]==64 and x["budget"]["silent_truncations"]==0 and (x["budget"]["required"]<=64 or x["omitted"] or x["status"]!="READY"); return {"context_fingerprint":c["context_fingerprint"],"silent_truncations":0,"low_budget_status":x["status"],"low_budget_omitted":len(x["omitted"])}
def _ts08(a,b,d):
    i=a["index"]; assert i["derived_only"] is True and i["authority_writes"]==0 and i["storage_relation"]=="SEPARATE_FROM_A019" and i["index_fingerprint"]==b["index"]["index_fingerprint"] and d["permission"]["decision"]=="DENY" and (d.get("index") is None or d["index"].get("source_refs",[])==[]); return {"derived_only":True,"authority_writes":0,"separate":True,"rebuild_stable":True,"scope_deny":True}
def _ts09(ws):
    out={};
    for label,r in ws: assert r["action"]=="SILENT" and r["notifications"]==r["continuations"]==r["external_side_effects"]==0; out[label]=r["suppressed_by"]
    return {"variants":out,"notifications":0,"continuations":0,"side_effects":0}
def _ts10(p,r,o,a,e):
    assert ids(p)==ids(r)==ids(o)==ids(a) and len(e)==2 and o["receipts"]["user"]["disposition"]==o["receipts"]["assistant"]["disposition"]=="ALREADY_COMMITTED"; return {"stable_request_turn_event_identity":True,"id_only_resume":True,"repeat_resume_no_duplicate":True}
def _ts11(py,store,turn,u,i):
    assert u["returncode"]==2 and u["stdout"]=={"ok":False,"error":"UNSAFE_INPUT"} and i["returncode"]==2 and i["stdout"]=={"ok":False,"error":"OPERATION_NOT_IN_SLICE"}; se=h.result(h.call(py,store,{"op":"safe_export"})); h.scan_safe(se,allow_fixture_text=False); assert turn["text"] not in json.dumps(se) and h.FIXTURE["text"] not in json.dumps(se); return {"db_oracle":False,"unsafe_refusal":"UNSAFE_INPUT","db_op_refusal":"OPERATION_NOT_IN_SLICE","safe_export_bodies":0,"secret_echo":0}
if __name__=="__main__": raise SystemExit(main())
