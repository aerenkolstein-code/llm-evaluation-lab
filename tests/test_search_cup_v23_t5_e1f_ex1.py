"""Phase A only: RAM synthetic engine simulations, never a published-corpus replay."""
import ast
from contextlib import ExitStack
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from search_cup import v23_t5_e1f_ex1 as x
from search_cup.contracts import SearchResult, canonical_json, fingerprint
from search_cup.protocol_v23 import seal, verify_seal
from search_cup.tools import BudgetedSearchProxy


class MemoryStore:
    """No export method; fsync acknowledgments here are simulation events only."""
    is_formal = False

    def __init__(self, fail=None):
        self.files, self.events, self.rows = {}, [], []
        self.fail = fail

    def write(self, name, data):
        if name in self.files:
            raise x.GateError("ARTIFACT_OVERWRITE_FORBIDDEN")
        if self.fail == name:
            raise OSError("simulated storage fault")
        self.files[name] = data
        self.events.extend([("file_fsync", name), ("replace", name), ("directory_fsync", name)])

    def append(self, name, data):
        self.files[name] += data

    def journal(self, row):
        self.rows.append(deepcopy(row))
        self.events.append(("journal", row.get("event", row.get("entrant_id"))))

    def journal_records(self):
        return deepcopy(self.rows)

    def preserve_partial_journal(self):
        if not self.exists("partial-durable-journal.jsonl"):
            self.write("partial-durable-journal.jsonl", b"".join((canonical_json(r) + "\n").encode() for r in self.rows))

    def exists(self, name):
        return name in self.files

    def read(self, name):
        return self.files[name]

    def names(self):
        return sorted(self.files)


def synthetic_source():
    return {"head": x.BASELINE_SHA, "tree": x.BASELINE_TREE, "object_tree": x.BASELINE_TREE,
        "branch": "refs/heads/main", "origin_main": x.BASELINE_SHA, "clean": True,
        "publication_ancestor": True, "construction_ancestor": True,
        "implementation_sha256": "1" * 64, "boundary_sha256": "2" * 64,
        "ci": dict.fromkeys(x.CI_FIELDS)}


def synthetic_visible():
    result = {}
    for n, text in enumerate(("Remote work is permitted. Python is required. Applications are open.",
            "Remote work is permitted. Python is required. Applications are open. Applications are closed.",
            "Remote work is permitted. Python is required.", "Remote work is permitted. Python is required. Applications are open."), 1):
        doc = f"t5-pv-doc-{n:03}"
        url = "https://example.invalid/t5-e1frozen-pv-001/" + doc
        result[url] = {"doc_id": doc, "result": SearchResult("SYNTHETIC RAM UNIT TEST", url, text)}
    return result


class SyntheticBackend:
    backend_id = x.ex0.parent.nfr.BACKEND_ID

    def __init__(self, store, visible, fail_at=None, hook=None, results=None):
        self.store, self.visible, self.fail_at, self.hook = store, visible, fail_at, hook
        self.calls = []
        self.results = results

    def __call__(self, request):
        # These assertions happen inside the capability guard; no external I/O.
        assert self.store.exists("run-start.json")
        assert self.store.rows[0]["event"] == "STARTED"
        self.calls.append((request.entrant_id, request.call_number, request.query))
        if self.hook:
            self.hook(request)
        if len(self.calls) == self.fail_at:
            raise RuntimeError("synthetic backend failure")
        values = [v["result"] for v in self.visible.values()]
        return self.results if self.results is not None else (values if request.call_number == 1 else [values[3], values[0]])


class ExecutorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.audit = {"published_retriever_query_calls": 0, "formal_replays": 0,
            "memory_simulations": 0, "synthetic_backend_calls": 0}
        def prohibited(*args, **kwargs):
            cls.audit["published_retriever_query_calls"] += 1
            raise AssertionError("PHASE_A_PUBLISHED_RETRIEVER_FORBIDDEN")
        p = patch.object(x.ex0.parent.nfr.FrozenLexicalRetriever, "__call__", side_effect=prohibited)
        p.start()
        cls.addClassCleanup(p.stop)
        cls.b = x._frozen_bundle(x.BINDING)
        cls.good = cls.simulate()
        if cls.good[0]["terminal_status"] != "PASS":
            raise AssertionError("synthetic successful path failed: " + repr(cls.good[0]) + " files=" + repr(cls.good[1].names()))

    @classmethod
    def tearDownClass(cls):
        assert cls.audit["published_retriever_query_calls"] == cls.audit["formal_replays"] == 0
        print("EX1_PHASE_A_TEST_COUNTS=" + canonical_json(cls.audit))

    @classmethod
    def simulate(cls, *, fail_at=None, hook=None, results=None, store=None, end_source=None, end_bundle=None, labels=None):
        store = store or MemoryStore()
        visible = synthetic_visible()
        backend = SyntheticBackend(store, visible, fail_at, hook, results)
        proxies = [BudgetedSearchProxy(alias, 4, backend) for alias in x.ex0.ALIASES]
        source = synthetic_source()
        def reference():
            assert len(x._validated_commits(store)) == 2
            store.events.append(("reference_load", None))
            return labels or {f"t5-pv-doc-{n:03}": "RELEVANT" if n <= 6 else "UNKNOWN" for n in range(1, 25)}
        result = x._execute(store, cls.b, source, "RAM-UNIT-TEST-NOT-AUTHORITY", proxies, visible, reference,
            lambda: (end_source or source, end_bundle or cls.b))
        cls.audit["memory_simulations"] += 1
        cls.audit["synthetic_backend_calls"] += len(backend.calls)
        return result, store, backend, proxies

    def test_retained_bundle_exact(self):
        x._verify_retained(self.b)
        self.assertEqual(x.BINDING, self.b["binding"]["canonical_fingerprint"])

    def test_wrong_binding_precedes_source_access(self):
        with patch.object(Path, "read_bytes") as read, self.assertRaises(x.GateError):
            x._frozen_bundle("0" * 64)
        read.assert_not_called()

    def test_all_retained_components_resealed_drift_rejected(self):
        for key in x.PINS:
            with self.subTest(component=key):
                b = deepcopy(self.b)
                b[key] = seal({**b[key], "changed": True})
                with self.assertRaises(x.GateError):
                    x._verify_retained(b)

    def test_parent_pin_drift_rejected(self):
        for key in x.ex0.PARENT_PINS:
            with self.subTest(pin=key):
                b = deepcopy(self.b)
                b["parent"]["exact_pins"][key] = "0" * 64
                b["parent"] = seal(b["parent"])
                with self.assertRaises(x.GateError):
                    x._verify_retained(b)

    def test_ex0_source_mutation_rejected(self):
        with patch.object(Path, "read_bytes", return_value=b"mutated"), self.assertRaisesRegex(x.GateError, "IMPLEMENTATION_DRIFT"):
            x._frozen_bundle(x.BINDING)

    def test_wrong_runtime_rejected(self):
        with patch.object(x.ex0.parent.qualification, "runtime_identity", return_value={"python_major_minor": "3.12", "unicode_data_version": "15.0.0"}):
            with self.assertRaises(ValueError):
                x._frozen_bundle(x.BINDING)

    def test_source_main_local_and_ci_success(self):
        source = synthetic_source()
        x._source_gate(source, x.BASELINE_SHA)
        source["ci"] = dict(zip(x.CI_FIELDS, ("workflow_dispatch", "refs/heads/main", x.BASELINE_SHA, "1", "123")))
        x._source_gate(source, x.BASELINE_SHA)

    def test_wrong_sha_tree_branch_dirty_ancestry(self):
        for key, bad in (("head", "0" * 40), ("tree", "0" * 40), ("object_tree", "0" * 40),
                ("branch", None), ("branch", "refs/heads/topic"), ("origin_main", "0" * 40),
                ("clean", False), ("publication_ancestor", False), ("construction_ancestor", False)):
            with self.subTest(field=key, value=bad):
                source = synthetic_source()
                source[key] = bad
                with self.assertRaises(x.GateError):
                    x._source_gate(source, x.BASELINE_SHA)

    def test_partial_wrong_and_rerun_ci_context(self):
        good = dict(zip(x.CI_FIELDS, ("workflow_dispatch", "refs/heads/main", x.BASELINE_SHA, "1", "123")))
        for key, bad in (("GITHUB_EVENT_NAME", "pull_request"), ("GITHUB_REF", "refs/pull/1/merge"),
                ("GITHUB_SHA", "0" * 40), ("GITHUB_RUN_ATTEMPT", "2"), ("GITHUB_RUN_ID", "")):
            for value in (bad, None):
                with self.subTest(field=key, value=value):
                    source = synthetic_source()
                    source["ci"] = {**good, key: value}
                    with self.assertRaises(x.GateError):
                        x._source_gate(source, x.BASELINE_SHA)
        source = synthetic_source()
        source["ci"].pop("GITHUB_RUN_ID")
        with self.assertRaises(x.GateError):
            x._source_gate(source, x.BASELINE_SHA)

    def reject_replay(self, **changes):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "never-created"
            args = dict(authority_receipt_id="TEST-REJECT-ONLY", expected_main_sha=x.BASELINE_SHA,
                expected_binding=x.BINDING, run_id=x.RUN_ID, output_dir=path)
            args.update(changes)
            with patch.object(x, "_frozen_bundle", return_value=self.b), patch.object(x, "_source_snapshot", return_value=synthetic_source()), \
                 patch.object(x, "_visible_backend", side_effect=AssertionError("NO_BACKEND_CONSTRUCTION")) as backend:
                result = x.replay(**args)
            self.assertEqual("PRESTART_NOT_EVALUABLE", result["terminal_status"])
            self.assertFalse(result["formal_execution_performed"])
            self.assertEqual(0, result["retriever_query_calls"])
            self.assertFalse(path.exists())
            backend.assert_not_called()

    def test_missing_authority_rejected_before_start(self):
        self.reject_replay(authority_receipt_id="")

    def test_wrong_run_identity_rejected_before_start(self):
        self.reject_replay(run_id=x.RUN_ID.replace("E1F-001", "E1F-002"))

    def test_wrong_expected_main_rejected_before_start(self):
        self.reject_replay(expected_main_sha="0" * 40)

    def test_wrong_binding_public_replay_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            result = x.replay(authority_receipt_id="TEST-REJECT-ONLY", expected_main_sha=x.BASELINE_SHA,
                expected_binding="0" * 64, run_id=x.RUN_ID, output_dir=Path(d) / "unused")
            self.assertEqual("EX0_BINDING_MISMATCH", result["reason_code"])
            self.assertEqual([], list(Path(d).iterdir()))

    def test_output_reuse_and_in_source_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            self.reject_replay(output_dir=d)
            with self.assertRaises(x.GateError):
                x._new_output(Path(d) / "missing-parent" / "child")
        with self.assertRaises(x.GateError):
            x._new_output(x._root() / "never-create-in-repo")

    def test_preflight_zero_and_not_run(self):
        with patch.object(x, "_frozen_bundle", return_value=self.b), patch.object(x, "_source_snapshot", return_value=synthetic_source()), \
             patch.object(BudgetedSearchProxy, "search", side_effect=AssertionError("ZERO_QUERY")), \
             patch.object(x.ex0, "visible_decision", side_effect=AssertionError("ZERO_DECISION")):
            p = x.preflight()
            self.assertEqual("PASS", p["terminal_status"])
            self.assertEqual({f"I{i}": "NOT_RUN" for i in range(1, 11)}, p["I1_I10"])
            self.assertFalse(p["formal_execution_allowed"])
            self.assertTrue(all(p[k] == 0 for k in x.ZERO_COUNTS))

    def test_preflight_dirty_zero_receipt(self):
        source = {**synthetic_source(), "clean": False}
        with patch.object(x, "_frozen_bundle", return_value=self.b), patch.object(x, "_source_snapshot", return_value=source):
            self.assertEqual("PRESTART_NOT_EVALUABLE", x.preflight()["terminal_status"])

    def test_ready_contains_only_zero_authoring_files(self):
        with tempfile.TemporaryDirectory() as d, patch.object(x, "_frozen_bundle", return_value=self.b), \
             patch.object(x, "_source_snapshot", return_value=synthetic_source()):
            path = Path(d) / "ready"
            result = x.write_ready(path)
            self.assertFalse(result["formal_execution_performed"])
            self.assertEqual(set(x.READY_FILES.values()) | {"MANIFEST.sha256"}, {p.name for p in path.iterdir()})
            self.assertFalse(set(x.ex0.FORMAL_FILES[:-1]) & {p.name for p in path.iterdir()})
            for name in x.READY_FILES.values():
                verify_seal(json.loads((path / name).read_bytes()))
            second = x.write_ready(Path(d) / "ready2")
            self.assertEqual(result, second)

    def test_plan_uses_exact_ex0_payloads(self):
        with patch.object(x, "_frozen_bundle", return_value=self.b):
            p = x.plan()
        self.assertEqual(self.b["run"], p["frozen_ex0_plan"])
        self.assertEqual(self.b["integrity"], p["frozen_ex0_integrity"])
        self.assertFalse(p["formal_execution_allowed"])

    def test_memory_success_exact_files_schemas_and_evidence(self):
        result, store, _, _ = self.good
        self.assertEqual("PASS", result["terminal_status"])
        self.assertFalse(result["formal_execution_performed"])
        self.assertEqual(set(x.ex0.FORMAL_FILES), set(store.names()))
        for name, schema in self.b["run"]["future_output_contracts"]["schemas"].items():
            data = x._json_records(store, name)
            for row in data if name.endswith(".jsonl") else [data]:
                x._shape(row, schema)
                verify_seal(row)
        check = x._json_records(store, "integrity-checks.json")
        self.assertEqual("PASS", x.integrity_comparable(check["checks"], store, self.b))
        self.assertTrue(all(r["status"] == "PASS" and r["actual_run_evidence"] for r in check["checks"].values()))

    def test_exact_query_schedule_order_and_eight_calls(self):
        _, store, backend, _ = self.good
        expected = [(p["entrant_id"], s["query_number"], s["query"]) for p in self.b["queries"]["profiles"] for s in p["queries"]]
        self.assertEqual(expected, backend.calls)
        self.assertEqual(8, len(x._json_records(store, "query-provenance.jsonl")))

    def test_distinct_four_ticket_budgets(self):
        _, store, _, proxies = self.good
        self.assertIsNot(proxies[0], proxies[1])
        self.assertEqual([4, 4], [p.calls_used for p in proxies])
        receipts = x._json_records(store, "resource-receipts.json")["receipts"]
        self.assertEqual(2, len({r["proxy_instance_id"] for r in receipts}))

    def test_duplicate_proxy_rejected_before_start(self):
        store = MemoryStore()
        backend = SyntheticBackend(store, synthetic_visible())
        p = BudgetedSearchProxy(x.ex0.ALIASES[0], 4, backend)
        with self.assertRaises(x.GateError):
            x._execute(store, self.b, synthetic_source(), "RAM", [p, p], {}, lambda: {}, lambda: None)
        self.assertEqual([], store.names())

    def test_published_backend_forbidden_in_memory_simulation(self):
        with x.ex0.authoring_guard():
            backend, visible = x._visible_backend()
        proxies = [BudgetedSearchProxy(alias, 4, backend) for alias in x.ex0.ALIASES]
        with self.assertRaisesRegex(x.GateError, "SIMULATION_CANNOT"):
            x._execute(MemoryStore(), self.b, synthetic_source(), "RAM", proxies, visible, lambda: {}, lambda: None)

    def test_first_seen_dedupe_and_visible_filter(self):
        store = self.good[1]
        for name in ("entrant-a-output.json", "entrant-b-output.json"):
            output = x._json_records(store, name)
            self.assertEqual(["t5-pv-doc-001", "t5-pv-doc-004"], [r["doc_id"] for r in output["submission"]["results"]])

    def test_visible_unknown_contradiction_and_injection(self):
        values = list(synthetic_visible().values())
        self.assertEqual("RETURN_AS_MATCH", x._decision(values[0]["result"], x._zero())["decision"])
        self.assertEqual("DO_NOT_RETURN", x._decision(values[1]["result"], x._zero())["decision"])
        self.assertEqual("DO_NOT_RETURN", x._decision(values[2]["result"], x._zero())["decision"])
        for bad in ({"result": values[0]["result"], "reference_labels": {}}, (values[0]["result"], "peer")):
            with self.assertRaises(x.GateError):
                x._decision(bad, x._zero())

    def test_fixture_cannot_read_reference_or_environment(self):
        for hook in (lambda r: Path("reference.json").read_bytes(), lambda r: x.os.environ.get("UNRELATED_SECRET")):
            with patch.object(x.ex0, "visible_decision", side_effect=hook):
                with self.assertRaises(x.GateError):
                    x._decision(next(iter(synthetic_visible().values()))["result"], x._zero())

    def test_capability_traps_provider_network_subprocess(self):
        from pkgutil import resolve_name
        for target in (*x.ex0.parent.qualification.GUARDED_TARGETS, *x.ex0.FIXTURE_GUARDS):
            with self.subTest(target=target):
                counts = x._zero()
                with x._capabilities(counts), self.assertRaises(x.GateError):
                    resolve_name(target)()
                self.assertEqual(1, sum(counts[k] for k in x.EXTERNAL_COUNTS))

    def test_start_and_durable_commits_precede_reference(self):
        _, store, _, _ = self.good
        events = store.events
        ref = events.index(("reference_load", None))
        for alias, name in zip(x.ex0.ALIASES, ("entrant-a-output.json", "entrant-b-output.json")):
            fs = events.index(("file_fsync", name))
            replace = events.index(("replace", name))
            directory = events.index(("directory_fsync", name))
            commit = events.index(("journal", alias))
            self.assertTrue(fs < replace < directory < commit < ref)
        self.assertEqual([1, 2], [c["commit_sequence"] for c in x._validated_commits(store)])

    def test_reference_rejected_without_two_commits(self):
        store = MemoryStore()
        with patch.object(x, "_load_reference") as load, self.assertRaises(x.GateError):
            x._reference_after_commits(store, self.b, load)
        load.assert_not_called()

    def test_reference_rejected_for_tampered_committed_bytes(self):
        store = deepcopy(self.good[1])
        store.files["entrant-a-output.json"] += b" "
        with self.assertRaises(x.GateError):
            x._validated_commits(store)

    def test_reference_rejected_for_forged_commit_or_duplicate(self):
        for mode in ("hash", "duplicate", "fsync"):
            store = deepcopy(self.good[1])
            if mode == "hash":
                store.rows[1]["journal_record_fingerprint"] = "0" * 64
            elif mode == "duplicate":
                store.rows[2] = deepcopy(store.rows[1])
            else:
                store.rows[1]["file_fsync"] = False
            with self.assertRaises(x.GateError):
                x._validated_commits(store)

    def test_reference_second_load_rejected(self):
        with self.assertRaisesRegex(x.GateError, "ALREADY_LOADED"):
            x._reference_after_commits(self.good[1], self.b, lambda: {})

    def test_backend_failure_spends_once_no_retry(self):
        r, store, backend, proxies = self.simulate(fail_at=1)
        self.assertEqual("NOT_EVALUABLE", r["terminal_status"])
        self.assertEqual(1, len(backend.calls))
        self.assertEqual([1, 0], [p.calls_used for p in proxies])
        self.assertEqual(1, len(x._json_records(store, "query-provenance.jsonl")))
        self.assertNotIn("adjudication.json", store.names())

    def test_partial_preserves_a_and_does_not_fabricate_b_metrics(self):
        r, store, backend, _ = self.simulate(fail_at=5)
        self.assertEqual("PARTIAL", r["completion_status"])
        self.assertEqual(5, len(backend.calls))
        self.assertIn("entrant-a-output.json", store.names())
        for missing in ("entrant-b-output.json", "adjudication.json", "metrics.json", "integrity-checks.json"):
            self.assertNotIn(missing, store.names())
        self.assertEqual("PARTIAL", x._json_records(store, "run-end.json")["state"])
        self.assertEqual("NOT_EVALUABLE", x._json_records(store, "post-run-receipt.json")["comparable_status"])
        self.assertFalse(any(e[0] == "reference_load" for e in store.events))

    def test_store_commit_failure_does_not_open_barrier(self):
        r, store, _, _ = self.simulate(store=MemoryStore(fail="entrant-b-output.json"))
        self.assertEqual("NOT_EVALUABLE", r["terminal_status"])
        self.assertIn("entrant-a-output.json", store.names())
        self.assertNotIn("hidden-reference-barrier-audit.json", store.names())

    def test_results_overrun_stops_after_one_call(self):
        values = [v["result"] for v in synthetic_visible().values()]
        r, _, backend, _ = self.simulate(results=values * 3)
        self.assertEqual("NOT_EVALUABLE", r["terminal_status"])
        self.assertEqual(1, len(backend.calls))

    def test_frozen_visible_content_mismatch_stops(self):
        result = next(iter(synthetic_visible().values()))["result"]
        bad = SearchResult(result.title, result.url, "changed")
        r, _, backend, _ = self.simulate(results=[bad])
        self.assertEqual("NOT_EVALUABLE", r["terminal_status"])
        self.assertEqual(1, len(backend.calls))

    def test_runtime_and_token_envelope_exceeded(self):
        receipt = deepcopy(x._json_records(self.good[1], "resource-receipts.json")["receipts"][0])
        for k, v in (("elapsed_ms", 60001), ("token_count", 8001), ("query_attempts", 5), ("spend_usd", 1)):
            with self.subTest(field=k), self.assertRaises(x.GateError):
                x._resource_check({**receipt, k: v}, self.b["resources"]["identical_envelope"])

    def test_timeout_stops_without_retry(self):
        with patch("search_cup.tools.perf_counter", side_effect=[0, 2]):
            r, _, backend, _ = self.simulate()
        self.assertEqual("NOT_EVALUABLE", r["terminal_status"])
        self.assertEqual(1, len(backend.calls))

    def test_end_source_mutation_prevents_comparability(self):
        r, store, _, _ = self.simulate(end_source={**synthetic_source(), "tree": "0" * 40})
        self.assertEqual("NOT_EVALUABLE", r["terminal_status"])
        self.assertEqual("PARTIAL", x._json_records(store, "run-end.json")["state"])
        self.assertEqual("FAIL", next(r for r in store.rows if r.get("event") == "HARD_GATE_FAILURE")["checks"]["I10"])
        self.assertNotIn("metrics.json", store.names())

    def test_end_bundle_mutation_preserves_partial(self):
        changed = deepcopy(self.b)
        changed["policy"]["changed"] = True
        r, store, _, _ = self.simulate(end_bundle=changed)
        self.assertEqual("PARTIAL", r["completion_status"])
        self.assertNotIn("metrics.json", store.names())

    def test_each_hard_gate_missing_failed_unknown_evidence_rejects(self):
        good = x._json_records(self.good[1], "integrity-checks.json")["checks"]
        for gate in good:
            for mode in ("missing", "FAIL", "UNKNOWN", "empty", "wrong_hash", "wrong_run"):
                with self.subTest(gate=gate, mode=mode):
                    checks = deepcopy(good)
                    if mode == "missing":
                        checks.pop(gate)
                    elif mode in ("FAIL", "UNKNOWN"):
                        checks[gate]["status"] = mode
                    elif mode == "empty":
                        checks[gate]["actual_run_evidence"] = []
                    elif mode == "wrong_hash":
                        checks[gate]["actual_run_evidence"][0]["file_sha256"] = "0" * 64
                    else:
                        checks[gate]["run_id"] = "other"
                    self.assertEqual("NOT_EVALUABLE", x.integrity_comparable(checks, self.good[1], self.b))

    def test_unknown_metrics_zero_denominator_and_no_backfill(self):
        def out(ids):
            return {"entrant_id": x.ex0.ALIASES[0], "submission": {"results": [{"doc_id": d} for d in ids]}}
        labels = {str(i): "UNKNOWN" for i in range(10)} | {"10": "RELEVANT"}
        metrics = x._metric_values([out(list(labels))], labels)[0]["values"]
        self.assertEqual(1, metrics[0]["value"])
        self.assertIsNone(metrics[1]["value"])
        self.assertEqual("NOT_EVALUABLE", metrics[1]["terminal_status"])
        self.assertEqual(10, metrics[2]["value"])
        labels = {"a": "UNKNOWN", "b": "NOT_RELEVANT"}
        self.assertIsNone(x._metric_values([out(["a"])], labels)[0]["values"][0]["value"])

    def test_manifest_covers_actual_payload_bytes(self):
        for store in (self.good[1], self.simulate(fail_at=5)[1]):
            lines = store.read("MANIFEST.sha256").decode().splitlines()
            parsed = {line.split("  ", 1)[1]: line.split("  ", 1)[0] for line in lines}
            self.assertEqual(set(store.names()) - {"MANIFEST.sha256"}, set(parsed))
            for name, digest in parsed.items():
                self.assertEqual(digest, x._hash(store.read(name)))

    def test_schema_upper_limits_and_extra_properties(self):
        schema = self.b["run"]["future_output_contracts"]["schemas"]["resource-receipts.json"]
        doc = deepcopy(x._json_records(self.good[1], "resource-receipts.json"))
        for bad in ({**doc, "extra": 1}, {**doc, "receipts": doc["receipts"] * 2}):
            with self.assertRaises(ValueError):
                x._shape(bad, schema)
        doc["receipts"][0]["query_attempts"] = 5
        with self.assertRaises(ValueError):
            x._shape(doc, schema)

    def test_disk_durable_order_immutable_and_exclusive_ledger(self):
        # Local primitives only: arbitrary bytes, no run-start or formal outputs.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d) / "unit-store"
            store = x._DiskStore(root)
            events = []
            fsync, replace = x.os.fsync, x.os.replace
            def sync(fd):
                events.append("fsync")
                return fsync(fd)
            def swap(a, b):
                events.append("replace")
                return replace(a, b)
            with patch.object(x.os, "fsync", side_effect=sync), patch.object(x.os, "replace", side_effect=swap):
                store.write("unit.bin", b"primitive-only")
            self.assertEqual(["fsync", "replace", "fsync"], events)
            with self.assertRaises(x.GateError):
                store.write("unit.bin", b"overwrite")
            self.assertEqual(b"primitive-only", store.read("unit.bin"))
            with self.assertRaises(FileExistsError):
                x._DiskStore(Path(d) / "second-name")
            self.assertFalse((Path(d) / "second-name").exists())

    def test_disk_fsync_failure_keeps_actual_bytes_and_ledger(self):
        with tempfile.TemporaryDirectory() as d:
            store = x._DiskStore(Path(d) / "unit-store")
            with patch.object(store, "_sync", side_effect=OSError("simulated dir sync failure")), self.assertRaises(OSError):
                store.write("unit.bin", b"preserve")
            self.assertEqual(b"preserve", store.read("unit.bin"))
            self.assertTrue(store.ledger.exists())

    def test_module_environment_envelope_is_named_only(self):
        tree = ast.parse((x._root() / x.MODULE_PATH).read_text())
        accesses = [n for n in ast.walk(tree) if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "os"]
        self.assertLessEqual({n.attr for n in accesses}, {"environ", "open", "O_RDONLY", "O_DIRECTORY", "fsync", "close", "replace"})
        self.assertEqual({"GITHUB_EVENT_NAME", "GITHUB_REF", "GITHUB_SHA", "GITHUB_RUN_ATTEMPT", "GITHUB_RUN_ID"}, set(x.CI_FIELDS))

    def test_complete_validator_rejects_missing_and_altered_payloads(self):
        self.assertEqual("PASS", x.validate_complete(self.good[1], self.b))
        for name in x.ex0.FORMAL_FILES:
            with self.subTest(path=name):
                store = deepcopy(self.good[1])
                store.files.pop(name)
                self.assertEqual("NOT_EVALUABLE", x.validate_complete(store, self.b))
                store = deepcopy(self.good[1])
                store.files[name] += b" "
                self.assertEqual("NOT_EVALUABLE", x.validate_complete(store, self.b))

    def test_late_manifest_failure_cannot_claim_complete(self):
        r, store, _, _ = self.simulate(store=MemoryStore(fail="MANIFEST.sha256"))
        self.assertEqual("NOT_EVALUABLE", r["terminal_status"])
        self.assertFalse(r["formal_execution_complete"])
        self.assertEqual("NOT_EVALUABLE", x.validate_complete(store, self.b))

    def test_scope_requires_exact_five_and_narrow_boundary(self):
        old = 'is_je1 = path.name == "v23_t4_je1.py"'
        new = 'is_je1 = path.name in {"v23_t4_je1.py", "v23_t5_e1f_ex1.py"}'
        changes = ["A\t" + p for p in x.ADDED_PATHS] + ["M\t" + x.BOUNDARY_PATH]
        x.scope_gate(changes, old, new)
        for bad in (changes[:-1], changes + ["A\textra.py"], changes + changes[:1]):
            with self.assertRaises(x.GateError):
                x.scope_gate(bad, old, new)
        with self.assertRaises(x.GateError):
            x.scope_gate(changes, old, new + "\nforbidden = set()")


if __name__ == "__main__":
    unittest.main()
