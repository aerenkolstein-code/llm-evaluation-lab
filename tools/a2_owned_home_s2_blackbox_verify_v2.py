#!/usr/bin/env python3
"""Corrected A2-S2 verifier wrapper.

The first final harness incorrectly started the independent wrong-revision probe
at turn_no=2 in a brand-new store/session. This wrapper changes that single A2
harness literal to turn_no=1, then executes the otherwise identical frozen matrix.
No Companion-Mind candidate code or expected behavior is changed.
"""
import os, pathlib
src_path=pathlib.Path(os.environ["GITHUB_WORKSPACE"])/"tools"/"a2_owned_home_s2_blackbox_verify.py"
src=src_path.read_text(encoding="utf-8")
old='cturn(2,"topic-exact-miss",'
new='cturn(1,"topic-exact-miss",'
if src.count(old)!=1:
    raise SystemExit(f"expected exactly one TS2-04 harness literal, found {src.count(old)}")
src=src.replace(old,new,1)
exec(compile(src,str(src_path)+"#v2","exec"),{"__name__":"__main__","__file__":str(src_path)})
