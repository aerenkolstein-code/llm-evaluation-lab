"""Renewed exact-target qualification; local calls and negative guard attempts are counted."""
import ast
from copy import deepcopy
from contextlib import redirect_stdout
import hashlib
import io
import json
from pathlib import Path
from pkgutil import resolve_name
import tempfile
import unittest
from unittest.mock import patch

from search_cup.contracts import SearchRequest, SearchResult, canonical_json, fingerprint
from search_cup.protocol_v23 import f1_eligibility, seal, verify_seal
from search_cup.tools import BudgetedSearchProxy, SearchBackendResponse, SearchBackendError, SearchBudgetExceeded
from search_cup import v23_frozen_retriever as nfr
from search_cup import v23_t3_f1q_r2 as q

ROOT = Path(__file__).resolve().parents[1]


class QualificationR2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.counts = {"retriever": 0, "proxy": 0, "injected_failure": 0, "negative_guard_blocked_attempts": 0}
        cls.recorded = []
        original_call, original_search = nfr.FrozenLexicalRetriever.__call__, BudgetedSearchProxy.search
        def counted(candidate, request):
            cls.counts["retriever"] += 1
            response = original_call(candidate, request)
            cls.recorded.append((candidate, request, response))
            return response
        def searched(proxy, query):
            before = len(proxy.traces)
            try:
                return original_search(proxy, query)
            finally:
                added = proxy.traces[before:]
                cls.counts["proxy"] += len(added)
                cls.counts["injected_failure"] += sum(t.error_code == "INJECTED_LOCAL_FAILURE" for t in added)
        for obj, name, replacement in ((nfr.FrozenLexicalRetriever, "__call__", counted),
                                       (BudgetedSearchProxy, "search", searched)):
            p = patch.object(obj, name, replacement)
            p.start()
            cls.addClassCleanup(p.stop)
        cls.ctx = q.resolve_target()
        cls.bundle = q.build_bundle()
        cls.initial_recorded = tuple(cls.recorded)
        cls.observed = cls.bundle["runtime"]["pass_receipts"][0]

    @classmethod
    def tearDownClass(cls):
        print("F1QR2_TEST_COUNTS=" + canonical_json(cls.counts))

    def copy_inputs(self, root):
        for name in (*q.SOURCE_PINS, q.TARGET_PATH, q.MODULE_PATH):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((ROOT / name).read_bytes())

    def test_exact_baseline_and_five_additions(self):
        self.assertEqual({"sha": "34e147f26b582486474b4d4b29eae7494add2d4b",
                          "tree": "311b541fddf212060476a3f994581e06c71d98f0"}, q.baseline())
        self.assertEqual({q.MODULE_PATH, q.TARGET_PATH, "tests/test_search_cup_v23_t3_f1q_r2.py",
            "docs/search-cup-v23-t3-f1q-r2.md", ".github/workflows/t3-f1-retriever-qualification-r2-offline.yml"}, set(q.APPROVED_PATHS))

    def test_baseline_drift_before_reads_and_calls(self):
        before = dict(self.counts)
        for wrong in ({"expected_sha": "0" * 40}, {"expected_tree": "0" * 40}):
            with patch.object(Path, "read_bytes") as read, self.assertRaisesRegex(ValueError, "BASELINE_DRIFT"):
                q.build_bundle(**wrong)
            read.assert_not_called()
        self.assertEqual(before, self.counts)

    def test_exact_versioned_target_json(self):
        target = json.loads((ROOT / q.TARGET_PATH).read_text())
        self.assertEqual(q.TARGET_JSON_FINGERPRINT, fingerprint(target))
        self.assertEqual(target, self.bundle["target"]["selected_target"])
        self.assertEqual(q.DESCRIPTOR_FINGERPRINT, target["candidate_descriptor_fingerprint"])
        self.assertEqual(q.CODE_SHA256, target["code_content_sha256"])
        self.assertEqual(nfr.CONFIG_FINGERPRINT, target["config_fingerprint"])
        self.assertEqual(nfr.TEST_CORPUS_FINGERPRINT, target["synthetic_fixture_corpus_fingerprint"])
        self.assertEqual(q.ACCEPTED_NFR_PACKAGE, target["accepted_nfr_package_fingerprint"])
        self.assertEqual(nfr.IMPLEMENTATION, target["module_class"])

    def test_exact_python_unicode_and_descriptor(self):
        self.assertEqual({"python_major_minor": "3.11", "unicode_data_version": "14.0.0"}, q.runtime_identity())
        d = self.bundle["target"]["published_candidate_descriptor"]
        verify_seal(d)
        self.assertEqual(q.DESCRIPTOR_FINGERPRINT, d["canonical_fingerprint"])
        self.assertEqual("EXPLICIT_AUTHORITY_PIN_TO_CANDIDATE_ID", d["selector"]["rule"])
        self.assertEqual("EXACT_MATCH", self.bundle["receipt"]["target_resolution"])

    def test_runtime_mismatch_never_assesses_criteria(self):
        before = dict(self.counts)
        for runtime in ({"python_major_minor": "3.12", "unicode_data_version": "15.0.0"},
                        {"python_major_minor": "3.12", "unicode_data_version": "14.0.0"}):
            with patch.object(q, "runtime_identity", return_value=runtime), patch.object(q, "run_probe_pass") as probes:
                bundle = q.build_bundle()
                q.validate_bundle(bundle)
                probes.assert_not_called()
            self.assertEqual("NOT_EVALUABLE", bundle["receipt"]["method_qualification_result"])
            self.assertEqual("TARGET_IDENTITY_MISMATCH", bundle["receipt"]["reason_code"])
            self.assertFalse(bundle["qualification"]["criterion_assessment_performed"])
            self.assertEqual({"UNKNOWN"}, {v["status"] for v in bundle["qualification"]["criteria"].values()})
            self.assertEqual(0, bundle["resources"]["qualification_fixture_retriever_calls"])
        self.assertEqual(before, self.counts)

    def test_wrong_descriptor_fails_closed_without_probes(self):
        original = nfr._assemble
        def wrong(*args):
            bundle = original(*args)
            bundle["candidate"] = seal({**bundle["candidate"], "result_limit": 9})
            return bundle
        before = dict(self.counts)
        with patch.object(nfr, "_assemble", wrong), patch.object(q, "run_probe_pass") as probe:
            bundle = q.build_bundle()
            probe.assert_not_called()
        self.assertEqual("DESCRIPTOR", bundle["target"]["mismatch_component"])
        self.assertEqual("NOT_EVALUABLE", bundle["receipt"]["method_qualification_result"])
        self.assertEqual(before, self.counts)

    def test_wrong_target_and_each_source_reject_before_probes(self):
        before = dict(self.counts)
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.copy_inputs(root)
            for name in (q.TARGET_PATH, *q.SOURCE_PINS):
                path = root / name
                original = path.read_bytes()
                path.write_bytes((b"{}" if name == q.TARGET_PATH else original + b"\n"))
                with self.subTest(path=name), patch.object(q, "run_probe_pass") as probe:
                    bundle = q.build_bundle(root=root)
                    self.assertEqual("NOT_EVALUABLE", bundle["receipt"]["target_resolution"])
                    probe.assert_not_called()
                path.write_bytes(original)
        self.assertEqual(before, self.counts)

    def test_source_reads_closed_without_legacy_inspection(self):
        allowed = set(q.SOURCE_PINS) | {q.MODULE_PATH, q.TARGET_PATH}
        seen = set()
        original = Path.read_bytes
        def read(path):
            name = path.resolve().relative_to(ROOT.resolve()).as_posix()
            self.assertIn(name, allowed)
            seen.add(name)
            return original(path)
        with patch.object(Path, "read_bytes", read):
            q.validate_bundle(self.bundle)
        self.assertEqual(allowed, seen)
        self.assertNotIn("search_cup/search_pro.py", seen)
        self.assertNotIn("search_cup/v23_t3_f1q.py", seen)

    def test_prior_nfr_is_only_identity_reconstruction(self):
        with patch.object(nfr, "run_fixture_conformance", side_effect=AssertionError("historical conformance not allowed")), \
             patch.object(nfr, "load_inputs", side_effect=AssertionError("legacy source reads not allowed")):
            q.validate_bundle(self.bundle)
        self.assertFalse(self.bundle["runtime"]["historical_nfr_conformance_executed"])
        self.assertTrue(self.bundle["target"]["prior_nfr_identity_only_not_qualification_proof"])

    def test_r1_original_query_exactly_preserved_at_proxy(self):
        for obs in self.observed["observations"]:
            self.assertEqual(obs["request"]["query"], obs["proxy_trace"]["query"])
        obs = self.observed["observations"][0]
        self.assertEqual("  ＡＬＰＨＡ, alpha!!!  ", obs["request"]["query"])
        self.assertEqual("alpha alpha", obs["normalized_query"])

    def test_r1_declared_source_normalization_only(self):
        analysis = q.source_observations(self.ctx)
        self.assertEqual(["query", "request_id"], analysis["request_attributes"])
        self.assertIn("unicodedata.normalize", analysis["fragments"]["normalize"]["source_excerpt"])
        self.assertTrue(all(analysis["checks"].values()))

    def test_r2_four_entrant_identities_same_results(self):
        values = self.observed["observations"][:4]
        self.assertEqual(4, len({v["request"]["entrant_id"] for v in values}))
        self.assertEqual(1, len({canonical_json(v["response"]["results"]) for v in values}))
        self.assertTrue(all(v["same_candidate_config_corpus"] for v in values))

    def test_r2_no_state_or_memory_after_other_queries(self):
        values = self.observed["observations"]
        self.assertEqual(values[0]["response"]["results"], values[9]["response"]["results"])
        self.assertEqual(self.observed["candidate_state_before"], self.observed["candidate_state_after"])
        self.assertEqual([], q.source_observations(self.ctx)["state_writes"])

    def test_r2_request_metadata_cannot_select_planner(self):
        candidate = q._node(self.ctx["sources"][nfr.CODE_PATH], "FrozenLexicalRetriever")
        attrs = {n.attr for n in ast.walk(candidate) if isinstance(n, ast.Attribute)}
        self.assertFalse(attrs & {"entrant_id", "provider", "model", "call_number"})
        config = json.loads(self.ctx["config"].canonical_content)
        self.assertTrue(all(config[k] == "NONE" for k in ("query_planning", "query_rewrite", "cross_query_memory", "semantic_model")))

    def test_r3_multiset_score_tie_limit_zero_exclusion(self):
        for index, expected_first in ((0, 6), (10, 9)):
            obs = self.observed["observations"][index]
            self.assertEqual(expected_first, obs["scores"]["lex-01"])
            self.assertEqual(3, obs["scores"]["lex-12"])
            self.assertEqual(12, sum(s > 0 for s in obs["scores"].values()))
            self.assertEqual(list(q.TOP_TEN), obs["ordered_doc_ids"])
        self.assertEqual([], self.observed["observations"][8]["ordered_doc_ids"])

    def test_r3_unicode_chinese_short_and_title_behavior(self):
        cases = {o["case_id"]: o for o in self.observed["observations"]}
        for case, ids in (("nfkc", ["lex-20"]), ("chinese", ["lex-20"]), ("short", ["lex-21"]),
                          ("punctuation", []), ("title-index", list(q.TOP_TEN))):
            self.assertEqual(ids, cases[case]["ordered_doc_ids"])
        self.assertEqual(4, cases["title-index"]["scores"]["lex-11"])

    def test_r3_one_scoring_and_ordering_path(self):
        calls = q.source_observations(self.ctx)["retrieval_call_names"]
        self.assertEqual(1, calls.count("overlap"))
        self.assertEqual(1, calls.count("sorted"))
        self.assertNotIn("rerank", calls)

    def test_r4_repeated_complete_packages_byte_identical(self):
        before = dict(self.counts)
        other = q.build_bundle()
        self.assertEqual(canonical_json(self.bundle), canonical_json(other))
        self.assertEqual(24, self.counts["retriever"] - before["retriever"])
        self.assertEqual(26, self.counts["proxy"] - before["proxy"])
        self.assertEqual(2, self.counts["injected_failure"] - before["injected_failure"])

    def test_r4_versioned_bindings_and_limit(self):
        d = self.bundle["target"]["published_candidate_descriptor"]
        self.assertEqual(10, d["result_limit"])
        self.assertEqual("deterministic-character-ngram-overlap/v1", d["algorithm_id"])
        self.assertEqual("unicode-nfkc-casefold-alnum-space/v1", d["normalization_id"])
        self.assertEqual(q.SOURCE_PINS["search_cup/contracts.py"], d["request_schema"]["source_sha256"])
        self.assertEqual(q.SOURCE_PINS["search_cup/tools.py"], d["result_schema"]["response_source_sha256"])

    def test_r5_actual_typed_outputs_and_exact_document_mapping(self):
        by_url = {d.url: d for d in self.ctx["corpus"].documents}
        for _, request, response in self.initial_recorded:
            self.assertIs(type(response), SearchBackendResponse)
            self.assertEqual(request.request_id, response.request_id)
            for result in response.results:
                self.assertIs(type(result), SearchResult)
                d = by_url[result.url]
                self.assertEqual((d.title, d.url, d.text[:240]), (result.title, result.url, result.snippet))

    def test_r5_request_and_backend_identity(self):
        for obs in self.observed["observations"]:
            self.assertEqual(obs["request"]["request_id"], obs["response"]["request_id"])
            self.assertEqual(obs["request"]["request_id"], obs["proxy_trace"]["backend_request_id"])
            self.assertEqual(nfr.BACKEND_ID, obs["response"]["backend_id"])
            self.assertEqual(nfr.BACKEND_ID, obs["proxy_trace"]["backend_id"])

    def test_r6_actual_same_instance_and_capability_envelope(self):
        for group in (self.initial_recorded[:12], self.initial_recorded[12:24]):
            candidate = group[0][0]
            self.assertTrue(all(c is candidate for c, _, _ in group))
            self.assertTrue(all(c.config is candidate.config and c.corpus is candidate.corpus for c, _, _ in group))
        self.assertEqual(5, self.observed["frozen_assignment_rejections"])

    def test_r6_detaches_mutable_constructor_inputs(self):
        config = json.loads(self.ctx["config"].canonical_content)
        docs = [d.as_dict() for d in self.ctx["corpus"].documents]
        frozen_config, frozen_corpus = nfr.FrozenConfig(config), nfr.FrozenCorpus(docs)
        config["result_limit"] = 1
        docs[0]["text"] = "changed"
        self.assertEqual(self.ctx["config"], frozen_config)
        self.assertEqual(self.ctx["corpus"], frozen_corpus)

    def test_r7_each_external_execution_seam_is_blocked(self):
        with q.external_guard() as attempts:
            for name in q.GUARDED_TARGETS:
                with self.subTest(name=name), self.assertRaises(q.ExternalOperationBlocked):
                    resolve_name(name)()
            environment = resolve_name("os.environ")
            for operation in (lambda: environment.get("FIXTURE_ONLY"), lambda: environment["FIXTURE_ONLY"],
                              lambda: list(environment), lambda: "FIXTURE_ONLY" in environment):
                with self.assertRaises(q.ExternalOperationBlocked):
                    operation()
        self.counts["negative_guard_blocked_attempts"] += len(attempts)
        self.assertEqual(len(q.GUARDED_TARGETS) + 4, len(attempts))

    def test_r7_candidate_runtime_reads_no_files(self):
        candidate = nfr.FrozenLexicalRetriever(self.ctx["corpus"], self.ctx["config"])
        with q.external_guard(), patch.object(Path, "read_bytes", side_effect=AssertionError("unexpected file read")), \
             patch("builtins.open", side_effect=AssertionError("unexpected file open")):
            result = candidate(SearchRequest("fixture", "alpha", 1, "local-no-io"))
        self.assertEqual(10, len(result.results))

    def test_r7_no_forbidden_candidate_imports(self):
        imports = q.source_observations(self.ctx)["imports"]
        self.assertFalse({"search_pro", "providers", "runner", "judge", "os", "socket", "subprocess"} & set(imports))

    def test_r7_zero_receipt_separates_local_and_infrastructure(self):
        r = self.bundle["resources"]
        self.assertTrue(all(type(r[k]) is int and r[k] == 0 for k in q.ZERO_FIELDS))
        self.assertEqual((24, 26, 2), tuple(r[k] for k in ("qualification_fixture_retriever_calls",
            "qualification_proxy_calls", "qualification_injected_failure_calls")))
        self.assertEqual({"currency": "USD", "value": 0}, r["spend"])
        self.assertTrue(all(r[k] is False for k in ("hidden_registry_loaded", "official_prompt_consumed",
                                                  "production_corpus_loaded", "reference_set_loaded")))
        self.assertIn("INFRASTRUCTURE_ONLY", r["ci_provenance_git_subprocesses"])

    def test_r8_success_trace_is_complete(self):
        t = self.observed["observations"][0]["proxy_trace"]
        self.assertEqual("SUCCEEDED", t["status"])
        self.assertEqual(10, t["result_count"])
        self.assertEqual(1, t["call_number"])
        self.assertEqual(q.TRANSPARENT_QUERY, t["query"])
        self.assertEqual(nfr.BACKEND_ID, t["backend_id"])
        self.assertTrue(t["backend_request_id"] and t["started_at_utc"])
        self.assertEqual(7.0, t["duration_ms"])
        self.assertEqual(q.TIMING_MODE, self.observed["timing_mode"])

    def test_r8_failure_trace_and_no_hidden_retry(self):
        t = self.observed["failure_trace"]
        self.assertEqual("FAILED", t["status"])
        self.assertEqual("INJECTED_LOCAL_FAILURE", t["error_code"])
        self.assertEqual("SearchBackendError", t["error_type"])
        self.assertTrue(t["retryable"])
        self.assertEqual((0, 1, 0), (t["result_count"], t["backend_attempts"], t["automatic_retries"]))
        self.assertTrue(t["error_message"] and t["backend_request_id"] and t["started_at_utc"])

    def test_r8_failure_consumes_one_ticket_budget_rejection_no_attempt(self):
        attempts = []
        def fail(request):
            attempts.append(request)
            raise SearchBackendError("controlled local fixture failure", backend_id=nfr.BACKEND_ID,
                request_id=request.request_id, error_code="INJECTED_LOCAL_FAILURE", retryable=True)
        proxy = BudgetedSearchProxy("fixture", 1, fail)
        with q.external_guard(), self.assertRaises(SearchBackendError):
            proxy.search("local failure probe")
        with self.assertRaises(SearchBudgetExceeded):
            proxy.search("local failure probe")
        self.assertEqual(1, len(attempts))
        self.assertEqual(1, proxy.calls_used)

    def test_all_eight_pass_goes_through_protocol_gate(self):
        qual = self.bundle["qualification"]
        self.assertEqual({"PASS"}, {c["status"] for c in qual["criteria"].values()})
        result, retriever = q.criterion_gate(qual["criteria"], self.bundle["evidence"]["items"])
        self.assertEqual("F1_ELIGIBLE", result)
        self.assertEqual(result, f1_eligibility(retriever))
        self.assertEqual(retriever, qual["protocol_retriever"])

    def test_each_single_fail_or_unknown_is_not_eligible(self):
        for key in q.CRITERIA:
            for status in ("FAIL", "UNKNOWN"):
                criteria = deepcopy(self.bundle["qualification"]["criteria"])
                criteria[key]["status"] = status
                result, retriever = q.criterion_gate(criteria, self.bundle["evidence"]["items"])
                with self.subTest(key=key, status=status):
                    self.assertEqual("NOT_F1_ELIGIBLE", result)
                    self.assertEqual(result, f1_eligibility(retriever))

    def test_missing_criterion_or_invalid_status_rejected(self):
        criteria = deepcopy(self.bundle["qualification"]["criteria"])
        del criteria["R8"]
        with self.assertRaisesRegex(ValueError, "EXACTLY_R1_R8_REQUIRED"):
            q.criterion_gate(criteria, self.bundle["evidence"]["items"])
        criteria = deepcopy(self.bundle["qualification"]["criteria"])
        criteria["R1"]["status"] = "GREEN"
        with self.assertRaisesRegex(ValueError, "CRITERION_SCHEMA_INVALID"):
            q.criterion_gate(criteria, self.bundle["evidence"]["items"])

    def test_pass_requires_non_history_active_evidence(self):
        evidence = [seal({**e, "history_only": True}) for e in self.bundle["evidence"]["items"]]
        with self.assertRaisesRegex(ValueError, "PASS_REQUIRES_ACTIVE_EVIDENCE"):
            q.criterion_gate(self.bundle["qualification"]["criteria"], evidence)

    def test_missing_duplicate_dangling_evidence_rejected(self):
        original = self.bundle["evidence"]["items"]
        for evidence in (original[1:], original + [original[0]]):
            with self.assertRaises(ValueError):
                q.criterion_gate(self.bundle["qualification"]["criteria"], evidence)
        for ids in ([], ["E_ABSENT"], ["E_IMPL", "E_IMPL"]):
            criteria = deepcopy(self.bundle["qualification"]["criteria"])
            criteria["R1"]["evidence_ids"] = ids
            with self.assertRaisesRegex(ValueError, "CRITERION_EVIDENCE_INVALID"):
                q.criterion_gate(criteria, original)

    def test_evidence_requires_sealed_identity_and_scope(self):
        original = self.bundle["evidence"]["items"][0]
        for key in ("scope_limitation", "supported_proposition", "source_locator", "source_identity", "observation_status"):
            changed = deepcopy(original)
            changed.pop(key)
            with self.subTest(key=key), self.assertRaises(ValueError):
                q.validate_evidence(seal(changed))
        with self.assertRaises(ValueError):
            q.validate_evidence({**original, "supported_proposition": "changed"})

    def test_each_evidence_link_is_resolved_and_non_history(self):
        items = self.bundle["evidence"]["items"]
        self.assertEqual(15, len(items))
        by_id = {e["evidence_id"]: e for e in items}
        self.assertEqual(len(items), len(by_id))
        for c in self.bundle["qualification"]["criteria"].values():
            self.assertTrue(c["proposition"] and c["limitation"])
            self.assertTrue(all(not by_id[i]["history_only"] for i in c["evidence_ids"]))

    def test_validator_performs_zero_calls(self):
        before = dict(self.counts)
        q.validate_bundle(self.bundle)
        self.assertEqual(before, self.counts)

    def test_resealed_false_observation_cannot_be_accepted(self):
        changed = deepcopy(self.bundle)
        changed["runtime"]["pass_receipts"][0]["observations"][0]["request"]["query"] = "changed"
        changed["runtime"]["pass_receipts"][0] = seal(changed["runtime"]["pass_receipts"][0])
        changed["runtime"] = seal(changed["runtime"])
        with self.assertRaisesRegex(ValueError, "QUALIFICATION_PACKAGE_MUTATED"):
            q.validate_bundle(changed)

    def test_resealing_cannot_promote_acceptance_or_execution(self):
        for field, value in (("independent_acceptance", "PASS"), ("formal_f1_status", "F1_ELIGIBLE"),
                             ("t5_execution_authorized", True), ("e1_execution_authorized", True),
                             ("live_execution_authorized", True), ("claims_ceiling", "MODEL_QUALITY")):
            changed = deepcopy(self.bundle)
            for key in changed:
                if field in changed[key]:
                    changed[key] = seal({**changed[key], field: value})
            changed["receipt"] = seal({**changed["receipt"], "package_fingerprint": fingerprint(
                {key: val["canonical_fingerprint"] for key, val in changed.items() if key != "receipt"})})
            with self.subTest(field=field), self.assertRaises(ValueError):
                q.validate_bundle(changed)

    def test_resealing_cannot_change_zero_accounting(self):
        for field, value in (("network_calls", 1), ("qualification_fixture_retriever_calls", 0), ("production_corpus_loaded", True)):
            changed = deepcopy(self.bundle)
            changed["resources"] = seal({**changed["resources"], field: value})
            with self.subTest(field=field), self.assertRaises(ValueError):
                q.validate_bundle(changed)

    def test_package_seals_and_cross_payload_identity(self):
        for p in self.bundle.values():
            verify_seal(p)
        expected = fingerprint({k: v["canonical_fingerprint"] for k, v in self.bundle.items() if k != "receipt"})
        self.assertEqual(expected, self.bundle["receipt"]["package_fingerprint"])
        self.assertEqual(self.bundle["evidence"]["canonical_fingerprint"], self.bundle["qualification"]["evidence_fingerprint"])

    def test_six_payload_manifest_and_immutable_output(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "package"
            report = q.write_bundle(path)
            self.assertEqual(self.bundle["receipt"], report)
            self.assertEqual(set(q.PAYLOADS.values()) | {"MANIFEST.sha256"}, {p.name for p in path.iterdir()})
            lines = (path / "MANIFEST.sha256").read_text().splitlines()
            self.assertEqual(6, len(lines))
            for line in lines:
                digest, name = line.split("  ")
                self.assertEqual(digest, hashlib.sha256((path / name).read_bytes()).hexdigest())
            before = dict(self.counts)
            with self.assertRaises(FileExistsError):
                q.write_bundle(path)
            self.assertEqual(before, self.counts)

    def test_cli_receipt_and_mismatch_exit(self):
        args = ["receipt", "--expected-source-sha", q.BASELINE_SHA, "--expected-source-tree", q.BASELINE_TREE]
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(0, q.main(args))
        self.assertEqual(self.bundle["receipt"], json.loads(out.getvalue()))
        with patch.object(q.unicodedata, "unidata_version", "15.0.0"), redirect_stdout(io.StringIO()) as out:
            self.assertEqual(2, q.main(args))
        self.assertEqual("TARGET_IDENTITY_MISMATCH", json.loads(out.getvalue())["reason_code"])

    def test_cli_has_no_execution_or_approval_switch(self):
        with patch("sys.stderr", io.StringIO()), self.assertRaises(SystemExit):
            q.main(["run", "--approve"])

    def test_workflow_pr_only_exact_head_and_python311(self):
        text = (ROOT / ".github/workflows/t3-f1-retriever-qualification-r2-offline.yml").read_text()
        self.assertIn("pull_request:", text)
        self.assertNotIn("workflow_dispatch", text)
        self.assertNotIn("secrets.", text)
        self.assertIn('python-version: "3.11"', text)
        self.assertIn('unicodedata.unidata_version == "14.0.0"', text)
        self.assertIn("ref: ${{ github.event.pull_request.head.sha }}", text)
        self.assertIn("persist-credentials: false", text)
        self.assertIn("q.APPROVED_PATHS", text)
        self.assertIn("q.validate_bundle", text)


if __name__ == "__main__":
    unittest.main()
