"""Immutable lexical retrieval and synthetic implementation evidence, never F1 qualification."""
from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import unicodedata
from urllib.parse import urlsplit

from .contracts import SearchRequest, SearchResult, canonical_json, fingerprint
from .protocol_v23 import assert_content_safe, seal, verify_seal
from .tools import SearchBackendResponse

WORK_ORDER = "WO-ENG-B1-SC-V23-T3-NFR-01 v0.1"
BASELINE_SHA = "db6ba8746e6776c02b5942e38919316aebf65fe0"
BASELINE_TREE = "52c37289c283ccbe89b974fae099ac0671aea678"
CANDIDATE_ID = "search-cup-v23-frozen-lexical-raw-v1"
BACKEND_ID = "search-cup-v23/frozen-lexical-raw-v1"
IMPLEMENTATION = "search_cup.v23_frozen_retriever:FrozenLexicalRetriever"
CODE_PATH = "search_cup/v23_frozen_retriever.py"
CONFIG_PATH = "configs/search-cup-v23-frozen-retriever-v1.json"
FIXTURE_PATH = "fixtures/search-cup/v23-frozen-retriever-test-corpus-v1.json"
CONFIG_FINGERPRINT = "2f60df7627f611c29f425dfccb94936cf606774fc619e48fe34c650f738ac7ca"
TEST_CORPUS_FINGERPRINT = "ec12c5e478b9b95c8f24104bca5147717ba7ca5018fea043cf8e9f658b7377d4"
CLAIMS_CEILING = "RETRIEVER_IMPLEMENTATION_EVIDENCE_ONLY"
APPROVED_PATHS = tuple(sorted((CODE_PATH, CONFIG_PATH, FIXTURE_PATH,
    "tests/test_search_cup_v23_frozen_retriever.py",
    "docs/search-cup-v23-frozen-retriever.md",
    ".github/workflows/t3-frozen-retriever-offline.yml")))
RETAINED_PINS = {
    "search_cup/contracts.py": "e08fea09a5e66694079425648642ba7ad14076c977b19fc1a5771ee9b4bac184",
    "search_cup/tools.py": "6bf6b34c651ca100c317f151a028ecf75d5ccdf53747df5c9152e900fa611af4",
    "search_cup/search_pro.py": "fddafa96bcb1c9694c32706c2f985fc0abc6cb484e457cf9b3dd65180aaeaab9",
    "search_cup/protocol_v23.py": "50b6927bd1bc22ba42a40857f5e71658eae38aae0cc7d38fad5fa1b49396127b",
    "search_cup/v23_schema.py": "8c34ffca7bb64a8c9c4ad0985290f4b41e9fb62baef6ec66066cd0e2a2af0fef",
    "search_cup/v23_t3_f1q.py": "90b18ffeb4ebe84a852158ac3545f1c5d25984121771b5f140736c9387733e0b",
    "search_cup/v23_t4_instance.py": "a60de48ee7467922b0f0a19d78594fd0785ae427cef75bf7d938880f619f7ad6",
    "search_cup/v23_t4_execution.py": "fbcdcd8b24d087bf9a26785773151fb8c23dd28a4107364d0c1d49a4ec71ea75",
    "search_cup/v23_t4_je1.py": "7be87d913a6aba9f4af6587820f71751d88b8f2f10c75e5b5caa8e005c9efb63",
}
INPUT_PINS = {
    CONFIG_PATH: "773bc12c7b571d14119641a61aeba69a81776cd131d6926e813c3c09fecbed4c",
    FIXTURE_PATH: "6f0a0121c9ebf95bbee8c0c36efdc1dd7558d42c29175959c452f63b4403ceca",
}
PAYLOADS = {
    "candidate": "candidate-descriptor.json", "config": "candidate-config.json",
    "corpus": "test-corpus-descriptor.json", "conformance": "implementation-conformance.json",
    "resources": "resource-zero-receipt.json",
}


def baseline(sha=BASELINE_SHA, tree=BASELINE_TREE):
    if (sha, tree) != (BASELINE_SHA, BASELINE_TREE):
        raise ValueError("BASELINE_DRIFT")
    return {"sha": sha, "tree": tree}


def claim_boundary():
    return {"claims_ceiling": CLAIMS_CEILING, "r1_r8_qualification_performed": False,
            "f1_eligible_claimed": False, "t5_execution_authorized": False,
            "live_execution_authorized": False}


def normalize(text: str) -> str:
    """NFKC, casefold, Unicode letters/numbers, one separator per other run."""
    if type(text) is not str:
        raise TypeError("TEXT_REQUIRED")
    folded = unicodedata.normalize("NFKC", text).casefold()
    return " ".join("".join(c if unicodedata.category(c)[0] in "LN" else " " for c in folded).split())


def character_units(text: str) -> tuple[tuple[str, int], ...]:
    counts = Counter()
    for span in normalize(text).split():
        size = 3 if len(span) >= 3 else 1
        counts.update(span[i:i + size] for i in range(len(span) - size + 1))
    return tuple(sorted(counts.items()))


def overlap(left: tuple[tuple[str, int], ...], right: tuple[tuple[str, int], ...]) -> int:
    right_counts = dict(right)
    return sum(min(count, right_counts.get(unit, 0)) for unit, count in left)


@dataclass(frozen=True, slots=True)
class CorpusDocument:
    doc_id: str
    title: str
    url: str
    text: str

    def __post_init__(self):
        if any(type(v) is not str for v in (self.doc_id, self.title, self.url, self.text)):
            raise ValueError("MALFORMED_CORPUS_DOCUMENT")
        if not self.doc_id.strip() or self.doc_id != self.doc_id.strip() or not self.title.strip():
            raise ValueError("MALFORMED_CORPUS_DOCUMENT")
        parsed = urlsplit(self.url)
        if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username
                or parsed.password or any(c.isspace() for c in self.url)):
            raise ValueError("MALFORMED_CORPUS_URL")
        assert_content_safe(self.as_dict())

    def as_dict(self):
        return {"doc_id": self.doc_id, "title": self.title, "url": self.url, "text": self.text}


@dataclass(frozen=True, slots=True, init=False)
class FrozenCorpus:
    documents: tuple[CorpusDocument, ...]
    canonical_content: str
    canonical_fingerprint: str

    def __init__(self, documents, *, expected_fingerprint=None):
        if type(documents) not in (list, tuple):
            raise ValueError("CORPUS_DOCUMENT_SEQUENCE_REQUIRED")
        copied = []
        for item in documents:
            if type(item) is CorpusDocument:
                item = item.as_dict()
            if type(item) is not dict or set(item) != {"doc_id", "title", "url", "text"}:
                raise ValueError("MALFORMED_CORPUS_DOCUMENT")
            copied.append(CorpusDocument(**item))
        ordered = tuple(sorted(copied, key=lambda d: d.doc_id))
        if len({d.doc_id for d in ordered}) != len(ordered):
            raise ValueError("DUPLICATE_DOC_ID")
        content = {"schema_id": "search-cup-v23-frozen-corpus/v1", "documents": [d.as_dict() for d in ordered]}
        digest = fingerprint(content)
        if expected_fingerprint is not None and expected_fingerprint != digest:
            raise ValueError("CORPUS_FINGERPRINT_MISMATCH")
        object.__setattr__(self, "documents", ordered)
        object.__setattr__(self, "canonical_content", canonical_json(content))
        object.__setattr__(self, "canonical_fingerprint", digest)


@dataclass(frozen=True, slots=True, init=False)
class FrozenConfig:
    canonical_content: str
    canonical_fingerprint: str

    def __init__(self, config):
        assert_content_safe(config)
        if type(config) is not dict or fingerprint(config) != CONFIG_FINGERPRINT:
            raise ValueError("CONFIG_MISMATCH")
        object.__setattr__(self, "canonical_content", canonical_json(config))
        object.__setattr__(self, "canonical_fingerprint", CONFIG_FINGERPRINT)


@dataclass(frozen=True, slots=True, init=False)
class FrozenLexicalRetriever:
    """One immutable corpus/config; no counters, caches or entrant-specific state."""
    corpus: FrozenCorpus
    config: FrozenConfig
    _index: tuple
    backend_id = BACKEND_ID

    def __init__(self, corpus: FrozenCorpus, config: FrozenConfig):
        if type(corpus) is not FrozenCorpus or type(config) is not FrozenConfig:
            raise TypeError("EXPLICIT_FROZEN_CORPUS_AND_CONFIG_REQUIRED")
        object.__setattr__(self, "corpus", corpus)
        object.__setattr__(self, "config", config)
        object.__setattr__(self, "_index", tuple((d, character_units(d.title + "\n" + d.text)) for d in corpus.documents))

    def __call__(self, request: SearchRequest) -> SearchBackendResponse:
        if type(request) is not SearchRequest:
            raise TypeError("SEARCHREQUEST_REQUIRED")
        query_units = character_units(request.query)
        scored = ((overlap(query_units, units), doc) for doc, units in self._index)
        ordered = sorted(((score, doc) for score, doc in scored if score > 0),
                         key=lambda row: (-row[0], row[1].doc_id))[:10]
        results = tuple(SearchResult(title=d.title, url=d.url, snippet=d.text[:240]) for _, d in ordered)
        return SearchBackendResponse(results=results, backend_id=BACKEND_ID, request_id=request.request_id)


def load_inputs(root=None, *, expected_sha=BASELINE_SHA, expected_tree=BASELINE_TREE):
    """Validate retained source bytes, never execute Git or inspect the environment."""
    baseline(expected_sha, expected_tree)
    root = Path(root) if root is not None else Path(__file__).resolve().parents[1]
    sources = {}
    for path, digest in {**RETAINED_PINS, **INPUT_PINS}.items():
        data = (root / path).read_bytes()
        if hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("PINNED_SOURCE_CONTENT_MISMATCH")
        sources[path] = data
    code = (root / CODE_PATH).read_bytes()
    if code != Path(__file__).resolve().read_bytes():
        raise ValueError("IMPLEMENTATION_CONTENT_MISMATCH")
    code_digest = hashlib.sha256(code).hexdigest()
    config = FrozenConfig(json.loads(sources[CONFIG_PATH]))
    fixture = json.loads(sources[FIXTURE_PATH])
    expected_header = {
        "schema_id": "search-cup-v23-retriever-test-fixture/v1", "fixture_id": "nfr-synthetic-fixture-v1",
        "purpose": "SYNTHETIC_TEST_FIXTURE_ONLY", "e1_corpus_authority": False,
        "d4_authority": False, "benchmark_corpus": False, "reference_set": False,
    }
    if {k: v for k, v in fixture.items() if k != "documents"} != expected_header:
        raise ValueError("TEST_FIXTURE_AUTHORITY_MISMATCH")
    corpus = FrozenCorpus(fixture["documents"], expected_fingerprint=TEST_CORPUS_FINGERPRINT)
    return config, corpus, code_digest, expected_header


# Golden synthetic expectations, not relevance judgments or an E1 reference set.
_TOP_TEN = tuple("lex-" + str(i).zfill(2) for i in range(1, 11))
FIXTURE_CASES = (
    ("multiset-limit-ties", "alpha alpha", "fixture-a", _TOP_TEN),
    ("entrant-invariance", "alpha alpha", "fixture-b", _TOP_TEN),
    ("nfkc-casefold", "ＣＡＦÉ!!!", "fixture-a", ("lex-20",)),
    ("chinese-trigrams", "数据目录", "fixture-a", ("lex-20",)),
    ("short-spans", "猫 ab", "fixture-a", ("lex-21",)),
    ("punctuation-only", "!!!", "fixture-a", ()),
    ("zero-score", "zzzzzz", "fixture-a", ()),
    ("repeat-after-other-queries", "alpha alpha", "fixture-a", _TOP_TEN),
)


def expected_observations():
    return [{"case_id": name, "query": query, "entrant_id": entrant,
             "request_id": "fixture-request-" + str(i), "ordered_doc_ids": list(ids),
             "result_count": len(ids), "backend_id": BACKEND_ID}
            for i, (name, query, entrant, ids) in enumerate(FIXTURE_CASES, 1)]


def run_fixture_conformance(config, corpus):
    candidate = FrozenLexicalRetriever(corpus, config)
    observed = []
    by_url = {d.url: d.doc_id for d in corpus.documents}
    calls = 0
    for i, (name, query, entrant, _) in enumerate(FIXTURE_CASES, 1):
        request = SearchRequest(entrant_id=entrant, query=query, call_number=i, request_id="fixture-request-" + str(i))
        calls += 1
        response = candidate(request)
        if request.query != query or type(response) is not SearchBackendResponse:
            raise ValueError("FIXTURE_CONFORMANCE_FAILED")
        observed.append({"case_id": name, "query": request.query, "entrant_id": entrant,
                         "request_id": response.request_id, "ordered_doc_ids": [by_url[r.url] for r in response.results],
                         "result_count": len(response.results), "backend_id": response.backend_id})
    if observed != expected_observations() or calls != len(FIXTURE_CASES):
        raise ValueError("FIXTURE_CONFORMANCE_FAILED")
    return observed, calls


def resource_receipt(fixture_calls):
    if type(fixture_calls) is not int or fixture_calls != len(FIXTURE_CASES):
        raise ValueError("FIXTURE_CALL_COUNT_MISMATCH")
    return seal({**claim_boundary(), **dict.fromkeys(("live_search_calls", "provider_calls", "model_calls",
        "network_calls", "credential_reads", "credit_consumption", "automatic_retries", "subprocess_calls",
        "e1_frozen_runs", "e1_live_runs", "t5_runs"), 0),
        "spend": {"currency": "USD", "value": 0}, "hidden_registry_loaded": False,
        "official_prompt_consumed": False, "local_fixture_retriever_calls": fixture_calls,
        "accounting_scope": "ONE_SYNTHETIC_PACKAGE_CONFORMANCE_BUILD"})


def _assemble(config, corpus, code_digest, fixture_header, observations, calls):
    settings = json.loads(config.canonical_content)
    candidate = seal({
        "schema_id": "search-cup-v23-frozen-retriever-candidate/v1", "work_order": WORK_ORDER,
        "source_baseline": baseline(), "candidate_id": CANDIDATE_ID, "retriever_class": "RAW_RETRIEVER",
        "module_class": IMPLEMENTATION, "backend_id": BACKEND_ID,
        "implementation_path": CODE_PATH, "code_content_sha256": code_digest,
        "config_fingerprint": config.canonical_fingerprint,
        "algorithm_id": settings["algorithm_id"], "normalization_id": settings["normalization_id"],
        "normalization_runtime": {"unicode_data_version": unicodedata.unidata_version},
        "selector": {"rule": "EXPLICIT_AUTHORITY_PIN_TO_CANDIDATE_ID", "candidate_id": CANDIDATE_ID,
                     "authority": WORK_ORDER, "implementation_authorized_by": "USER_APPROVAL_IN_TASK_THREAD"},
        "search_proxy": {"path": "search_cup/tools.py", "symbol": "BudgetedSearchProxy",
                         "source_sha256": RETAINED_PINS["search_cup/tools.py"]},
        "request_schema": {"path": "search_cup/contracts.py", "symbol": "SearchRequest",
                           "source_sha256": RETAINED_PINS["search_cup/contracts.py"]},
        "result_schema": {"response_path": "search_cup/tools.py", "response_symbol": "SearchBackendResponse",
                          "response_source_sha256": RETAINED_PINS["search_cup/tools.py"],
                          "result_path": "search_cup/contracts.py", "result_symbol": "SearchResult",
                          "result_source_sha256": RETAINED_PINS["search_cup/contracts.py"]},
        "result_mapping": {"title": "document.title", "url": "document.url", "snippet": "document.text[:240]"},
        "result_limit": 10, "retry_fallback_policy": {"automatic_retries": 0, "fallback_policy": "NONE"},
        "capabilities": ["LOCAL_DETERMINISTIC_LEXICAL_RETRIEVAL"],
        "corpus_binding": "EXPLICIT_IMMUTABLE_CALLER_SUPPLIED_CORPUS_REQUIRED",
        "retained_source_pins": RETAINED_PINS, **claim_boundary(),
    })
    config_payload = seal({"config": settings, "config_fingerprint": config.canonical_fingerprint,
                           "source_path": CONFIG_PATH, "source_content_sha256": INPUT_PINS[CONFIG_PATH]})
    corpus_payload = seal({**fixture_header, "corpus_fingerprint": corpus.canonical_fingerprint,
                           "corpus_canonical_json": corpus.canonical_content,
                           "document_count": len(corpus.documents), "source_path": FIXTURE_PATH,
                           "source_content_sha256": INPUT_PINS[FIXTURE_PATH],
                           "fixture_instance_fingerprint": fingerprint({"candidate": candidate["canonical_fingerprint"],
                                                                        "corpus": corpus.canonical_fingerprint})})
    resources = resource_receipt(calls)
    package_id = fingerprint({"source_baseline": baseline(), "candidate": candidate["canonical_fingerprint"],
                              "config": config_payload["canonical_fingerprint"], "corpus": corpus_payload["canonical_fingerprint"],
                              "resources": resources["canonical_fingerprint"], "observations": observations})
    report = seal({"schema_id": "search-cup-v23-nfr-implementation-conformance/v1", "work_order": WORK_ORDER,
                   "source_baseline": baseline(), "implementation_conformance": "PASS",
                   "independent_acceptance": "PENDING", "candidate_identity_acceptance": "PENDING",
                   "candidate_fingerprint": candidate["canonical_fingerprint"], "code_content_sha256": code_digest,
                   "config_fingerprint": config.canonical_fingerprint, "test_corpus_fingerprint": corpus.canonical_fingerprint,
                   "package_fingerprint": package_id, "local_fixture_retriever_calls": calls,
                   "conformance_cases": observations, "resource_receipt_fingerprint": resources["canonical_fingerprint"],
                   **claim_boundary()})
    return {"candidate": candidate, "config": config_payload, "corpus": corpus_payload,
            "conformance": report, "resources": resources}


def build_bundle(**kwargs):
    config, corpus, code_digest, header = load_inputs(**kwargs)
    observations, calls = run_fixture_conformance(config, corpus)
    return _assemble(config, corpus, code_digest, header, observations, calls)


def validate_bundle(bundle, **kwargs):
    """Validate source/claims/golden report bindings without executing another query."""
    if type(bundle) is not dict or set(bundle) != set(PAYLOADS):
        raise ValueError("PACKAGE_SHAPE_MISMATCH")
    for payload in bundle.values():
        verify_seal(payload)
    config, corpus, code_digest, header = load_inputs(**kwargs)
    expected = _assemble(config, corpus, code_digest, header, expected_observations(), len(FIXTURE_CASES))
    if canonical_json(bundle) != canonical_json(expected):
        raise ValueError("CANDIDATE_PACKAGE_MUTATED")


def write_bundle(output_dir, **kwargs):
    target = Path(output_dir)
    if target.exists():
        raise FileExistsError("OUTPUT_DIRECTORY_ALREADY_EXISTS")
    bundle = build_bundle(**kwargs)
    validate_bundle(bundle, **kwargs)
    target.mkdir(parents=False, exist_ok=False)
    for key, name in PAYLOADS.items():
        (target / name).write_text(canonical_json(bundle[key]), encoding="utf-8")
    manifest = "".join(hashlib.sha256(p.read_bytes()).hexdigest() + "  " + p.name + "\n" for p in sorted(target.iterdir()))
    (target / "MANIFEST.sha256").write_text(manifest, encoding="utf-8")
    return bundle["conformance"]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("receipt", "bundle"))
    parser.add_argument("--expected-source-sha", required=True)
    parser.add_argument("--expected-source-tree", required=True)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args(argv)
    kwargs = {"expected_sha": args.expected_source_sha, "expected_tree": args.expected_source_tree}
    if args.command == "bundle":
        if args.output_dir is None:
            parser.error("bundle requires --output-dir")
        result = write_bundle(args.output_dir, **kwargs)
    else:
        if args.output_dir is not None:
            parser.error("receipt does not write a directory")
        result = build_bundle(**kwargs)["conformance"]
    print(canonical_json(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
