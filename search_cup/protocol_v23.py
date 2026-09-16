"""SEARCH-CUP v2.3 protocol validation only. No execution authority or I/O.

SP5 P0-01 canonical JSON/fingerprint is reused after a strict finite-JSON gate.
v1 CompetitionSpec, historical receipts and PR #17 are never execution inputs.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import unquote

from .contracts import canonical_json, fingerprint
from .v23_schema import (
    A1_BEHAVIORS, ABLATION_CAPABILITIES, E1_BEHAVIORS, HASH, MEASURE, PRINCIPAL, REF, RETRIEVER, SEARCHSPEC_SCHEMA,
    TERMINALS, TEXT, arr, const, enum, obj, validate_shape,
)


def finite_json(value: object) -> None:
    if type(value) is dict:
        if any(type(k) is not str for k in value):
            raise ValueError("JSON keys must be strings")
        for item in value.values():
            finite_json(item)
    elif type(value) is list:
        for item in value:
            finite_json(item)
    elif type(value) is float and not math.isfinite(value):
        raise ValueError("non-finite JSON number")
    elif value is not None and type(value) not in (str, bool, int, float):
        raise ValueError("non-JSON value")


PRIVATE_KEYS = frozenset({"api_key", "apikey", "access_token", "refresh_token",
    "authorization", "password", "credentials", "private_key", "private_archive",
    "raw", "l0", "health", "relationship", "financial", "google_drive",
    "hidden_registry", "answer_key"})
PRIVATE_PATTERNS = (
    r"(?:docs|drive)\.google\.com", r"(?:file|gdrive)://",
    r"\b(?:sk|ghp|github_pat)[-_][A-Za-z0-9_-]{12,}",
    r"\b(?:Bearer|Basic)\s+[A-Za-z0-9+/=_-]{8,}",
    r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----",
    r"\b(?:api[_-]?key|access[_-]?token|password)\s*[:=]\s*\S+",
)
NORMALIZED_PRIVATE_KEYS = frozenset(re.sub(r"[^a-z0-9]", "", k) for k in PRIVATE_KEYS)


def assert_content_safe(value: object) -> None:
    """Bounded credential/private-locator scanner, not a general-purpose DLP oracle.

    The caller still owns public-safe source classification. Rejected values and
    keys are never echoed. No environment, secret store or archive is consulted.
    """
    finite_json(value)

    def visit(item: object) -> None:
        if isinstance(item, dict):
            for key, child in item.items():
                if re.sub(r"[^a-z0-9]", "", key.lower()) in NORMALIZED_PRIVATE_KEYS:
                    raise ValueError("excluded private field")
                visit(key)
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)
        elif isinstance(item, str):
            decoded = unquote(unquote(item))
            if any(re.search(pattern, decoded, re.I) for pattern in PRIVATE_PATTERNS):
                raise ValueError("excluded credential or private locator")
    visit(value)


def seal(document: dict) -> dict:
    """Canonical identity; only the top-level fingerprint field is excluded."""
    assert_content_safe(document)
    result = json.loads(canonical_json(document))
    result.pop("canonical_fingerprint", None)
    result["canonical_fingerprint"] = fingerprint(result)
    return result


def verify_seal(document: dict) -> None:
    assert_content_safe(document)
    if type(document) is not dict or document.get("canonical_fingerprint") != seal(document)["canonical_fingerprint"]:
        raise ValueError("canonical fingerprint mismatch")


def reference(document: dict, identity: str, version: str = "1") -> dict:
    assert_content_safe(document)
    return {"id": identity, "version": version, "fingerprint": fingerprint(document)}


def timestamp(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise ValueError("invalid timestamp") from None
    if parsed.tzinfo is None:
        raise ValueError("timestamp requires timezone")
    return parsed


def validate_measure(measure: dict, unit: str | None = None) -> None:
    validate_shape(measure, MEASURE)
    if (measure["state"] == "KNOWN") != (measure["value"] is not None):
        raise ValueError("measurement missingness/value mismatch")
    if unit is not None and measure["unit"] != unit:
        raise ValueError("measurement unit mismatch")


def f1_eligibility(retriever: dict | None) -> str:
    if retriever is None:
        return "NOT_F1_ELIGIBLE"
    validate_shape(retriever, RETRIEVER)
    assert_content_safe(retriever)
    qualification = retriever["qualification"]
    if qualification is None:
        return ("NOT_F1_ELIGIBLE_BY_DEFAULT" if "search_pro" in retriever["backend_id"].lower()
                else "NOT_F1_ELIGIBLE")
    identity = {k: v for k, v in retriever.items() if k != "qualification"}
    if qualification["backend_fingerprint"] != fingerprint(identity):
        return "NOT_F1_ELIGIBLE"
    checks = qualification["criteria"]
    if set(checks) != {f"R{i}" for i in range(1, 9)} or any(
        c["status"] != "PASS" or not c["evidence"] for c in checks.values()
    ):
        return "NOT_F1_ELIGIBLE"
    # A PASS assertion cannot contradict the declared capability surface.
    if retriever["class"] == "INTEGRATED_SEARCH_STACK" or set(retriever["capabilities"]) - {"RETRIEVAL", "RANKING"}:
        return "NOT_F1_ELIGIBLE"
    return "F1_ELIGIBLE"


COMMON = {"task", "scope", "a0", "a1", "resources", "output", "judgment"}
SYSTEM_COMMON = {"task", "scope", "a0", "output", "judgment", "disclosure_standard"}
REQUIRED_CONTROLS = {
    "JUDGMENT_ONLY": COMMON | {"candidate_set", "evidence_packet", "rubric", "ordering", "tools", "privacy"},
    "E1_FROZEN": COMMON | {"corpus", "index", "retriever", "environment", "prompt_context", "tools", "privacy"},
    "E1_LIVE": COMMON | {"retriever", "time_window", "environment", "prompt_context", "tools", "privacy"},
    "E2_RETRIEVER": COMMON | {"control_model"},
    "E_PLUS_J": SYSTEM_COMMON | {"architecture"},
    "GLM_SEARCH_STACK": SYSTEM_COMMON,
    "SYSTEM_PLAYOFF": SYSTEM_COMMON,
    "ECONOMIC_TRACK": SYSTEM_COMMON | {"economic_package"},
}
TRACK_CLAIM = {
    "JUDGMENT_ONLY": "JUDGMENT_ON_FROZEN_PACKAGE",
    "E1_FROZEN": "EXECUTION_ON_FROZEN_ENVIRONMENT",
    "E1_LIVE": "EXECUTION_IN_LIVE_WINDOW",
    "E2_RETRIEVER": "RETRIEVER_SYSTEM_PERFORMANCE",
    "E_PLUS_J": "DECLARED_SYSTEM_PERFORMANCE",
    "GLM_SEARCH_STACK": "DECLARED_SYSTEM_PERFORMANCE",
    "SYSTEM_PLAYOFF": "DECLARED_SYSTEM_PERFORMANCE",
    "ECONOMIC_TRACK": "OBSERVED_ECONOMIC_EFFICIENCY",
}


def a0_resource_binding(doc: dict) -> str:
    """F1 technical envelope; F2 common deadline; F3 common real resources.

    Per-system internal search-call counts/cost limits remain fingerprinted in
    SearchSpec but are not falsely required to be equal in F2/F3.
    """
    resource = doc["resources"]
    if doc["fairness_mode"] == "F1":
        return fingerprint(resource)
    keys = ("max_total_runtime_ms", "money_ceiling") if doc["fairness_mode"] == "F3" else ("max_total_runtime_ms",)
    return fingerprint({key: resource[key] for key in keys})


def control_bindings(doc: dict) -> dict[str, str]:
    """Derived controls cannot be replaced with arbitrary purported hashes."""
    bindings = {k: fingerprint(doc[k]) for k in ("task", "scope", "a0", "a1", "resources", "privacy")}
    bindings.update(output=doc["output_contract"]["fingerprint"], judgment=doc["judgment_contract"]["fingerprint"])
    if doc["track_id"] == "E2_RETRIEVER":
        # Equal accounting rules, not fabricated raw-call equivalence between
        # different backends/stacks. The complete local envelope is still sealed.
        keys = ("failure_policy", "exhaustion_policy", "budget_rejection_policy", "retry_policy",
                "automatic_retries", "manual_retry_policy", "max_total_runtime_ms")
        bindings["resources"] = fingerprint({key: doc["resources"][key] for key in keys})
    if doc["retriever"] is not None:
        bindings["retriever"] = fingerprint(doc["retriever"])
    for key in ("system_disclosure", "economic_package"):
        if doc[key] is not None:
            bindings[key] = fingerprint(doc[key])
    overlay = doc["overlay"]
    if overlay["kind"] == "JUDGMENT":
        bindings.update({key: overlay[key]["fingerprint"] for key in ("candidate_set", "evidence_packet", "rubric")})
        bindings["ordering"] = overlay["order_policy"]["fingerprint"]
        bindings["tools"] = fingerprint([])
    elif overlay["kind"] == "FROZEN":
        bindings.update({key: overlay[key]["fingerprint"] for key in ("corpus", "index")})
    else:
        bindings["time_window"] = overlay["window_policy"]["fingerprint"]
    return bindings


@dataclass(frozen=True)
class SearchSpecV2:
    canonical_content: str

    def __post_init__(self) -> None:
        document = json.loads(self.canonical_content)
        self.validate(document)
        if canonical_json(document) != self.canonical_content:
            raise ValueError("noncanonical SearchSpec representation")

    @classmethod
    def from_mapping(cls, document: dict) -> "SearchSpecV2":
        cls.validate(document)
        return cls(canonical_json(document))

    @staticmethod
    def validate(doc: dict) -> None:
        assert_content_safe(doc)
        validate_shape(doc, SEARCHSPEC_SCHEMA)
        verify_seal(doc)
        created = timestamp(doc["created_at"])
        if doc["spec_status"] in ("FROZEN", "RETIRED"):
            if doc["frozen_at"] is None or timestamp(doc["frozen_at"]) < created:
                raise ValueError("frozen SearchSpec requires valid freeze timestamp")
        elif doc["frozen_at"] is not None:
            raise ValueError("draft cannot assert freeze")
        if doc["task"]["output_cardinality"]["minimum"] > doc["task"]["output_cardinality"]["maximum"]:
            raise ValueError("invalid output cardinality")
        for key in ("task", "scope"):
            if doc["a0"][key + "_fingerprint"] != fingerprint(doc[key]):
                raise ValueError("A0 binding mismatch")
        resource = doc["resources"]
        if doc["a0"]["resource_fingerprint"] != a0_resource_binding(doc):
            raise ValueError("A0 resource binding mismatch")
        for key, unit in (("max_total_runtime_ms", "ms"), ("token_ceiling", "tokens"), ("money_ceiling", None)):
            validate_measure(resource[key], unit)
        track, mode = doc["track_id"], doc["fairness_mode"]
        controls = doc["variable_control"]
        required = REQUIRED_CONTROLS[track]
        if not required <= controls["fixed"].keys():
            raise ValueError("missing variable controls")
        for key, value in control_bindings(doc).items():
            if key in required and controls["fixed"].get(key) != value:
                raise ValueError("control fingerprint mismatch")
        if mode == "ABLATION":
            if track != "E2_RETRIEVER" or controls["principal"] != "ONE_CAPABILITY" or len(controls["changed_capabilities"]) != 1:
                raise ValueError("ablation requires exactly one changed capability")
            if set(controls["fixed_capabilities"]) != set(ABLATION_CAPABILITIES) - set(controls["changed_capabilities"]):
                raise ValueError("ablation must freeze all non-target capabilities")
        elif controls["principal"] != PRINCIPAL[track] or controls["changed_capabilities"] or controls["fixed_capabilities"]:
            raise ValueError("principal changed-variable mismatch")
        expected_mode = "F1" if track in ("JUDGMENT_ONLY", "E1_FROZEN", "E1_LIVE") else "F3" if track == "ECONOMIC_TRACK" else "F2"
        if mode != expected_mode and not (track == "E2_RETRIEVER" and mode == "ABLATION"):
            raise ValueError("track/fairness mismatch")
        allowed_claims = {TRACK_CLAIM[track]}
        if mode == "ABLATION":
            allowed_claims.add("SINGLE_CAPABILITY_EFFECT")
        overlay = doc["overlay"]
        if overlay["kind"] == "FROZEN" or (overlay["kind"] == "LIVE" and overlay["exhaustive_reference"] is not None):
            if track != "JUDGMENT_ONLY":
                allowed_claims.add("ABSOLUTE_RECALL")
        if not set(doc["claims"]) <= allowed_claims:
            raise ValueError("claims ceiling exceeded")
        if track == "JUDGMENT_ONLY":
            if overlay["kind"] != "JUDGMENT" or overlay["allowed_tools"] or doc["retriever"] is not None:
                raise ValueError("Judgment-only must have no retriever or tools")
            if any(resource[k] != 0 for k in ("max_search_calls", "max_search_turns", "max_results_per_call", "max_follow_links")) or resource["search_unit"] != "NONE":
                raise ValueError("Judgment-only requires zero search and verification")
            if doc["a1"]["owner"] != "NONE" or doc["a1"]["allowed"]:
                raise ValueError("Judgment-only forbids query planning")
        else:
            if overlay["kind"] == "JUDGMENT" or doc["retriever"] is None or resource["search_unit"] == "NONE":
                raise ValueError("search track requires retrieval/environment contract")
            stack_planning = set(doc["retriever"]["capabilities"]) & set(A1_BEHAVIORS)
            if stack_planning and (doc["a1"]["owner"] != "SEARCH_STACK" or not stack_planning <= set(doc["a1"]["allowed"])):
                raise ValueError("search-stack planning ownership must be explicit")
            if doc["retriever"]["class"] == "INTEGRATED_SEARCH_STACK" and resource["search_unit"] != "INTEGRATED_STACK_INVOCATION":
                raise ValueError("integrated invocation is not a raw-call equivalent")
        if track in ("E1_FROZEN", "E1_LIVE"):
            expected = "FROZEN" if track == "E1_FROZEN" else "LIVE"
            if overlay["kind"] != expected:
                raise ValueError("Live/Frozen overlay mismatch")
            if doc["a1"]["owner"] != "ENTRANT" or not set(doc["a1"]["allowed"]) <= set(E1_BEHAVIORS):
                raise ValueError("E1 planning must remain bounded and entrant-owned")
            if f1_eligibility(doc["retriever"]) != "F1_ELIGIBLE" or resource["search_unit"] != "RAW_BACKEND_ATTEMPT":
                raise ValueError("F1 retriever not qualified")
        if overlay["kind"] == "LIVE" and doc["retriever"] is not None:
            if overlay["backend"]["fingerprint"] != doc["retriever"]["identity"]["fingerprint"]:
                raise ValueError("live backend binding mismatch")
            if not controls["qualified_nuisance"]:
                raise ValueError("live drift qualification required")
        if mode in ("F2", "F3", "ABLATION") and doc["system_disclosure"] is None:
            raise ValueError("system capability/resource disclosure required")
        if mode == "F1" and (doc["system_disclosure"] is not None or doc["economic_package"] is not None):
            raise ValueError("F1 cannot carry a system/economic comparison package")
        if mode == "F3":
            economic = doc["economic_package"]
            if economic is None or not {"MACHINE_ELAPSED", "OPERATOR_ACTIVE"} <= set(economic["time_kinds"]):
                raise ValueError("real-resource/normalization package required")
            if resource["money_ceiling"]["unit"] != economic["currency"]:
                raise ValueError("currency mismatch")
            basis = economic["basis"]
            if basis in ("MONEY", "MONEY_AND_TIME") and resource["money_ceiling"]["state"] != "KNOWN":
                raise ValueError("money-aligned comparison requires known ceiling")
            if basis in ("WALL_CLOCK", "MONEY_AND_TIME") and resource["max_total_runtime_ms"]["state"] != "KNOWN":
                raise ValueError("time-aligned comparison requires known ceiling")

    def as_dict(self) -> dict:
        return json.loads(self.canonical_content)

    @property
    def fingerprint(self) -> str:
        return self.as_dict()["canonical_fingerprint"]

    def require_successor(self, successor: "SearchSpecV2", old_run_id: str, new_run_id: str) -> None:
        old, new = self.as_dict(), successor.as_dict()
        if old["spec_status"] != "FROZEN" or new["spec_status"] != "FROZEN":
            raise ValueError("version transition requires frozen specs")
        if self.fingerprint != successor.fingerprint and (old["spec_version"] == new["spec_version"] or old_run_id == new_run_id):
            raise ValueError("post-freeze change requires new version and run identity")


def compare_controls(specs: list[SearchSpecV2]) -> None:
    if len(specs) < 2:
        raise ValueError("comparison requires at least two declarations")
    docs = [spec.as_dict() for spec in specs]
    first = docs[0]
    for doc in docs[1:]:
        if doc["spec_status"] != "FROZEN" or first["spec_status"] != "FROZEN":
            raise ValueError("comparison requires frozen declarations")
        if (doc["track_id"], doc["fairness_mode"]) != (first["track_id"], first["fairness_mode"]):
            raise ValueError("cross-track/fairness aggregation forbidden")
        if doc["variable_control"]["fixed"] != first["variable_control"]["fixed"]:
            raise ValueError("non-principal control changed")
        if any(doc["variable_control"][key] != first["variable_control"][key] for key in ("changed_capabilities", "fixed_capabilities")):
            raise ValueError("ablation capability controls changed")
        if doc["claims"] != first["claims"]:
            raise ValueError("claims policy changed")
        if first["fairness_mode"] == "F1" and doc["canonical_fingerprint"] != first["canonical_fingerprint"]:
            raise ValueError("F1 requires identical SearchSpec identity")


INSTANCE_SCHEMA = obj({
    "schema_id": const("search-instance-bindings/v2"), "spec_fingerprint": HASH,
    "decisions": obj({f"D{i}": obj({
        "status": enum("FROZEN", "DEFERRED", "NOT_APPLICABLE"),
        "artifact": {"anyOf": [REF, {"type": "null"}]},
        "approval": {"anyOf": [REF, {"type": "null"}]}, "reason": TEXT,
    }) for i in range(1, 9)}),
    "canonical_fingerprint": HASH,
})


def instance_gate(spec: SearchSpecV2, package: dict | None, artifacts: dict | None = None) -> dict:
    """Inspect separately frozen bindings; T1 always denies execution.

    Artifacts are inert JSON supplied by the caller, never fetched by locator.
    Approval references are declarations for Board verification, not credentials
    and not trusted authorization. No boolean can unlock a runner through T1.
    """
    doc = spec.as_dict()
    required = {"D1", "D2", "D5", "D7"}
    if doc["track_id"] == "JUDGMENT_ONLY":
        required.add("D3")
    if doc["overlay"]["kind"] == "FROZEN":
        required.add("D4")
    if doc["fairness_mode"] == "F1" and doc["track_id"] != "JUDGMENT_ONLY":
        required.add("D6")
    if doc["fairness_mode"] in ("F2", "F3", "ABLATION"):
        required.add("D8")
    missing = sorted(required)
    if package is not None:
        validate_shape(package, INSTANCE_SCHEMA)
        verify_seal(package)
        if package["spec_fingerprint"] != spec.fingerprint:
            raise ValueError("instance/SearchSpec mismatch")
        artifacts = artifacts or {}
        assert_content_safe(artifacts)
        missing = []
        for name in sorted(required):
            decision = package["decisions"][name]
            ref = decision["artifact"]
            if decision["status"] != "FROZEN" or ref is None or decision["approval"] is None:
                missing.append(name)
                continue
            artifact = artifacts.get(ref["fingerprint"])
            if artifact is None or fingerprint(artifact) != ref["fingerprint"]:
                missing.append(name)
                continue
            validate_instance_artifact(name, artifact, spec)
        if doc["spec_status"] != "FROZEN":
            missing.append("SPEC_NOT_FROZEN")
    reasons = (["INSTANCE_BINDINGS_MISSING"] if missing else []) + ["T1_IMPLEMENTATION_ONLY"]
    return seal({"schema_id": "search-execution-gate/v2", "spec_fingerprint": spec.fingerprint,
                 "track_id": doc["track_id"], "terminal_status": "BLOCKED",
                 "execution_allowed": False, "missing_decisions": missing,
                 "reason_codes": reasons, "provider_calls": 0, "search_calls": 0,
                 "judge_calls": 0, "official_prompt_consumed": False,
                 "hidden_registry_loaded": False})


def validate_instance_artifact(name: str, artifact: dict, spec: SearchSpecV2) -> None:
    """Validate material contents, not a status label or a self-asserted digest."""
    doc = spec.as_dict()
    common = {"schema_id": const(f"search-instance/{name.lower()}/v2"),
              "spec_fingerprint": const(spec.fingerprint)}
    expected = {"D1": doc["track_id"], "D2": spec.fingerprint,
                "D7": fingerprint(doc["resources"])}
    if name in expected:
        payload = {"binding": const(expected[name])}
        if name == "D2":
            payload["searchspec"] = SEARCHSPEC_SCHEMA
        elif name == "D7":
            payload["resources"] = SEARCHSPEC_SCHEMA["properties"]["resources"]
        validate_shape(artifact, obj({**common, **payload}))
        if name == "D2" and SearchSpecV2.from_mapping(artifact["searchspec"]).fingerprint != spec.fingerprint:
            raise ValueError("task instance mismatch")
        if name == "D7" and artifact["resources"] != doc["resources"]:
            raise ValueError("resource instance mismatch")
    elif name == "D3":
        from .v23_judgment import validate_package
        if set(artifact) != {*common, "judgment_package"}:
            raise ValueError("judgment instance shape mismatch")
        validate_shape({key: artifact[key] for key in common}, obj(common))
        validate_package(artifact["judgment_package"])
        if artifact["judgment_package"]["searchspec"]["canonical_fingerprint"] != spec.fingerprint:
            raise ValueError("judgment instance mismatch")
    elif name == "D4":
        validate_shape(artifact, obj({**common, "frozen_overlay": SEARCHSPEC_SCHEMA["properties"]["overlay"]}))
        if artifact["frozen_overlay"] != doc["overlay"] or doc["overlay"]["kind"] != "FROZEN":
            raise ValueError("corpus/index instance mismatch")
    elif name == "D5":
        validate_shape(artifact, obj({**common, "roster": arr(ENTRANT, 1)}))
        ids = [e["entrant_id"] for e in artifact["roster"]]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate roster alias")
        for entrant in artifact["roster"]:
            validate_entrant(entrant)
        if doc["track_id"] == "E2_RETRIEVER" and fingerprint(artifact["roster"]) != doc["variable_control"]["fixed"]["control_model"]:
            raise ValueError("E2 control model roster mismatch")
    elif name == "D6":
        validate_shape(artifact, obj({**common, "retriever": RETRIEVER}))
        if artifact["retriever"] != doc["retriever"] or f1_eligibility(artifact["retriever"]) != "F1_ELIGIBLE":
            raise ValueError("retriever qualification instance mismatch")
    elif name == "D8":
        validate_shape(artifact, obj({**common, "system_disclosure": SEARCHSPEC_SCHEMA["properties"]["system_disclosure"],
            "economic_package": SEARCHSPEC_SCHEMA["properties"]["economic_package"],
            "variable_control": SEARCHSPEC_SCHEMA["properties"]["variable_control"]}))
        if any(artifact[key] != doc[key] for key in ("system_disclosure", "economic_package", "variable_control")):
            raise ValueError("system/economic/ablation instance mismatch")
    else:
        raise ValueError("unknown instance decision")


def metric_ratio(numerator: dict, denominator: dict, definition: dict) -> dict:
    from .v23_schema import METRIC
    validate_shape(definition, METRIC)
    validate_measure(numerator)
    validate_measure(denominator)
    if "NOT_APPLICABLE" in (numerator["state"], denominator["state"]):
        state, value = "NOT_EVALUABLE", None
    elif "UNKNOWN" in (numerator["state"], denominator["state"]):
        state, value = "UNKNOWN", None
    elif denominator["value"] == 0:
        state, value = "NOT_EVALUABLE", None
    else:
        state, value = "PASS", numerator["value"] / denominator["value"]
    return seal({"definition_fingerprint": fingerprint(definition), "terminal_status": state,
                 "value": value, "raw_numerator": numerator, "raw_denominator": denominator})


ENTRANT = obj({"entrant_id": TEXT, "provider": TEXT, "requested_model_id": TEXT,
               "resolved_model_id": {"type": ["string", "null"]},
               "resolution_status": enum("KNOWN", "UNKNOWN"),
               "identity_status": enum("AS_REQUESTED", "DECLARED_ALIAS", "UNRESOLVED", "SUBSTITUTED"),
               "alias_evidence": {"anyOf": [REF, {"type": "null"}]},
               "endpoint_mode": TEXT, "config_fingerprint": HASH})


def validate_entrant(entrant: dict) -> None:
    validate_shape(entrant, ENTRANT)
    assert_content_safe(entrant)
    known = entrant["resolution_status"] == "KNOWN"
    if known != bool(entrant["resolved_model_id"]):
        raise ValueError("model resolution missingness mismatch")
    identity = entrant["identity_status"]
    if not known and identity != "UNRESOLVED":
        raise ValueError("unresolved model cannot assert resolved identity")
    if known and (identity == "UNRESOLVED" or (identity == "AS_REQUESTED" and entrant["requested_model_id"] != entrant["resolved_model_id"])):
        raise ValueError("unrecorded model substitution")
    if identity == "DECLARED_ALIAS" and entrant["alias_evidence"] is None:
        raise ValueError("model alias requires frozen evidence")


OUTPUT_SCHEMA = obj({
    "schema_id": const("search-output/v2"), "run_id": TEXT,
    "spec_id": TEXT, "spec_version": TEXT, "spec_fingerprint": HASH,
    "architecture_authority": const("SEARCH-CUP/v2.3"),
    "track_id": SEARCHSPEC_SCHEMA["properties"]["track_id"],
    "fairness_mode": SEARCHSPEC_SCHEMA["properties"]["fairness_mode"],
    "entrant": ENTRANT, "environment": REF,
    "retriever_fingerprint": {"anyOf": [HASH, {"type": "null"}]},
    "resource_receipt_fingerprint": HASH, "query_call_provenance": arr(REF),
    "result_provenance": arr(REF), "submission_fingerprint": HASH,
    "terminal_status": enum(*TERMINALS),
    "failure_class": enum("NONE", "INFRASTRUCTURE", "POLICY", "INSUFFICIENT_EVIDENCE", "MODEL_QUALITY", "NON_COMPARABLE"),
    "confidence": {"type": ["number", "null"], "minimum": 0},
    "unknown_reasons": arr(TEXT), "quality_score": const(None),
    "secret_exclusion": obj({"scanner": const("public-safe-patterns/v1"), "status": const("PASS")}),
    "official_prompt_consumed": const(False), "hidden_registry_loaded": const(False),
    "judge_invoked": const(False), "canonical_fingerprint": HASH,
})


def validate_output(output: dict, spec: SearchSpecV2, resource_receipt: dict) -> None:
    from .v23_accounting import validate_resource_receipt
    validate_shape(output, OUTPUT_SCHEMA)
    verify_seal(output)
    validate_resource_receipt(resource_receipt, spec)
    doc = spec.as_dict()
    for key, expected in (("spec_id", doc["spec_id"]), ("spec_version", doc["spec_version"]),
                          ("spec_fingerprint", spec.fingerprint), ("track_id", doc["track_id"]),
                          ("fairness_mode", doc["fairness_mode"]),
                          ("retriever_fingerprint", fingerprint(doc["retriever"]) if doc["retriever"] else None),
                          ("resource_receipt_fingerprint", resource_receipt["canonical_fingerprint"])):
        if output[key] != expected:
            raise ValueError("output binding mismatch")
    for key in ("run_id", "spec_fingerprint", "track_id", "fairness_mode"):
        if output[key] != resource_receipt[key]:
            raise ValueError("resource/output identity mismatch")
    entrant = output["entrant"]
    if fingerprint(entrant) != resource_receipt["entrant_fingerprint"]:
        raise ValueError("resource/entrant identity mismatch")
    validate_entrant(entrant)
    status, failure = output["terminal_status"], output["failure_class"]
    if status == "FAIL" and failure != "MODEL_QUALITY":
        raise ValueError("infrastructure is not model-quality failure")
    if status == "PASS" and failure != "NONE":
        raise ValueError("successful output cannot hide failure")
    if status == "UNKNOWN" and (not output["unknown_reasons"] or failure != "INSUFFICIENT_EVIDENCE"):
        raise ValueError("UNKNOWN requires explicit unresolved evidence")
    if status in ("PASS", "FAIL") and entrant["resolution_status"] != "KNOWN":
        raise ValueError("unknown model identity is non-comparable")
    if entrant["identity_status"] == "SUBSTITUTED" and (status in ("PASS", "FAIL") or failure != "NON_COMPARABLE"):
        raise ValueError("model substitution must terminate non-comparable")
    if status in ("PASS", "FAIL") and resource_receipt["terminal_status"] != "PASS":
        raise ValueError("invalid accounting cannot become model-quality judgment")
    if output["confidence"] is not None and output["confidence"] > 1:
        raise ValueError("confidence outside unit interval")
