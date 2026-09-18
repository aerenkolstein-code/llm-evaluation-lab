"""EX1 Phase A: local executor implementation; E1F-001 requires separate authority.

Authoring never queries. Replay consumes its identity at the durable STARTED
marker and never retries. In-memory test stores cannot export formal artifacts.
"""
from __future__ import annotations

import argparse
from contextlib import ExitStack, contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from time import perf_counter
from unittest.mock import patch
import uuid

from .contracts import SearchResult, canonical_json, fingerprint
from .protocol_v23 import assert_content_safe, seal, verify_seal
from .tools import BudgetedSearchProxy
from .v23_schema import validate_shape
from . import v23_t5_e1f_execution_readiness as ex0

WORK_ORDER = "WO-ENG-B1-SC-V23-T5-E1F-EX1 v0.1"
MODULE_PATH = "search_cup/v23_t5_e1f_ex1.py"
BASELINE_SHA = "a6eec1fe6971802c72b84b8fbdc0ad40537ade4e"
BASELINE_TREE = "64447897feb5694a13b2c12a4543a803f8f5e2dd"
EX0_PUBLICATION = "e5d52274827210df6d876d6fc83da31acf58991f"
EX0_SOURCE_SHA256 = "ca9b06dc8d1d7ce2c3f6e4c4be0ef9bfa102f66342b83fc34cc2d3880b9660fd"
BINDING = "7d4255fe28d0ee611465f88513d084c3371120d32afbc74d5cf4a3583d9082cb"
RUN_ID = "T5-E1FROZEN-PV-001-EXEC-V1:" + BINDING + ":E1F-001"
PINS = {
    "binding": BINDING,
    "parent": "628a7984fd88a556ebe1ce0cd42939f2f43378775b3fcbc1d4d5819107364cd4",
    "profile_a": "048707e3482dca1deedff648777d026fba7589c7449e3b360e2008bf001296d9",
    "profile_b": "d54b88ad938f22603e43995afe67d1d4041402a6c89d53ebd01281e54d808fa6",
    "policy": "6102aea3d2ce119a69059bbe61641031b72b72c45ba813cc6deecd9219b3f84e",
    "queries": "7f0e1fc370efae4ca2ed9f22405a85e39041cca53f13dd7edd5b1c183064f4df",
    "resources": "bb597e3b93fc710d0f470c322379f98f4b7f8963926333dff5373881cb6a0cab",
    "environment": "e675a47fc2d6d5eaae9a763d28ad21657b6b27b5665b92738579aa55ab4720aa",
    "run": "188c0eedc56703aad5396db54b54364013f345f7523b551d920d3d80a7fd0cc8",
    "integrity": "9e47fbc6daac0357453ff91209a7ff629c86777c0085b6c9d10de1a3679b97ce",
    "receipt": "59c817f6416da3e996043a5cc6000b38ab268738993bf46958be5205494a47d0",
}
ADDED_PATHS = (MODULE_PATH, "tests/test_search_cup_v23_t5_e1f_ex1.py",
    "docs/search-cup-v23-t5-e1f-ex1-offline-replay.md", ".github/workflows/t5-e1f-ex1-offline-replay.yml")
BOUNDARY_PATH = "tests/test_search_cup_v23.py"
CI_FIELDS = ("GITHUB_EVENT_NAME", "GITHUB_REF", "GITHUB_SHA", "GITHUB_RUN_ATTEMPT", "GITHUB_RUN_ID")
EXTERNAL_COUNTS = ("provider_calls", "model_calls", "live_search_calls", "network_calls", "credential_reads",
    "follow_links", "fallback_calls", "judge_calls", "credit_consumption")
ZERO_COUNTS = (*EXTERNAL_COUNTS, "formal_run_output_count", "entrant_calls", "fixture_decision_calls",
    "retriever_query_calls", "proxy_calls", "e1_frozen_runs", "e1_live_runs", "automatic_retries")
READY_FILES = {"preflight": "source-preflight.json", "authority": "retained-ex0-authority.json",
    "plan": "replay-plan.json", "receipt": "run-ready-receipt.json"}
ABSENT_FINGERPRINT = "0" * 64


class GateError(ValueError):
    """Public-safe fixed reason; never copy exception messages into artifacts."""


def _root():
    return Path(__file__).resolve().parents[1]


def _now():
    return datetime.now(timezone.utc).isoformat()


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _identity():
    return {"run_id": RUN_ID, "execution_binding_fingerprint": BINDING,
        "parent_package_fingerprint": ex0.PARENT_PINS["package_fingerprint"]}


def _zero():
    return {**dict.fromkeys(ZERO_COUNTS, 0), "spend": {"value": 0, "unit": "USD"},
        "official_prompt_consumed": False, "hidden_registry_loaded": False,
        "reference_labels_exposed_to_fixture": False}


def scope_gate(changes, before_boundary, after_boundary):
    expected = sorted(["A\t" + p for p in ADDED_PATHS] + ["M\t" + BOUNDARY_PATH])
    old = 'is_je1 = path.name == "v23_t4_je1.py"'
    new = 'is_je1 = path.name in {"v23_t4_je1.py", "v23_t5_e1f_ex1.py"}'
    before_comment = "# User-approved JE1 scope amendment: only this executor needs local"
    after_comment = "# User-approved JE1/EX1 scope: these local executors need only"
    if (sorted(changes) != expected or before_boundary.count(old) != 1
            or before_boundary.replace(old, new).replace(before_comment, after_comment) != after_boundary):
        raise GateError("SCOPE_AMENDMENT_REQUIRED")
    return {"added_paths": sorted(ADDED_PATHS), "modified_paths": [BOUNDARY_PATH],
            "boundary_amendment": "EX1_ADDED_TO_EXISTING_LOCAL_EXECUTOR_EXCEPTION_ONLY"}


def _source_snapshot():
    """Only fixed read-only Git operations and five named non-secret fields."""
    def git(*args, optional=False):
        r = subprocess.run(["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-C", str(_root()), *args],
            text=True, capture_output=True, timeout=10, env={"PATH": "/usr/local/bin:/usr/bin:/bin", "LC_ALL": "C",
                "GIT_CONFIG_NOSYSTEM": "1", "GIT_CONFIG_GLOBAL": "/dev/null", "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"})
        if r.returncode and not optional:
            raise GateError("SOURCE_UNAVAILABLE")
        return r.stdout.strip() if r.returncode == 0 else None
    head = git("rev-parse", "HEAD")
    return {"head": head, "tree": git("rev-parse", "HEAD^{tree}"), "object_tree": git("rev-parse", head + "^{tree}"),
        "branch": git("symbolic-ref", "-q", "HEAD", optional=True),
        "origin_main": git("rev-parse", "refs/remotes/origin/main", optional=True),
        "clean": git("status", "--porcelain=v1", "--untracked-files=all") == "",
        "publication_ancestor": git("merge-base", "--is-ancestor", EX0_PUBLICATION, head, optional=True) is not None,
        "construction_ancestor": git("merge-base", "--is-ancestor", BASELINE_SHA, head, optional=True) is not None,
        "implementation_sha256": _hash((_root() / MODULE_PATH).read_bytes()),
        "boundary_sha256": _hash((_root() / BOUNDARY_PATH).read_bytes()),
        "ci": {key: os.environ.get(key) for key in CI_FIELDS}}


def _source_gate(source, expected_sha, *, formal=True):
    if not re.fullmatch(r"[0-9a-f]{40}", expected_sha or "") or source.get("head") != expected_sha:
        raise GateError("SOURCE_SHA_MISMATCH")
    if not re.fullmatch(r"[0-9a-f]{40}", source.get("tree", "")) or source["tree"] != source.get("object_tree"):
        raise GateError("SOURCE_TREE_MISMATCH")
    if source.get("clean") is not True:
        raise GateError("DIRTY_SOURCE")
    if not source.get("publication_ancestor") or not source.get("construction_ancestor"):
        raise GateError("BASELINE_DRIFT")
    if not formal:
        return
    if source.get("branch") != "refs/heads/main" or source.get("origin_main") != expected_sha:
        raise GateError("MAIN_ONLY")
    ci = source.get("ci", {})
    if set(ci) != set(CI_FIELDS):
        raise GateError("CI_CONTEXT_INCOMPLETE")
    if any(v is not None for v in ci.values()):
        if (ci["GITHUB_EVENT_NAME"] != "workflow_dispatch" or ci["GITHUB_REF"] != "refs/heads/main"
                or ci["GITHUB_SHA"] != expected_sha or not ci["GITHUB_RUN_ID"]):
            raise GateError("FORMAL_CI_CONTEXT_MISMATCH")
        if ci["GITHUB_RUN_ATTEMPT"] != "1":
            raise GateError("FORMAL_RERUN_FORBIDDEN")


def _frozen_bundle(expected_binding):
    if expected_binding != BINDING:
        raise GateError("EX0_BINDING_MISMATCH")
    if _hash((_root() / ex0.MODULE_PATH).read_bytes()) != EX0_SOURCE_SHA256:
        raise GateError("EX0_IMPLEMENTATION_DRIFT")
    b = ex0.build_bundle()
    ex0.validate_bundle(b, expected_fingerprint=BINDING)
    _verify_retained(b)
    return b


def _verify_retained(b):
    if set(b) != set(PINS):
        raise GateError("EX0_PACKAGE_SHAPE")
    for key, digest in PINS.items():
        verify_seal(b[key])
        if b[key]["canonical_fingerprint"] != digest:
            raise GateError("EX0_COMPONENT_DRIFT")
    if b["parent"]["exact_pins"] != ex0.PARENT_PINS or b["receipt"]["planned_run_namespace"] != RUN_ID:
        raise GateError("PARENT_OR_RUN_DRIFT")


def _pins(b):
    names = {"execution_binding": "binding", "profile_a": "profile_a", "profile_b": "profile_b", "decision_policy": "policy",
        "query_plan": "queries", "resource_plan": "resources", "environment_recheck": "environment", "future_run_plan": "run", "integrity_plan": "integrity"}
    return {**{"parent_" + k: v for k, v in b["parent"]["exact_pins"].items()},
            **{name: b[key]["canonical_fingerprint"] for name, key in names.items()}}


def _failure(code):
    return seal({"work_order": WORK_ORDER, **_identity(), "terminal_status": "PRESTART_NOT_EVALUABLE", "reason_code": code,
        "formal_execution_allowed": False, "formal_execution_performed": False, "formal_e1_execution_performed": False,
        "run_identity_consumed": False, **_zero(), "independent_acceptance": "PENDING", "merge_authorized": False})


def preflight(expected_binding=BINDING):
    try:
        b = _frozen_bundle(expected_binding)
        source = _source_snapshot()
        _source_gate(source, source["head"], formal=False)
        return seal({"work_order": WORK_ORDER, "phase": "A_RUN_READY", "terminal_status": "PASS", **_identity(),
            "source": source, "construction_base": {"sha": BASELINE_SHA, "tree": BASELINE_TREE}, "pins": _pins(b),
            "formal_execution_allowed": False, "formal_execution_performed": False, "formal_e1_execution_performed": False,
            "I1_I10": {f"I{i}": "NOT_RUN" for i in range(1, 11)}, **_zero(), "independent_acceptance": "PENDING",
            "merge_authorized": False, "phase_b_execution_authorized": False, "claims_ceiling": ex0.CLAIMS_CEILING})
    except Exception as error:
        return _failure(str(error) if isinstance(error, GateError) else "PREFLIGHT_CHECK_FAILED")


def plan(expected_binding=BINDING):
    b = _frozen_bundle(expected_binding)
    return seal({"work_order": WORK_ORDER, **_identity(), "frozen_ex0_plan": b["run"],
        "frozen_ex0_integrity": b["integrity"], "formal_execution_allowed": False, "formal_execution_performed": False,
        "hard_locks": ["AUTHORITY_RECEIPT", "EXACT_BINDING", "EXACT_RUN_ID", "MAIN_ONLY", "CLEAN_EXACT_SOURCE", "RUNTIME", "RUN_ATTEMPT_1", "NEW_OUTPUT", "UNUSED_LOCAL_LEDGER"],
        "token_accounting": "MODEL_TOKEN_CONSUMPTION: zero for deterministic fixtures with no model/provider; text characters are not relabeled model tokens.",
        "integrity_commitment": "fingerprint of run_id/check-ID-to-status/comparable_status; evidence graph is separately sealed in integrity-checks.json to avoid post-receipt hash cycles",
        "journal": "Append-only local sidecar; submission rows are copied verbatim into final barrier audit. On partial failure retain a sidecar copy with actual files.",
        "one_shot_scope": "Exclusive local journal in output parent; CI attempt1 lock. Cross-runner/new-dispatch one-shot consumption additionally belongs to the explicit external governance receipt.",
        "preflight_reference_scope": "EX0 authoring verification occurs before formal context creation. Only the gated late loader supplies reference content to formal adjudication."})


def write_ready(output_dir, expected_binding=BINDING):
    out = _new_output(output_dir)
    p = preflight(expected_binding)
    if p["terminal_status"] != "PASS":
        return p
    parts = {"preflight": p, "plan": plan(expected_binding), "authority": seal({"retained_pins": PINS,
        "publication": EX0_PUBLICATION, "artifact_id": 10547078775,
        "artifact_digest": "sha256:76ff6a7272b4796c8d30a2d4f66ef58b93c23ad8a4c5057ef775d823655807c0"})}
    package = fingerprint({READY_FILES[k]: v["canonical_fingerprint"] for k, v in parts.items()})
    parts["receipt"] = seal({**p, "run_ready_package_fingerprint": package, "source_preflight_fingerprint": p["canonical_fingerprint"],
        "component_fingerprints": {READY_FILES[k]: v["canonical_fingerprint"] for k, v in parts.items()},
        "approval": "WO-ENG-B1-SC-V23-T5-E1F-EX1 v0.1批准并施工", "approval_scope": "PHASE_A_FIVE_PATHS_ONLY"})
    out.mkdir()
    for key, name in READY_FILES.items():
        (out / name).write_text(canonical_json(parts[key]), encoding="utf-8")
    ex0.parent.write_manifest(out)
    return parts["receipt"]


def _new_output(value):
    path = Path(value).absolute()
    if path.exists() or path.is_symlink():
        raise GateError("OUTPUT_DIRECTORY_REUSED")
    if not path.parent.is_dir() or path.parent.resolve().is_relative_to(_root().resolve()):
        raise GateError("OUTPUT_MUST_BE_NEW_OUTSIDE_SOURCE")
    return path


class _DiskStore:
    """Durable single writer. Sidecar is a local one-shot ledger, never a secret."""
    is_formal = True

    @staticmethod
    def ledger_path(root):
        return root.parent / (".t5-e1f-" + _hash(RUN_ID.encode()) + ".journal.jsonl")

    def __init__(self, root):
        self.root = root
        self.ledger = self.ledger_path(root)
        # Exclusive creation also stops two simultaneous attempts in one store.
        with self.ledger.open("xb") as f:
            f.flush()
            os.fsync(f.fileno())
        self._sync(root.parent)
        root.mkdir(exist_ok=False)
        self._sync(root.parent)

    @staticmethod
    def _sync(path):
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def write(self, name, data):
        if Path(name).name != name or name.startswith("."):
            raise GateError("ARTIFACT_NAME_INVALID")
        target = self.root / name
        if target.exists() or target.is_symlink():
            raise GateError("ARTIFACT_OVERWRITE_FORBIDDEN")
        temporary = self.root / ("." + name + ".tmp-" + uuid.uuid4().hex)
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        self._sync(self.root)

    def append(self, name, data):
        if name not in {"query-provenance.jsonl", "result-provenance.jsonl"}:
            raise GateError("APPEND_TARGET_FORBIDDEN")
        with (self.root / name).open("ab") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        self._sync(self.root)

    def journal(self, record):
        with self.ledger.open("ab") as stream:
            stream.write((canonical_json(record) + "\n").encode())
            stream.flush()
            os.fsync(stream.fileno())
        self._sync(self.root.parent)

    def journal_records(self):
        return [json.loads(line) for line in self.ledger.read_bytes().splitlines()]

    def preserve_partial_journal(self):
        if not self.exists("partial-durable-journal.jsonl"):
            self.write("partial-durable-journal.jsonl", self.ledger.read_bytes())

    def exists(self, name):
        return (self.root / name).exists()

    def read(self, name):
        return (self.root / name).read_bytes()

    def names(self):
        return sorted(p.name for p in self.root.iterdir() if p.is_file())


def _manifest(store):
    data = "".join(_hash(store.read(n)) + "  " + n + "\n" for n in store.names() if n != "MANIFEST.sha256")
    store.write("MANIFEST.sha256", data.encode())


def _shape(value, schema):
    """Reuse protocol validator; add its currently absent upper-bound checks."""
    validate_shape(value, schema)
    def upper(v, s):
        if isinstance(v, list):
            if len(v) > s.get("maxItems", len(v)):
                raise GateError("SCHEMA_MAX_ITEMS")
            for item in v:
                upper(item, s.get("items", {}))
        elif isinstance(v, dict):
            for k, item in v.items():
                upper(item, s.get("properties", {}).get(k, {}))
        elif type(v) in (int, float) and v > s.get("maximum", v):
            raise GateError("SCHEMA_MAXIMUM")
    upper(value, schema)


def _record(b, name, **fields):
    value = seal({**_identity(), **fields})
    _shape(value, b["run"]["future_output_contracts"]["schemas"][name])
    return value


def _write(store, name, value):
    store.write(name, canonical_json(value).encode())


@contextmanager
def _capabilities(counts, *, fixture=False):
    """Pinned trusted code and traps; not a sandbox for arbitrary Python."""
    def deny(counter):
        def fail(*args, **kwargs):
            counts[counter] += 1
            raise GateError("FORBIDDEN_CAPABILITY")
        return fail
    class NoEnvironment:
        get = __getitem__ = __iter__ = __len__ = __contains__ = keys = values = items = copy = deny("credential_reads")
    with ExitStack() as stack:
        for target in ex0.parent.qualification.GUARDED_TARGETS:
            counter = "credential_reads" if target == "os.getenv" else "judge_calls" if ".judge." in target else "live_search_calls" if ".search_pro." in target else "network_calls"
            stack.enter_context(patch(target, side_effect=deny(counter)))
        for target in ex0.FIXTURE_GUARDS:
            stack.enter_context(patch(target, side_effect=deny("provider_calls")))
        stack.enter_context(patch("os.environ", NoEnvironment()))
        if fixture:
            for target in ("builtins.open", "pathlib.Path.open", "pathlib.Path.read_text", "pathlib.Path.read_bytes", "os.open"):
                stack.enter_context(patch(target, side_effect=deny("credential_reads")))
        yield


def _decision(record, counts):
    if type(record) is not SearchResult:
        raise GateError("VISIBLE_INPUT_ONLY")
    with _capabilities(counts, fixture=True):
        counts["fixture_decision_calls"] += 1
        result = ex0.visible_decision(record)
    if any(counts[k] for k in EXTERNAL_COUNTS):
        raise GateError("CAPABILITY_TRAP_OBSERVED")
    return result


def _visible_backend():
    # Reference file is deliberately absent from this formal-context constructor.
    data = json.loads((_root() / ex0.parent.CORPUS_PATH).read_bytes())
    cfg = json.loads((_root() / ex0.parent.nfr.CONFIG_PATH).read_bytes())
    corpus = ex0.parent.nfr.FrozenCorpus(data["documents"], expected_fingerprint=ex0.PARENT_PINS["corpus_fingerprint"])
    config = ex0.parent.nfr.FrozenConfig(cfg)
    ex0.parent.reproduce_index(corpus, config, expected_corpus=ex0.PARENT_PINS["corpus_fingerprint"], expected_index=ex0.PARENT_PINS["index_fingerprint"])
    backend = ex0.parent.nfr.FrozenLexicalRetriever(corpus, config)
    visible = {d.url: {"doc_id": d.doc_id, "result": SearchResult(d.title, d.url, d.text[:240])} for d in corpus.documents}
    return backend, visible


def _load_reference():
    raw = (_root() / ex0.parent.REFERENCE_PATH).read_bytes()
    if _hash(raw) != ex0.SOURCE_PINS[ex0.parent.REFERENCE_PATH]:
        raise GateError("REFERENCE_BYTES_DRIFT")
    reference = seal(json.loads(raw))
    if reference["canonical_fingerprint"] != ex0.PARENT_PINS["reference_set_fingerprint"]:
        raise GateError("REFERENCE_SEAL_DRIFT")
    return {row["doc_id"]: row["label"] for row in reference["labels"]}


def _resource(b, alias, proxy, elapsed):
    return seal({
        "entrant_id": alias, "run_id": RUN_ID, "execution_binding_fingerprint": BINDING,
        "proxy_instance_id": RUN_ID + ":" + alias + ":proxy:" + str(id(proxy)),
        "query_attempts": proxy.calls_used, "search_turns": proxy.calls_used, "results_per_call_limit": 10,
        "automatic_retries": 0, "follow_links": 0, "fallback_calls": 0, "provider_calls": 0, "model_calls": 0,
        "elapsed_ms": elapsed, "token_count": 0, "token_accounting_basis": "NO_MODEL_OR_PROVIDER_TOKEN_CONSUMPTION_DETERMINISTIC_FIXTURE",
        "spend_usd": 0, "terminal_status": "PASS"})


def _resource_check(receipt, envelope):
    if (receipt["query_attempts"] != envelope["max_search_calls"] or receipt["search_turns"] != envelope["max_search_turns"]
            or receipt["elapsed_ms"] > envelope["max_total_runtime_ms"]["value"]
            or receipt["token_count"] > envelope["token_ceiling"]["value"] or receipt["spend_usd"] != 0):
        raise GateError("RESOURCE_ENVELOPE_EXCEEDED")


def _json_records(store, name):
    data = store.read(name)
    return [json.loads(line) for line in data.splitlines()] if name.endswith(".jsonl") else json.loads(data)


def _run_entrant(b, profile, proxy, visible, store, counts, deliveries):
    alias = profile["entrant_id"]
    if proxy.calls_used or proxy.traces or proxy._entrant_id != alias:
        raise GateError("FRESH_ISOLATED_PROXY_REQUIRED")
    counts["entrant_calls"] += 1
    begun = perf_counter()
    query_rows, result_rows, seen, selected = [], [], {}, []
    envelope = b["resources"]["identical_envelope"]
    for step in profile["query_schedule"]:
        number, query = step["query_number"], step["query"]
        counts["proxy_calls"] += 1
        failed = False
        try:
            with _capabilities(counts, fixture=True):
                results = proxy.search(query)
        except Exception:
            failed = True
            results = ()
        if proxy.calls_used != number:
            raise GateError("PROXY_TRACE_MISSING")
        trace = proxy.traces[-1]
        counts["retriever_query_calls"] += 1
        error = trace.error_code if re.fullmatch(r"[A-Z0-9_]{1,64}", trace.error_code or "") else "BACKEND_FAILURE" if failed else None
        q = _record(b, "query-provenance.jsonl", entrant_id=alias, query_number=number, query=query,
            call_id=alias + ":q" + str(number), request_id=trace.backend_request_id, backend_id=trace.backend_id,
            backend_attempts=1, started_at_utc=trace.started_at_utc, duration_ms=trace.duration_ms,
            terminal_status="ERROR" if failed else "PASS", error_code=error)
        store.append("query-provenance.jsonl", (canonical_json(q) + "\n").encode())
        query_rows.append(q)
        if failed:
            raise GateError("PLANNED_QUERY_FAILED_NO_RETRY")
        if any(counts[k] for k in EXTERNAL_COUNTS):
            raise GateError("CAPABILITY_TRAP_OBSERVED")
        if (trace.duration_ms > envelope["timeout_per_call_ms"] or len(results) > envelope["max_results_per_call"]
                or (perf_counter() - begun) * 1000 > envelope["max_total_runtime_ms"]["value"]):
            raise GateError("RESOURCE_ENVELOPE_EXCEEDED")
        for rank, result in enumerate(results, 1):
            if type(result) is not SearchResult or result.url not in visible or visible[result.url]["result"] != result:
                raise GateError("FROZEN_VISIBLE_RESULT_MISMATCH")
            doc_id = visible[result.url]["doc_id"]
            row = _record(b, "result-provenance.jsonl", entrant_id=alias, call_id=q["call_id"], request_id=q["request_id"],
                backend_id=q["backend_id"], rank=rank, doc_id=doc_id,
                visible_result={"title": result.title, "url": result.url, "snippet": result.snippet})
            store.append("result-provenance.jsonl", (canonical_json(row) + "\n").encode())
            result_rows.append(row)
            if doc_id in seen:
                if seen[doc_id] != result:
                    raise GateError("CONFLICTING_FROZEN_IDENTITY")
                continue
            seen[doc_id] = result
            # The actual decision invocation gets only this single SearchResult.
            deliveries.append({"entrant_id": alias, "visible_result": row["visible_result"], "doc_id": doc_id})
            decision = _decision(result, counts)
            if decision["decision"] == "RETURN_AS_MATCH":
                selected.append({"doc_id": doc_id, "evidence_locator": result.url + "#text",
                                 "corpus_fingerprint": ex0.PARENT_PINS["corpus_fingerprint"]})
    elapsed = round((perf_counter() - begun) * 1000, 3)
    receipt = _resource(b, alias, proxy, elapsed)
    _resource_check(receipt, envelope)
    schema = b["run"]["parent_output_contract"]["json_schema"]
    submission = {"entrant_identity": profile["parent_identity"], "spec_fingerprint": ex0.PARENT_PINS["spec_fingerprint"],
        "environment_fingerprint": schema["properties"]["environment_fingerprint"]["const"],
        "retriever_fingerprint": schema["properties"]["retriever_fingerprint"]["const"],
        "resource_receipt_fingerprint": fingerprint(receipt),
        "query_call_provenance": [{"entrant_id": alias, "call_id": r["call_id"], "request_id": r["request_id"],
            "original_query": r["query"], "backend_id": r["backend_id"], "backend_attempts": r["backend_attempts"],
            "terminal_status": r["terminal_status"]} for r in query_rows],
        "result_provenance": [{"call_id": r["call_id"], "request_id": r["request_id"], "backend_id": r["backend_id"],
            "rank": r["rank"], "doc_id": r["doc_id"], "url": r["visible_result"]["url"]} for r in result_rows],
        "results": selected, "terminal_status": "PASS"}
    submission["submission_fingerprint"] = fingerprint(submission)
    _shape(submission, schema)
    name = "entrant-a-output.json" if alias == ex0.ALIASES[0] else "entrant-b-output.json"
    return _record(b, name, entrant_id=alias, submission=submission, resource_receipt=receipt)


def _commit_submission(store, name, output):
    _write(store, name, output)
    data = store.read(name)
    if data != canonical_json(output).encode():
        raise GateError("DURABLE_OUTPUT_READBACK_MISMATCH")
    records = store.journal_records()
    commits = [r for r in records if "submission_fingerprint" in r]
    start = _json_records(store, "run-start.json")
    previous = commits[-1]["journal_record_fingerprint"] if commits else start["canonical_fingerprint"]
    row = {"entrant_id": output["entrant_id"], "run_id": RUN_ID,
        "submission_fingerprint": output["submission"]["submission_fingerprint"], "output_file": name,
        "output_sha256": _hash(data), "commit_sequence": len(commits) + 1,
        "file_fsync": True, "directory_fsync": True}
    row["journal_record_fingerprint"] = fingerprint({"previous": previous, **row})
    store.journal(row)
    return row


def _validated_commits(store):
    records = store.journal_records()
    commits = [r for r in records if "submission_fingerprint" in r]
    if len(commits) != 2 or [r["entrant_id"] for r in commits] != list(ex0.ALIASES):
        raise GateError("REFERENCE_BARRIER_CLOSED")
    previous = _json_records(store, "run-start.json")["canonical_fingerprint"]
    for i, row in enumerate(commits, 1):
        data = store.read(row["output_file"])
        doc = json.loads(data)
        content = {k: v for k, v in row.items() if k != "journal_record_fingerprint"}
        if (row["run_id"] != RUN_ID or row["commit_sequence"] != i or not row["file_fsync"] or not row["directory_fsync"]
                or _hash(data) != row["output_sha256"] or doc["entrant_id"] != row["entrant_id"]
                or row["submission_fingerprint"] != doc["submission"]["submission_fingerprint"]
                or fingerprint({"previous": previous, **content}) != row["journal_record_fingerprint"]):
            raise GateError("DURABLE_COMMIT_CHAIN_INVALID")
        verify_seal(doc)
        previous = row["journal_record_fingerprint"]
    return commits


def _reference_after_commits(store, b, loader):
    commits = _validated_commits(store)
    if any(r.get("event") == "REFERENCE_LOAD" for r in store.journal_records()):
        raise GateError("REFERENCE_ALREADY_LOADED")
    store.journal(seal({"event": "REFERENCE_LOAD", "run_id": RUN_ID, "sequence": 3,
                        "after_commit_fingerprint": commits[-1]["journal_record_fingerprint"]}))
    labels = loader()
    if not labels or any(label not in {"RELEVANT", "NOT_RELEVANT", "UNKNOWN"} for label in labels.values()):
        raise GateError("REFERENCE_LABEL_INVALID")
    audit = _record(b, "hidden-reference-barrier-audit.json", submission_commits=commits, reference_load_sequence=3,
        reference_set_fingerprint=ex0.PARENT_PINS["reference_set_fingerprint"],
        reference_labels_exposed_to_fixture=False, cross_entrant_access_count=0)
    _write(store, "hidden-reference-barrier-audit.json", audit)
    return labels


def _metric_values(submissions, labels):
    """The three published T5 equations; UNKNOWN never becomes a negative."""
    result = []
    for output in submissions:
        values = [labels[row["doc_id"]] for row in output["submission"]["results"]]
        first = values[:10]
        parts = (("Recall@Budget", values.count("RELEVANT"), list(labels.values()).count("RELEVANT")),
                 ("Precision@K", first.count("RELEVANT"), len(first) - first.count("UNKNOWN")),
                 ("UNKNOWN_RETURN_COUNT", values.count("UNKNOWN"), 1))
        result.append({"entrant_id": output["entrant_id"], "values": [
            {"metric_id": name, "numerator": numerator, "denominator": denominator,
             "terminal_status": "PASS" if denominator else "NOT_EVALUABLE",
             "value": numerator / denominator if denominator else None} for name, numerator, denominator in parts]})
    return result


def _conditions(b, records, source, end_source, counts, deliveries, commits):
    """Compute every gate from actual observations, not a preassigned PASS map."""
    q = records.get("query-provenance.jsonl", [])
    rows = records.get("result-provenance.jsonl", [])
    outs = [records.get(name, {}) for name in ("entrant-a-output.json", "entrant-b-output.json")]
    receipts = records.get("resource-receipts.json", {}).get("receipts", [])
    start, end = records.get("run-start.json", {}), records.get("run-end.json", {})
    post = records.get("post-run-receipt.json", {})
    def parent():
        _verify_retained(b)
        p = records["preflight.json"]
        return p["retained_pins"] == _pins(b) == start["frozen_pins"] and (p["main_sha"], p["main_tree"]) == (source["head"], source["tree"])
    def runtime():
        expected = {"python_major_minor": "3.11", "unicode_data_version": "14.0.0"}
        return records["preflight.json"]["runtime"] == ex0.parent.qualification.runtime_identity() == expected and bool(q) and all(r["backend_id"] == ex0.parent.nfr.BACKEND_ID for r in q)
    def budgets():
        if len(receipts) != 2 or len({r["proxy_instance_id"] for r in receipts}) != 2 or [r["entrant_id"] for r in receipts] != list(ex0.ALIASES):
            return False
        for r in receipts:
            verify_seal(r)
            _resource_check(r, b["resources"]["identical_envelope"])
            if any(r[k] != 0 for k in ("automatic_retries", "follow_links", "fallback_calls", "provider_calls", "model_calls")):
                return False
        return len(q) == 8 and len(rows) <= 80 and all(r["duration_ms"] <= 1000 and r["backend_attempts"] == 1 for r in q)
    def behavior():
        expected = [(p["entrant_id"], item["query_number"], item["query"]) for p in b["queries"]["profiles"] for item in p["queries"]]
        return [(r["entrant_id"], r["query_number"], r["query"]) for r in q] == expected and all(r["terminal_status"] == "PASS" for r in q)
    def barrier():
        a = records["hidden-reference-barrier-audit.json"]
        return (a["submission_commits"] == commits and len(commits) == 2
            and a["reference_load_sequence"] == 3 and not a["reference_labels_exposed_to_fixture"] and a["cross_entrant_access_count"] == 0)
    def isolation():
        expected = []
        seen = set()
        for row in rows:
            key = (row["entrant_id"], row["doc_id"])
            if key not in seen:
                expected.append({"entrant_id": row["entrant_id"], "doc_id": row["doc_id"], "visible_result": row["visible_result"]})
                seen.add(key)
        return bool(deliveries) and deliveries == expected and len({r["proxy_instance_id"] for r in receipts}) == 2
    def provenance():
        schema_map = b["run"]["future_output_contracts"]["schemas"]
        for name, data in records.items():
            if name not in schema_map:
                continue
            for item in data if name.endswith(".jsonl") else [data]:
                _shape(item, schema_map[name])
                verify_seal(item)
                if any(item[k] != v for k, v in _identity().items()):
                    return False
        by_call = {r["call_id"]: r for r in q}
        if len(by_call) != len(q) or len({r["request_id"] for r in q}) != len(q):
            return False
        seen_ranks = set()
        for r in rows:
            call = by_call[r["call_id"]]
            rank_key = (r["call_id"], r["rank"])
            if rank_key in seen_ranks or any(r[k] != call[k] for k in ("entrant_id", "request_id", "backend_id")):
                return False
            seen_ranks.add(rank_key)
        for alias, output, resource in zip(ex0.ALIASES, outs, receipts):
            s = output["submission"]
            own_q = [r for r in q if r["entrant_id"] == alias]
            own_r = [r for r in rows if r["entrant_id"] == alias]
            if output["entrant_id"] != alias or s["entrant_identity"]["entrant_id"] != alias or output["resource_receipt"] != resource:
                return False
            if s["submission_fingerprint"] != fingerprint({k: v for k, v in s.items() if k != "submission_fingerprint"}) or s["resource_receipt_fingerprint"] != fingerprint(resource):
                return False
            if s["spec_fingerprint"] != ex0.PARENT_PINS["spec_fingerprint"] or len(s["query_call_provenance"]) != len(own_q) or len(s["result_provenance"]) != len(own_r):
                return False
            for short, actual in zip(s["query_call_provenance"], own_q):
                if short != {"entrant_id": alias, "call_id": actual["call_id"], "request_id": actual["request_id"], "original_query": actual["query"],
                    "backend_id": actual["backend_id"], "terminal_status": actual["terminal_status"], "backend_attempts": actual["backend_attempts"]}:
                    return False
            for short, actual in zip(s["result_provenance"], own_r):
                if short != {**{k: actual[k] for k in ("call_id", "request_id", "backend_id", "rank", "doc_id")}, "url": actual["visible_result"]["url"]}:
                    return False
            if len({r["doc_id"] for r in s["results"]}) != len(s["results"]):
                return False
            for r in s["results"]:
                if not any(row["doc_id"] == r["doc_id"] and row["visible_result"]["url"] + "#text" == r["evidence_locator"] for row in own_r):
                    return False
        return True
    def semantics():
        for alias, output in zip(ex0.ALIASES, outs):
            seen, selected = {}, []
            for row in rows:
                if row["entrant_id"] != alias:
                    continue
                doc = row["doc_id"]
                value = row["visible_result"]
                if doc in seen:
                    if seen[doc] != value:
                        return False
                    continue
                seen[doc] = value
                if _decision(SearchResult(**value), counts)["decision"] == "RETURN_AS_MATCH":
                    selected.append(doc)
            if selected != [r["doc_id"] for r in output["submission"]["results"]]:
                return False
        return True
    def external():
        return (all(counts[k] == 0 for k in EXTERNAL_COUNTS)
            and post["external_counts"] == {k: 0 for k in EXTERNAL_COUNTS} and post["spend_usd"] == 0
            and all(post[k] is False for k in ("official_prompt_consumed", "hidden_registry_loaded", "reference_labels_exposed_to_fixture")))
    def unchanged():
        return source == end_source and start["frozen_pins"] == end["frozen_pins"] == _pins(b) and end["start_fingerprint"] == start["canonical_fingerprint"]
    result = {}
    for i, check in enumerate((parent, runtime, budgets, behavior, barrier, isolation, provenance, semantics, external, unchanged), 1):
        try:
            result[f"I{i}"] = "PASS" if check() else "FAIL"
        except Exception:
            result[f"I{i}"] = "FAIL"
    return result


def _commitment(statuses, comparable):
    return fingerprint({"run_id": RUN_ID, "checks": statuses, "comparable_status": comparable})


def _evidence(name, data):
    value = [json.loads(line) for line in data.splitlines()] if name.endswith(".jsonl") else json.loads(data)
    digest = fingerprint(value) if isinstance(value, list) else value["canonical_fingerprint"]
    return {"path": name, "file_sha256": _hash(data), "record_fingerprint": digest}


def integrity_comparable(checks, store, b):
    if set(checks) != set(b["integrity"]["checks"]):
        return "NOT_EVALUABLE"
    for name, row in checks.items():
        if row.get("status") != "PASS" or row.get("run_id") != RUN_ID or not row.get("actual_run_evidence"):
            return "NOT_EVALUABLE"
        evidence = row["actual_run_evidence"]
        if {r["path"] for r in evidence} != set(b["integrity"]["checks"][name]["required_evidence_files"]):
            return "NOT_EVALUABLE"
        for ref in evidence:
            try:
                if ref != _evidence(ref["path"], store.read(ref["path"])):
                    return "NOT_EVALUABLE"
            except Exception:
                return "NOT_EVALUABLE"
    return "PASS"


def validate_complete(store, b):
    """A loose receipt or a partly written bundle can never establish PASS."""
    try:
        if set(store.names()) != set(ex0.FORMAL_FILES):
            return "NOT_EVALUABLE"
        expected_manifest = "".join(_hash(store.read(n)) + "  " + n + "\n" for n in store.names() if n != "MANIFEST.sha256")
        if store.read("MANIFEST.sha256") != expected_manifest.encode():
            return "NOT_EVALUABLE"
        records = {}
        for name, schema in b["run"]["future_output_contracts"]["schemas"].items():
            value = _json_records(store, name)
            for row in value if name.endswith(".jsonl") else [value]:
                verify_seal(row)
                _shape(row, schema)
                if any(row[k] != v for k, v in _identity().items()):
                    return "NOT_EVALUABLE"
            records[name] = value
        integrity, post, metrics = (records[n] for n in ("integrity-checks.json", "post-run-receipt.json", "metrics.json"))
        if integrity_comparable(integrity["checks"], store, b) != "PASS":
            return "NOT_EVALUABLE"
        commitment = _commitment({k: r["status"] for k, r in integrity["checks"].items()}, integrity["comparable_status"])
        end = records["run-end.json"]
        if (integrity["comparable_status"] != "PASS" or post["comparable_status"] != "PASS"
                or end["state"] != "COMPLETED" or end["terminal_status"] != "PASS"
                or end["start_fingerprint"] != records["run-start.json"]["canonical_fingerprint"]
                or post["run_end_fingerprint"] != end["canonical_fingerprint"]
                or post["integrity_fingerprint"] != commitment or metrics["integrity_fingerprint"] != commitment
                or metrics["adjudication_fingerprint"] != records["adjudication.json"]["canonical_fingerprint"]
                or any(v["terminal_status"] != "PASS" for r in metrics["entrant_metrics"] for v in r["values"])):
            return "NOT_EVALUABLE"
        _validated_commits(store)
        return "PASS"
    except Exception:
        return "NOT_EVALUABLE"


def _finish_complete(store, b, source, end_source, counts, deliveries, outputs, labels, commits):
    start = _json_records(store, "run-start.json")
    end = _record(b, "run-end.json", state="COMPLETED", ended_at=_now(), start_fingerprint=start["canonical_fingerprint"],
                  frozen_pins=_pins(b), terminal_status="PASS")
    post_fields = {"run_end_fingerprint": end["canonical_fingerprint"], "integrity_fingerprint": ABSENT_FINGERPRINT,
        "formal_execution_performed": store.is_formal, "comparable_status": "NOT_EVALUABLE",
        "external_counts": {k: counts[k] for k in EXTERNAL_COUNTS}, "spend_usd": 0,
        "official_prompt_consumed": False, "hidden_registry_loaded": False, "reference_labels_exposed_to_fixture": False,
        "benchmark_claim": False, "model_quality_claim": False, "live_web_claim": False}
    records = {name: _json_records(store, name) for name in store.names() if name.endswith((".json", ".jsonl"))}
    records.update({"run-end.json": end, "post-run-receipt.json": _record(b, "post-run-receipt.json", **post_fields)})
    statuses = _conditions(b, records, source, end_source, counts, deliveries, commits)
    if any(value != "PASS" for value in statuses.values()):
        store.journal(seal({"event": "HARD_GATE_FAILURE", "run_id": RUN_ID, "checks": statuses}))
        raise GateError("ACTUAL_INTEGRITY_GATE_FAILED")
    metrics = _metric_values(outputs, labels)
    comparable = "PASS" if all(v == "PASS" for v in statuses.values()) and all(v["terminal_status"] == "PASS" for r in metrics for v in r["values"]) else "NOT_EVALUABLE"
    verdict = _commitment(statuses, comparable)
    end = _record(b, "run-end.json", state="COMPLETED", ended_at=end["ended_at"], start_fingerprint=start["canonical_fingerprint"],
                  frozen_pins=_pins(b), terminal_status="PASS" if comparable == "PASS" else "NOT_EVALUABLE")
    post = _record(b, "post-run-receipt.json", **{**post_fields, "run_end_fingerprint": end["canonical_fingerprint"],
        "integrity_fingerprint": verdict, "comparable_status": comparable})
    _write(store, "run-end.json", end)
    metric_record = _record(b, "metrics.json", adjudication_fingerprint=records["adjudication.json"]["canonical_fingerprint"],
        integrity_fingerprint=verdict, entrant_metrics=metrics)
    _write(store, "metrics.json", metric_record)
    # Post receipt's complete bytes are now fixed; verdict commitment has no
    # evidence hashes. This makes the final evidence graph acyclic.
    checks = {name: {"status": statuses[name], "run_id": RUN_ID, "actual_run_evidence": [
        _evidence(path, canonical_json(post).encode() if path == "post-run-receipt.json" else store.read(path))
        for path in rule["required_evidence_files"]]} for name, rule in b["integrity"]["checks"].items()}
    integrity = _record(b, "integrity-checks.json", checks=checks, comparable_status=comparable)
    _write(store, "integrity-checks.json", integrity)
    _write(store, "post-run-receipt.json", post)
    actual = {name: _json_records(store, name) for name in store.names() if name.endswith((".json", ".jsonl"))}
    if _conditions(b, actual, source, end_source, counts, deliveries, _validated_commits(store)) != statuses:
        raise GateError("FINAL_EVIDENCE_CHANGED")
    if comparable == "PASS" and integrity_comparable(checks, store, b) != "PASS":
        raise GateError("UNRESOLVED_HARD_EVIDENCE")
    _manifest(store)
    if comparable == "PASS" and validate_complete(store, b) != "PASS":
        raise GateError("COMPLETE_ARTIFACT_INVALID")
    return {"terminal_status": comparable, "comparable_status": comparable, "run_id": RUN_ID,
        "formal_execution_performed": store.is_formal, "in_memory_simulation": not store.is_formal,
        "integrity_verdict_fingerprint": verdict, "integrity_record_fingerprint": integrity["canonical_fingerprint"],
        "counts": counts, "formal_execution_complete": store.is_formal, "automatic_retries": 0}


def _partial(store, b, counts):
    started = store.exists("run-start.json")
    try:
        if started and not store.exists("run-end.json"):
            start = _json_records(store, "run-start.json")
            end = _record(b, "run-end.json", state="PARTIAL", ended_at=_now(), start_fingerprint=start["canonical_fingerprint"],
                frozen_pins=_pins(b), terminal_status="NOT_EVALUABLE")
            _write(store, "run-end.json", end)
        if started and not store.exists("post-run-receipt.json"):
            end = _json_records(store, "run-end.json")
            post = _record(b, "post-run-receipt.json", run_end_fingerprint=end["canonical_fingerprint"],
                integrity_fingerprint=ABSENT_FINGERPRINT, formal_execution_performed=store.is_formal, comparable_status="NOT_EVALUABLE",
                external_counts={k: counts[k] for k in EXTERNAL_COUNTS}, spend_usd=0, official_prompt_consumed=False,
                hidden_registry_loaded=False, reference_labels_exposed_to_fixture=False, benchmark_claim=False,
                model_quality_claim=False, live_web_claim=False)
            _write(store, "post-run-receipt.json", post)
        store.preserve_partial_journal()
        if not store.exists("MANIFEST.sha256"):
            _manifest(store)
    except Exception:
        pass  # Already committed bytes and the one-shot ledger remain authoritative.
    return {"terminal_status": "NOT_EVALUABLE" if started else "PRESTART_NOT_EVALUABLE", "completion_status": "PARTIAL",
        "run_id": RUN_ID, "formal_execution_performed": bool(started and store.is_formal), "formal_execution_complete": False,
        "run_identity_consumed": bool(started and store.is_formal), "in_memory_simulation": not store.is_formal,
        "reason_code": "PARTIAL_INSPECT_DURABLE_EVIDENCE_NO_RETRY", "counts": counts, "automatic_retries": 0}


def _execute(store, b, source, authority, proxies, visible, reference_loader, end_probe):
    """Internal engine. Production can reach it only after replay's PRESTART gates."""
    counts, deliveries, outputs = _zero(), [], []
    if len(proxies) != 2 or id(proxies[0]) == id(proxies[1]) or any(p.calls_used for p in proxies):
        raise GateError("FRESH_ISOLATED_PROXY_REQUIRED")
    if not store.is_formal and any(type(p._backend) is ex0.parent.nfr.FrozenLexicalRetriever for p in proxies):
        raise GateError("SIMULATION_CANNOT_QUERY_PUBLISHED_RETRIEVER")
    if store.is_formal:
        # No caller-supplied source dictionary can unlock a production engine.
        observed = _source_snapshot()
        _source_gate(observed, source["head"])
        if observed != source or not authority:
            raise GateError("FORMAL_SOURCE_OR_AUTHORITY_CHANGED")
    try:
        pre = _record(b, "preflight.json", main_sha=source["head"], main_tree=source["tree"], authority_receipt_id=authority,
            runtime=ex0.parent.qualification.runtime_identity(), retained_pins=_pins(b), terminal_status="PASS")
        _write(store, "preflight.json", pre)
        # Empty streams are actual initialized logs, not invented query records.
        store.write("query-provenance.jsonl", b"")
        store.write("result-provenance.jsonl", b"")
        start = _record(b, "run-start.json", state="STARTED", started_at=_now(), frozen_pins=_pins(b))
        _write(store, "run-start.json", start)
        counts["e1_frozen_runs"] = int(store.is_formal)
        store.journal(seal({"event": "STARTED", "run_id": RUN_ID, "start_fingerprint": start["canonical_fingerprint"]}))
        for key, proxy, name in zip(("profile_a", "profile_b"), proxies, ("entrant-a-output.json", "entrant-b-output.json")):
            out = _run_entrant(b, b[key], proxy, visible, store, counts, deliveries)
            _commit_submission(store, name, out)
            counts["formal_run_output_count"] += int(store.is_formal)
            outputs.append(out)
        receipts = _record(b, "resource-receipts.json", receipts=[o["resource_receipt"] for o in outputs])
        _write(store, "resource-receipts.json", receipts)
        labels = _reference_after_commits(store, b, reference_loader)
        adjudication = _record(b, "adjudication.json", reference_set_fingerprint=ex0.PARENT_PINS["reference_set_fingerprint"],
            barrier_audit_fingerprint=_json_records(store, "hidden-reference-barrier-audit.json")["canonical_fingerprint"],
            entrant_decisions=[{"entrant_id": out["entrant_id"], "submission_fingerprint": out["submission"]["submission_fingerprint"],
                "labels": [{"doc_id": r["doc_id"], "label": labels[r["doc_id"]]} for r in out["submission"]["results"]]} for out in outputs])
        _write(store, "adjudication.json", adjudication)
        end_source, end_bundle = end_probe()
        if canonical_json(b) != canonical_json(end_bundle):
            raise GateError("FROZEN_PACKAGE_MUTATED_AFTER_START")
        return _finish_complete(store, b, source, end_source, counts, deliveries, outputs, labels, _validated_commits(store))
    except Exception:
        return _partial(store, b, counts)


def replay(*, authority_receipt_id, expected_main_sha, expected_binding, run_id, output_dir):
    """Implemented for separately approved Phase B; Phase A never calls it successfully."""
    try:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{2,199}", authority_receipt_id or ""):
            raise GateError("AUTHORITY_RECEIPT_REQUIRED")
        assert_content_safe(authority_receipt_id)
        if run_id != RUN_ID:
            raise GateError("EXACT_RUN_ID_REQUIRED")
        b = _frozen_bundle(expected_binding)
        source = _source_snapshot()
        _source_gate(source, expected_main_sha)
        path = _new_output(output_dir)
        if _DiskStore.ledger_path(path).exists():
            raise GateError("LOCAL_RUN_ID_ALREADY_CLAIMED")
        with ex0.authoring_guard():
            backend, visible = _visible_backend()
            proxies = [BudgetedSearchProxy(alias, 4, backend) for alias in ex0.ALIASES]
        if any(p.calls_used or p.traces for p in proxies):
            raise GateError("PROXY_NOT_FRESH")
    except Exception as error:
        return _failure(str(error) if isinstance(error, GateError) else "PRESTART_CHECK_FAILED")
    store = None
    try:
        store = _DiskStore(path)
        return _execute(store, b, source, authority_receipt_id, proxies, visible, _load_reference,
            lambda: (_source_snapshot(), _frozen_bundle(BINDING)))
    except Exception:
        return _partial(store, b, _zero()) if store is not None else _failure("PRESTART_STORE_UNAVAILABLE")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    for name in ("preflight", "plan", "run-ready", "replay"):
        sub = subs.add_parser(name)
        sub.add_argument("--expected-binding", required=True)
        if name in {"run-ready", "replay"}:
            sub.add_argument("--output-dir", required=True, type=Path)
        if name == "replay":
            sub.add_argument("--authority-receipt", required=True)
            sub.add_argument("--expected-main-sha", required=True)
            sub.add_argument("--run-id", required=True)
    a = parser.parse_args(argv)
    try:
        if a.command == "replay":
            result = replay(authority_receipt_id=a.authority_receipt, expected_main_sha=a.expected_main_sha,
                expected_binding=a.expected_binding, run_id=a.run_id, output_dir=a.output_dir)
        elif a.command == "run-ready":
            result = write_ready(a.output_dir, a.expected_binding)
        else:
            result = preflight(a.expected_binding) if a.command == "preflight" else plan(a.expected_binding)
    except Exception as error:
        result = _failure(str(error) if isinstance(error, GateError) else "COMMAND_FAILED")
    print(canonical_json(result))
    return 0 if result.get("terminal_status", "PASS") == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
