"""NFR implementation conformance only; every local fixture call is counted."""
import ast
from contextlib import ExitStack, redirect_stdout
from copy import deepcopy
from dataclasses import FrozenInstanceError
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from search_cup.contracts import SearchRequest, SearchResult, canonical_json, fingerprint
from search_cup.protocol_v23 import seal
from search_cup.tools import BudgetedSearchProxy, SearchBackendResponse, SearchBudgetExceeded
from search_cup import v23_frozen_retriever as nfr

ROOT = Path(__file__).resolve().parents[1]


class FrozenRetrieverTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_calls = 0
        original = nfr.FrozenLexicalRetriever.__call__
        def counted(candidate, request):
            cls.fixture_calls += 1
            return original(candidate, request)
        cls.counter_patch = patch.object(nfr.FrozenLexicalRetriever, "__call__", counted)
        cls.counter_patch.start()
        cls.addClassCleanup(cls.counter_patch.stop)
        cls.config, cls.corpus, cls.code_digest, cls.header = nfr.load_inputs()
        cls.bundle = nfr.build_bundle()

    @classmethod
    def tearDownClass(cls):
        print("NFR_LOCAL_FIXTURE_RETRIEVER_CALLS=" + str(cls.fixture_calls))

    def candidate(self, corpus=None):
        return nfr.FrozenLexicalRetriever(corpus if corpus is not None else self.corpus, self.config)

    def query(self, query, *, entrant="fixture-user", request_id="fixture-request", candidate=None):
        return (candidate or self.candidate())(SearchRequest(entrant, query, 1, request_id))

    def documents(self):
        return [d.as_dict() for d in self.corpus.documents]

    def copy_sources(self, root):
        for path in (*nfr.RETAINED_PINS, *nfr.INPUT_PINS, nfr.CODE_PATH):
            target = root / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((ROOT / path).read_bytes())

    def test_exact_baseline_selector_and_six_new_paths(self):
        self.assertEqual({"sha": "db6ba8746e6776c02b5942e38919316aebf65fe0",
                          "tree": "52c37289c283ccbe89b974fae099ac0671aea678"}, nfr.baseline())
        self.assertEqual({
            "search_cup/v23_frozen_retriever.py", "configs/search-cup-v23-frozen-retriever-v1.json",
            "fixtures/search-cup/v23-frozen-retriever-test-corpus-v1.json",
            "tests/test_search_cup_v23_frozen_retriever.py", "docs/search-cup-v23-frozen-retriever.md",
            ".github/workflows/t3-frozen-retriever-offline.yml",
        }, set(nfr.APPROVED_PATHS))
        candidate = self.bundle["candidate"]
        self.assertEqual("search-cup-v23-frozen-lexical-raw-v1", candidate["candidate_id"])
        self.assertEqual("EXPLICIT_AUTHORITY_PIN_TO_CANDIDATE_ID", candidate["selector"]["rule"])
        self.assertEqual(candidate["candidate_id"], candidate["selector"]["candidate_id"])
        self.assertEqual(nfr.WORK_ORDER, candidate["selector"]["authority"])
        self.assertEqual("RAW_RETRIEVER", candidate["retriever_class"])
        self.assertEqual("search_cup.v23_frozen_retriever:FrozenLexicalRetriever", candidate["module_class"])

    def test_wrong_baseline_rejected_before_any_source_read_or_fixture_call(self):
        before = self.fixture_calls
        for delta in ({"expected_sha": "0" * 40}, {"expected_tree": "0" * 40}):
            with patch.object(Path, "read_bytes") as read, self.assertRaisesRegex(ValueError, "BASELINE_DRIFT"):
                nfr.build_bundle(**delta)
            read.assert_not_called()
        self.assertEqual(before, self.fixture_calls)

    def test_config_is_exact_versioned_and_fingerprint_reproducible(self):
        config = json.loads((ROOT / nfr.CONFIG_PATH).read_text())
        self.assertEqual(nfr.CONFIG_FINGERPRINT, fingerprint(config))
        self.assertEqual(self.config.canonical_content, canonical_json(config))
        for key, value in {"result_limit": 11, "automatic_retries": 1, "query_rewrite": "ENABLED",
                           "retriever_class": "INTEGRATED_SEARCH_STACK", "ngram_size": 2}.items():
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "CONFIG_MISMATCH"):
                nfr.FrozenConfig({**config, key: value})

    def test_config_and_corpus_copy_mutable_inputs(self):
        settings = json.loads(self.config.canonical_content)
        config = nfr.FrozenConfig(settings)
        docs = self.documents()
        corpus = nfr.FrozenCorpus(docs)
        settings["result_limit"] = 1
        docs[0]["text"] = "mutated"
        docs.pop()
        self.assertEqual(self.config, config)
        self.assertEqual(self.corpus, corpus)

    def test_corpus_order_and_canonical_bytes_independent_of_input_order(self):
        other = nfr.FrozenCorpus(list(reversed(self.documents())), expected_fingerprint=nfr.TEST_CORPUS_FINGERPRINT)
        self.assertEqual(self.corpus.canonical_content, other.canonical_content)
        self.assertEqual("ec12c5e478b9b95c8f24104bca5147717ba7ca5018fea043cf8e9f658b7377d4", other.canonical_fingerprint)
        self.assertEqual(other.canonical_fingerprint, hashlib.sha256(other.canonical_content.encode()).hexdigest())
        self.assertEqual(self.query("alpha alpha").results, self.query("alpha alpha", candidate=self.candidate(other)).results)

    def test_duplicate_document_ids_fail_closed(self):
        docs = self.documents()
        with self.assertRaisesRegex(ValueError, "DUPLICATE_DOC_ID"):
            nfr.FrozenCorpus(docs + [docs[0]])

    def test_malformed_documents_and_urls_fail_closed(self):
        base = self.documents()[0]
        bad = [None, "bad", {**base, "extra": 1}, {k: v for k, v in base.items() if k != "text"}]
        bad += [{**base, **delta} for delta in (
            {"doc_id": ""}, {"doc_id": " id "}, {"title": " "}, {"text": 7},
            {"url": "file:///local"}, {"url": "https://"}, {"url": "https://fixture.example.test/a b"},
            {"url": "https://user:pass@fixture.example.test/"},
        )]
        for document in bad:
            with self.subTest(document=document), self.assertRaises(ValueError):
                nfr.FrozenCorpus([document])

    def test_corpus_supplied_fingerprint_mismatch_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "CORPUS_FINGERPRINT_MISMATCH"):
            nfr.FrozenCorpus(self.documents(), expected_fingerprint="0" * 64)

    def test_corpus_config_candidate_and_index_are_immutable(self):
        candidate = self.candidate()
        for obj, attr, value in ((self.corpus, "documents", ()), (self.corpus.documents[0], "text", "new"),
                                 (self.config, "canonical_content", "{}"), (candidate, "corpus", None),
                                 (candidate, "_index", ())):
            with self.subTest(attr=attr), self.assertRaises(FrozenInstanceError):
                setattr(obj, attr, value)
        self.assertIsInstance(candidate._index, tuple)
        self.assertTrue(all(isinstance(units, tuple) for _, units in candidate._index))
        with self.assertRaises(TypeError):
            self.candidate()._index[0][1][0] = ("new", 1)

    def test_constructor_requires_explicit_immutable_inputs(self):
        for corpus, config in ((self.documents(), self.config), (self.corpus, {}), (None, self.config)):
            with self.assertRaises(TypeError):
                nfr.FrozenLexicalRetriever(corpus, config)

    def test_normalization_nfkc_casefold_separators_and_unicode(self):
        self.assertEqual("abc strasse café 12 数据", nfr.normalize(" ＡＢＣ—Straße\tCAFE\u0301 / ①２ 😺 数据 "))
        self.assertEqual("", nfr.normalize("... 😺 \t"))
        self.assertEqual("i", nfr.normalize("İ"))
        self.assertEqual(nfr.normalize("ＡＢＣ--猫"), nfr.normalize(nfr.normalize("ＡＢＣ--猫")))

    def test_features_stay_within_spans_and_short_spans_use_unigrams(self):
        self.assertEqual((("a", 1), ("abc", 2), ("b", 1), ("猫", 1)), nfr.character_units("ABC ab abc 猫"))
        self.assertEqual((("aaa", 3),), nfr.character_units("aaaaa"))
        self.assertNotIn("c d", dict(nfr.character_units("abc def")))
        self.assertEqual((), nfr.character_units("!!!"))

    def test_integer_multiset_overlap_counts_multiplicity(self):
        self.assertEqual(2, nfr.overlap(nfr.character_units("aaaa"), nfr.character_units("aaaaa")))
        self.assertEqual(3, nfr.overlap(nfr.character_units("alpha alpha"), nfr.character_units("alpha")))
        self.assertEqual(6, nfr.overlap(nfr.character_units("alpha alpha"), nfr.character_units("alpha alpha alpha")))
        self.assertIs(type(nfr.overlap((), ())), int)

    def test_score_descending_then_doc_id_ascending_and_limit_ten(self):
        # Put the highest score at a later doc_id to distinguish ranking from ID sorting.
        docs = self.documents()
        docs[0]["text"], docs[11]["text"] = docs[11]["text"], docs[0]["text"]
        corpus = nfr.FrozenCorpus(docs)
        result = self.query("alpha alpha", candidate=self.candidate(corpus)).results
        ids = [r.url.rsplit("/", 1)[1] for r in result]
        self.assertEqual(["lex-12"] + ["lex-" + str(i).zfill(2) for i in range(1, 10)], ids)
        self.assertEqual(10, len(result))

    def test_zero_score_empty_features_and_empty_corpus_return_no_results(self):
        self.assertEqual((), self.query("zzzzzz").results)
        self.assertEqual((), self.query("!!!").results)
        self.assertEqual((), self.query("alpha", candidate=self.candidate(nfr.FrozenCorpus([]))).results)

    def test_no_synonym_translation_or_short_query_expansion(self):
        for query in ("coffee", "目录数据"):
            self.assertEqual((), self.query(query).results)
        # 'al' uses unigrams and overlaps 'ab'; it does not expand to 'alpha'.
        self.assertEqual(["https://fixture.example.test/lex-21"], [r.url for r in self.query("al").results])
        self.assertEqual(1, len(self.query("猫").results))

    def test_original_query_and_incoming_request_id_are_unchanged(self):
        request = SearchRequest("a", "  ＡＬＰＨＡ!!! ", 7, "incoming-id")
        before = deepcopy(request)
        response = self.candidate()(request)
        self.assertEqual(before, request)
        self.assertEqual("incoming-id", response.request_id)
        self.assertEqual(nfr.BACKEND_ID, response.backend_id)
        self.assertIsNone(response.response_id)
        self.assertEqual("", self.candidate()(SearchRequest("a", "alpha")).request_id)

    def test_request_type_is_checked_without_fallback(self):
        with self.assertRaisesRegex(TypeError, "SEARCHREQUEST_REQUIRED"):
            self.candidate()({"query": "alpha"})

    def test_result_contract_title_url_and_snippet_are_stable(self):
        docs = self.documents()
        docs[0]["text"] = "alpha " * 60
        result = self.query("alpha alpha", candidate=self.candidate(nfr.FrozenCorpus(docs)))
        self.assertIs(type(result), SearchBackendResponse)
        self.assertTrue(all(type(r) is SearchResult for r in result.results))
        first = result.results[0]
        self.assertEqual(docs[0]["title"], first.title)
        self.assertEqual(docs[0]["url"], first.url)
        self.assertEqual(docs[0]["text"][:240], first.snippet)

    def test_entrant_request_and_call_identity_do_not_change_results(self):
        candidate = self.candidate()
        responses = [candidate(SearchRequest(entrant, "alpha alpha", number, request_id))
                     for entrant, number, request_id in (("provider-a-model-x", 1, "a"),
                                                         ("provider-b-model-y", 99, "b"), ("neutral", 0, ""))]
        self.assertEqual(responses[0].results, responses[1].results)
        self.assertEqual(responses[0].results, responses[2].results)

    def test_no_cross_query_state_or_corpus_rewrite(self):
        candidate = self.candidate()
        before = (candidate.corpus, candidate.config, candidate._index)
        first = self.query("alpha alpha", candidate=candidate)
        self.query("猫", candidate=candidate)
        self.query("!!!", candidate=candidate)
        self.assertEqual(first, self.query("alpha alpha", candidate=candidate))
        self.assertEqual(before, (candidate.corpus, candidate.config, candidate._index))
        self.assertFalse(hasattr(candidate, "__dict__"))

    def test_budgeted_proxy_preserves_query_identity_and_counts_once(self):
        candidate = self.candidate()
        proxy = BudgetedSearchProxy("fixture-entrant", 1, candidate)
        before = self.fixture_calls
        results = proxy.search("  ＡＬＰＨＡ!  ")
        self.assertEqual(before + 1, self.fixture_calls)
        trace = proxy.traces[0]
        self.assertEqual("  ＡＬＰＨＡ!  ", trace.query)
        self.assertEqual("SUCCEEDED", trace.status)
        self.assertEqual(nfr.BACKEND_ID, trace.backend_id)
        self.assertEqual(len(results), trace.result_count)
        self.assertTrue(trace.backend_request_id)
        self.assertEqual(0, trace.automatic_retries)
        self.assertEqual(1, trace.backend_attempts)
        with self.assertRaises(SearchBudgetExceeded):
            proxy.search("alpha")
        self.assertEqual(before + 1, self.fixture_calls)

    def test_proxy_failure_is_auditable_without_retry_or_fallback(self):
        proxy = BudgetedSearchProxy("fixture", 2, self.candidate())
        before = self.fixture_calls
        with patch.object(nfr, "character_units", side_effect=ValueError("SYNTHETIC_FAILURE")), self.assertRaises(ValueError):
            proxy.search("alpha")
        self.assertEqual(before + 1, self.fixture_calls)
        self.assertEqual("FAILED", proxy.traces[0].status)
        self.assertEqual(0, proxy.traces[0].automatic_retries)
        self.assertEqual(nfr.BACKEND_ID, proxy.traces[0].backend_id)

    def test_queries_and_builder_do_not_access_environment_network_provider_or_subprocess(self):
        class NoEnvironment(dict):
            def get(self, *args):
                raise AssertionError("environment access forbidden")
            __getitem__ = get
        with ExitStack() as stack:
            guards = [stack.enter_context(patch(target, side_effect=AssertionError("forbidden capability"))) for target in (
                "socket.socket", "urllib.request.urlopen", "subprocess.run", "subprocess.Popen", "os.getenv",
                "search_cup.search_pro.SearchProBackend.__call__", "search_cup.search_pro.SearchProBackend.from_env",
                "search_cup.search_pro._default_transport", "search_cup.tools.FakeSearchBackend.__call__")]
            stack.enter_context(patch("os.environ", NoEnvironment()))
            self.assertEqual(10, len(self.query("alpha").results))
            bundle = nfr.build_bundle()
        self.assertEqual(self.bundle, bundle)
        for guard in guards:
            guard.assert_not_called()

    def test_runtime_queries_perform_no_file_access(self):
        candidate = self.candidate()
        with patch.object(Path, "read_bytes", side_effect=AssertionError("file read forbidden")), \
             patch("builtins.open", side_effect=AssertionError("file open forbidden")):
            self.assertEqual(10, len(self.query("alpha", candidate=candidate).results))

    def test_no_forbidden_import_or_entrant_branch_in_retriever(self):
        tree = ast.parse((ROOT / nfr.CODE_PATH).read_text())
        banned = {"os", "subprocess", "socket", "requests", "httpx", "random", "time", "datetime",
                  "search_pro", "runner", "judge", "providers"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                self.assertFalse(banned & {a.name.split(".")[0] for a in node.names})
            if isinstance(node, ast.ImportFrom):
                self.assertNotIn((node.module or "").split(".")[0], banned)
        candidate = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "FrozenLexicalRetriever")
        attributes = {n.attr for n in ast.walk(candidate) if isinstance(n, ast.Attribute)}
        self.assertFalse(attributes & {"entrant_id", "provider_id", "model_id", "call_number"})
        self.assertNotIn("f1_eligibility", {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)})

    def test_source_reads_are_closed_and_no_legacy_code_changes(self):
        allowed = set(nfr.RETAINED_PINS) | set(nfr.INPUT_PINS) | {nfr.CODE_PATH}
        original = Path.read_bytes
        seen = set()
        def checked(path):
            relative = path.relative_to(ROOT).as_posix()
            self.assertIn(relative, allowed)
            seen.add(relative)
            return original(path)
        with patch.object(Path, "read_bytes", checked):
            nfr.build_bundle()
        self.assertEqual(allowed, seen)
        for path, digest in nfr.RETAINED_PINS.items():
            self.assertEqual(digest, hashlib.sha256((ROOT / path).read_bytes()).hexdigest())

    def test_source_input_and_implementation_content_mutation_fail_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.copy_sources(root)
            for path in ("search_cup/v23_t3_f1q.py", nfr.CONFIG_PATH, nfr.FIXTURE_PATH, nfr.CODE_PATH):
                target = root / path
                saved = target.read_bytes()
                target.write_bytes(saved + b"\n")
                with self.subTest(path=path), self.assertRaisesRegex(ValueError, "CONTENT_MISMATCH"):
                    nfr.build_bundle(root=root)
                target.write_bytes(saved)

    def test_descriptor_binds_code_config_corpus_schemas_and_unicode_runtime(self):
        candidate = self.bundle["candidate"]
        self.assertEqual(hashlib.sha256((ROOT / nfr.CODE_PATH).read_bytes()).hexdigest(), candidate["code_content_sha256"])
        self.assertEqual(nfr.CONFIG_FINGERPRINT, candidate["config_fingerprint"])
        self.assertEqual(nfr.unicodedata.unidata_version, candidate["normalization_runtime"]["unicode_data_version"])
        for key in ("request_schema", "result_schema", "search_proxy", "capabilities", "retry_fallback_policy"):
            self.assertIn(key, candidate)
        self.assertEqual(nfr.TEST_CORPUS_FINGERPRINT, self.bundle["corpus"]["corpus_fingerprint"])

    def test_repeated_package_build_is_deterministic_with_exact_call_accounting(self):
        before = self.fixture_calls
        other = nfr.build_bundle()
        self.assertEqual(before + 8, self.fixture_calls)
        self.assertEqual(canonical_json(self.bundle), canonical_json(other))
        self.assertEqual(8, other["conformance"]["local_fixture_retriever_calls"])
        self.assertEqual(nfr.expected_observations(), other["conformance"]["conformance_cases"])
        self.assertEqual(self.corpus.canonical_content, self.bundle["corpus"]["corpus_canonical_json"])

    def test_validator_checks_bindings_without_executing_fixture_again(self):
        before = self.fixture_calls
        nfr.validate_bundle(self.bundle)
        self.assertEqual(before, self.fixture_calls)
        changed = deepcopy(self.bundle)
        changed["candidate"] = seal({**changed["candidate"], "code_content_sha256": "0" * 64})
        with self.assertRaises(ValueError):
            nfr.validate_bundle(changed)

    def test_candidate_claims_and_fixture_authority_cannot_be_resealed_into_approval(self):
        self.assertEqual("PENDING", self.bundle["conformance"]["independent_acceptance"])
        for field in ("r1_r8_qualification_performed", "f1_eligible_claimed", "t5_execution_authorized", "live_execution_authorized"):
            self.assertIs(False, self.bundle["conformance"][field])
            changed = deepcopy(self.bundle)
            changed["conformance"] = seal({**changed["conformance"], field: True})
            with self.subTest(field=field), self.assertRaises(ValueError):
                nfr.validate_bundle(changed)
        for field in ("e1_corpus_authority", "d4_authority", "reference_set", "benchmark_corpus"):
            changed = deepcopy(self.bundle)
            changed["corpus"] = seal({**changed["corpus"], field: True})
            with self.subTest(field=field), self.assertRaises(ValueError):
                nfr.validate_bundle(changed)

    def test_zero_operation_receipt_has_separate_positive_local_count(self):
        resource = self.bundle["resources"]
        expected = {"live_search_calls", "provider_calls", "model_calls", "network_calls", "credential_reads",
                    "credit_consumption", "automatic_retries", "subprocess_calls", "e1_frozen_runs", "e1_live_runs", "t5_runs"}
        self.assertEqual(expected, {k for k, v in resource.items() if type(v) is int and v == 0})
        self.assertEqual(8, resource["local_fixture_retriever_calls"])
        self.assertEqual({"currency": "USD", "value": 0}, resource["spend"])
        self.assertFalse(resource["hidden_registry_loaded"] or resource["official_prompt_consumed"])
        self.assertEqual("RETRIEVER_IMPLEMENTATION_EVIDENCE_ONLY", resource["claims_ceiling"])
        for delta in (True, 0, 9):
            with self.assertRaises(ValueError):
                nfr.resource_receipt(delta)

    def test_manifest_byte_hashes_and_fresh_directory_rule(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "bundle"
            before = self.fixture_calls
            nfr.write_bundle(target)
            self.assertEqual(before + 8, self.fixture_calls)
            self.assertEqual(set(nfr.PAYLOADS.values()) | {"MANIFEST.sha256"}, {p.name for p in target.iterdir()})
            manifest = (target / "MANIFEST.sha256").read_text()
            self.assertEqual(5, len(manifest.splitlines()))
            for line in manifest.splitlines():
                digest, name = line.split("  ", 1)
                self.assertEqual(digest, hashlib.sha256((target / name).read_bytes()).hexdigest())
            with self.assertRaises(FileExistsError):
                nfr.write_bundle(target)
            self.assertEqual(before + 8, self.fixture_calls)
            self.assertEqual(manifest, (target / "MANIFEST.sha256").read_text())

    def test_cli_outputs_implementation_evidence_only(self):
        before = self.fixture_calls
        with redirect_stdout(io.StringIO()) as output:
            self.assertEqual(0, nfr.main(["receipt", "--expected-source-sha", nfr.BASELINE_SHA,
                                         "--expected-source-tree", nfr.BASELINE_TREE]))
        receipt = json.loads(output.getvalue())
        self.assertEqual(before + 8, self.fixture_calls)
        self.assertFalse(receipt["r1_r8_qualification_performed"] or receipt["f1_eligible_claimed"])
        self.assertEqual("PASS", receipt["implementation_conformance"])
        self.assertNotIn("qualification_result", receipt)


if __name__ == "__main__":
    unittest.main()
