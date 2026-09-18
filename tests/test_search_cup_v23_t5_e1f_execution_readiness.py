"""EX0 authoring and pure synthetic phrase tests; never an entrant or retriever replay."""
import ast
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from copy import deepcopy
import dis
import hashlib
import io
import json
from pathlib import Path
from pkgutil import resolve_name
import tempfile
from types import CodeType
import unittest
from unittest.mock import patch

from search_cup.contracts import SearchResult, canonical_json
from search_cup.protocol_v23 import seal, verify_seal
from search_cup import v23_t5_e1f_execution_readiness as t

ROOT = Path(__file__).resolve().parents[1]


class ExecutionReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.counts = {"retriever_query_calls": 0, "proxy_calls": 0,
                      "pure_synthetic_decisions": 0, "negative_guard_blocked_attempts": 0}
        def blocked(name):
            def deny(*args, **kwargs):
                cls.counts[name] += 1
                raise AssertionError("EX0_TEST_QUERY_FORBIDDEN")
            return deny
        for target, counter in zip(t.parent.QUERY_GUARDS[:2], ("retriever_query_calls", "proxy_calls")):
            p = patch(target, side_effect=blocked(counter))
            p.start()
            cls.addClassCleanup(p.stop)
        cls.bundle = t.build_bundle()
        cls.parent = t.parent.build_bundle()
        cls.expected = cls.bundle["binding"]["canonical_fingerprint"]
        cls.method_hash = hashlib.sha256((ROOT / t.MODULE_PATH).read_bytes()).hexdigest()

    @classmethod
    def tearDownClass(cls):
        print("EX0_TEST_COUNTS=" + canonical_json(cls.counts))

    def decision(self, text="", *, title="Synthetic test", url="https://example.invalid/unit"):
        self.counts["pure_synthetic_decisions"] += 1
        return t.visible_decision(SearchResult(title, url, text))

    def components(self):
        return {k: deepcopy(self.bundle[k]) for k in t.COMPONENTS}

    def copy_sources(self, root):
        for name in (*t.SOURCE_PINS, t.MODULE_PATH):
            path = root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((ROOT / name).read_bytes())

    def test_exact_authorized_baseline(self):
        self.assertEqual({"sha": "a583f6042dbfd78d251434141cdbf9b86cb910a9",
                          "tree": "669c6cb0785aaa5cead04d0b009c14f70a7d98af"}, t.baseline())

    def test_exact_four_added_paths(self):
        paths = {"search_cup/v23_t5_e1f_execution_readiness.py",
            "tests/test_search_cup_v23_t5_e1f_execution_readiness.py",
            "docs/search-cup-v23-t5-e1f-execution-readiness.md",
            ".github/workflows/t5-e1f-execution-readiness-offline.yml"}
        self.assertEqual(paths, set(t.APPROVED_PATHS))
        self.assertEqual([], t.scope_gate(["A\t" + p for p in paths])["modified_paths"])

    def test_scope_rejects_existing_edit_extra_missing_and_duplicate(self):
        good = ["A\t" + p for p in t.APPROVED_PATHS]
        for bad in (good + ["A\textra.py"], good[:-1], good + good[:1],
                    [good[0].replace("A\t", "M\t")] + good[1:]):
            with self.subTest(rows=bad), self.assertRaisesRegex(ValueError, "SCOPE_AMENDMENT_REQUIRED"):
                t.scope_gate(bad)

    def test_wrong_baseline_precedes_reads(self):
        for kw in ({"expected_sha": "0" * 40}, {"expected_tree": "0" * 40}):
            with patch.object(Path, "read_bytes") as read, self.assertRaisesRegex(ValueError, "BASELINE_DRIFT"):
                t.build_bundle(**kw)
            read.assert_not_called()

    def test_wrong_runtime_precedes_reads(self):
        for version in (dict(python_major_minor="3.12", unicode_data_version="14.0.0"),
                        dict(python_major_minor="3.11", unicode_data_version="15.0.0")):
            with patch.object(t.parent.qualification, "runtime_identity", return_value=version), \
                 patch.object(Path, "read_bytes") as read, self.assertRaisesRegex(ValueError, "RUNTIME_MISMATCH"):
                t.build_bundle()
            read.assert_not_called()

    def test_all_published_parent_pins(self):
        for key, expected in t.PARENT_PINS.items():
            self.assertEqual(expected, self.parent["receipt"][key])
        self.assertEqual("dd4742c12343b602a1f755093cc7267b442fae2fa5cbb96570f7a5107bd227bf", t.PARENT_PINS["package_fingerprint"])
        self.assertEqual(t.PARENT_PINS, self.bundle["parent"]["exact_pins"])
        t.validate_parent(self.parent)

    def test_each_parent_receipt_pin_mutation_rejected_even_resealed(self):
        for key in t.PARENT_PINS:
            with self.subTest(pin=key):
                bad = deepcopy(self.parent)
                bad["receipt"][key] = "0" * 64
                if key != "canonical_fingerprint":
                    bad["receipt"] = seal(bad["receipt"])
                with self.assertRaises(ValueError):
                    t.validate_parent(bad)

    def test_every_parent_component_mutation_rejected_even_resealed(self):
        for key in t.parent.PAYLOADS:
            if key == "receipt":
                continue
            with self.subTest(component=key):
                bad = deepcopy(self.parent)
                bad[key]["unauthorized_mutation"] = True
                bad[key] = seal(bad[key])
                with self.assertRaisesRegex(ValueError, "PARENT_PACKAGE_DRIFT"):
                    t.validate_parent(bad)

    def test_parent_shape_and_invalid_seal_rejected(self):
        bad = deepcopy(self.parent)
        del bad["reference"]
        with self.assertRaises(ValueError):
            t.validate_parent(bad)
        bad = deepcopy(self.parent)
        bad["receipt"]["canonical_fingerprint"] = "0" * 64
        with self.assertRaises(ValueError):
            t.validate_parent(bad)

    def test_each_retained_source_byte_mutation_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.copy_sources(root)
            for name in t.SOURCE_PINS:
                with self.subTest(path=name):
                    path = root / name
                    original = path.read_bytes()
                    path.write_bytes(original + b"\n")
                    with self.assertRaisesRegex(ValueError, "RETAINED_SOURCE_MUTATED"):
                        t.build_bundle(root=root)
                    path.write_bytes(original)

    def test_loaded_method_must_match_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.copy_sources(root)
            (root / t.MODULE_PATH).write_text("different method")
            with self.assertRaisesRegex(ValueError, "LOADED_METHOD_MISMATCH"):
                t.build_bundle(root=root)

    def test_successor_is_distinct_and_parent_gate_remains_blocked(self):
        b = self.bundle["binding"]
        self.assertEqual("T5-E1FROZEN-PV-001-EXEC-V1", b["execution_id"])
        self.assertNotEqual(b["execution_id"], b["parent_instance_id"])
        self.assertEqual("SYNTHETIC_FIXTURE_REPLAY", b["execution_class"])
        gate = self.bundle["receipt"]["parent_gate"]
        self.assertEqual([], gate["missing_decisions"])
        self.assertEqual(["T1_IMPLEMENTATION_ONLY"], gate["reason_codes"])
        self.assertFalse(gate["execution_allowed"])

    def test_current_authoring_approval_does_not_authorize_execution(self):
        b = self.bundle["binding"]
        self.assertEqual(t.WORK_ORDER + "批准并施工", b["authoring_approval"]["preconstruction_user_instruction"])
        self.assertFalse(b["authoring_approval"]["execution_permission"])
        self.assertFalse(b["successor_execution_authorized"])
        self.assertFalse(b["merge_authorized"])

    def test_fixture_identities_are_unchanged_parent_entries(self):
        for key, entrant in zip(("profile_a", "profile_b"), self.parent["roster"]["entrants"]):
            self.assertEqual(entrant, self.bundle[key]["parent_identity"])
            self.assertEqual("DETERMINISTIC_LOCAL_FIXTURE_NOT_MODEL", self.bundle[key]["program_class"])
            self.assertEqual(0, self.bundle[key]["formal_invocations"])

    def test_each_fixture_behavior_changes_binding(self):
        for key in ("profile_a", "profile_b"):
            changed = self.components()
            changed[key]["query_schedule"][0]["query"] += " changed"
            changed[key] = seal(changed[key])
            self.assertNotEqual(self.expected, t.execution_binding(changed, self.method_hash)["canonical_fingerprint"])

    def test_all_nine_component_fingerprints_are_committed(self):
        self.assertEqual(9, len(t.COMPONENTS))
        for key in t.COMPONENTS:
            with self.subTest(component=key):
                changed = self.components()
                changed[key]["change"] = "would require new review"
                changed[key] = seal(changed[key])
                self.assertNotEqual(self.expected, t.execution_binding(changed, self.method_hash)["canonical_fingerprint"])

    def test_implementation_and_component_set_are_bound(self):
        self.assertNotEqual(self.expected, t.execution_binding(self.components(), "0" * 64)["canonical_fingerprint"])
        parts = self.components()
        del parts["policy"]
        with self.assertRaises(ValueError):
            t.execution_binding(parts, self.method_hash)

    def test_exact_a_query_schedule(self):
        self.assertEqual(["remote work", "python required", "applications open", "remote python applications open"],
            [q["query"] for q in self.bundle["profile_a"]["query_schedule"]])
        self.assertEqual("BROAD_DECOMPOSED_QUERY_V1", self.bundle["profile_a"]["profile_id"])

    def test_exact_b_query_schedule(self):
        self.assertEqual(["working from home python mandatory accepting applications", "fully remote python recruitment open",
            "telecommuting python required applications accepted", "home-based python recruiting open"],
            [q["query"] for q in self.bundle["profile_b"]["query_schedule"]])
        self.assertEqual("SYNONYM_SWEEP_QUERY_V1", self.bundle["profile_b"]["profile_id"])

    def test_queries_are_nonadaptive_and_first_seen_deduplicated(self):
        q = self.bundle["queries"]
        self.assertFalse(q["adaptive_queries"])
        self.assertTrue(q["queries_planned_before_started"])
        self.assertEqual(1, q["max_attempts_per_query"])
        self.assertEqual("DEDUPLICATE_BY_EXACT_FROZEN_URL_DOC_ID_KEEP_FIRST_QUERY_THEN_RANK", q["union_policy"])
        for p in q["profiles"]:
            self.assertEqual([1, 2, 3, 4], [item["query_number"] for item in p["queries"]])

    def test_every_true_phrase_in_each_visible_field(self):
        for predicate, yes, _ in t.PHRASES:
            for phrase in yes:
                for field in ("title", "url", "snippet"):
                    values = dict(title="Synthetic", url="https://example.invalid/unit", text="")
                    values["text" if field == "snippet" else field] = phrase
                    with self.subTest(predicate=predicate, phrase=phrase, field=field):
                        self.assertEqual("TRUE", self.decision(**values)["predicates"][predicate]["state"])

    def test_every_negative_phrase_blocks_match(self):
        for predicate, _, no in t.PHRASES:
            for phrase in no:
                with self.subTest(predicate=predicate, phrase=phrase):
                    result = self.decision(phrase)
                    self.assertEqual("FALSE", result["predicates"][predicate]["state"])
                    self.assertEqual("DO_NOT_RETURN", result["decision"])

    def test_all_true_is_match(self):
        d = self.decision("Remote work is permitted. Python is required. Applications are open.")
        self.assertEqual(("TRUE", "RETURN_AS_MATCH"), (d["truth_state"], d["decision"]))

    def test_no_phrase_and_partial_evidence_remain_unknown(self):
        for text in ("Unspecified job announcement", "Remote work is permitted. Python is required."):
            d = self.decision(text)
            self.assertEqual(("UNKNOWN", "DO_NOT_RETURN"), (d["truth_state"], d["decision"]))
            self.assertEqual("INSUFFICIENT_VISIBLE_EVIDENCE", d["predicates"]["applications_open"]["reason_code"])

    def test_contradiction_in_each_predicate_is_unknown(self):
        for name, yes, no in t.PHRASES:
            result = self.decision(yes[0], title=no[0])["predicates"][name]
            self.assertEqual("UNKNOWN", result["state"])
            self.assertEqual("CONTRADICTORY_VISIBLE_EVIDENCE", result["reason_code"])

    def test_false_takes_precedence_over_other_unknown(self):
        result = self.decision("Remote work is permitted. remote work is forbidden Python is not required")
        self.assertEqual("UNKNOWN", result["predicates"]["remote"]["state"])
        self.assertEqual("FALSE", result["truth_state"])
        self.assertEqual("DO_NOT_RETURN", result["decision"])

    def test_exact_case_punctuation_and_no_cross_field_normalization(self):
        for text in ("remote work is permitted.", "Remote work is permitted", "Ｒemote work is permitted."):
            self.assertEqual("UNKNOWN", self.decision(text)["predicates"]["remote"]["state"])
        d = self.decision("permitted.", title="Remote work is")
        self.assertEqual("UNKNOWN", d["predicates"]["remote"]["state"])

    def test_decision_has_no_io_peer_or_reference_dependency(self):
        allowed = {"type", "SearchResult", "any", "str", "ValueError", "PHRASES", "bool", "all"}
        def inspect(code):
            for instruction in dis.get_instructions(code):
                if instruction.opname in {"LOAD_GLOBAL", "LOAD_NAME"}:
                    self.assertIn(instruction.argval, allowed)
            for value in code.co_consts:
                if isinstance(value, CodeType):
                    inspect(value)
        inspect(t.visible_decision.__code__)
        record = SearchResult("Synthetic", "https://example.invalid/unit", "Python is required.")
        with ExitStack() as stack:
            mocks = [stack.enter_context(patch(name, side_effect=AssertionError("FORBIDDEN_INPUT"))) for name in
                ("builtins.open", "pathlib.Path.read_text", "pathlib.Path.read_bytes", "os.getenv", "socket.create_connection",
                 "search_cup.v23_t5_e1f_instance.build_bundle")]
            self.counts["pure_synthetic_decisions"] += 1
            self.assertEqual("TRUE", t.visible_decision(record)["predicates"]["python_required"]["state"])
            for mock in mocks:
                mock.assert_not_called()

    def test_extra_inputs_subclasses_and_nonstring_fields_rejected(self):
        with self.assertRaises(TypeError):
            t.visible_decision(SearchResult("T", "U", ""), peer_state={})
        class UntrustedResult(SearchResult):
            pass
        for bad in ({"title": "T", "url": "U", "snippet": ""}, UntrustedResult("T", "U", ""), SearchResult("T", "U", None)):
            with self.assertRaises(ValueError):
                t.visible_decision(bad)

    def test_mutating_decision_result_does_not_mutate_future_policy(self):
        first = self.decision("Python is required.")
        first["predicates"]["python_required"]["positive_matches"].clear()
        self.assertEqual(["Python is required."], self.decision("Python is required.")["predicates"]["python_required"]["positive_matches"])

    def test_profiles_exclude_peer_and_labels(self):
        for key in ("profile_a", "profile_b"):
            p = self.bundle[key]
            self.assertEqual(["title", "url", "snippet"], p["input_fields"])
            for field in ("reference_material_access", "peer_state_access", "external_reads", "credential_access"):
                self.assertEqual("FORBIDDEN", p[field])
            self.assertIsNone(p["api_endpoint"])

    def test_resource_envelope_exact_and_isolated(self):
        r = self.bundle["resources"]
        self.assertEqual(self.parent["resources"]["resources"], r["identical_envelope"])
        e = r["identical_envelope"]
        for key, value in (("max_search_calls", 4), ("max_search_turns", 4), ("max_results_per_call", 10),
                           ("max_follow_links", 0), ("automatic_retries", 0), ("timeout_per_call_ms", 1000)):
            self.assertEqual(value, e[key])
        for key, value in (("max_total_runtime_ms", 60000), ("token_ceiling", 8000), ("money_ceiling", 0)):
            self.assertEqual(value, e[key]["value"])
        budgets = r["per_entrant"]
        self.assertEqual(2, len({b["budget_state_id_template"] for b in budgets}))
        for b in budgets:
            self.assertEqual((4, 0, []), (b["constructor_max_calls"], b["initial_calls_used"], b["initial_traces"]))
            self.assertEqual("FRESH_PROXY_BEFORE_EACH_ENTRANT", b["lifecycle"])
            self.assertEqual("FORBIDDEN", b["peer_budget_access"])

    def test_retry_fallback_and_budget_transfer_forbidden(self):
        r = self.bundle["resources"]
        self.assertEqual("NONE", r["fallback_policy"])
        self.assertEqual("FORBIDDEN", r["ticket_transfer"])
        self.assertEqual("NO_BACKEND_NO_TICKET", r["prebackend_rejection"])
        self.assertEqual("FORBIDDEN", r["parent_retry_policy"]["manual_retry_policy"])
        self.assertEqual(0, r["parent_retry_policy"]["automatic_retries"])

    def test_run_order_cardinality_and_namespace(self):
        r = self.bundle["run"]
        self.assertEqual(list(t.ALIASES), r["entrant_order"])
        self.assertEqual((2, 8, 80), (r["planned_submissions"], r["max_backend_attempts"], r["max_result_provenance_rows"]))
        self.assertEqual([1, 2], [s["order"] for s in r["schedule"]])
        self.assertEqual(t.EXECUTION_ID + ":" + self.expected + ":E1F-001", self.bundle["receipt"]["planned_run_namespace"])
        self.assertTrue(all(s["state"] == "PLANNED_NOT_EXECUTED" for s in r["schedule"]))

    def test_barrier_requires_both_durable_submissions_and_never_exposes_labels(self):
        r = self.bundle["run"]
        barrier = r["reference_barrier"]
        self.assertEqual("CLOSED", barrier["initial_state"])
        self.assertEqual(list(t.ALIASES), barrier["requires_committed_entrants"])
        self.assertEqual(2, barrier["requires_distinct_submissions"])
        self.assertIn("FSYNC", barrier["durability"])
        self.assertEqual("NEVER", barrier["fixture_reference_access"])
        self.assertEqual("AFTER_BOTH_DURABLE_SUBMISSIONS_ONLY", barrier["adjudicator_reference_access"])
        self.assertLess(r["states"].index("B_SUBMISSION_COMMITTED"), r["states"].index("REFERENCE_ACCESS_ENABLED"))
        self.assertTrue(barrier["no_cross_entrant_synthesis_before_barrier"])

    def test_future_schemas_complete_closed_and_parent_untouched(self):
        r = self.bundle["run"]
        self.assertEqual(set(t.FORMAL_FILES) - {"MANIFEST.sha256"}, set(r["future_output_contracts"]["schemas"]))
        for name, schema in r["future_output_contracts"]["schemas"].items():
            self.assertFalse(schema["additionalProperties"], name)
            self.assertEqual(set(schema["properties"]), set(schema["required"]))
            self.assertIn("run_id", schema["required"])
        for name in ("entrant-a-output.json", "entrant-b-output.json"):
            self.assertEqual(self.parent["output"]["json_schema"], r["future_output_contracts"]["schemas"][name]["properties"]["submission"])
        self.assertEqual(self.parent["searchspec"]["metrics"], r["parent_metric_definitions"])

    def test_start_end_have_identical_required_pin_fields(self):
        schemas = self.bundle["run"]["future_output_contracts"]["schemas"]
        start = schemas["run-start.json"]["properties"]["frozen_pins"]
        end = schemas["run-end.json"]["properties"]["frozen_pins"]
        self.assertEqual(start, end)
        self.assertTrue({"execution_binding", "profile_a", "profile_b", "query_plan", "resource_plan", "environment_recheck"} <= set(start["required"]))

    def test_integrity_i1_to_i10_are_plans_not_pass_evidence(self):
        plan = self.bundle["integrity"]
        self.assertEqual({f"I{i}" for i in range(1, 11)}, set(plan["checks"]))
        for row in plan["checks"].values():
            self.assertEqual("NOT_RUN", row["run_status"])
            self.assertEqual([], row["actual_run_evidence"])
            self.assertTrue(row["required_evidence_files"])
            self.assertTrue(set(row["required_evidence_files"]) <= set(t.FORMAL_FILES))
        self.assertFalse(plan["plan_is_run_evidence"])
        for key in ("failed_hard_gate_result", "missing_hard_evidence_result", "missing_or_unknown_gate_result"):
            self.assertEqual("NOT_EVALUABLE", plan[key])

    def test_zero_execution_receipt_and_pending_acceptance(self):
        r = self.bundle["receipt"]
        self.assertTrue(all(r[k] == 0 for k in t.ZERO_FIELDS))
        for key, value in t.boundary().items():
            self.assertEqual(value, r[key])
        self.assertEqual((0, "USD"), (r["spend"]["value"], r["spend"]["unit"]))
        self.assertEqual("NOT_RUN", r["post_run_integrity"])
        self.assertEqual("PENDING", r["independent_acceptance"])

    def test_guards_block_all_query_and_external_execution_seams(self):
        for target in (*t.parent.QUERY_GUARDS, *t.parent.qualification.GUARDED_TARGETS, *t.FIXTURE_GUARDS):
            with self.subTest(target=target), t.authoring_guard() as attempts:
                with self.assertRaises(RuntimeError):
                    resolve_name(target)("synthetic-negative-probe")
                self.assertTrue(attempts["fixture_decision"] or any(attempts["parent_guard"].values()))
                self.counts["negative_guard_blocked_attempts"] += 1

    def test_authoring_also_blocks_fixture_policy_and_environment_values(self):
        import os
        with t.authoring_guard():
            with self.assertRaises(RuntimeError):
                t.visible_decision(SearchResult("T", "U", ""))
            self.counts["negative_guard_blocked_attempts"] += 1
            with self.assertRaises(RuntimeError):
                os.environ.get("SYNTHETIC_UNUSED_ENV_KEY")
            self.counts["negative_guard_blocked_attempts"] += 1

    def test_swallowed_guard_failure_still_rejects_bundle(self):
        original = t._assemble
        def bad(*args):
            try:
                t.visible_decision(SearchResult("T", "U", ""))
            except RuntimeError:
                self.counts["negative_guard_blocked_attempts"] += 1
            return original(*args)
        with patch.object(t, "_assemble", side_effect=bad), self.assertRaisesRegex(RuntimeError, "BLOCKED_OPERATION_OBSERVED"):
            t.build_bundle()

    def test_module_imports_no_live_runner_judge_or_provider(self):
        tree = ast.parse((ROOT / t.MODULE_PATH).read_text())
        forbidden = {"os", "socket", "subprocess", "requests", "httpx", "urllib", "runner", "judge", "providers", "search_pro"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                self.assertFalse({n.name.split(".")[0] for n in node.names} & forbidden)
            elif isinstance(node, ast.ImportFrom):
                self.assertFalse(set((node.module or "").split(".")) & forbidden)

    def test_two_independent_builds_byte_identical_and_all_seals_valid(self):
        other = t.build_bundle()
        self.assertEqual(canonical_json(self.bundle).encode(), canonical_json(other).encode())
        for part in other.values():
            verify_seal(part)
        t.validate_bundle(other, expected_fingerprint=self.expected)

    def test_resealed_mutation_cannot_substitute_for_frozen_plan(self):
        bad = deepcopy(self.bundle)
        bad["queries"]["profiles"][0]["queries"][0]["query"] = "unapproved query"
        bad["queries"] = seal(bad["queries"])
        with self.assertRaisesRegex(ValueError, "FROZEN_READINESS_PACKAGE_MUTATED"):
            t.validate_bundle(bad, expected_fingerprint=self.expected)

    def test_external_review_fingerprint_required(self):
        with self.assertRaises(TypeError):
            t.validate_bundle(self.bundle)
        with self.assertRaisesRegex(ValueError, "RETAINED_EXECUTION_PIN_MISMATCH"):
            t.validate_bundle(self.bundle, expected_fingerprint="0" * 64)

    def test_write_manifest_validate_and_no_formal_output(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "readiness"
            receipt = t.write_bundle(output)
            self.assertEqual(set(t.PAYLOADS.values()) | {"MANIFEST.sha256"}, {p.name for p in output.iterdir()})
            self.assertEqual({"MANIFEST.sha256"}, set(t.FORMAL_FILES) & {p.name for p in output.iterdir()})
            self.assertEqual(11, len((output / "MANIFEST.sha256").read_text().splitlines()))
            self.assertEqual(receipt, t.validate_directory(output, expected_fingerprint=self.expected))
            for line in (output / "MANIFEST.sha256").read_text().splitlines():
                digest, name = line.split("  ")
                self.assertEqual(digest, hashlib.sha256((output / name).read_bytes()).hexdigest())

    def test_manifest_tamper_and_resealed_rehashed_bundle_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "readiness"
            t.write_bundle(output)
            path = output / "fixture-profile-a.json"
            part = json.loads(path.read_bytes())
            part["external_reads"] = "ALLOW"
            path.write_text(canonical_json(seal(part)))
            with self.assertRaisesRegex(ValueError, "READINESS_BYTE_MANIFEST_MISMATCH"):
                t.validate_directory(output, expected_fingerprint=self.expected)
            t.parent.write_manifest(output)
            with self.assertRaisesRegex(ValueError, "FROZEN_READINESS_PACKAGE_MUTATED"):
                t.validate_directory(output, expected_fingerprint=self.expected)

    def test_existing_output_extra_file_and_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "readiness"
            t.write_bundle(output)
            with self.assertRaises(FileExistsError):
                t.write_bundle(output)
            extra = output / "unexpected.json"
            extra.write_text("{}")
            with self.assertRaisesRegex(ValueError, "READINESS_FILE_SET_MISMATCH"):
                t.validate_directory(output, expected_fingerprint=self.expected)
            extra.unlink()
            path = output / "fixture-profile-a.json"
            saved = Path(directory) / "saved.json"
            saved.write_bytes(path.read_bytes())
            path.unlink()
            path.symlink_to(saved)
            with self.assertRaisesRegex(ValueError, "READINESS_NONREGULAR_FILE"):
                t.validate_directory(output, expected_fingerprint=self.expected)

    def test_cli_requires_pins_and_has_no_execute_or_replay(self):
        for argv in (["execute"], ["replay"], ["receipt"], ["validate", "--expected-source-sha", t.BASELINE_SHA,
                      "--expected-source-tree", t.BASELINE_TREE, "--output", "unused"]):
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
                t.main(argv)
            self.assertEqual(2, error.exception.code)

    def test_cli_receipt_is_same_deterministic_no_execution_receipt(self):
        output = io.StringIO()
        with redirect_stdout(output):
            t.main(["receipt", "--expected-source-sha", t.BASELINE_SHA, "--expected-source-tree", t.BASELINE_TREE])
        self.assertEqual(self.bundle["receipt"], json.loads(output.getvalue()))


if __name__ == "__main__":
    unittest.main()
