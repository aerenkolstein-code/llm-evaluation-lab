"""T3 qualification method tests; no retriever, provider or entrant executes."""
import ast
from contextlib import ExitStack, redirect_stdout
from copy import deepcopy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from search_cup.contracts import canonical_json, fingerprint
from search_cup.protocol_v23 import seal, verify_seal
from search_cup import v23_t3_f1q as f1q


class F1QualificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sources = f1q.load_sources()
        cls.inventory = f1q.discover_candidates(cls.sources)
        cls.bundle = f1q.build_bundle()

    def test_baseline_is_exact_and_source_bytes_are_pinned(self):
        self.assertEqual("6c1b664a2264a021dc9ebca26514eca130ceaaec", f1q.BASELINE_SHA)
        self.assertEqual("2fcc3b0f2bf641d01ab8a90ab6b771be4e5c7434", f1q.BASELINE_TREE)
        for path, text in self.sources.items():
            self.assertEqual(f1q.SOURCE_PINS[path], hashlib.sha256(text.encode()).hexdigest())

    def test_wrong_source_sha_or_tree_fails_before_source_read(self):
        for delta in ({"expected_sha": "0" * 40}, {"expected_tree": "0" * 40}):
            with self.subTest(delta=delta), patch.object(Path, "read_bytes") as read:
                with self.assertRaisesRegex(ValueError, "SOURCE_BASELINE_MISMATCH"):
                    f1q.load_sources(**delta)
                read.assert_not_called()

    def test_source_mutation_or_missing_source_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for path, text in self.sources.items():
                target = root / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(text)
            (root / "search_cup/tools.py").write_text(self.sources["search_cup/tools.py"] + "\n# drift\n")
            with self.assertRaisesRegex(ValueError, "SOURCE_CONTENT_MISMATCH"):
                f1q.build_bundle(root=root)
            (root / "search_cup/tools.py").unlink()
            with self.assertRaises(FileNotFoundError):
                f1q.build_bundle(root=root)

    def test_discovery_keeps_both_current_main_backends(self):
        self.assertEqual(["search_cup.search_pro:SearchProBackend", "search_cup.tools:FakeSearchBackend"],
                         [c["candidate_id"] for c in self.inventory])
        self.assertEqual((None, "CANDIDATE_AMBIGUOUS"), f1q.select_candidate(self.inventory))
        self.assertEqual(self.inventory, f1q.discover_candidates(dict(reversed(list(self.sources.items())))))

    def test_no_candidate_is_not_evaluable_not_eligible(self):
        empty = f1q.discover_candidates({"search_cup/tools.py": "class URLReader:\n    def read(self, url): pass\n"})
        self.assertEqual((None, "NO_CANDIDATE"), f1q.select_candidate(empty))
        with patch.object(f1q, "discover_candidates", return_value=[]):
            bundle = f1q.build_bundle()
        self.assertEqual("NOT_EVALUABLE", bundle["receipt"]["qualification_result"])
        self.assertEqual(["NO_CANDIDATE"], bundle["receipt"]["reason_codes"])

    def test_ambiguity_never_picks_by_name_order_class_or_convenience(self):
        with patch.object(f1q, "freeze_candidate", side_effect=AssertionError("selection forbidden")) as freeze:
            bundle = f1q.build_bundle()
        freeze.assert_not_called()
        self.assertIsNone(bundle["descriptor"]["selected_candidate"])
        self.assertIsNone(bundle["receipt"]["candidate_fingerprint"])
        for items in (self.inventory, list(reversed(self.inventory))):
            self.assertEqual((None, "CANDIDATE_AMBIGUOUS"), f1q.select_candidate(items))

    def test_discovery_detects_an_additional_typed_implementation_without_calling_it(self):
        sources = dict(self.sources)
        sources["search_cup/tools.py"] += "\nclass AdditionalBackend:\n    def __call__(self, request: SearchRequest):\n        raise AssertionError('MUST NOT EXECUTE')\n"
        inventory = f1q.discover_candidates(sources)
        self.assertEqual(3, len(inventory))
        self.assertEqual("CANDIDATE_AMBIGUOUS", f1q.select_candidate(inventory)[1])

    def test_duplicate_candidate_id_cannot_be_counted_as_unique(self):
        with self.assertRaisesRegex(ValueError, "DUPLICATE_CANDIDATE_IDENTITY"):
            f1q.select_candidate([self.inventory[0], self.inventory[0]])

    def test_unique_descriptor_binds_contract_config_and_implementation(self):
        for discovered in self.inventory:
            chosen, reason = f1q.select_candidate([discovered])
            self.assertEqual("UNIQUE_CANDIDATE", reason)
            descriptor = f1q.freeze_candidate(chosen, self.sources)
            verify_seal(descriptor)
            self.assertEqual(f1q.source_identity(), descriptor["source"])
            self.assertEqual(fingerprint(descriptor["config"]), descriptor["config_fingerprint"])
            for key in ("candidate_id", "retriever_class", "implementation", "search_proxy", "request_schema",
                        "result_schema", "normalization_identity", "retry_fallback_policy", "capability_declaration"):
                self.assertIn(key, descriptor)
            self.assertFalse(descriptor["config"]["frozen_instance"])

    def gate_fixture(self):
        # Hypothetical, in-memory method fixture; never exported as a candidate.
        discovered = next(c for c in self.inventory if c["candidate_id"].endswith(":FakeSearchBackend"))
        candidate = f1q.freeze_candidate(discovered, self.sources)
        config = {**candidate["config"], "frozen_instance": True,
                  "results_by_query": {"test-only-query": []}, "result_limit": 1}
        candidate = seal({**candidate, "config": config, "config_fingerprint": fingerprint(config),
                          "capability_declaration": {**candidate["capability_declaration"],
                                                     "equalized_entrant_configuration": "FROZEN_IDENTICAL"}})
        item = f1q.make_evidence("TEST-METHOD", "GENERATED_OFFLINE_RECEIPT", "test-only://method-fixture",
                                {"content_sha256": fingerprint({"test_only": True})},
                                "Synthetic method input for the all-of gate.",
                                "Not evidence of actual retriever neutrality; never exported.")
        checks = {r: {"status": "PASS", "evidence_ids": ["TEST-METHOD"]} for r in f1q.CRITERIA}
        return candidate, checks, [item]

    def test_exactly_eight_pass_values_with_evidence_pass_the_method_gate(self):
        self.assertEqual("F1_ELIGIBLE", f1q.criterion_gate(*self.gate_fixture()))

    def test_any_fail_or_unknown_prevents_eligibility(self):
        for criterion in f1q.CRITERIA:
            for status in ("FAIL", "UNKNOWN"):
                candidate, checks, evidence = self.gate_fixture()
                checks[criterion]["status"] = status
                with self.subTest(criterion=criterion, status=status):
                    self.assertEqual("NOT_F1_ELIGIBLE", f1q.criterion_gate(candidate, checks, evidence))

    def test_r1_r8_enum_is_exact_and_closed(self):
        self.assertEqual({f"R{i}" for i in range(1, 9)}, set(f1q.CRITERIA))
        candidate, checks, evidence = self.gate_fixture()
        for delta in ({r: v for r, v in checks.items() if r != "R8"}, {**checks, "R9": checks["R1"]},
                      {**checks, "R1": {"status": "GREEN", "evidence_ids": ["TEST-METHOD"]}}):
            with self.subTest(delta=delta), self.assertRaises(ValueError):
                f1q.criterion_gate(candidate, delta, evidence)

    def test_missing_evidence_cannot_compensate_with_other_passes(self):
        candidate, checks, evidence = self.gate_fixture()
        checks["R1"]["evidence_ids"] = []
        self.assertEqual("NOT_F1_ELIGIBLE", f1q.criterion_gate(candidate, checks, evidence))

    def test_integrated_class_and_relabel_are_rejected(self):
        _, checks, evidence = self.gate_fixture()
        discovered = next(c for c in self.inventory if c["candidate_id"].endswith(":SearchProBackend"))
        candidate = f1q.freeze_candidate(discovered, self.sources)
        self.assertEqual("NOT_F1_ELIGIBLE", f1q.criterion_gate(candidate, checks, evidence))
        with self.assertRaisesRegex(ValueError, "RELABEL"):
            f1q.criterion_gate(seal({**candidate, "retriever_class": "RAW_RETRIEVER"}), checks, evidence)

    def test_no_separately_approved_frozen_class_is_invented(self):
        candidate, checks, evidence = self.gate_fixture()
        self.assertEqual("NOT_F1_ELIGIBLE", f1q.criterion_gate(
            seal({**candidate, "retriever_class": "FROZEN_RETRIEVER"}), checks, evidence))

    def test_unbound_configuration_does_not_qualify_on_eight_pass_assertions(self):
        _, checks, evidence = self.gate_fixture()
        for discovered in self.inventory:
            candidate = f1q.freeze_candidate(discovered, self.sources)
            self.assertEqual("NOT_F1_ELIGIBLE", f1q.criterion_gate(candidate, checks, evidence))

    def test_search_pro_is_not_presumptively_pass_because_adapter_exists(self):
        self.assertTrue(any(c["candidate_id"].endswith(":SearchProBackend") for c in self.inventory))
        self.assertEqual("NOT_EVALUABLE", self.bundle["receipt"]["qualification_result"])
        self.assertTrue(all(c["status"] == "UNKNOWN" for c in self.bundle["qualification"]["criteria"].values()))

    def test_historical_p1_p2_receipts_cannot_alone_satisfy_checks(self):
        candidate, checks, evidence = self.gate_fixture()
        for lineage in ("P1", "P2"):
            historical = seal({**evidence[0], "history_only": True,
                               "supported_proposition": lineage + " historical smoke passed; history only."})
            self.assertEqual("NOT_F1_ELIGIBLE", f1q.criterion_gate(candidate, checks, [historical]))
        self.assertEqual([], self.bundle["evidence"]["historical_live_receipts_used"])

    def test_evidence_requires_kind_locator_identity_proposition_limit_and_seal(self):
        item = self.bundle["evidence"]["entries"][0]
        for key in ("source_kind", "locator", "source_identity", "supported_proposition", "scope_limitation", "observed_frozen"):
            changed = {k: v for k, v in item.items() if k != key}
            with self.subTest(key=key), self.assertRaises(ValueError):
                f1q.validate_evidence(seal(changed))
        with self.assertRaises(ValueError):
            f1q.validate_evidence({**item, "canonical_fingerprint": "0" * 64})
        for change in ({"source_kind": "HISTORICAL_RECEIPT"}, {"supported_proposition": ""},
                       {"source_identity": {"content_sha256": "missing"}}, {"observed_frozen": "ASSUMED"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                f1q.validate_evidence(seal({**item, **change}))

    def test_repository_evidence_binds_exact_sha_tree_and_locator(self):
        item = self.bundle["evidence"]["entries"][0]
        for delta in ({"sha": "0" * 40}, {"tree": "0" * 40}):
            with self.assertRaises(ValueError):
                f1q.validate_evidence(seal({**item, "source_identity": {**item["source_identity"], **delta}}))
        with self.assertRaises(ValueError):
            f1q.validate_evidence(seal({**item, "locator": "https://example.test/unbound"}))

    def test_public_document_evidence_requires_frozen_excerpt_without_private_locator(self):
        item = f1q.make_evidence("TEST-PUBLIC", "OFFICIAL_PUBLIC_DOC", "https://docs.example.test/public",
                                {"content_sha256": "a" * 64}, "Test proposition", "Test-only fixture", excerpt="Short public excerpt")
        f1q.validate_evidence(item)
        with self.assertRaises(ValueError):
            f1q.validate_evidence(seal({**item, "excerpt": ""}))
        with self.assertRaises(ValueError):
            f1q.make_evidence("TEST-PRIVATE", "OFFICIAL_PUBLIC_DOC", "https://docs.google.com/document/d/private",
                               {"content_sha256": "a" * 64}, "Test", "Excluded")

    def test_dangling_and_duplicate_evidence_references_rejected(self):
        candidate, checks, evidence = self.gate_fixture()
        for ids in (["MISSING"], ["TEST-METHOD", "TEST-METHOD"]):
            changed = {**checks, "R1": {"status": "PASS", "evidence_ids": ids}}
            with self.assertRaises(ValueError):
                f1q.criterion_gate(candidate, changed, evidence)
        with self.assertRaises(ValueError):
            f1q.criterion_gate(candidate, checks, evidence + evidence)

    def test_descriptor_config_and_source_binding_tamper_rejected(self):
        candidate, checks, evidence = self.gate_fixture()
        for delta in ({"config_fingerprint": "0" * 64}, {"source": {"sha": "0" * 40, "tree": f1q.BASELINE_TREE}}):
            with self.assertRaises(ValueError):
                f1q.criterion_gate(seal({**candidate, **delta}), checks, evidence)

    def test_deterministic_descriptor_package_and_negative_conformance(self):
        self.assertEqual(canonical_json(self.bundle), canonical_json(f1q.build_bundle()))
        self.assertEqual("55be768878c849a7efda8e7be9bd3cf627ba5aa7f86f4c1f4efa9a671443aa6c", self.bundle["receipt"]["package_fingerprint"])
        self.assertEqual("PASS", self.bundle["receipt"]["package_conformance"])
        self.assertEqual("PENDING", self.bundle["receipt"]["independent_acceptance"])
        self.assertEqual("NOT_EVALUABLE", self.bundle["receipt"]["retriever_qualification"])
        self.assertEqual("NOT_ASSESSED_NO_UNIQUE_CANDIDATE", self.bundle["qualification"]["assessment_state"])

    def test_authorization_and_result_cannot_be_changed_by_resealing(self):
        for delta in ({"t5_execution_authorized": True}, {"live_execution_authorized": True},
                      {"qualification_result": "F1_ELIGIBLE"}, {"package_fingerprint": "0" * 64},
                      {"claims_ceiling": "BENCHMARK"}):
            bundle = deepcopy(self.bundle)
            bundle["receipt"] = seal({**bundle["receipt"], **delta})
            with self.subTest(delta=delta), self.assertRaises(ValueError):
                f1q.validate_bundle(bundle)

    def test_zero_operation_receipt_is_exact(self):
        receipt = self.bundle["resources"]
        verify_seal(receipt)
        zero_fields = {"provider_calls", "search_calls", "network_search_calls", "follow_links", "automatic_retries",
                       "credential_reads", "credit_consumption", "model_calls", "entrant_runs", "e1_frozen_runs", "e1_live_runs"}
        self.assertEqual(zero_fields, {k for k, v in receipt.items() if type(v) is int})
        self.assertTrue(all(receipt[k] == 0 for k in zero_fields))
        self.assertEqual({"currency": "USD", "value": 0}, receipt["spend"])
        for key in ("formal_retriever_execution_performed", "official_prompt_consumed", "hidden_registry_loaded"):
            self.assertIs(False, receipt[key])
        changed = deepcopy(self.bundle)
        changed["resources"] = seal({**receipt, "automatic_retries": 1})
        with self.assertRaises(ValueError):
            f1q.validate_bundle(changed)

    def test_authoring_has_no_network_provider_search_or_environment_calls(self):
        class NoEnvironment(dict):
            def get(self, *args):
                raise AssertionError("environment access forbidden")
            __getitem__ = get
        from unittest.mock import patch as guard_patch
        with ExitStack() as stack:
            mocks = [stack.enter_context(guard_patch(target, side_effect=AssertionError("forbidden capability")))
                     for target in ("socket.socket", "urllib.request.urlopen", "subprocess.run", "os.getenv")]
            stack.enter_context(guard_patch("os.environ", NoEnvironment()))
            rebuilt = f1q.build_bundle()
        self.assertEqual(self.bundle, rebuilt)
        for guard in mocks:
            guard.assert_not_called()

    def test_source_reads_are_only_the_public_allowlist(self):
        original = Path.read_bytes
        seen = []
        root = Path(f1q.__file__).resolve().parents[1]
        def allowed(path):
            relative = path.relative_to(root).as_posix()
            self.assertIn(relative, f1q.SOURCE_PINS)
            seen.append(relative)
            return original(path)
        with patch.object(Path, "read_bytes", allowed):
            f1q.build_bundle()
        self.assertEqual(set(f1q.SOURCE_PINS), set(seen))

    def test_no_backend_runner_judge_provider_import_or_pr17_binding(self):
        tree = ast.parse(Path(f1q.__file__).read_text())
        banned = {"search_pro", "tools", "runner", "judge", "providers", "provider_adapters", "demo", "socket", "requests", "httpx", "os", "subprocess"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                self.assertFalse(banned & {a.name.split(".")[-1] for a in node.names})
            if isinstance(node, ast.ImportFrom):
                self.assertNotIn((node.module or "").split(".")[-1], banned)
        rendered = canonical_json(self.bundle)
        self.assertNotIn("pull/17", rendered)
        self.assertNotIn("refs/pull/17", rendered)
        self.assertTrue(all(e["source_identity"].get("sha", f1q.BASELINE_SHA) == f1q.BASELINE_SHA
                            for e in self.bundle["evidence"]["entries"]))

    def test_published_t4_je0_je1_source_is_unchanged_by_authoring(self):
        f1q.build_bundle()
        root = Path(f1q.__file__).resolve().parents[1]
        for path in ("search_cup/v23_t4_instance.py", "search_cup/v23_t4_execution.py", "search_cup/v23_t4_je1.py"):
            self.assertEqual(f1q.SOURCE_PINS[path], hashlib.sha256((root / path).read_bytes()).hexdigest())

    def test_manifest_covers_all_payloads_and_used_output_is_untouched(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "qualification"
            f1q.write_bundle(root)
            names = {p.name for p in root.iterdir()}
            self.assertEqual(set(f1q.FILENAMES.values()) | {"MANIFEST.sha256"}, names)
            manifest = (root / "MANIFEST.sha256").read_text()
            self.assertEqual(5, len(manifest.splitlines()))
            for line in manifest.splitlines():
                digest, name = line.split("  ", 1)
                self.assertEqual(digest, hashlib.sha256((root / name).read_bytes()).hexdigest())
            with self.assertRaises(FileExistsError):
                f1q.write_bundle(root)
            self.assertEqual(manifest, (root / "MANIFEST.sha256").read_text())

    def test_cli_negative_qualification_is_successful_authoring_only(self):
        args = ["receipt", "--expected-source-sha", f1q.BASELINE_SHA, "--expected-source-tree", f1q.BASELINE_TREE]
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(0, f1q.main(args))
        receipt = json.loads(output.getvalue())
        self.assertEqual("NOT_EVALUABLE", receipt["qualification_result"])
        self.assertFalse(receipt["t5_execution_authorized"] or receipt["live_execution_authorized"])


if __name__ == "__main__":
    unittest.main()
