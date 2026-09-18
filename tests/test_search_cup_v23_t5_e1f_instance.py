"""T5 authoring conformance and adversarial mutation checks, with zero query execution."""
import ast
from collections import Counter
from copy import deepcopy
from contextlib import redirect_stdout, redirect_stderr
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from search_cup.contracts import canonical_json, fingerprint
from search_cup.protocol_v23 import SearchSpecV2, REQUIRED_CONTROLS, f1_eligibility, instance_gate, seal, verify_seal
from search_cup import v23_t5_e1f_instance as t
from search_cup import v23_t3_f1q_r2 as q
from search_cup import v23_frozen_retriever as nfr
from search_cup.tools import BudgetedSearchProxy

ROOT = Path(__file__).resolve().parents[1]


class T5AuthoringTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.counts = {"local_fixture_retriever_calls": 0, "proxy_calls": 0,
                      "negative_guard_blocked_attempts": 0, "infrastructure_git_calls": 0}
        def forbidden(name):
            def deny(*args, **kwargs):
                cls.counts[name] += 1
                raise AssertionError("NO_QUERY_EXECUTION_IN_T5_TESTS")
            return deny
        for obj, name, counter in ((nfr.FrozenLexicalRetriever, "__call__", "local_fixture_retriever_calls"),
                                   (BudgetedSearchProxy, "search", "proxy_calls")):
            p = patch.object(obj, name, side_effect=forbidden(counter))
            p.start()
            cls.addClassCleanup(p.stop)
        cls.bundle = t.build_bundle()
        cls.spec = SearchSpecV2.from_mapping(cls.bundle["searchspec"])
        cls.config = json.loads((ROOT / t.CONFIG_PATH).read_text())

    @classmethod
    def tearDownClass(cls):
        print("T5_TEST_COUNTS=" + canonical_json(cls.counts))

    def copy_inputs(self, root):
        for name in (*self.config["source_pins"], t.MODULE_PATH, t.CONFIG_PATH, t.CORPUS_PATH, t.REFERENCE_PATH):
            dest = root / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes((ROOT / name).read_bytes())

    def test_exact_baseline_and_seven_additions(self):
        self.assertEqual({"sha": "4785c392eb0b9e5d04c8eef04289a4888c222839",
                          "tree": "07849a3696009c47d284b896fd3f1676f617e98b"}, t.baseline())
        self.assertEqual(7, len(t.APPROVED_PATHS))
        self.assertEqual(set(t.APPROVED_PATHS), {t.MODULE_PATH, t.CONFIG_PATH, t.CORPUS_PATH, t.REFERENCE_PATH,
            "tests/test_search_cup_v23_t5_e1f_instance.py", "docs/search-cup-v23-t5-e1f-pv-001.md",
            ".github/workflows/t5-e1f-instance-offline.yml"})

    def test_actual_git_scope_has_no_existing_edits(self):
        # Repository provenance only, outside the authoring guard; no credentials.
        def git(*args):
            self.counts["infrastructure_git_calls"] += 1
            return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()
        if git("rev-parse", "--is-shallow-repository") == "true":
            self.skipTest("Full-history scope proof runs in dedicated T5 CI; ordinary Test uses a shallow merge checkout.")
        self.assertEqual(t.BASELINE_TREE, git("rev-parse", t.BASELINE_SHA + "^{tree}"))
        git("merge-base", "--is-ancestor", t.BASELINE_SHA, "HEAD")
        changed = git("diff", "--name-status", t.BASELINE_SHA).splitlines()
        untracked = git("ls-files", "--others", "--exclude-standard").splitlines()
        self.assertEqual(sorted("A\t" + p for p in t.APPROVED_PATHS), sorted(changed + ["A\t" + p for p in untracked]))

    def test_baseline_drift_fails_before_input_reads(self):
        for kwargs in ({"expected_sha": "0" * 40}, {"expected_tree": "0" * 40}):
            with patch.object(Path, "read_bytes") as read, self.assertRaisesRegex(ValueError, "BASELINE_DRIFT"):
                t.build_bundle(**kwargs)
            read.assert_not_called()

    def test_all_retained_sources_are_byte_pinned(self):
        required = {q.MODULE_PATH, nfr.CODE_PATH, "search_cup/protocol_v23.py", "search_cup/v23_schema.py",
            "search_cup/contracts.py", "search_cup/tools.py", "search_cup/v23_t4_instance.py",
            "search_cup/v23_t4_execution.py", "search_cup/v23_t4_je1.py"}
        self.assertTrue(required <= set(self.config["source_pins"]))
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.copy_inputs(root)
            for name in self.config["source_pins"]:
                with self.subTest(path=name):
                    path = root / name
                    original = path.read_bytes()
                    path.write_bytes(original + b"\n")
                    with self.assertRaisesRegex(ValueError, "RETAINED_SOURCE_MUTATED"):
                        t.build_bundle(root=root)
                    path.write_bytes(original)

    def test_instance_config_cannot_expand_scope(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.copy_inputs(root)
            changed = deepcopy(self.config)
            changed["execution_allowed"] = True
            (root / t.CONFIG_PATH).write_text(canonical_json(changed))
            with self.assertRaisesRegex(ValueError, "INSTANCE_CONFIG_MISMATCH"):
                t.build_bundle(root=root)

    def test_wrong_python_and_unicode_fail_before_reads(self):
        for runtime in ({"python_major_minor": "3.12", "unicode_data_version": "14.0.0"},
                        {"python_major_minor": "3.11", "unicode_data_version": "15.0.0"}):
            with patch.object(q, "runtime_identity", return_value=runtime), patch.object(Path, "read_bytes") as read:
                with self.assertRaisesRegex(ValueError, "RUNTIME_MISMATCH"):
                    t.build_bundle()
                read.assert_not_called()

    def test_changed_loaded_authoring_module_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.copy_inputs(root)
            (root / t.MODULE_PATH).write_text("different implementation")
            with self.assertRaisesRegex(ValueError, "LOADED_AUTHORING_MODULE_MISMATCH"):
                t.build_bundle(root=root)

    def test_d1_d8_exact_statuses_and_resolved_authoring_approval(self):
        artifacts = self.bundle["manifest"]["artifacts"]
        decisions = self.bundle["bindings"]["decisions"]
        self.assertEqual({f"D{i}" for i in range(1, 9)}, set(decisions))
        for name, decision in decisions.items():
            if name in t.REQUIRED_DECISIONS:
                self.assertEqual("FROZEN", decision["status"])
                for key in ("artifact", "approval"):
                    digest = decision[key]["fingerprint"]
                    self.assertEqual(digest, fingerprint(artifacts[digest]))
                self.assertFalse(artifacts[decision["approval"]["fingerprint"]]["execution_allowed"])
            else:
                self.assertEqual("NOT_APPLICABLE", decision["status"])
                self.assertIsNone(decision["artifact"])
                self.assertIsNone(decision["approval"])

    def test_gate_complete_and_still_blocked(self):
        gate = instance_gate(self.spec, self.bundle["bindings"], self.bundle["manifest"]["artifacts"])
        self.assertEqual([], gate["missing_decisions"])
        self.assertEqual("BLOCKED", gate["terminal_status"])
        self.assertFalse(gate["execution_allowed"])
        self.assertEqual(["T1_IMPLEMENTATION_ONLY"], gate["reason_codes"])
        self.assertEqual(gate, self.bundle["receipt"]["instance_gate"])

    def test_missing_material_fails_closed_for_each_required_decision(self):
        for name in t.REQUIRED_DECISIONS:
            artifacts = deepcopy(self.bundle["manifest"]["artifacts"])
            del artifacts[self.bundle["bindings"]["decisions"][name]["artifact"]["fingerprint"]]
            gate = instance_gate(self.spec, self.bundle["bindings"], artifacts)
            self.assertEqual([name], gate["missing_decisions"])
            self.assertFalse(gate["execution_allowed"])

    def test_execution_flag_cannot_be_added_to_strict_bindings(self):
        altered = deepcopy(self.bundle["bindings"])
        altered["execution_allowed"] = True
        with self.assertRaises(ValueError):
            instance_gate(self.spec, seal(altered), self.bundle["manifest"]["artifacts"])

    def test_frozen_exact_searchspec_and_claims(self):
        doc = self.spec.as_dict()
        self.assertEqual((t.SPEC_ID, "FROZEN", "E1_FROZEN", "F1"),
                         tuple(doc[k] for k in ("spec_id", "spec_status", "track_id", "fairness_mode")))
        self.assertEqual("SYNTHETIC_FROZEN_RETRIEVAL_PROTOCOL_VALIDATION", doc["task"]["task_class"])
        self.assertEqual(["EXECUTION_ON_FROZEN_ENVIRONMENT"], doc["claims"])
        self.assertEqual(t.CLAIMS_CEILING, self.bundle["output"]["claims_ceiling"])
        self.assertFalse(self.bundle["receipt"]["benchmark_claim"])
        self.assertFalse(self.bundle["receipt"]["model_quality_claim"])

    def test_adding_generic_absolute_recall_claim_is_not_this_instance(self):
        mutated = deepcopy(self.bundle)
        mutated["searchspec"]["claims"].append("ABSOLUTE_RECALL")
        mutated["searchspec"] = seal(mutated["searchspec"])
        SearchSpecV2.from_mapping(mutated["searchspec"])  # legal generic protocol, outside this narrower WO
        with self.assertRaisesRegex(ValueError, "T5_PACKAGE_MUTATED"):
            t.validate_bundle(mutated)

    def test_control_hashes_resolve_concrete_material(self):
        fixed = self.spec.as_dict()["variable_control"]["fixed"]
        self.assertEqual(REQUIRED_CONTROLS["E1_FROZEN"], set(fixed))
        for digest in fixed.values():
            self.assertEqual(digest, fingerprint(self.bundle["manifest"]["artifacts"][digest]))

    def test_all_new_protocol_references_resolve(self):
        doc = self.spec.as_dict()
        refs = [doc["overlay"][k] for k in ("corpus", "collection_provenance", "index", "reference_set", "reproduction_procedure")]
        refs += [doc["output_contract"], doc["judgment_contract"], doc["resources"]["retry_policy"],
                 self.bundle["output"]["evidence_contract"], self.bundle["output"]["environment"]]
        for ref in refs:
            self.assertEqual(ref["fingerprint"], fingerprint(self.bundle["manifest"]["artifacts"][ref["fingerprint"]]))

    def test_a0_not_scored_and_a1_remains_entrant_owned(self):
        doc = self.spec.as_dict()
        self.assertEqual("HUMAN_MODEL_CO_DESIGN", doc["a0"]["origin"])
        self.assertFalse(doc["a0"]["scored"])
        self.assertTrue(doc["a0"]["frozen"])
        self.assertEqual("ENTRANT", doc["a1"]["owner"])
        self.assertEqual(["QUERY_WORDING", "SYNONYMS", "SUBDIRECTION", "BOUNDED_REFINEMENT", "EVIDENCE_FOLLOWING"], doc["a1"]["allowed"])
        self.assertEqual(["TASK", "SCOPE", "BUDGET", "EVIDENCE", "UNKNOWN_RULE"], doc["a1"]["forbidden_mutations"])
        self.assertEqual("ENTRANT_MODEL_CONFIG", doc["variable_control"]["principal"])

    def test_corpus_is_exact_24_public_safe_literals(self):
        docs = self.bundle["corpus"]["documents"]
        self.assertEqual([f"t5-pv-doc-{i:03}" for i in range(1, 25)], [d["doc_id"] for d in docs])
        for doc in docs:
            self.assertEqual({"doc_id", "title", "url", "text"}, set(doc))
            self.assertEqual("https://example.invalid/t5-e1frozen-pv-001/" + doc["doc_id"], doc["url"])
        self.assertEqual(self.config["corpus_fingerprint"], nfr.FrozenCorpus(docs).canonical_fingerprint)
        self.assertFalse(self.bundle["provenance"]["external_sources_used"])
        self.assertFalse(self.bundle["provenance"]["randomness_used"])

    def test_reference_population_and_exact_reason_groups(self):
        rows = self.bundle["reference"]["labels"]
        self.assertEqual({"RELEVANT": 6, "NOT_RELEVANT": 16, "UNKNOWN": 2}, dict(Counter(r["label"] for r in rows)))
        self.assertEqual(["ALL_THREE_EXPLICIT"] * 6 + ["REMOTE_FORBIDDEN"] * 6 + ["PYTHON_NOT_REQUIRED"] * 6
                         + ["APPLICATIONS_CLOSED"] * 4 + ["REMOTE_UNKNOWN", "APPLICATION_STATUS_UNKNOWN"],
                         [r["reason_code"] for r in rows])

    def test_each_label_has_actual_frozen_evidence_and_three_conditions(self):
        docs = {d["doc_id"]: d for d in self.bundle["corpus"]["documents"]}
        rows = self.bundle["reference"]["labels"]
        self.assertEqual(set(docs), {r["doc_id"] for r in rows})
        for row in rows:
            doc = docs[row["doc_id"]]
            self.assertEqual(doc["url"] + "#text", row["evidence_locator"])
            self.assertEqual(self.config["corpus_fingerprint"], row["corpus_fingerprint"])
            self.assertEqual({"remote", "python_required", "applications_open"}, set(row["condition_evidence"]))
            states = []
            for condition in row["condition_evidence"].values():
                self.assertIn(condition["verbatim"], doc["text"])
                states.append(condition["state"])
            expected = "NOT_RELEVANT" if "FALSE" in states else "UNKNOWN" if "UNKNOWN" in states else "RELEVANT"
            self.assertEqual(expected, row["label"])

    def test_semantic_edge_cases_are_explicit_not_rank_labels(self):
        docs = self.bundle["corpus"]["documents"]
        self.assertIn("Working from home is allowed.", docs[1]["text"])
        self.assertIn("Python proficiency is welcomed but never mandatory.", docs[13]["text"])
        self.assertIn("Recruitment has ended; submissions are closed.", docs[20]["text"])
        self.assertIn("Work-location arrangements are unspecified.", docs[22]["text"])
        self.assertIn("current application status is unspecified", docs[23]["text"])
        self.assertEqual("UNKNOWN", self.bundle["reference"]["labels"][22]["label"])
        self.assertEqual("UNKNOWN", self.bundle["reference"]["labels"][23]["label"])
        self.assertIn("NOT_RETRIEVER_RANKINGS", self.bundle["reference"]["label_authority"])

    def test_modified_corpus_or_reference_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.copy_inputs(root)
            for name, reason in ((t.CORPUS_PATH, "CORPUS_INPUT_MISMATCH"), (t.REFERENCE_PATH, "REFERENCE_INPUT_MISMATCH")):
                path = root / name
                original = path.read_bytes()
                value = json.loads(original)
                if name == t.CORPUS_PATH:
                    value["documents"][0]["text"] = "No frozen evidence."
                else:
                    value["labels"][-1]["label"] = "NOT_RELEVANT"
                path.write_text(canonical_json(value))
                with self.assertRaisesRegex(ValueError, reason):
                    t.build_bundle(root=root)
                path.write_bytes(original)

    def test_duplicate_document_rejected_by_constructor(self):
        docs = deepcopy(self.bundle["corpus"]["documents"])
        docs[-1]["doc_id"] = docs[0]["doc_id"]
        with self.assertRaisesRegex(ValueError, "DUPLICATE_DOC_ID"):
            nfr.FrozenCorpus(docs)

    def test_private_locator_is_rejected_not_fetched(self):
        docs = deepcopy(self.bundle["corpus"]["documents"])
        docs[0]["url"] = "https://drive.google.com/synthetic-private-locator"
        with self.assertRaises(ValueError):
            nfr.FrozenCorpus(docs)

    def test_two_independent_index_builds_and_actual_content(self):
        item = self.bundle["index"]
        self.assertEqual([self.config["index_fingerprint"]] * 2, item["two_build_fingerprints"])
        self.assertEqual(item["index_fingerprint"], fingerprint(item["index_content"]))
        self.assertEqual(24, len(item["index_content"]["documents"]))
        self.assertEqual(10, item["result_limit"])
        self.assertEqual(t.DESCRIPTOR_FINGERPRINT, item["retriever_descriptor_fingerprint"])
        self.assertEqual(nfr.CONFIG_FINGERPRINT, item["config_fingerprint"])
        self.assertEqual(self.bundle["reproduction"]["canonical_fingerprint"], item["reproduction_procedure_fingerprint"])

    def test_reproduction_rejects_wrong_corpus_config_descriptor_and_index(self):
        _, _, _, _, corpus, config = t.resolve_inputs()
        good = {"expected_corpus": self.config["corpus_fingerprint"], "expected_index": self.config["index_fingerprint"]}
        cases = [(corpus, config, {**good, "expected_corpus": "0" * 64}, "CORPUS_FINGERPRINT_MISMATCH"),
                 (corpus, {}, good, "RETRIEVER_CONFIG_MISMATCH"),
                 (corpus, config, {**good, "descriptor_fingerprint": "0" * 64}, "DESCRIPTOR_MISMATCH"),
                 (corpus, config, {**good, "expected_index": "0" * 64}, "INDEX_FINGERPRINT_MISMATCH")]
        for c, conf, kwargs, reason in cases:
            with self.assertRaisesRegex(ValueError, reason):
                t.reproduce_index(c, conf, **kwargs)

    def test_corrupted_index_algorithm_not_accepted(self):
        _, _, _, _, corpus, config = t.resolve_inputs()
        with patch.object(nfr, "character_units", return_value=(("bad", 1),)):
            with self.assertRaisesRegex(ValueError, "INDEX_FINGERPRINT_MISMATCH"):
                t.reproduce_index(corpus, config, expected_corpus=self.config["corpus_fingerprint"],
                                  expected_index=self.config["index_fingerprint"])

    def test_roster_two_exact_not_connected_configs(self):
        roster = self.bundle["roster"]
        self.assertEqual(["t5-fixture-agent-a", "t5-fixture-agent-b"], [e["entrant_id"] for e in roster["entrants"]])
        for suffix, entry, config in zip(("a", "b"), roster["entrants"], roster["configurations"]):
            self.assertEqual(f"fixture-agent-{suffix}-v1", entry["requested_model_id"])
            self.assertEqual(entry["requested_model_id"], entry["resolved_model_id"])
            self.assertEqual("KNOWN", entry["resolution_status"])
            self.assertEqual("AS_REQUESTED", entry["identity_status"])
            self.assertIsNone(entry["alias_evidence"])
            self.assertEqual("synthetic-not-connected", entry["provider"])
            self.assertEqual("NOT_CONNECTED", entry["endpoint_mode"])
            self.assertIsNone(config["connection_details"])
            self.assertEqual(fingerprint(config), entry["config_fingerprint"])

    def test_exact_accepted_f1_binding_not_new_qualification(self):
        value = self.bundle["retriever"]
        self.assertEqual(t.ACCEPTED_F1Q_PACKAGE, value["historical_qualification_package"]["receipt"]["package_fingerprint"])
        self.assertEqual("F1_ELIGIBLE", f1_eligibility(self.spec.as_dict()["retriever"]))
        self.assertEqual(self.spec.as_dict()["retriever"], value["retriever"])
        d6 = self.bundle["bindings"]["decisions"]["D6"]["artifact"]["fingerprint"]
        self.assertEqual(value["retriever"], self.bundle["manifest"]["artifacts"][d6]["retriever"])
        self.assertEqual(t.DESCRIPTOR_FINGERPRINT, value["descriptor"]["canonical_fingerprint"])
        self.assertFalse(value["qualification_rerun"])

    def test_historical_qualification_evidence_resolves_without_queries(self):
        value = self.bundle["retriever"]
        evidence = {e["canonical_fingerprint"]: e for e in value["historical_qualification_package"]["evidence"]["items"]}
        for row in value["retriever"]["qualification"]["criteria"].values():
            self.assertEqual("PASS", row["status"])
            for ref in row["evidence"]:
                verify_seal(evidence[ref["fingerprint"]])
                self.assertEqual(ref["id"], evidence[ref["fingerprint"]]["evidence_id"])
        q.validate_bundle(value["historical_qualification_package"])

    def test_exact_resources_zero_retries_follow_links_fallback(self):
        r = self.spec.as_dict()["resources"]
        expected = {"max_search_calls": 4, "max_search_turns": 4, "max_results_per_call": 10,
            "max_follow_links": 0, "automatic_retries": 0, "timeout_per_call_ms": 1000,
            "manual_retry_policy": "FORBIDDEN", "search_unit": "RAW_BACKEND_ATTEMPT",
            "failure_policy": "INFRASTRUCTURE_NOT_QUALITY", "exhaustion_policy": "STOP_NO_EXPANSION",
            "budget_rejection_policy": "NO_BACKEND_NO_TICKET"}
        self.assertEqual(expected, {k: r[k] for k in expected})
        for key, value, unit in (("max_total_runtime_ms", 60000, "ms"), ("token_ceiling", 8000, "tokens"), ("money_ceiling", 0, "USD")):
            self.assertEqual(("KNOWN", value, unit), tuple(r[key][k] for k in ("state", "value", "unit")))
        self.assertEqual("NONE", self.bundle["resources"]["retry_policy"]["fallback_policy"])
        self.assertEqual(10, self.bundle["index"]["result_limit"])

    def test_environment_is_exact_runtime_predicate(self):
        env = self.bundle["environment"]
        self.assertEqual("t5-e1frozen-pv-001-offline-runtime-v1", env["environment_id"])
        self.assertEqual(("3.11", "14.0.0"), (env["python_major_minor"], env["unicode_data_version"]))
        self.assertEqual(t.baseline(), env["source_baseline"])
        for key in ("network_access", "provider_access", "model_access", "credential_access"):
            self.assertEqual("FORBIDDEN", env[key])
        self.assertTrue(env["future_execution_recheck_required"])

    def test_output_schema_freezes_identity_evidence_provenance(self):
        output = self.bundle["output"]
        fields = {"spec_fingerprint", "entrant_identity", "environment_fingerprint", "retriever_fingerprint",
            "resource_receipt_fingerprint", "query_call_provenance", "result_provenance", "results",
            "submission_fingerprint", "terminal_status"}
        self.assertEqual(fields, set(output["required_fields"]))
        self.assertEqual(fields, set(output["json_schema"]["required"]))
        self.assertFalse(output["json_schema"]["additionalProperties"])
        self.assertEqual(4, output["json_schema"]["properties"]["query_call_provenance"]["maxItems"])
        evidence = self.bundle["manifest"]["evidence_contract"]
        self.assertEqual("FORBIDDEN", evidence["outside_corpus_evidence"])
        self.assertEqual("FORBIDDEN", evidence["live_verification"])
        self.assertEqual(0, evidence["follow_links"])

    def test_reference_labels_not_in_entrant_prompt(self):
        prompt = self.bundle["manifest"]["prompt_context"]
        self.assertFalse(prompt["reference_labels_in_context"])
        self.assertNotIn("labels", prompt)
        self.assertNotIn("condition_evidence", canonical_json(prompt))
        self.assertNotIn("ALL_THREE_EXPLICIT", canonical_json(prompt))
        self.assertFalse(self.bundle["adjudication"]["reference_visible_to_entrant"])
        self.assertEqual("NONE", self.bundle["adjudication"]["judge_model"])

    def test_unknown_and_zero_denominator_contracts_are_explicit(self):
        adjudication = self.bundle["adjudication"]
        self.assertEqual("EXCLUDE_FROM_BINARY_TRUTH_DENOMINATORS_COUNT_SEPARATELY", adjudication["unknown_binary_denominator_policy"])
        self.assertEqual("NOT_EVALUABLE", adjudication["zero_denominator"])
        metrics = {m["metric_id"]: m for m in self.spec.as_dict()["metrics"]}
        self.assertEqual("6 frozen RELEVANT documents", metrics["Recall@Budget"]["denominator"])
        self.assertIn("without backfill", metrics["Precision@K"]["denominator"])
        self.assertIn("UNKNOWN_RETURN_COUNT", metrics)
        self.assertTrue(all(m["zero_denominator"] == "NOT_EVALUABLE" for m in metrics.values()))

    def test_zero_execution_receipt_is_separate_from_published_history(self):
        receipt = self.bundle["receipt"]
        for field in t.ZERO_FIELDS:
            self.assertEqual(0, receipt[field])
        for field in ("execution_allowed", "formal_e1_execution_performed", "official_prompt_consumed", "hidden_registry_loaded",
                      "benchmark_claim", "model_quality_claim", "live_web_claim", "qualification_probes_rerun", "metrics_executed"):
            self.assertIs(False, receipt[field])
        self.assertEqual((0, "USD"), (receipt["spend"]["value"], receipt["spend"]["unit"]))
        self.assertEqual("PENDING", receipt["independent_acceptance"])
        self.assertFalse(receipt["merge_authorized"])
        self.assertFalse(receipt["successor_execution_authorized"])

    def test_guards_reject_queries_before_any_backend(self):
        for target in ("search_cup.v23_frozen_retriever.FrozenLexicalRetriever.__call__", "search_cup.tools.BudgetedSearchProxy.search"):
            from pkgutil import resolve_name
            with t.authoring_guard() as attempts:
                with self.assertRaises(q.ExternalOperationBlocked):
                    resolve_name(target)(None, None)
                self.assertEqual(["QUERY_OR_EXECUTION"], attempts["query_or_execution"])
                self.counts["negative_guard_blocked_attempts"] += 1

    def test_guards_reject_network_model_runner_judge_environment(self):
        from pkgutil import resolve_name
        for target in ("socket.create_connection", "urllib.request.urlopen", "search_cup.runner.run_match",
                       "search_cup.judge.judge_match", "search_cup.search_pro.SearchProBackend.from_env", "os.getenv"):
            with t.authoring_guard() as attempts:
                with self.assertRaises(q.ExternalOperationBlocked):
                    resolve_name(target)("synthetic-probe")
                self.assertEqual(1, len(attempts["external"]))
                self.counts["negative_guard_blocked_attempts"] += 1

    def test_no_qualification_or_nfr_probe_rerun(self):
        from pkgutil import resolve_name
        for target in t.QUERY_GUARDS[2:]:
            with t.authoring_guard() as attempts:
                with self.assertRaises(q.ExternalOperationBlocked):
                    resolve_name(target)()
                self.counts["negative_guard_blocked_attempts"] += 1
        self.assertEqual(0, self.counts["local_fixture_retriever_calls"])
        self.assertEqual(0, self.counts["proxy_calls"])

    def test_module_ast_has_no_execution_imports(self):
        tree = ast.parse((ROOT / t.MODULE_PATH).read_text())
        forbidden = {"os", "subprocess", "socket", "requests", "httpx", "runner", "judge", "providers", "search_pro"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                self.assertFalse(any(a.name.split(".")[0] in forbidden for a in node.names))
            if isinstance(node, ast.ImportFrom):
                self.assertFalse(set((node.module or "").split(".")) & forbidden)

    def test_two_full_bundles_are_canonical_byte_identical(self):
        one, two = t.build_bundle(), t.build_bundle()
        self.assertEqual(canonical_json(one).encode(), canonical_json(two).encode())
        self.assertEqual(canonical_json(self.bundle), canonical_json(one))
        t.validate_bundle(one)

    def test_all_top_seals_and_package_fingerprints_validate(self):
        for payload in self.bundle.values():
            verify_seal(payload)
        expected = fingerprint({t.PAYLOADS[k]: v["canonical_fingerprint"] for k, v in self.bundle.items() if k != "receipt"})
        self.assertEqual(expected, self.bundle["receipt"]["package_fingerprint"])
        for digest, material in self.bundle["manifest"]["artifacts"].items():
            self.assertEqual(digest, fingerprint(material))

    def test_resealed_nested_material_tamper_still_rejected(self):
        for key in ("reference", "resources", "roster", "environment", "receipt"):
            mutated = deepcopy(self.bundle)
            mutated[key]["unapproved_extension"] = True
            mutated[key] = seal(mutated[key])
            with self.subTest(payload=key), self.assertRaisesRegex(ValueError, "T5_PACKAGE_MUTATED"):
                t.validate_bundle(mutated)

    def test_write_validate_and_final_byte_manifest(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory) / "instance"
            receipt = t.write_bundle(out)
            self.assertEqual(receipt, t.validate_directory(out))
            lines = (out / "MANIFEST.sha256").read_text().splitlines()
            self.assertEqual(15, len(lines))
            for line in lines:
                digest, name = line.split("  ")
                self.assertEqual(digest, hashlib.sha256((out / name).read_bytes()).hexdigest())
            with self.assertRaises(FileExistsError):
                t.write_bundle(out)
            (out / "ci-source.json").write_text('{"synthetic_test_only":true}')
            (out / "focused-tests.log").write_text("synthetic test log\n")
            self.assertEqual(17, len(t.write_manifest(out).splitlines()))
            t.validate_directory(out)
            (out / "corpus.json").write_bytes((out / "corpus.json").read_bytes() + b" ")
            with self.assertRaisesRegex(ValueError, "ARTIFACT_BYTE_MANIFEST_MISMATCH"):
                t.validate_directory(out)

    def test_unexpected_or_nonregular_artifact_file_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            for key, name in t.PAYLOADS.items():
                (out / name).write_text(canonical_json(self.bundle[key]))
            t.write_manifest(out)
            (out / "extra.json").write_text("{}")
            with self.assertRaisesRegex(ValueError, "ARTIFACT_FILE_SET_MISMATCH"):
                t.validate_directory(out)
            (out / "extra.json").unlink()
            (out / "corpus.json").unlink()
            (out / "corpus.json").symlink_to(ROOT / t.CORPUS_PATH)
            with self.assertRaisesRegex(ValueError, "ARTIFACT_NONREGULAR_FILE"):
                t.validate_directory(out)

    def test_cli_requires_explicit_baseline_and_has_no_execute_flag(self):
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            t.main(["receipt"])
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            t.main(["execute", "--expected-source-sha", t.BASELINE_SHA, "--expected-source-tree", t.BASELINE_TREE])
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            t.main(["receipt", "--expected-source-sha", t.BASELINE_SHA, "--expected-source-tree", t.BASELINE_TREE])
        self.assertFalse(json.loads(stdout.getvalue())["execution_allowed"])

    def test_dedicated_workflow_pr_only_exact_head_no_secret(self):
        text = (ROOT / ".github/workflows/t5-e1f-instance-offline.yml").read_text()
        self.assertIn("name: T5 E1 Frozen Instance Offline", text)
        self.assertIn("  pull_request:", text)
        self.assertNotIn("workflow_dispatch", text)
        self.assertNotIn("secrets.", text)
        self.assertNotIn("contents: write", text)
        self.assertIn("ref: ${{ github.event.pull_request.head.sha }}", text)
        self.assertIn("persist-credentials: false", text)
        self.assertIn("SCOPE_AMENDMENT_REQUIRED", text)
        self.assertIn("BASELINE_DRIFT", text)
        self.assertIn("--is-ancestor", text)
        for name in t.APPROVED_PATHS:
            self.assertIn(name, text)


if __name__ == "__main__":
    unittest.main()
