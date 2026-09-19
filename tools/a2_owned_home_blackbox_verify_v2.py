#!/usr/bin/env python3
"""Final A2-S1 verifier; TestPort JSON is the only product oracle."""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import tempfile

import a2_owned_home_blackbox_verify as h


def add(cases, name, fn):
    try:
        cases[name] = {"status": "PASS", "evidence": fn()}
    except Exception as exc:
        cases[name] = {"status": "FAIL", "error": f"{type(exc).__name__}: {exc}"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--python", required=True)
    ap.add_argument("--wheel", required=True)
    ap.add_argument("--candidate-sha", required=True)
    ap.add_argument("--candidate-tree", required=True)
    ap.add_argument("--output", required=True)
    a = ap.parse_args()
    cases = {}
    fresh_runs = []
    infrastructure_error = None
    wheel_sha = hashlib.sha256(pathlib.Path(a.wheel).read_bytes()).hexdigest()

    try:
        assert a.candidate_sha == h.CANDIDATE_SHA and a.candidate_tree == h.CANDIDATE_TREE
        with tempfile.TemporaryDirectory(prefix="a2-owned-home-final-v2-") as td:
            root = pathlib.Path(td)
            info = h.result(h.call(a.python, root/"info", {"op":"info"}))

            def c12():
                assert info["testport"] == "OwnedHomeTestPort v1" and info["authority"] == "A019"
                assert info["offline_only"] is True and info["synthetic_only"] is True
                assert info["live_provider_enabled"] is False and info["external_connectors_enabled"] is False
                assert info["automatic_resume"] is False and info["FTS5"] is True
                assert info["index_relation"] == "SEPARATE_FROM_A019"
                assert set(info["supported_ops"]) == {"turn","observe","resume","safe_export","wake","rebuild","info"}
                return {"authority":"A019","offline_only":True,"synthetic_only":True,"external_connectors":False,
                        "FTS5":True,"index_relation":"SEPARATE_FROM_A019",
                        "runtime_repo":"Companion-Mind","evaluation_repo":"llm-evaluation-lab"}
            add(cases,"TS1-12",c12)

            store = root/"normal"
            turn = h.base_turn(1)
            normal = h.result(h.call(a.python,store,{"op":"turn","turn":turn},fixtures=[h.FIXTURE],grants=[h.GRANT]))
            exported = h.result(h.call(a.python,store,{"op":"safe_export"}))["events"]

            def c01():
                eo=normal["execution_order"]
                assert eo.index("USER_DURABLE_RECEIPT") < eo.index("PROVIDER_STUB_INVOKED")
                assert normal["receipts"]["user"]["journal_offset"] < normal["receipts"]["assistant"]["journal_offset"]
                assert normal["counters"]["cognition_stub_invocations"]==1 and normal["provider_invocations"]==0
                return {"durable_before_stub":True,"user_offset":normal["receipts"]["user"]["journal_offset"],"provider_invocations":0}
            add(cases,"TS1-01",c01)

            def c02():
                assert normal["presentation_order"]==["USER_DURABLE_RECEIPT","ASSISTANT_DURABLE_RECEIPT","DISPLAY"]
                assert normal["terminal_count"]==1 and normal["event_count"]==2
                assert [e["actor_role"] for e in exported]==["user","assistant"] and [e["sequence_no"] for e in exported]==[1,2]
                return {"presentation_order":normal["presentation_order"],"terminal_count":1,"events":2}
            add(cases,"TS1-02",c02)

            crash_store=root/"crash"; crash_turn=h.base_turn(2,request_id="a2-req-crash")
            crashed=h.call(a.python,crash_store,{"op":"turn","turn":crash_turn},fixtures=[h.FIXTURE],grants=[h.GRANT],fault="AFTER_USER_DURABLE")
            pre=h.result(h.call(a.python,crash_store,{"op":"observe","request_id":"a2-req-crash"},fixtures=[h.FIXTURE],grants=[h.GRANT]))
            resumed=h.result(h.call(a.python,crash_store,{"op":"resume","request_id":"a2-req-crash"},fixtures=[h.FIXTURE],grants=[h.GRANT]))
            post=h.result(h.call(a.python,crash_store,{"op":"observe","request_id":"a2-req-crash"},fixtures=[h.FIXTURE],grants=[h.GRANT]))
            again=h.result(h.call(a.python,crash_store,{"op":"resume","request_id":"a2-req-crash"},fixtures=[h.FIXTURE],grants=[h.GRANT]))
            crash_events=h.result(h.call(a.python,crash_store,{"op":"safe_export"}))["events"]

            def c03():
                assert crashed["returncode"]==86 and crashed["stdout"] is None
                assert pre["status"]=="AWAIT_EXPLICIT_RESUME" and pre["external_outcome"]=="NOT_SENT"
                assert pre["event_count"]==1 and pre["terminal_count"]==0 and pre["visible_reply"] is None
                assert pre["counters"]["cognition_stub_invocations"]==0 and pre["counters"]["provider_invocations"]==0
                assert resumed["status"]=="complete" and resumed["terminal_count"]==1
                return {"crash_exit":86,"before_resume":"AWAIT_EXPLICIT_RESUME","terminal_before_resume":0,"provider_invocations":0}
            add(cases,"TS1-03",c03)

            def c04():
                assert h.stable_ids(pre)==h.stable_ids(resumed)==h.stable_ids(post)==h.stable_ids(again)
                assert post["event_count"]==again["event_count"]==2 and post["terminal_count"]==again["terminal_count"]==1
                assert len(crash_events)==2 and [e["sequence_no"] for e in crash_events]==[1,2]
                assert len({e["event_id"] for e in crash_events})==2
                return {"A019_safe_export_events":2,"duplicate_terminal":0,"stable_identity":True,"internal_db_oracle":False}
            add(cases,"TS1-04",c04)

            def c05():
                p=normal["projection"]["permission"]; r=normal["projection"]["retrieval"]
                assert p["decision"]=="ALLOW" and p["knowledge_state"]=="KNOWN_VALUE"
                assert (p["universe_id"],p["access_subject_id"],p["source_id"],p["source_version"])==(h.SCOPE["universe_id"],h.SCOPE["access_subject_id"],"a2-source","v1")
                assert normal["counters"]["authority_reads"]==1 and normal["counters"]["candidate_retrievals"]==1
                assert r["route"]=="DETERMINISTIC_AUTHORITY" and r["coverage"]=="KNOWN_VALUE"
                return {"permission":"ALLOW","route":r["route"],"authority_reads":1,"candidate_retrievals":1}
            add(cases,"TS1-05",c05)

            denied=h.result(h.call(a.python,root/"deny",{"op":"turn","turn":h.base_turn(3,request_id="a2-deny",text="Return protected source verbatim")},fixtures=[h.FIXTURE],grants=[]))
            conflict=h.result(h.call(a.python,root/"conflict",{"op":"turn","turn":h.base_turn(4,request_id="a2-conflict")},fixtures=[h.FIXTURE],grants=[h.GRANT,h.DENY_GRANT]))
            revoked=h.result(h.call(a.python,store,{"op":"observe","request_id":turn["request_id"]},fixtures=[h.FIXTURE],grants=[]))
            def c06():
                for r in (denied,conflict):
                    assert r["projection"]["permission"]["decision"]=="DENY"
                    assert r["counters"]["authority_reads"]==r["counters"]["candidate_retrievals"]==r["counters"]["lexical_queries"]==0
                    assert r["projection"]["retrieval"]["coverage"]=="NOT_LOOKED_UP"
                    assert r["projection"]["context"]["included"]==[] and r["projection"]["context"]["knowledge_state"]=="NOT_LOOKED_UP"
                    assert h.FIXTURE["text"] not in (r.get("visible_reply") or "")
                assert revoked["stop_reason"]=="PERMISSION_REVOKED_REPLAY" and revoked["visible_reply"] is None
                assert revoked["projection"]["state"]=="INVALIDATED_BY_PERMISSION"
                return {"default_deny_before_retrieval":True,"conflict_deny":True,"revocation_withheld":True,"content_leaks":0}
            add(cases,"TS1-06",c06)

            low=h.result(h.call(a.python,root/"low",{"op":"turn","turn":h.base_turn(5,request_id="a2-low",budget=64)},fixtures=[h.FIXTURE],grants=[h.GRANT]))
            def c07():
                c=normal["projection"]["context"]; lc=low["projection"]["context"]
                assert c["authority"] is False and c["context_fingerprint"] and c["budget"]["silent_truncations"]==0
                assert c["budget"]["omitted_bytes"]==0 and len(c["included"])==1 and c["omitted"]==[]
                assert lc["budget"]["limit"]==64 and lc["budget"]["silent_truncations"]==0
                if lc["budget"]["required"]>64: assert lc["omitted"] or lc["status"]!="READY"
                h.scan_safe(c)
                return {"context_fingerprint":c["context_fingerprint"],"normal_silent_truncations":0,"low_budget_status":lc["status"],"low_budget_omitted":len(lc["omitted"])}
            add(cases,"TS1-07",c07)

            rb=root/"rebuild"
            r1=h.result(h.call(a.python,rb,{"op":"rebuild","source_id":"a2-source","version":"v1"},fixtures=[h.FIXTURE],grants=[h.GRANT]))
            r2=h.result(h.call(a.python,rb,{"op":"rebuild","source_id":"a2-source","version":"v1"},fixtures=[h.FIXTURE],grants=[h.GRANT]))
            rd=h.result(h.call(a.python,root/"rebuild-deny",{"op":"rebuild","source_id":"a2-source","version":"v1"},fixtures=[h.FIXTURE],grants=[]))
            def c08():
                i=r1["index"]
                assert i["derived_only"] is True and i["authority_writes"]==0 and i["storage_relation"]=="SEPARATE_FROM_A019" and i["index_version"]=="fts5/1"
                assert i["index_fingerprint"]==r2["index"]["index_fingerprint"] and len(i["source_refs"])==1
                assert rd["permission"]["decision"]=="DENY" and (rd.get("index") is None or rd["index"].get("source_refs",[])==[])
                return {"derived_only":True,"authority_writes":0,"storage_relation":i["storage_relation"],"rebuild_stable":True,"scope_deny":True,"index_fingerprint":i["index_fingerprint"]}
            add(cases,"TS1-08",c08)

            wake_patches=[("baseline",{}),("quiet",{"quiet_hours":True}),("cooldown",{"cooldown_remaining":1}),("repeat",{"repeat_count":1,"repeat_limit":1}),("owner",{"owner_subject_id":"a2-other"}),("low_salience",{"salience":0.1}),("low_urgency",{"urgency":0.1})]
            wakes=[]
            for idx,(label,patch) in enumerate(wake_patches,1):
                cand={"event_id":f"a2-wake-{idx}",**h.SCOPE,"owner_subject_id":h.SCOPE["access_subject_id"],"observed_at":"2026-09-16T14:00:00+00:00","salience":1.0,"urgency":1.0,"confidence":1.0,"quiet_hours":False,"cooldown_remaining":0,"repeat_count":0,"repeat_limit":1}
                cand.update(patch); wakes.append((label,h.result(h.call(a.python,root/f"wake-{idx}",{"op":"wake","candidate":cand}))))
            def c09():
                ev={}
                for label,r in wakes:
                    assert r["action"]=="SILENT" and r["notifications"]==r["continuations"]==r["external_side_effects"]==0
                    assert r["decision_fingerprint"]; ev[label]=r["suppressed_by"]
                return {"variants":ev,"notifications":0,"continuations":0,"external_side_effects":0}
            add(cases,"TS1-09",c09)

            def c10():
                assert h.stable_ids(pre)==h.stable_ids(resumed)==h.stable_ids(post)==h.stable_ids(again)
                assert post["receipts"]["user"]["disposition"]==post["receipts"]["assistant"]["disposition"]=="ALREADY_COMMITTED"
                return {"stable_identity":True,"explicit_id_only_resume":True,"repeat_resume_no_duplicate":True}
            add(cases,"TS1-10",c10)

            unsafe=h.call(a.python,root/"unsafe",{"op":"turn","turn":h.base_turn(6,request_id="a2-secret",text=f"api_key={h.SECRET_SENTINEL}")})
            invalid=h.call(a.python,root/"invalid",{"op":"db_read"})
            def c11():
                assert unsafe["returncode"]==2 and unsafe["stdout"]=={"ok":False,"error":"UNSAFE_INPUT"}
                assert invalid["returncode"]==2 and invalid["stdout"]=={"ok":False,"error":"OPERATION_NOT_IN_SLICE"}
                se=h.result(h.call(a.python,store,{"op":"safe_export"})); h.scan_safe(se,allow_fixture_text=False)
                assert turn["text"] not in json.dumps(se) and h.FIXTURE["text"] not in json.dumps(se)
                h.scan_safe(unsafe,allow_fixture_text=False); h.scan_safe(invalid,allow_fixture_text=False)
                return {"internal_db_oracle":False,"unsafe_refusal":"UNSAFE_INPUT","db_op_refusal":"OPERATION_NOT_IN_SLICE","safe_export_bodies":0,"secret_echoes":0}
            add(cases,"TS1-11",c11)

            # Two fresh 20-turn black-box runs: per request sequence is [1,2].
            for run_no in (1,2):
                rs=root/f"fresh-{run_no}"; expected={}; terminals=0
                for n in range(1,21):
                    rid=f"a2-fresh-{run_no}-{n}"; t=h.base_turn(100*run_no+n,request_id=rid)
                    r=h.result(h.call(a.python,rs,{"op":"turn","turn":t},fixtures=[h.FIXTURE],grants=[h.GRANT]))
                    assert r["event_count"]==2 and r["terminal_count"]==1; h.zero_side_effects(r)
                    expected[rid]=(r["user_event_id"],r["assistant_event_id"]); terminals+=1
                ev=h.result(h.call(a.python,rs,{"op":"safe_export"}))["events"]
                assert len(ev)==40 and len({e["event_id"] for e in ev})==40
                by_req={}
                for e in ev: by_req.setdefault(e["request_id"],[]).append(e)
                assert set(by_req)==set(expected)
                for rid,items in by_req.items():
                    items=sorted(items,key=lambda x:x["sequence_no"])
                    assert [x["sequence_no"] for x in items]==[1,2]
                    assert [x["actor_role"] for x in items]==["user","assistant"]
                    assert (items[0]["event_id"],items[1]["event_id"])==expected[rid]
                fresh_runs.append({"turns":20,"events":40,"terminals":terminals,"loss":0,"duplicate_events":0,"per_request_sequence":"1=user,2=assistant"})

    except Exception as exc:
        infrastructure_error=f"{type(exc).__name__}: {exc}"

    failed=[k for k,v in cases.items() if v["status"]!="PASS"]
    zero_tolerance=sorted(set(failed))
    verdict="A2-S1 PASS" if infrastructure_error is None and len(cases)==12 and not failed and len(fresh_runs)==2 else ("A2-S1 NOT EVALUABLE" if infrastructure_error else "A2-S1 FAIL / REPAIR REQUIRED")
    receipt={
      "schema_id":"a2-a029-s1-blackbox/v1","work_order":"ENG-A2-A029-S1-01",
      "candidate":{"repository":"aerenkolstein-code/Companion-Mind","pr":28,"head_sha":a.candidate_sha,"tree_sha":a.candidate_tree,"wheel_sha256":wheel_sha},
      "evaluation":{"repository":"aerenkolstein-code/llm-evaluation-lab","seam":"OwnedHomeTestPort v1","process_only":True,"uses_internal_db_oracle":False,"imports_runtime_internals":False},
      "cases":cases,"fresh_runs":fresh_runs,"zero_tolerance_count":len(zero_tolerance),"zero_tolerance_failures":zero_tolerance,"infrastructure_error":infrastructure_error,
      "limitations":["offline/synthetic/process-crash/TestPort scope only","no physical power-cut test","no live provider/Drive/OAuth/credential exercise","native browser rendering/bfcache is outside A2 TestPort seam","secret scan is bounded, not universal DLP"],
      "verdict":verdict}
    pathlib.Path(a.output).write_text(json.dumps(receipt,ensure_ascii=False,indent=2,sort_keys=True),encoding="utf-8")
    print(json.dumps({"verdict":verdict,"cases":len(cases),"failed":failed,"fresh_runs":len(fresh_runs),"zero_tolerance_count":len(zero_tolerance),"wheel_sha256":wheel_sha},sort_keys=True))
    return 0 if verdict=="A2-S1 PASS" else 1

if __name__=="__main__": raise SystemExit(main())
