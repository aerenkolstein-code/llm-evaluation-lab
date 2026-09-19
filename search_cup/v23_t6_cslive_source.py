"""T6 controlled-source primitives. Synthetic bytes only; no transport or file I/O.

A source publication is data, never a query planner or executable instruction.
Runtime/source admission is deliberately separate from offline mechanism testing.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
from html.parser import HTMLParser
import json
import re
from typing import Callable
from urllib.parse import urlsplit
from xml.etree import ElementTree

PARSER_VERSION = "t6-cslive-rss/v1"


class SourceError(ValueError):
    """Stable, content-safe error code; untrusted input never enters messages."""
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def canonical(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False)


def digest(value: object) -> str:
    return sha256(canonical(value).encode("utf-8")).hexdigest()


def aware_time(text: str) -> datetime:
    try:
        value = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if value.tzinfo is None:
            raise ValueError
        return value.astimezone(timezone.utc)
    except (AttributeError, TypeError, ValueError, OverflowError):
        raise SourceError("INVALID_OBSERVATION_TIME") from None


def date_evidence(raw: str) -> tuple[str, str | None]:
    """Retain raw field separately; naive/invalid dates are UNKNOWN, not guessed."""
    if not raw:
        return "UNKNOWN", None
    try:
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            dt = parsedate_to_datetime(raw)
        if dt.tzinfo is None:
            raise ValueError
        return "KNOWN", dt.astimezone(timezone.utc).isoformat()
    except (ValueError, TypeError, OverflowError, AttributeError):
        return "UNKNOWN", None


@dataclass(frozen=True)
class SourcePolicy:
    source_id: str = "synthetic-rss"
    source_url: str = "https://source.example.invalid/jobs/rss"
    allowed_item_host: str = "source.example.invalid"
    max_input_bytes: int = 2 * 1024 * 1024
    max_items: int = 100
    max_body_bytes: int = 32 * 1024
    min_interval_seconds: int = 24 * 60 * 60
    mode: str = "SYNTHETIC_ONLY"

    def __post_init__(self) -> None:
        if self.mode != "SYNTHETIC_ONLY" or not self.source_id:
            raise SourceError("SOURCE_NOT_ADMITTED")
        try:
            u = urlsplit(self.source_url)
            if (u.scheme != "https" or u.hostname != self.allowed_item_host
                    or not self.allowed_item_host.endswith(".invalid")
                    or u.username or u.password or u.port or u.query or u.fragment
                    or any(ord(c) < 33 for c in self.source_url) or "\\" in self.source_url):
                raise ValueError
        except (ValueError, TypeError, AttributeError):
            raise SourceError("SOURCE_POLICY_REJECTED") from None
        for name, cap in (("max_input_bytes", 2097152), ("max_items", 100),
                          ("max_body_bytes", 32768)):
            n = getattr(self, name)
            if type(n) is not int or not 0 < n <= cap:
                raise SourceError("SOURCE_LIMIT_INVALID")
        if type(self.min_interval_seconds) is not int or self.min_interval_seconds < 86400:
            raise SourceError("POLLING_POLICY_REJECTED")

    @property
    def fingerprint(self) -> str:
        return digest(asdict(self))


class _PlainHTML(HTMLParser):
    blocked = frozenset({"script", "style", "img", "iframe", "object", "embed",
                         "svg", "math", "link", "meta", "base", "audio", "video", "source"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.blocked or any(k.lower().startswith("on") for k, _ in attrs):
            raise SourceError("UNSAFE_HTML")
        self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_decl(self, decl: str) -> None:
        raise SourceError("UNSAFE_HTML")

    def unknown_decl(self, data: str) -> None:
        raise SourceError("UNSAFE_HTML")


def plain_html(text: str) -> str:
    parser = _PlainHTML()
    try:
        parser.feed(text)
        parser.close()
    except SourceError:
        raise
    except (ValueError, AssertionError):
        raise SourceError("INVALID_HTML") from None
    return " ".join("".join(parser.parts).split())


def _safe_link(link: str, host: str) -> None:
    try:
        u = urlsplit(link)
        if (u.scheme != "https" or u.hostname != host or u.username or u.password
                or u.port or any(ord(c) < 33 for c in link) or "\\" in link):
            raise ValueError
    except (ValueError, AttributeError):
        raise SourceError("ITEM_LINK_REJECTED") from None


@dataclass(frozen=True)
class SourceRecord:
    source_id: str
    item_id: str
    title: str
    body: str
    link: str
    published_raw: str
    published_state: str
    published_utc: str | None
    expires_raw: str
    expires_state: str
    expires_utc: str | None
    field_evidence_json: str

    @property
    def content_hash(self) -> str:
        return digest(asdict(self))


def _field(item: ElementTree.Element, name: str) -> str:
    # Reject nested XML in fields; content:encoded/description HTML must be text.
    matches = [x for x in item if x.tag == name]
    if len(matches) > 1:
        raise SourceError("DUPLICATE_FIELD")
    if not matches:
        return ""
    if len(matches[0]):
        raise SourceError("NESTED_XML_FIELD")
    return matches[0].text or ""


def parse_rss(payload: bytes, policy: SourcePolicy) -> tuple[tuple[SourceRecord, ...], int]:
    if type(payload) is not bytes or len(payload) > policy.max_input_bytes:
        raise SourceError("INPUT_BYTES_LIMIT")
    try:
        text = payload.decode("utf-8-sig", errors="strict")
    except UnicodeError:
        raise SourceError("ENCODING_REJECTED") from None
    if "\x00" in text or re.search(r"<!\s*(?:DOCTYPE|ENTITY)", text, re.I):
        raise SourceError("DTD_ENTITY_REJECTED")
    if re.search(r"<\?xml[^?]*encoding\s*=\s*['\"](?!utf-8['\"])", text, re.I):
        raise SourceError("ENCODING_REJECTED")
    try:
        root = ElementTree.fromstring(text)
    except (ElementTree.ParseError, ValueError):
        raise SourceError("INVALID_XML") from None
    channels = root.findall("channel")
    if root.tag != "rss" or len(channels) != 1:
        raise SourceError("RSS_SHAPE_REJECTED")
    nodes = channels[0].findall("item")
    if len(nodes) > policy.max_items:
        raise SourceError("ITEM_COUNT_LIMIT")
    by_id: dict[str, SourceRecord] = {}
    duplicates = 0
    for item in nodes:
        fields = {k: _field(item, k) for k in (
            "title", "description", "link", "guid", "pubDate", "expiryDate",
            "{http://purl.org/rss/1.0/modules/content/}encoded")}
        desc = fields["description"]
        encoded = fields["{http://purl.org/rss/1.0/modules/content/}encoded"]
        if len((desc + encoded).encode("utf-8")) > policy.max_body_bytes:
            raise SourceError("BODY_BYTES_LIMIT")
        if any(len(fields[k].encode("utf-8")) > 4096 for k in
               ("title", "link", "guid", "pubDate", "expiryDate")):
            raise SourceError("METADATA_BYTES_LIMIT")
        link = fields["link"]
        _safe_link(link, policy.allowed_item_host)
        identity = fields["guid"] or link  # GUID is opaque, NOT a URL.
        title = plain_html(fields["title"])
        if not identity or not title:
            raise SourceError("REQUIRED_FIELD_MISSING")
        # Preserve both channels in field evidence; no adjudication by ingestion.
        body = plain_html(desc) + ("\n" + plain_html(encoded) if encoded else "")
        ps, pu = date_evidence(fields["pubDate"])
        es, eu = date_evidence(fields["expiryDate"])
        record = SourceRecord(policy.source_id, identity, title, body, link,
                              fields["pubDate"], ps, pu, fields["expiryDate"], es, eu,
                              canonical(fields))
        if identity in by_id:
            if by_id[identity] != record:
                raise SourceError("IDENTITY_COLLISION")
            duplicates += 1
        else:
            by_id[identity] = record
    return tuple(by_id[k] for k in sorted(by_id)), duplicates


@dataclass(frozen=True)
class Epoch:
    epoch_id: str
    source_id: str
    fetched_at: str
    policy_fingerprint: str
    payload_hash: str
    records: tuple[SourceRecord, ...]
    duplicate_count: int
    previous_fingerprint: str | None
    parser_version: str = PARSER_VERSION

    @property
    def content_hash(self) -> str:
        return digest([asdict(r) for r in self.records])

    @property
    def fingerprint(self) -> str:
        return digest(asdict(self))

    def as_dict(self) -> dict:
        return {**asdict(self), "content_hash": self.content_hash,
                "epoch_fingerprint": self.fingerprint}


def epoch_delta(before: Epoch, after: Epoch) -> dict:
    if before.source_id != after.source_id or before.policy_fingerprint != after.policy_fingerprint:
        raise SourceError("EPOCH_POLICY_DRIFT")
    a = {r.item_id: r.content_hash for r in before.records}
    b = {r.item_id: r.content_hash for r in after.records}
    changed = sorted(k for k in a.keys() & b.keys() if a[k] != b[k])
    return {"state": "NO_DRIFT_OBSERVED" if a == b else "DRIFT_OBSERVED",
            "added": sorted(b.keys() - a.keys()), "removed": sorted(a.keys() - b.keys()),
            "changed": changed, "before": before.fingerprint, "after": after.fingerprint}


class EpochStore:
    """Explicit injected-byte epochs; no default/fallback network implementation."""
    def __init__(self, policy: SourcePolicy, *, clock: Callable[[], str]):
        self.policy = policy
        self.clock = clock
        self.epochs: list[Epoch] = []
        self.last_attempt: datetime | None = None
        self.current: Epoch | None = None
        self.events: list[dict] = []
        self._seen_ids: set[str] = set()

    def _event(self, data: dict) -> None:
        body = {**data, "sequence": len(self.events) + 1,
                "previous_hash": self.events[-1]["event_hash"] if self.events else None}
        self.events.append({**body, "event_hash": digest(body)})

    def ingest(self, payload: bytes | None, *, epoch_id: str, source_url: str,
               response_status: int = 200, final_url: str | None = None) -> Epoch:
        previous = self.epochs[-1] if self.epochs else None
        self.current = None  # Even an invalid clock must invalidate the current view.
        now = None
        try:
            try:
                now = aware_time(self.clock())
            except SourceError:
                raise
            except Exception:
                raise SourceError("CLOCK_FAILED") from None
            if self.last_attempt is not None:
                seconds = (now - self.last_attempt).total_seconds()
                if seconds < 0:
                    raise SourceError("CLOCK_REGRESSION")
                if seconds < self.policy.min_interval_seconds:
                    raise SourceError("POLL_TOO_FREQUENT")
            self.last_attempt = now
            if not isinstance(epoch_id, str) or not epoch_id or epoch_id in self._seen_ids:
                raise SourceError("EPOCH_ID_REUSED")
            self._seen_ids.add(epoch_id)  # failed attempt is not silently retried
            if source_url != self.policy.source_url:
                raise SourceError("SOURCE_URL_REJECTED")
            if final_url is not None and final_url != source_url:
                raise SourceError("REDIRECT_REJECTED")
            if type(response_status) is not int or response_status != 200:
                raise SourceError("SOURCE_RESPONSE_FAILED")
            if payload is None:
                raise SourceError("SOURCE_ACQUISITION_FAILED")
            records, dupes = parse_rss(payload, self.policy)
            epoch = Epoch(epoch_id, self.policy.source_id, now.isoformat(), self.policy.fingerprint,
                          sha256(payload).hexdigest(), records, dupes,
                          previous.fingerprint if previous else None)
            self.epochs.append(epoch)
            self.current = epoch
            self._event({"kind": "INGEST", "state": "SUCCESS", "time": now.isoformat(),
                         "epoch_id": epoch_id, "epoch_fingerprint": epoch.fingerprint,
                         "payload_hash": epoch.payload_hash, "record_count": len(records)})
            return epoch
        except SourceError as exc:
            self._event({"kind": "INGEST", "state": "REJECTED", "time": now.isoformat() if now else None,
                         "error_code": exc.code, "no_stale_fallback": True})
            raise

    def require_current(self) -> Epoch:
        if self.current is None:
            raise SourceError("NO_CURRENT_EPOCH")
        return self.current
