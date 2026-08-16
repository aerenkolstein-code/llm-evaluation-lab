"""Immutable, canonical contracts for SEARCH-CUP-02."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, is_dataclass
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Sequence


def _jsonable(value: object) -> object:
    if is_dataclass(value):
        return _jsonable(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list, set, frozenset)):
        return [_jsonable(item) for item in value]
    return value


def canonical_json(value: object) -> str:
    """Return the one canonical UTF-8 JSON representation used for hashing."""

    return json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def fingerprint(value: object) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _required_text(value: object, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _required_bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{label} must be boolean")
    return value


def _string_tuple(value: object, label: str, *, allow_empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        raise ValueError(f"{label} must be an array")
    normalized = tuple(_required_text(item, f"{label}[]") for item in value)
    if not normalized and not allow_empty:
        raise ValueError(f"{label} must not be empty")
    return normalized


FORBIDDEN_CANDIDATE_KEYS = frozenset(
    {
        "account_data",
        "credentials",
        "family",
        "financial",
        "google_drive",
        "health",
        "l0",
        "private_archive",
        "raw",
        "relationship",
    }
)


def _scan_forbidden_keys(value: object, path: str = "candidate") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            normalized = str(key).strip().lower()
            if normalized in FORBIDDEN_CANDIDATE_KEYS:
                raise ValueError(f"{path}.{key}: private field is not allowed")
            _scan_forbidden_keys(item, f"{path}.{key}")
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for index, item in enumerate(value):
            _scan_forbidden_keys(item, f"{path}[{index}]")


@dataclass(frozen=True)
class CandidateCard:
    """Public-safe candidate context stored as canonical content."""

    canonical_content: str
    fingerprint: str

    @classmethod
    def from_mapping(cls, document: Mapping[str, object]) -> "CandidateCard":
        _scan_forbidden_keys(document)
        _required_text(document.get("candidate_id"), "candidate_id")
        _required_text(document.get("legal_name"), "legal_name")
        _required_text(document.get("technical_name"), "technical_name")
        base = document.get("base")
        languages = document.get("languages")
        positioning = document.get("current_positioning")
        targets = document.get("current_target_roles")
        if not all(isinstance(item, Mapping) for item in (base, languages, positioning, targets)):
            raise ValueError("candidate card is missing a required profile section")
        content = canonical_json(document)
        return cls(
            canonical_content=content,
            fingerprint=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        )

    @classmethod
    def load(cls, path: str | Path) -> "CandidateCard":
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError("candidate card must be a JSON object")
        return cls.from_mapping(document)

    @property
    def canonical_bytes(self) -> bytes:
        return self.canonical_content.encode("utf-8")

    def as_dict(self) -> Mapping[str, object]:
        return MappingProxyType(json.loads(self.canonical_content))


@dataclass(frozen=True)
class EntrantConfig:
    entrant_id: str
    provider: str
    exact_model_id: str
    endpoint_mode: str
    sampling_json: str

    @classmethod
    def from_mapping(cls, document: Mapping[str, object]) -> "EntrantConfig":
        sampling = document.get("sampling", {})
        if not isinstance(sampling, Mapping):
            raise ValueError("entrant sampling must be an object")
        return cls(
            entrant_id=_required_text(document.get("entrant_id"), "entrant_id"),
            provider=_required_text(document.get("provider"), "provider"),
            exact_model_id=_required_text(document.get("exact_model_id"), "exact_model_id"),
            endpoint_mode=_required_text(document.get("endpoint_mode"), "endpoint_mode"),
            sampling_json=canonical_json(sampling),
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "entrant_id": self.entrant_id,
            "provider": self.provider,
            "exact_model_id": self.exact_model_id,
            "endpoint_mode": self.endpoint_mode,
            "sampling": json.loads(self.sampling_json),
        }


@dataclass(frozen=True)
class CompetitionSpec:
    competition_id: str
    task: str
    max_search_calls: int
    search_backend_id: str
    official_match_authorized: bool
    entrants: tuple[EntrantConfig, ...]
    canonical_content: str
    fingerprint: str

    @classmethod
    def from_mapping(cls, document: Mapping[str, object]) -> "CompetitionSpec":
        competition_id = _required_text(document.get("competition_id"), "competition_id")
        task = _required_text(document.get("task"), "task")
        backend = _required_text(document.get("search_backend_id"), "search_backend_id")
        budget = document.get("max_search_calls")
        if not isinstance(budget, int) or isinstance(budget, bool) or budget != 20:
            raise ValueError("SEARCH-CUP-02 requires max_search_calls == 20")
        authorized = document.get("official_match_authorized")
        if not isinstance(authorized, bool):
            raise ValueError("official_match_authorized must be boolean")
        raw_entrants = document.get("entrants")
        if not isinstance(raw_entrants, list) or len(raw_entrants) != 4:
            raise ValueError("SEARCH-CUP-02 requires exactly four entrants")
        entrants = tuple(
            EntrantConfig.from_mapping(item)
            for item in raw_entrants
            if isinstance(item, Mapping)
        )
        if len(entrants) != 4:
            raise ValueError("every entrant must be an object")
        entrant_ids = [item.entrant_id for item in entrants]
        providers = [item.provider.lower() for item in entrants]
        if len(set(entrant_ids)) != 4 or len(set(providers)) != 4:
            raise ValueError("entrant IDs and providers must be unique")
        if set(providers) != {"openai", "gemini", "deepseek", "glm"}:
            raise ValueError("entrants must be OpenAI, Gemini, DeepSeek, and GLM")
        content = canonical_json(document)
        return cls(
            competition_id=competition_id,
            task=task,
            max_search_calls=budget,
            search_backend_id=backend,
            official_match_authorized=authorized,
            entrants=entrants,
            canonical_content=content,
            fingerprint=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        )

    @classmethod
    def load(cls, path: str | Path) -> "CompetitionSpec":
        document = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError("competition spec must be a JSON object")
        return cls.from_mapping(document)

    @property
    def canonical_bytes(self) -> bytes:
        return self.canonical_content.encode("utf-8")


@dataclass(frozen=True)
class SearchRequest:
    entrant_id: str
    query: str

    def __post_init__(self) -> None:
        _required_text(self.entrant_id, "entrant_id")
        _required_text(self.query, "query")


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str

    def __post_init__(self) -> None:
        _required_text(self.title, "search result title")
        _required_text(self.url, "search result URL")


@dataclass(frozen=True)
class SearchTrace:
    entrant_id: str
    call_number: int
    query: str
    status: str
    result_count: int
    error_type: str | None = None


@dataclass(frozen=True)
class URLReadResult:
    url: str
    status: str
    title: str = ""
    text: str = ""

    def __post_init__(self) -> None:
        _required_text(self.url, "URL read URL")
        if self.status not in {"OK", "BLOCKED", "JS_REQUIRED", "NOT_FOUND"}:
            raise ValueError("unsupported URL read status")


@dataclass(frozen=True)
class Lead:
    company: str
    role: str
    source_url: str
    official_source: bool
    open_status: str
    remote_scope: str
    location_constraint: str
    employment_type: str
    required_skills: tuple[str, ...]
    candidate_fit: str
    mismatch_risks: tuple[str, ...]
    portfolio_relevance: str
    confidence: float
    next_action: str
    evidence_urls: tuple[str, ...]
    claimed_novel: bool = False

    def __post_init__(self) -> None:
        for label in (
            "company",
            "role",
            "source_url",
            "open_status",
            "remote_scope",
            "location_constraint",
            "employment_type",
            "candidate_fit",
            "portfolio_relevance",
            "next_action",
        ):
            _required_text(getattr(self, label), label)
        if self.open_status not in {"OPEN", "CLOSED", "UNVERIFIED"}:
            raise ValueError("open_status must be OPEN, CLOSED, or UNVERIFIED")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if not self.evidence_urls:
            raise ValueError("lead must include at least one evidence URL")

    @property
    def key(self) -> str:
        return self.source_url.strip().rstrip("/").lower()

    @classmethod
    def from_mapping(cls, document: Mapping[str, object]) -> "Lead":
        confidence = document.get("confidence")
        if not isinstance(confidence, (int, float)) or isinstance(confidence, bool):
            raise ValueError("confidence must be numeric")
        return cls(
            company=_required_text(document.get("company"), "company"),
            role=_required_text(document.get("role"), "role"),
            source_url=_required_text(document.get("source_url"), "source_url"),
            official_source=_required_bool(
                document.get("official_source"), "official_source"
            ),
            open_status=_required_text(document.get("open_status"), "open_status"),
            remote_scope=_required_text(document.get("remote_scope"), "remote_scope"),
            location_constraint=_required_text(
                document.get("location_constraint"), "location_constraint"
            ),
            employment_type=_required_text(
                document.get("employment_type"), "employment_type"
            ),
            required_skills=_string_tuple(
                document.get("required_skills", []),
                "required_skills",
                allow_empty=True,
            ),
            candidate_fit=_required_text(document.get("candidate_fit"), "candidate_fit"),
            mismatch_risks=_string_tuple(
                document.get("mismatch_risks", []),
                "mismatch_risks",
                allow_empty=True,
            ),
            portfolio_relevance=_required_text(
                document.get("portfolio_relevance"), "portfolio_relevance"
            ),
            confidence=float(confidence),
            next_action=_required_text(document.get("next_action"), "next_action"),
            evidence_urls=_string_tuple(document.get("evidence_urls", []), "evidence_urls"),
            claimed_novel=_required_bool(
                document.get("claimed_novel", False), "claimed_novel"
            ),
        )


@dataclass(frozen=True)
class Submission:
    entrant: EntrantConfig
    candidate_fingerprint: str
    competition_fingerprint: str
    leads: tuple[Lead, ...]
    apply_now_urls: tuple[str, ...]
    search_strategy_summary: str
    rejected_or_downgraded: tuple[str, ...]
    uncertainties: tuple[str, ...]
    search_calls: int

    def __post_init__(self) -> None:
        if len(self.leads) > 20:
            raise ValueError("submission may contain at most 20 leads")
        if len(self.apply_now_urls) > 5:
            raise ValueError("submission may contain at most five Apply-Now leads")
        lead_urls = {lead.source_url for lead in self.leads}
        if any(url not in lead_urls for url in self.apply_now_urls):
            raise ValueError("Apply-Now URLs must refer to submitted leads")
        if not 0 <= self.search_calls <= 20:
            raise ValueError("search_calls must be between 0 and 20")
        _required_text(self.search_strategy_summary, "search_strategy_summary")

    def as_dict(self) -> dict[str, object]:
        return {
            "entrant": self.entrant.as_dict(),
            "candidate_fingerprint": self.candidate_fingerprint,
            "competition_fingerprint": self.competition_fingerprint,
            "leads": [asdict(lead) for lead in self.leads],
            "apply_now_urls": list(self.apply_now_urls),
            "search_strategy_summary": self.search_strategy_summary,
            "rejected_or_downgraded": list(self.rejected_or_downgraded),
            "uncertainties": list(self.uncertainties),
            "search_calls": self.search_calls,
        }

    @classmethod
    def from_mapping(cls, document: Mapping[str, object]) -> "Submission":
        raw_entrant = document.get("entrant")
        raw_leads = document.get("leads")
        if not isinstance(raw_entrant, Mapping) or not isinstance(raw_leads, list):
            raise ValueError("submission is missing entrant or leads")
        if not all(isinstance(item, Mapping) for item in raw_leads):
            raise ValueError("every submitted lead must be an object")
        search_calls = document.get("search_calls")
        if not isinstance(search_calls, int) or isinstance(search_calls, bool):
            raise ValueError("submission search_calls must be an integer")
        return cls(
            entrant=EntrantConfig.from_mapping(raw_entrant),
            candidate_fingerprint=_required_text(
                document.get("candidate_fingerprint"), "candidate_fingerprint"
            ),
            competition_fingerprint=_required_text(
                document.get("competition_fingerprint"),
                "competition_fingerprint",
            ),
            leads=tuple(Lead.from_mapping(item) for item in raw_leads),
            apply_now_urls=_string_tuple(
                document.get("apply_now_urls", []),
                "apply_now_urls",
                allow_empty=True,
            ),
            search_strategy_summary=_required_text(
                document.get("search_strategy_summary"),
                "search_strategy_summary",
            ),
            rejected_or_downgraded=_string_tuple(
                document.get("rejected_or_downgraded", []),
                "rejected_or_downgraded",
                allow_empty=True,
            ),
            uncertainties=_string_tuple(
                document.get("uncertainties", []),
                "uncertainties",
                allow_empty=True,
            ),
            search_calls=search_calls,
        )


@dataclass(frozen=True)
class FrozenSubmission:
    entrant_id: str
    canonical_content: str
    sha256: str

    @classmethod
    def freeze(cls, submission: Submission) -> "FrozenSubmission":
        content = canonical_json(submission.as_dict())
        return cls(
            entrant_id=submission.entrant.entrant_id,
            canonical_content=content,
            sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        )

    def thaw_verified(self) -> Submission:
        actual = hashlib.sha256(self.canonical_content.encode("utf-8")).hexdigest()
        if actual != self.sha256:
            raise ValueError("frozen submission hash mismatch")
        document = json.loads(self.canonical_content)
        if not isinstance(document, dict):
            raise ValueError("frozen submission must contain an object")
        submission = Submission.from_mapping(document)
        if submission.entrant.entrant_id != self.entrant_id:
            raise ValueError("frozen submission entrant mismatch")
        return submission


@dataclass(frozen=True)
class RegistryLeadAssessment:
    source_url: str
    real_open: bool
    practical_fit: bool
    geography_eligible: bool
    actionable: bool
    primary_source: bool
    fabricated: bool = False
    us_only: bool = False
    senior_or_phd_mismatch: bool = False

    @property
    def key(self) -> str:
        return self.source_url.strip().rstrip("/").lower()


@dataclass(frozen=True)
class JudgeRegistrySnapshot:
    snapshot_id: str
    known_well_keys: tuple[str, ...]
    assessments: tuple[RegistryLeadAssessment, ...]
    fingerprint: str

    @classmethod
    def create(
        cls,
        snapshot_id: str,
        known_well_urls: Sequence[str],
        assessments: Sequence[RegistryLeadAssessment],
    ) -> "JudgeRegistrySnapshot":
        known = tuple(sorted({url.strip().rstrip("/").lower() for url in known_well_urls}))
        assessment_tuple = tuple(sorted(assessments, key=lambda item: item.key))
        assessment_keys = [item.key for item in assessment_tuple]
        if len(set(assessment_keys)) != len(assessment_keys):
            raise ValueError("judge registry assessments must have unique URLs")
        payload = {
            "snapshot_id": _required_text(snapshot_id, "snapshot_id"),
            "known_well_keys": known,
            "assessments": [asdict(item) for item in assessment_tuple],
        }
        return cls(
            snapshot_id=snapshot_id,
            known_well_keys=known,
            assessments=assessment_tuple,
            fingerprint=fingerprint(payload),
        )

    def verify(self) -> None:
        payload = {
            "snapshot_id": self.snapshot_id,
            "known_well_keys": self.known_well_keys,
            "assessments": [asdict(item) for item in self.assessments],
        }
        if fingerprint(payload) != self.fingerprint:
            raise ValueError("judge registry snapshot hash mismatch")
