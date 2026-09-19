"""Pure evidence derivation. No file, process, transport or environment access."""
from __future__ import annotations

from dataclasses import asdict
import json

from .v23_t6_cslive_retriever import ControlledSourceRetriever, SearchRequest, runtime_identity
from .v23_t6_cslive_source import EpochStore, SourceError, SourcePolicy, canonical, digest, epoch_delta

BASE = "72932d41c862753d489ef2d2e1c6a2619f34a2d9"
BASE_TREE = "05c0953bfe67f9d684160a79ef7c9307dcd2a3a4"
PATHS = (
    "search_cup/v23_t6_cslive_source.py",
    "search_cup/v23_t6_cslive_retriever.py",
    "search_cup/v23_t6_cslive_evidence.py",
    "configs/search-cup-v23-t6-controlled-source-v1.json",
    "fixtures/search-cup/v23-t6-controlled-source-synthetic.json",
    "tests/test_search_cup_v23_t6_cslive.py",
    "docs/search-cup-v23-t6-cslive.md",
    ".github/workflows/t6-cslive-offline.yml",
)

REQUIREMENTS = {
    "R1": ("test_raw_query_parameter", "test_invalid_query_no_rewrite"),
    "R2": ("test_no_network_secret", "test_one_attempt_each", "test_source_has_no_query"),
    "R3": ("test_entrant_exchange", "test_deterministic_ties"),
    "R4": ("test_runtime_drift", "test_config_drift", "test_epoch_immutable"),
    "R5": ("test_normalized_provenance", "test_source_guid_opaque"),
    "R6": ("test_same_epoch_results", "test_budget_limit"),
    "R7": ("test_no_network_secret", "test_import_boundary", "test_html_rejected"),
    "R8": ("test_hash_chain", "test_manifest_inputs", "test_failed_refresh_no_stale"),
}


def verify_chain(events: list[dict]) -> bool:
    previous = None
    for i, event in enumerate(events):
        payload = {k: v for k, v in event.items() if k != "event_hash"}
        if (event.get("sequence") != i + 1 or event.get("previous_hash") != previous
                or event.get("event_hash") != digest(payload)):
            return False
        previous = event["event_hash"]
    return True


def _validate_config(config: dict) -> SourcePolicy:
    if set(config) != {"schema_id", "candidate_id", "mode", "source_policy", "production_source", "budget", "query", "claims"}:
        raise SourceError("CONFIG_SCHEMA_REJECTED")
    if (config["schema_id"] != "t6-cslive-config/v1"
            or config["candidate_id"] != "t6-controlled-source-fts5-v1"
            or config["mode"] != "SYNTHETIC_ONLY"):
        raise SourceError("CONFIG_DRIFT")
    if config["budget"] != {"epochs": 2, "entrants": ["fixture-a", "fixture-b"],
            "calls_per_entrant_per_epoch": 4, "results_per_call": 10,
            "automatic_retries": 0, "follow_links": 0, "fallback": False}:
        raise SourceError("CONFIG_DRIFT")
    if config["query"] != {"tokenizer": "unicode61 remove_diacritics 0", "title_weight": 1,
            "body_weight": 1, "order": ["bm25 ASC", "source_id ASC", "item_id ASC"],
            "raw_match_parameter": True}:
        raise SourceError("CONFIG_DRIFT")
    if config["claims"] != ["SYNTHETIC_OFFLINE_COMPONENT_VALIDATION_ONLY"]:
        raise SourceError("CLAIMS_REJECTED")
    if config["production_source"] != {"candidate": "Himalayas RSS",
            "url": "https://himalayas.app/jobs/rss", "admission": "NOT_ADMITTED",
            "live_access": "NOT_RUN", "rights": "NOT_VERIFIED"}:
        raise SourceError("SOURCE_ADMISSION_NOT_AUTHORIZED")
    return SourcePolicy(**config["source_policy"])


def assemble(config: dict, fixture: dict) -> dict[str, object]:
    policy = _validate_config(config)
    if fixture.get("synthetic") is not True or len(fixture.get("epochs", [])) != 2:
        raise SourceError("SYNTHETIC_FIXTURE_REQUIRED")
    runtime = runtime_identity()
    epochs, queries, results, deltas = [], [], [], []
    current_stamp = [""]
    store = EpochStore(policy, clock=lambda: current_stamp[0])
    for raw in fixture["epochs"]:
        current_stamp[0] = raw["captured_at"]
        e = store.ingest(raw["rss"].encode("utf-8"), epoch_id=raw["epoch_id"], source_url=policy.source_url)
        if len(store.epochs) > 1:
            deltas.append(epoch_delta(store.epochs[-2], e))
        epochs.append(e.as_dict())
        with ControlledSourceRetriever(e, clock=lambda: current_stamp[0], expected_runtime=runtime) as backend:
            schedules = fixture["queries"]
            for key in ("fixture-a", "fixture-b"):
                if len(schedules[key]) != 4:
                    raise SourceError("SCHEDULE_REJECTED")
            for key, number in (("fixture-a", 1), ("fixture-b", 1), ("fixture-b", 2), ("fixture-a", 2),
                                ("fixture-a", 3), ("fixture-b", 3), ("fixture-b", 4), ("fixture-a", 4)):
                response = backend.search(SearchRequest(key, number, schedules[key][number - 1]))
                event = json.loads(response.provenance_json)
                queries.append(event)
                results.extend({"epoch_id": e.epoch_id, "entrant_id": key, "call_number": number,
                                "query_event_hash": event["event_hash"], **asdict(r)} for r in response.results)
    return {"config.json": config, "source-policy.json": asdict(policy), "runtime.json": runtime,
            "epochs.json": epochs, "epoch-delta.json": deltas, "ingest-events.json": store.events,
            "query-provenance.json": queries, "result-provenance.json": results,
            "resource-receipt.json": {"synthetic_epochs": len(epochs), "search_attempts": sum(q["match_attempts"] for q in queries),
                "normalized_result_rows": len(results), "real_source_acquisitions": 0, "network_calls": 0,
                "provider_calls": 0, "model_calls": 0, "credential_reads": 0, "automatic_retries": 0,
                "follow_links": 0, "fallback_calls": 0, "spend": {"amount": 0, "currency": "USD"},
                "scope": "candidate code under tested deny-network/deny-secret harness; CI control plane excluded"}}


def qualification(test_records: dict[str, dict], *, source_hashes: dict[str, str]) -> dict:
    """Derive each scoped criterion from required actual named test results."""
    criteria = {}
    for criterion, names in REQUIREMENTS.items():
        records = [test_records.get(n) for n in names]
        refs = [{"id": n, "fingerprint": digest(record)} for n, record in zip(names, records) if record]
        if any(r is not None and r.get("status") == "FAIL" for r in records):
            status = "FAIL"
        elif all(r and r.get("status") == "PASS" and r.get("id") == n for n, r in zip(names, records)) and set(source_hashes) == set(PATHS):
            status = "PASS"
        else:
            status = "UNKNOWN"
        criteria[criterion] = {"status": status, "evidence": refs,
                               "scope": "SYNTHETIC_OFFLINE_CLIENT_PATH_ONLY"}
    return {"schema_id": "t6-cslive-scoped-qualification/v1", "criteria": criteria,
            "source_fingerprint": digest(source_hashes),
            "offline_mechanism_result": "PASS" if all(c["status"] == "PASS" for c in criteria.values()) else "NOT_EVALUABLE",
            "production_source_admission": "NOT_ADMITTED", "production_f1_eligibility": "NOT_F1_ELIGIBLE",
            "independent_qa": "PENDING", "live_validation": "NOT_RUN", "execution_authorized": False,
            "open_gates": ["SOURCE_RIGHTS_AND_CADENCE", "INDEPENDENT_F1_REVIEW", "INSTANCE_TRACK_FREEZE", "SEPARATE_LIVE_AUTHORITY"]}
