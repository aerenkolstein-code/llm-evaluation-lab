"""SP3 inert contract transforms and append-only record validation.

These functions do not score a candidate, invoke a judge, read a corpus/registry,
retrieve a URL or create a benchmark instance. Tests use synthetic supplied data.
"""

from __future__ import annotations

import json
import unicodedata
from dataclasses import dataclass

from .contracts import canonical_json, fingerprint
from .protocol_v23 import ENTRANT, SearchSpecV2, assert_content_safe, seal, timestamp, validate_entrant, verify_seal
from .v23_schema import HASH, REF, TEXT, arr, const, enum, obj, validate_shape


PROVENANCE_KEYS = {"provider", "model", "entrant", "submission", "branch", "commit", "run_id", "rank", "order"}
POOL_POLICY = obj({
    "id": TEXT, "version": TEXT, "normalization": const("NFKC_CASEFOLD_WHITESPACE_V1"),
    "identity_fields": arr(TEXT, 1), "visible_fields": arr(TEXT, 1),
    "collision_policy": const("UNKNOWN_IDENTITY"), "ordering": const("CANDIDATE_ID_ASC"),
})
POOL_ITEM = obj({"fields": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
                 "object_fingerprint": HASH, "evidence": arr(REF, 1),
                 "frozen_submission": REF, "source_alias": TEXT})


def _normal(value: str) -> str:
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def pool_candidates(items: list[dict], policy: dict) -> tuple[dict, dict]:
    validate_shape(policy, POOL_POLICY)
    assert_content_safe(policy)
    if not set(policy["identity_fields"]) <= set(policy["visible_fields"]):
        raise ValueError("identity fields must be frozen visible fields")
    if type(items) is not list or not items:
        raise ValueError("candidate pool requires nonempty supplied items")
    if any(any(token in field.lower() for token in PROVENANCE_KEYS) for field in policy["visible_fields"]):
        raise ValueError("provenance field cannot be visible")
    groups: dict[str, list[dict]] = {}
    field_schema = {**POOL_ITEM, "properties": {**POOL_ITEM["properties"], "fields": obj({key: TEXT for key in policy["visible_fields"]})}}
    for item in items:
        validate_shape(item, field_schema)
        assert_content_safe(item)
        key = {name: _normal(item["fields"][name]) for name in policy["identity_fields"]}
        candidate_id = "candidate-" + fingerprint({"key": key, "policy": policy})
        groups.setdefault(candidate_id, []).append(item)
    candidates, collisions, ledger = [], [], []
    for identity, group in sorted(groups.items()):
        evidence = {canonical_json(e): e for item in group for e in item["evidence"]}
        provenance = sorted({canonical_json({"submission": item["frozen_submission"], "source_alias": item["source_alias"]}) for item in group})
        ledger.append({"candidate_id": identity, "sources": [json.loads(p) for p in provenance]})
        # Same normalized key is not proof that materially different objects match.
        normalized_fields = [{key: _normal(value) if key in policy["identity_fields"] else value
                              for key, value in item["fields"].items()} for item in group]
        if len({item["object_fingerprint"] for item in group}) > 1 or len({canonical_json(f) for f in normalized_fields}) > 1:
            collisions.append({"candidate_id": identity, "terminal_status": "UNKNOWN_IDENTITY",
                               "evidence": [evidence[key] for key in sorted(evidence)]})
            continue
        candidates.append({"candidate_id": identity, "fields": normalized_fields[0],
                           "evidence": [evidence[key] for key in sorted(evidence)]})
    public = seal({"schema_id": "search-candidate-pool/v2", "policy": policy,
                   "candidates": candidates, "collisions": collisions})
    hidden = seal({"schema_id": "search-provenance-ledger/v2",
                   "candidate_set_fingerprint": public["canonical_fingerprint"], "entries": ledger})
    # Detect literal source labels embedded in allowlisted values as well as keys.
    rendered = canonical_json(public).casefold()
    if any(item["source_alias"].casefold() in rendered or item["frozen_submission"]["id"].casefold() in rendered for item in items):
        raise ValueError("provenance signal in blind package")
    return public, hidden


def validate_pool(pool: dict) -> None:
    verify_seal(pool)
    try:
        policy = pool["policy"]
        validate_shape(policy, POOL_POLICY)
        candidate_schema = obj({"candidate_id": TEXT, "fields": obj({k: TEXT for k in policy["visible_fields"]}),
                                "evidence": arr(REF, 1)})
        validate_shape(pool, obj({"schema_id": const("search-candidate-pool/v2"), "policy": POOL_POLICY,
            "candidates": arr(candidate_schema), "collisions": arr(obj({"candidate_id": TEXT,
                "terminal_status": const("UNKNOWN_IDENTITY"), "evidence": arr(REF, 1)})), "canonical_fingerprint": HASH}))
        if not set(policy["identity_fields"]) <= set(policy["visible_fields"]) or any(
            any(token in key.lower() for token in PROVENANCE_KEYS) for key in policy["visible_fields"]
        ):
            raise ValueError("invalid blind field policy")
        ids = [c["candidate_id"] for c in pool["candidates"]]
        if ids != sorted(set(ids)):
            raise ValueError("candidate identity/order mismatch")
        for candidate in pool["candidates"]:
            normalized = {k: _normal(v) if k in policy["identity_fields"] else v for k, v in candidate["fields"].items()}
            key = {k: normalized[k] for k in policy["identity_fields"]}
            expected_id = "candidate-" + fingerprint({"key": key, "policy": policy})
            if candidate["candidate_id"] != expected_id or normalized != candidate["fields"]:
                raise ValueError("candidate identity must derive from normalized task key")
    except (KeyError, TypeError):
        raise ValueError("candidate pool shape mismatch") from None


DIMENSION = obj({"id": TEXT, "allowed_values": arr(TEXT, 1), "evidence_threshold": TEXT,
                 "unknown_rule": const("INSUFFICIENT_EVIDENCE_NOT_NEGATIVE"), "hard_constraint": {"type": "boolean"},
                 "satisfying_values": arr(TEXT)})
RUBRIC = obj({"id": TEXT, "version": TEXT, "dimensions": arr(DIMENSION, 1),
              "confidence_allowed": {"type": "boolean"}, "hard_constraints_first": const(True),
              "aggregation": obj({"method": TEXT, "tie_policy": enum("ADJUDICATE", "PRESERVE_DISAGREEMENT"),
                                  "unknown_policy": const("PRESERVE"), "frozen_before_outputs": const(True)})})
ADJUDICATION = obj({"id": TEXT, "version": TEXT, "allowed": {"type": "boolean"},
                   "triggers": arr(enum("DISAGREEMENT", "CRITICAL_UNKNOWN", "IDENTITY_COLLISION", "CONTRADICTION", "RUBRIC_EDGE")),
                   "thresholds": REF, "evidence_policy": const("FROZEN_PACKET_ONLY"),
                   "append_only": const(True)})


def judgment_contract(pool: dict, evidence_packet: dict, rubric: dict, adjudication: dict,
                      *, output_schema: dict, resource_fingerprint: str, source_overlay: dict) -> dict:
    validate_pool(pool)
    validate_shape(rubric, RUBRIC)
    validate_shape(adjudication, ADJUDICATION)
    validate_shape(output_schema, REF)
    validate_shape(resource_fingerprint, HASH)
    assert_content_safe(evidence_packet)
    if pool["collisions"]:
        raise ValueError("UNKNOWN_IDENTITY must be adjudicated before candidate freeze")
    if not pool["candidates"]:
        raise ValueError("frozen judgment pool must not be empty")
    dimension_ids = [d["id"] for d in rubric["dimensions"]]
    if len(set(dimension_ids)) != len(dimension_ids):
        raise ValueError("duplicate rubric dimensions")
    for dimension in rubric["dimensions"]:
        if not set(dimension["satisfying_values"]) <= set(dimension["allowed_values"]) or (
            dimension["hard_constraint"] and not dimension["satisfying_values"]
        ):
            raise ValueError("rubric hard-constraint satisfaction must be explicit")
    # Evidence is inert bytes/locators, never opened by this module.
    validate_shape(evidence_packet, obj({"id": TEXT, "version": TEXT, "entries": arr(obj({
        "reference": REF, "excerpt": TEXT, "captured_at": TEXT,
        "locator": TEXT, "corpus_fingerprint": {"anyOf": [HASH, {"type": "null"}]},
    }))}))
    evidence_refs = {canonical_json(e["reference"]) for e in evidence_packet["entries"]}
    if len(evidence_refs) != len(evidence_packet["entries"]):
        raise ValueError("conflicting evidence identity")
    for item in pool["candidates"]:
        if not {canonical_json(e) for e in item["evidence"]} <= evidence_refs:
            raise ValueError("candidate evidence missing from frozen packet")
    validate_shape(source_overlay, obj({"kind": enum("SYNTHETIC", "FROZEN", "LIVE"),
        "corpus": {"anyOf": [REF, {"type": "null"}]},
        "reference_set": {"anyOf": [REF, {"type": "null"}]},
        "capture_cutoff": {"type": ["string", "null"]},
        "adjudication_time": {"type": ["string", "null"]},
        "drift_policy": {"anyOf": [REF, {"type": "null"}]}}))
    for entry in evidence_packet["entries"]:
        capture = timestamp(entry["captured_at"])
        if source_overlay["kind"] == "FROZEN":
            if source_overlay["corpus"] is None or source_overlay["reference_set"] is None or entry["corpus_fingerprint"] != source_overlay["corpus"]["fingerprint"]:
                raise ValueError("evidence outside frozen corpus")
        if source_overlay["kind"] == "LIVE":
            if source_overlay["capture_cutoff"] is None or source_overlay["adjudication_time"] is None or source_overlay["drift_policy"] is None:
                raise ValueError("live adjudication overlay incomplete")
            cutoff = timestamp(source_overlay["capture_cutoff"])
            if capture > cutoff or timestamp(source_overlay["adjudication_time"]) < cutoff:
                raise ValueError("live evidence/cutoff mismatch")
    package = seal({"schema_id": "search-judgment-package/v2", "candidate_pool": pool,
                    "evidence_packet": evidence_packet, "rubric": rubric, "adjudication": adjudication,
                    "output_schema": output_schema, "resource_fingerprint": resource_fingerprint,
                    "source_overlay": source_overlay, "allowed_tools": [],
                    "order_policy": "CANDIDATE_ID_ASC", "independent_first_pass": True})
    return package


def judgment_package(pool: dict, evidence_packet: dict, rubric: dict, adjudication: dict,
                     *, output_schema: dict, resource_fingerprint: str, source_overlay: dict,
                     spec: SearchSpecV2) -> dict:
    core = judgment_contract(pool, evidence_packet, rubric, adjudication, output_schema=output_schema,
                             resource_fingerprint=resource_fingerprint, source_overlay=source_overlay)
    doc = spec.as_dict()
    if doc["track_id"] != "JUDGMENT_ONLY" or doc["spec_status"] != "FROZEN":
        raise ValueError("judgment package requires frozen Judgment-only SearchSpec")
    if resource_fingerprint != fingerprint(doc["resources"]) or doc["judgment_contract"]["fingerprint"] != fingerprint(core):
        raise ValueError("judgment contract/SearchSpec binding mismatch")
    for key, value in (("candidate_set", fingerprint(pool)), ("evidence_packet", fingerprint(evidence_packet)),
                       ("rubric", fingerprint(rubric)), ("adjudication_policy", fingerprint(adjudication)),
                       ("output_schema", output_schema["fingerprint"]), ("blind_transform", fingerprint(pool["policy"])),
                       ("order_policy", fingerprint(core["order_policy"])), ("aggregation_policy", fingerprint(rubric["aggregation"]))):
        if doc["overlay"][key]["fingerprint"] != value:
            raise ValueError("judgment overlay/SearchSpec binding mismatch")
    return seal({**core, "searchspec": doc})


def validate_package(package: dict) -> None:
    verify_seal(package)
    try:
        spec = SearchSpecV2.from_mapping(package["searchspec"])
        rebuilt = judgment_package(package["candidate_pool"], package["evidence_packet"],
            package["rubric"], package["adjudication"], output_schema=package["output_schema"],
            resource_fingerprint=package["resource_fingerprint"], source_overlay=package["source_overlay"], spec=spec)
    except (KeyError, TypeError):
        raise ValueError("judgment package shape mismatch") from None
    if package != rebuilt:
        raise ValueError("judgment package contains unfrozen fields or controls")


def judge_view(package: dict) -> bytes:
    """A single byte-identical view for every future judge, not a judge call."""
    validate_package(package)
    return canonical_json(package).encode("utf-8")


RECORD_SCHEMA = obj({
    "record_id": TEXT, "run_id": TEXT, "candidate_id": TEXT, "judge_alias": TEXT,
    "judge_identity": ENTRANT,
    "package_fingerprint": HASH, "rubric_fingerprint": HASH,
    "state": enum("ACCEPT", "REJECT", "UNKNOWN", "NOT_EVALUABLE", "ERROR", "BLOCKED"),
    "dimensions": arr(obj({"id": TEXT, "value": TEXT}), 1),
    "confidence": {"type": ["number", "null"], "minimum": 0},
    "evidence_used": arr(REF), "reason_codes": arr(TEXT, 1),
    "failure_class": enum("NONE", "INSUFFICIENT_EVIDENCE", "INFRASTRUCTURE", "POLICY"),
    "committed_at": TEXT, "observed_peer_records": const([]),
    "canonical_fingerprint": HASH,
})


def validate_record(record: dict, package: dict) -> None:
    validate_shape(record, RECORD_SCHEMA)
    verify_seal(record)
    validate_package(package)
    timestamp(record["committed_at"])
    validate_entrant(record["judge_identity"])
    if record["judge_identity"]["entrant_id"] != record["judge_alias"]:
        raise ValueError("sealed judge identity/alias mismatch")
    if record["state"] in ("ACCEPT", "REJECT", "UNKNOWN") and (
        record["judge_identity"]["resolution_status"] != "KNOWN" or record["judge_identity"]["identity_status"] == "SUBSTITUTED"
    ):
        raise ValueError("unresolved/substituted judge cannot issue comparable judgment")
    if record["package_fingerprint"] != package["canonical_fingerprint"] or record["rubric_fingerprint"] != fingerprint(package["rubric"]):
        raise ValueError("judgment package binding mismatch")
    candidate = next((c for c in package["candidate_pool"]["candidates"] if c["candidate_id"] == record["candidate_id"]), None)
    if candidate is None:
        raise ValueError("candidate not frozen in package")
    if not {canonical_json(e) for e in record["evidence_used"]} <= {canonical_json(e) for e in candidate["evidence"]}:
        raise ValueError("new evidence forbidden")
    dimensions = {d["id"]: d for d in package["rubric"]["dimensions"]}
    if len(record["dimensions"]) != len(dimensions) or {d["id"] for d in record["dimensions"]} != dimensions.keys():
        raise ValueError("rubric dimension mismatch")
    for item in record["dimensions"]:
        if item["value"] not in [*dimensions[item["id"]]["allowed_values"], "UNKNOWN"]:
            raise ValueError("value outside frozen rubric")
    state = record["state"]
    expected_failure = {"ACCEPT": "NONE", "REJECT": "NONE", "UNKNOWN": "INSUFFICIENT_EVIDENCE",
                        "NOT_EVALUABLE": "INFRASTRUCTURE", "ERROR": "INFRASTRUCTURE", "BLOCKED": "POLICY"}[state]
    if record["failure_class"] != expected_failure:
        raise ValueError("judgment state/failure mismatch")
    if state in ("ACCEPT", "REJECT") and not record["evidence_used"]:
        raise ValueError("quality decision requires frozen evidence")
    if state in ("ACCEPT", "REJECT") and any(d["value"] == "UNKNOWN" and dimensions[d["id"]]["hard_constraint"] for d in record["dimensions"]):
        raise ValueError("hard-constraint UNKNOWN cannot become quality decision")
    if state == "ACCEPT" and any(dimensions[d["id"]]["hard_constraint"] and
                                d["value"] not in dimensions[d["id"]]["satisfying_values"] for d in record["dimensions"]):
        raise ValueError("hard constraints precede soft acceptance")
    confidence = record["confidence"]
    if confidence is not None and (confidence > 1 or not package["rubric"]["confidence_allowed"]):
        raise ValueError("confidence violates frozen rubric")


@dataclass(frozen=True)
class JudgmentJournal:
    package_json: str
    judge_aliases: tuple[str, ...]
    entries_json: str = "[]"

    def __post_init__(self) -> None:
        package = json.loads(self.package_json)
        validate_package(package)
        if type(self.judge_aliases) is not tuple or not self.judge_aliases or len(set(self.judge_aliases)) != len(self.judge_aliases):
            raise ValueError("judge aliases must be unique")
        validate_shape(list(self.judge_aliases), arr(TEXT, 1))
        assert_content_safe(list(self.judge_aliases))
        entries = json.loads(self.entries_json)
        if type(entries) is not list or canonical_json(entries) != self.entries_json:
            raise ValueError("journal must be canonical")
        prior: list[dict] = []
        for entry in entries:
            self._validate_entry(entry, prior, package)
            prior.append(entry)

    def _validate_entry(self, entry: dict, prior: list[dict], package: dict) -> None:
        if entry.get("kind") == "FIRST_PASS":
            validate_shape(entry, obj({"kind": const("FIRST_PASS"), "record": RECORD_SCHEMA}))
            record = entry["record"]
            validate_record(record, package)
            if record["judge_alias"] not in self.judge_aliases:
                raise ValueError("undeclared judge alias")
            for old in prior:
                if old["kind"] == "FIRST_PASS" and old["record"]["run_id"] != record["run_id"]:
                    raise ValueError("one journal requires one run identity")
                if old["kind"] == "FIRST_PASS" and old["record"]["judge_alias"] == record["judge_alias"] and old["record"]["judge_identity"] != record["judge_identity"]:
                    raise ValueError("judge identity changed during run")
                if old["kind"] == "FIRST_PASS" and (old["record"]["record_id"] == record["record_id"] or
                    (old["record"]["judge_alias"], old["record"]["candidate_id"]) == (record["judge_alias"], record["candidate_id"])):
                    raise ValueError("first-pass overwrite forbidden")
            if any(old["kind"] == "HUMAN_OVERRIDE" for old in prior):
                raise ValueError("first pass must precede synthesis/adjudication")
        elif entry.get("kind") == "HUMAN_OVERRIDE":
            validate_shape(entry, obj({"kind": const("HUMAN_OVERRIDE"), "candidate_id": TEXT,
                "prior_machine_fingerprints": arr(HASH, 1), "adjudicator_alias": TEXT,
                "decision": enum("ACCEPT", "REJECT", "UNKNOWN"),
                "trigger": enum("DISAGREEMENT", "CRITICAL_UNKNOWN", "IDENTITY_COLLISION", "CONTRADICTION", "RUBRIC_EDGE"),
                "reason_code": TEXT, "evidence_used": arr(REF, 1), "timestamp": TEXT,
                "previous_journal_fingerprint": HASH, "canonical_fingerprint": HASH}))
            verify_seal(entry)
            policy = package["adjudication"]
            if not policy["allowed"] or entry["trigger"] not in policy["triggers"]:
                raise ValueError("adjudication trigger not frozen")
            if entry["previous_journal_fingerprint"] != fingerprint(prior):
                raise ValueError("adjudication chain mismatch")
            records = [old["record"] for old in prior if old["kind"] == "FIRST_PASS"]
            expected = {(j, c["candidate_id"]) for j in self.judge_aliases for c in package["candidate_pool"]["candidates"]}
            if {(r["judge_alias"], r["candidate_id"]) for r in records} != expected:
                raise ValueError("all independent first passes required before adjudication")
            related = [r for r in records if r["candidate_id"] == entry["candidate_id"]]
            if set(entry["prior_machine_fingerprints"]) != {r["canonical_fingerprint"] for r in related} or not related:
                raise ValueError("override must preserve all prior machine judgments")
            if entry["trigger"] == "DISAGREEMENT" and len({r["state"] for r in related}) < 2:
                raise ValueError("disagreement trigger lacks disagreement")
            if entry["trigger"] == "CRITICAL_UNKNOWN" and not any(r["state"] == "UNKNOWN" for r in related):
                raise ValueError("UNKNOWN trigger lacks unresolved judgment")
            if entry["trigger"] == "IDENTITY_COLLISION":
                raise ValueError("identity collisions must be resolved before package freeze")
            admissible = next(c["evidence"] for c in package["candidate_pool"]["candidates"] if c["candidate_id"] == entry["candidate_id"])
            if not {canonical_json(e) for e in entry["evidence_used"]} <= {canonical_json(e) for e in admissible}:
                raise ValueError("adjudicator cannot add evidence")
            if any(timestamp(entry["timestamp"]) < timestamp(r["committed_at"]) for r in records):
                raise ValueError("override predates first pass")
            if any(timestamp(entry["timestamp"]) < timestamp(old["timestamp"]) for old in prior if old["kind"] == "HUMAN_OVERRIDE"):
                raise ValueError("override predates append-only history")
        else:
            raise ValueError("unsupported judgment journal entry")

    def append(self, entry: dict) -> "JudgmentJournal":
        return JudgmentJournal(self.package_json, self.judge_aliases,
                               canonical_json([*json.loads(self.entries_json), entry]))


def integrity_gate(checks: dict) -> str:
    from .v23_schema import CHECK
    validate_shape(checks, obj({f"J{i}": CHECK for i in range(1, 11)}))
    assert_content_safe(checks)
    return "PASS" if all(c["status"] == "PASS" and c["evidence"] for c in checks.values()) else "NOT_EVALUABLE"
