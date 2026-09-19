"""Local FTS5 execution on one explicit synthetic epoch; no persistent database.

Raw query is the MATCH bound parameter. Invalid FTS syntax is a typed failure,
not a reason to expand, fix, retry, call a provider, or consult another epoch.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import platform
import sqlite3
from typing import Callable

from .v23_t6_cslive_source import Epoch, SourceError, aware_time, canonical, digest

TOKENIZER = "unicode61 remove_diacritics 0"
SCHEMA = ("CREATE VIRTUAL TABLE docs USING fts5(title, body, source_id UNINDEXED, "
          "item_id UNINDEXED, link UNINDEXED, content_hash UNINDEXED, "
          "tokenize='unicode61 remove_diacritics 0')")
QUERY_SQL = ("SELECT title,body,source_id,item_id,link,content_hash, "
             "bm25(docs,1.0,1.0,0.0,0.0,0.0,0.0) AS score "
             "FROM docs WHERE docs MATCH ? "
             "ORDER BY score ASC, source_id COLLATE BINARY ASC, "
             "item_id COLLATE BINARY ASC LIMIT ?")


def runtime_identity() -> dict:
    db = sqlite3.connect(":memory:")
    try:
        db.execute(SCHEMA)
        return {"python": platform.python_version(), "sqlite_version": sqlite3.sqlite_version,
                "sqlite_source_id": db.execute("SELECT sqlite_source_id()").fetchone()[0],
                "fts5": True, "tokenizer": TOKENIZER, "schema_hash": digest(SCHEMA),
                "query_sql_hash": digest(QUERY_SQL)}
    except sqlite3.DatabaseError:
        raise SourceError("FTS5_UNAVAILABLE") from None
    finally:
        db.close()


@dataclass(frozen=True)
class SearchRequest:
    entrant_id: str
    call_number: int
    query: str


@dataclass(frozen=True)
class SearchResult:
    title: str
    body: str
    source_id: str
    item_id: str
    url: str
    content_hash: str
    score: float
    rank: int


@dataclass(frozen=True)
class SearchResponse:
    state: str
    error_code: str | None
    results: tuple[SearchResult, ...]
    provenance_json: str


class ControlledSourceRetriever:
    """One epoch + one configuration shared by both permitted entrants."""
    def __init__(self, epoch: Epoch, *, clock: Callable[[], str], expected_runtime: dict,
                 entrants: tuple[str, ...] = ("fixture-a", "fixture-b"),
                 max_calls: int = 4, max_results: int = 10):
        if (type(max_calls) is not int or not 0 < max_calls <= 4
                or type(max_results) is not int or not 0 < max_results <= 10
                or len(entrants) != 2 or len(set(entrants)) != 2):
            raise SourceError("RETRIEVER_CONFIG_REJECTED")
        actual = runtime_identity()
        if canonical(actual) != canonical(expected_runtime):
            raise SourceError("RUNTIME_DRIFT")
        if epoch.parser_version != "t6-cslive-rss/v1":
            raise SourceError("PARSER_VERSION_DRIFT")
        self.epoch = epoch
        self.clock = clock
        self.runtime = actual
        self.config = {"candidate_id": "t6-controlled-source-fts5-v1", "max_calls": max_calls,
                       "max_results": max_results, "tokenizer": TOKENIZER,
                       "title_weight": 1.0, "body_weight": 1.0,
                       "tie_break": ["source_id", "item_id"], "query_rewrite": False,
                       "runtime_fingerprint": digest(actual)}
        self._config_fingerprint = digest(self.config)
        self._epoch_fingerprint = epoch.fingerprint
        self._counts = dict.fromkeys(entrants, 0)
        self.provenance: list[dict] = []
        self._db = sqlite3.connect(":memory:")
        try:
            self._db.execute(SCHEMA)
            self._db.executemany("INSERT INTO docs VALUES (?,?,?,?,?,?)", [
                (r.title, r.body, r.source_id, r.item_id, r.link, r.content_hash)
                for r in sorted(epoch.records, key=lambda r: (r.source_id, r.item_id))])
            self._db.commit()
            self._db.execute("PRAGMA query_only=ON")
        except sqlite3.DatabaseError:
            self._db.close()
            raise SourceError("INDEX_BUILD_FAILED") from None

    def close(self) -> None:
        self._db.close()

    def __enter__(self) -> "ControlledSourceRetriever":
        return self

    def __exit__(self, *_: object) -> None:
        self.close()

    def search(self, request: SearchRequest) -> SearchResponse:
        stamp = aware_time(self.clock()).isoformat()
        error = None
        attempted = False
        results: tuple[SearchResult, ...] = ()
        if digest(self.config) != self._config_fingerprint or self.epoch.fingerprint != self._epoch_fingerprint:
            error = "RETRIEVER_BINDING_DRIFT"
        elif aware_time(stamp) < aware_time(self.epoch.fetched_at):
            error = "QUERY_BEFORE_EPOCH"
        elif not isinstance(request.entrant_id, str) or request.entrant_id not in self._counts:
            error = "UNKNOWN_ENTRANT"
        elif type(request.call_number) is not int or request.call_number != self._counts[request.entrant_id] + 1:
            error = "CALL_SEQUENCE_REJECTED"
        elif self._counts[request.entrant_id] >= self.config["max_calls"]:
            error = "CALL_BUDGET_EXHAUSTED"
        elif not isinstance(request.query, str) or not request.query or len(request.query.encode("utf-8")) > 4096:
            error = "QUERY_CONTRACT_REJECTED"
        else:
            self._counts[request.entrant_id] += 1
            attempted = True
            try:
                rows = self._db.execute(QUERY_SQL, (request.query, self.config["max_results"])).fetchall()
                results = tuple(SearchResult(*row, rank=i + 1) for i, row in enumerate(rows))
            except sqlite3.OperationalError:
                error = "FTS_QUERY_FAILED"
            except sqlite3.DatabaseError:
                error = "INDEX_QUERY_FAILED"
        state = "SUCCESS" if error is None else "FAILED" if attempted else "REJECTED"
        # Exact query retained as data; never interpolated in SQL or logs as code.
        body = {"sequence": len(self.provenance) + 1,
                "previous_hash": self.provenance[-1]["event_hash"] if self.provenance else None,
                "entrant_id": request.entrant_id if isinstance(request.entrant_id, str) else None,
                "call_number": request.call_number if type(request.call_number) is int else None,
                "query": request.query if isinstance(request.query, str) else None, "state": state, "error_code": error,
                "match_attempts": int(attempted), "time": stamp,
                "epoch_id": self.epoch.epoch_id, "epoch_fingerprint": self.epoch.fingerprint,
                "config_fingerprint": digest(self.config), "result_count": len(results),
                "result_fingerprints": [digest(asdict(r)) for r in results],
                "automatic_retries": 0, "follow_links": 0, "network_calls": 0}
        event = {**body, "event_hash": digest(body)}
        self.provenance.append(event)
        return SearchResponse(state, error, results, canonical(event))
