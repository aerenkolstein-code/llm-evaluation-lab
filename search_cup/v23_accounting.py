"""Pure offline accounting reducer: records supplied facts, never calls a tool.

An attempted failure spends a ticket; pre-boundary rejection does not. Actual
overruns remain visible (never dropped to make a receipt appear within budget).
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from .contracts import canonical_json, fingerprint
from .protocol_v23 import SearchSpecV2, assert_content_safe, seal, validate_measure
from .v23_schema import COUNT, MEASURE, NUMBER, REF, TEXT, arr, const, enum, obj, validate_shape


EVENT_SCHEMA = obj({
    "event_id": TEXT, "kind": enum("SEARCH", "VERIFY", "MODEL"),
    "unit": enum("RAW_BACKEND_ATTEMPT", "INTEGRATED_STACK_INVOCATION", "VERIFICATION", "MODEL_REQUEST"),
    "status": enum("SUCCEEDED", "FAILED", "REJECTED"),
    "crossed_boundary": {"type": "boolean"}, "turn": COUNT, "result_count": COUNT,
    "elapsed_ms": NUMBER, "tokens": MEASURE, "money": MEASURE,
    "retry_kind": enum("NONE", "MANUAL", "AUTOMATIC"),
    "retry_of": {"type": ["string", "null"]},
    "failure_class": enum("NONE", "INFRASTRUCTURE", "BUDGET", "POLICY"),
    "request_fingerprint": {"anyOf": [REF, {"type": "null"}]},
    "result_fingerprints": arr(REF),
})


def measure(value: float | int | None, unit: str, *, state: str | None = None, reason: str = "observed fixture value") -> dict:
    result = {"state": state or ("KNOWN" if value is not None else "UNKNOWN"),
              "value": value, "unit": unit, "reason": reason}
    validate_measure(result)
    return result


def total_measure(values: list[dict], unit: str) -> dict:
    for item in values:
        validate_measure(item, unit)
    if any(item["state"] == "UNKNOWN" for item in values):
        return measure(None, unit, reason="at least one raw component unobservable")
    if any(item["state"] == "NOT_APPLICABLE" for item in values):
        return measure(None, unit, state="NOT_APPLICABLE", reason="component not applicable; no zero imputation")
    return measure(sum(item["value"] for item in values), unit, reason="sum of raw observed components")


@dataclass(frozen=True)
class ResourceLedger:
    """Immutable event history; a new append returns a new verified ledger."""

    spec: SearchSpecV2
    run_id: str
    events_json: str = "[]"

    def __post_init__(self) -> None:
        if self.spec.as_dict()["spec_status"] != "FROZEN":
            raise ValueError("accounting requires frozen SearchSpec")
        validate_shape(self.run_id, TEXT)
        assert_content_safe(self.run_id)
        events = json.loads(self.events_json)
        if type(events) is not list or canonical_json(events) != self.events_json:
            raise ValueError("noncanonical accounting events")
        prior: list[dict] = []
        for event in events:
            self._validate_event(event, prior)
            prior.append(event)

    @property
    def events(self) -> list[dict]:
        return json.loads(self.events_json)

    def _validate_event(self, event: dict, prior: list[dict]) -> None:
        validate_shape(event, EVENT_SCHEMA)
        assert_content_safe(event)
        resource = self.spec.as_dict()["resources"]
        validate_measure(event["tokens"], "tokens")
        validate_measure(event["money"], resource["money_ceiling"]["unit"])
        if event["event_id"] in {e["event_id"] for e in prior}:
            raise ValueError("duplicate accounting event")
        if event["crossed_boundary"] != (event["status"] != "REJECTED"):
            raise ValueError("attempt/status mismatch")
        if event["status"] == "SUCCEEDED" and event["failure_class"] != "NONE":
            raise ValueError("successful event cannot have failure")
        if event["status"] == "FAILED" and event["failure_class"] != "INFRASTRUCTURE":
            raise ValueError("backend failure must remain infrastructure")
        if event["status"] == "REJECTED":
            if event["failure_class"] not in ("BUDGET", "POLICY") or event["result_count"] or event["result_fingerprints"]:
                raise ValueError("invalid pre-boundary rejection")
            if any(event[k]["state"] != "KNOWN" or event[k]["value"] != 0 for k in ("money", "tokens")):
                raise ValueError("pre-boundary rejection must not consume backend resources")
        if len(event["result_fingerprints"]) != event["result_count"]:
            raise ValueError("result provenance count mismatch")
        expected_unit = {"SEARCH": resource["search_unit"], "VERIFY": "VERIFICATION", "MODEL": "MODEL_REQUEST"}[event["kind"]]
        # A denied Judgment-only request may be recorded, but never an attempt.
        if expected_unit == "NONE":
            if event["crossed_boundary"]:
                raise ValueError("Judgment-only prohibits search attempts")
        elif event["unit"] != expected_unit:
            raise ValueError("resource-unit equivalence is forbidden")
        if self.spec.as_dict()["track_id"] == "JUDGMENT_ONLY" and event["kind"] == "VERIFY" and event["crossed_boundary"]:
            raise ValueError("Judgment-only prohibits live verification")
        if event["crossed_boundary"] and event["request_fingerprint"] is None:
            raise ValueError("attempt must retain request provenance")
        if event["kind"] == "SEARCH" and event["crossed_boundary"]:
            last_turn = max((e["turn"] for e in prior if e["kind"] == "SEARCH" and e["crossed_boundary"]), default=0)
            if event["turn"] < max(1, last_turn) or event["turn"] > last_turn + 1:
                raise ValueError("search-turn sequence invalid")
        elif event["kind"] != "SEARCH" and event["turn"] != 0:
            raise ValueError("non-search event cannot increment search turns")
        if event["retry_kind"] == "NONE":
            if event["retry_of"] is not None:
                raise ValueError("undeclared retry")
        else:
            target = next((e for e in prior if e["event_id"] == event["retry_of"]), None)
            if target is None or target["kind"] != event["kind"] or target["status"] != "FAILED":
                raise ValueError("retry must reference a prior failed same-kind attempt")
            if event["retry_kind"] == "MANUAL" and resource["manual_retry_policy"] != "NEW_BUDGETED_EVENT":
                raise ValueError("manual retry forbidden")
            if event["retry_kind"] == "AUTOMATIC":
                root = target
                while root["retry_of"] is not None:
                    root = next(e for e in prior if e["event_id"] == root["retry_of"])
                def root_id(item: dict) -> str:
                    while item["retry_of"] is not None:
                        item = next(e for e in prior if e["event_id"] == item["retry_of"])
                    return item["event_id"]
                count = sum(e["retry_kind"] == "AUTOMATIC" and root_id(e) == root["event_id"] for e in prior)
                if count >= resource["automatic_retries"]:
                    raise ValueError("automatic retry policy exceeded")

    def append(self, event: dict) -> "ResourceLedger":
        return ResourceLedger(self.spec, self.run_id, canonical_json([*self.events, event]))

    def receipt(self, *, entrant_fingerprint: str, elapsed_ms: float,
                operator_ms: dict, waiting_ms: dict, outcomes: dict, price_evidence: list[dict]) -> dict:
        from .v23_schema import HASH
        validate_shape(entrant_fingerprint, HASH)
        validate_shape(elapsed_ms, NUMBER)
        validate_measure(operator_ms, "ms")
        validate_measure(waiting_ms, "ms")
        validate_shape(price_evidence, arr(REF))
        assert_content_safe(outcomes)
        for value in outcomes.values():
            validate_measure(value)
        doc, events = self.spec.as_dict(), self.events
        resource = doc["resources"]
        attempts = [e for e in events if e["crossed_boundary"]]
        search = [e for e in attempts if e["kind"] == "SEARCH"]
        verification = [e for e in attempts if e["kind"] == "VERIFY"]
        tokens = total_measure([e["tokens"] for e in attempts], "tokens")
        money = total_measure([e["money"] for e in attempts], resource["money_ceiling"]["unit"])
        turns = max((e["turn"] for e in search), default=0)
        violations = []
        for label, observed, ceiling in (("SEARCH_CALLS", len(search), resource["max_search_calls"]),
                                          ("SEARCH_TURNS", turns, resource["max_search_turns"]),
                                          ("FOLLOW_LINKS", len(verification), resource["max_follow_links"])):
            if observed > ceiling:
                violations.append(label + "_EXCEEDED")
        if any(e["result_count"] > resource["max_results_per_call"] for e in search):
            violations.append("RESULT_LIMIT_EXCEEDED")
        if any(e["elapsed_ms"] > resource["timeout_per_call_ms"] for e in attempts):
            violations.append("CALL_TIMEOUT_EXCEEDED")
        for label, observed, ceiling in (("TOKENS", tokens, resource["token_ceiling"]),
                                          ("MONEY", money, resource["money_ceiling"]),
                                          ("RUNTIME", measure(elapsed_ms, "ms"), resource["max_total_runtime_ms"])):
            if ceiling["state"] == "KNOWN":
                if observed["state"] != "KNOWN":
                    violations.append(label + "_COMPLIANCE_UNKNOWN")
                elif observed["value"] > ceiling["value"]:
                    violations.append(label + "_EXCEEDED")
        if elapsed_ms < max((e["elapsed_ms"] for e in attempts), default=0):
            raise ValueError("elapsed time shorter than a recorded call")
        if doc["fairness_mode"] == "F3" and money["state"] == "KNOWN" and not price_evidence:
            violations.append("PRICE_EVIDENCE_MISSING")
        if any(e["status"] == "REJECTED" for e in events):
            violations.append("REQUEST_REJECTED")
        infrastructure = sum(e["status"] == "FAILED" for e in attempts)
        terminal = "BLOCKED" if violations else "NOT_EVALUABLE" if infrastructure else "PASS"
        return seal({
            "schema_id": "search-resource-receipt/v2", "run_id": self.run_id,
            "spec_fingerprint": self.spec.fingerprint, "track_id": doc["track_id"],
            "fairness_mode": doc["fairness_mode"], "entrant_fingerprint": entrant_fingerprint,
            "retriever_fingerprint": fingerprint(doc["retriever"]) if doc["retriever"] else None,
            "resource_contract_fingerprint": fingerprint(resource), "events": events,
            "search_unit": resource["search_unit"],
            "search_attempted": len(search), "search_succeeded": sum(e["status"] == "SUCCEEDED" for e in search),
            "search_failed": sum(e["status"] == "FAILED" for e in search),
            "search_remaining": max(0, resource["max_search_calls"] - len(search)),
            "search_turns": turns, "results": sum(e["result_count"] for e in search),
            "follow_links": len(verification), "provider_requests": sum(e["kind"] == "MODEL" for e in attempts),
            "automatic_retries": sum(e["retry_kind"] == "AUTOMATIC" for e in attempts),
            "manual_retries": sum(e["retry_kind"] == "MANUAL" for e in attempts),
            "retry_policy": resource["retry_policy"], "tokens": tokens, "money": money,
            "money_by_class": {kind: total_measure([e["money"] for e in attempts if e["kind"] == kind], money["unit"])
                               for kind in ("SEARCH", "VERIFY", "MODEL")},
            "paid_failed_attempts": [e["event_id"] for e in attempts if e["status"] == "FAILED" and
                                     (e["money"]["state"] != "KNOWN" or e["money"]["value"] > 0)],
            "elapsed_ms": elapsed_ms, "operator_ms": operator_ms, "waiting_ms": waiting_ms,
            "infrastructure_failures": infrastructure, "outcome_inputs": outcomes,
            "price_evidence": price_evidence, "terminal_status": terminal,
            "reason_codes": sorted(violations), "quality_score": None,
            "secret_exclusion": {"scanner": "public-safe-patterns/v1", "status": "PASS"},
            "evidence_kind": "OFFLINE_SUPPLIED_ACCOUNTING_FACTS_NOT_EXECUTION",
        })


def validate_resource_receipt(document: dict, spec: SearchSpecV2) -> None:
    """Recompute every derived field; a fresh self-hash is not accounting proof."""
    from .protocol_v23 import verify_seal
    verify_seal(document)
    try:
        ledger = ResourceLedger(spec, document["run_id"], canonical_json(document["events"]))
        rebuilt = ledger.receipt(entrant_fingerprint=document["entrant_fingerprint"],
            elapsed_ms=document["elapsed_ms"], operator_ms=document["operator_ms"],
            waiting_ms=document["waiting_ms"], outcomes=document["outcome_inputs"],
            price_evidence=document["price_evidence"])
    except (KeyError, TypeError):
        raise ValueError("resource receipt shape mismatch") from None
    if document != rebuilt:
        raise ValueError("resource receipt accounting mismatch")
