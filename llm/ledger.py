"""One SQLite file: the per-call log, the daily budget derived from it, and the cache.

The budget is never stored as a counter. It is `SUM(quota_spent)` over today's
rows, so a crash between reserving and settling can waste one call but can never
overspend the day, and the number in the report is the number in the table.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path

from config import REPO_ROOT
from llm.turn import Json

LEDGER_PATH = REPO_ROOT / ".llm_cache" / "ledger.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    run_id TEXT NOT NULL,
    incident_id TEXT NOT NULL,
    agent TEXT NOT NULL,
    backend TEXT NOT NULL,
    model TEXT NOT NULL,
    cache_key TEXT NOT NULL,
    status TEXT NOT NULL,
    tokens_in INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    latency_ms REAL NOT NULL DEFAULT 0,
    cost_usd_equiv REAL NOT NULL DEFAULT 0,
    quota_spent INTEGER NOT NULL DEFAULT 0,
    detail TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS calls_by_run ON calls(run_id);
CREATE INDEX IF NOT EXISTS calls_by_backend_ts ON calls(backend, ts);
CREATE TABLE IF NOT EXISTS cache (
    cache_key TEXT PRIMARY KEY,
    backend TEXT NOT NULL,
    model TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class CallStatus(StrEnum):
    """A row exists for every decision, including the ones that never called out."""

    reserved = "reserved"
    ok = "ok"
    hit = "hit"
    error = "error"
    skipped = "skipped"


@dataclass(frozen=True, slots=True)
class CachedReply:
    backend: str
    model: str
    payload: Json
    created_at: str


@dataclass(frozen=True, slots=True)
class CallRow:
    id: int
    agent: str
    backend: str
    model: str
    cache_key: str
    status: str
    tokens_in: int
    tokens_out: int
    latency_ms: float
    cost_usd_equiv: float
    quota_spent: int
    detail: str


class Ledger:
    def __init__(self, path: str | Path = LEDGER_PATH) -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def reserve(
        self,
        *,
        run_id: str,
        incident_id: str,
        agent: str,
        backend: str,
        model: str,
        cache_key: str,
        now: datetime | None = None,
    ) -> int:
        """Claim one call before the network request so a crash cannot hide it."""
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            cursor = self._conn.execute(
                "INSERT INTO calls (ts, run_id, incident_id, agent, backend, model, cache_key,"
                " status, quota_spent) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1)",
                (
                    _stamp(now),
                    run_id,
                    incident_id,
                    agent,
                    backend,
                    model,
                    cache_key,
                    CallStatus.reserved.value,
                ),
            )
            self._conn.execute("COMMIT")
        except BaseException:
            self._conn.execute("ROLLBACK")
            raise
        return int(cursor.lastrowid or 0)

    def settle(
        self,
        row_id: int,
        *,
        status: CallStatus,
        tokens_in: int = 0,
        tokens_out: int = 0,
        latency_ms: float = 0.0,
        cost_usd_equiv: float = 0.0,
        detail: str = "",
    ) -> None:
        if status is CallStatus.reserved:
            raise ValueError("settle needs a terminal status")
        quota = 0 if status is CallStatus.skipped else 1
        self._conn.execute(
            "UPDATE calls SET status = ?, tokens_in = ?, tokens_out = ?, latency_ms = ?,"
            " cost_usd_equiv = ?, quota_spent = ?, detail = ? WHERE id = ?",
            (
                status.value,
                tokens_in,
                tokens_out,
                latency_ms,
                cost_usd_equiv,
                quota,
                detail,
                row_id,
            ),
        )

    def log_skipped(
        self,
        *,
        run_id: str,
        incident_id: str,
        agent: str,
        backend: str,
        model: str,
        cache_key: str,
        detail: str,
        now: datetime | None = None,
    ) -> int:
        cursor = self._conn.execute(
            "INSERT INTO calls (ts, run_id, incident_id, agent, backend, model, cache_key, status,"
            " quota_spent, detail) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?)",
            (
                _stamp(now),
                run_id,
                incident_id,
                agent,
                backend,
                model,
                cache_key,
                CallStatus.skipped.value,
                detail,
            ),
        )
        return int(cursor.lastrowid or 0)

    def spent_today(self, backend: str, *, now: datetime | None = None) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(SUM(quota_spent), 0) AS spent FROM calls"
            " WHERE backend = ? AND substr(ts, 1, 10) = ?",
            (backend, _stamp(now)[:10]),
        ).fetchone()
        return int(row["spent"])

    def turns(self, run_id: str) -> int:
        """Every row that reached a backend, hits included, so replay costs the same turns."""
        row = self._conn.execute(
            "SELECT COUNT(*) AS turns FROM calls WHERE run_id = ? AND status IN (?, ?, ?)",
            (run_id, CallStatus.ok.value, CallStatus.hit.value, CallStatus.error.value),
        ).fetchone()
        return int(row["turns"])

    def get_cache(self, key: str) -> CachedReply | None:
        row = self._conn.execute(
            "SELECT backend, model, payload, created_at FROM cache WHERE cache_key = ?", (key,)
        ).fetchone()
        if row is None:
            return None
        return CachedReply(
            backend=row["backend"],
            model=row["model"],
            payload=json.loads(row["payload"]),
            created_at=row["created_at"],
        )

    def put_cache(
        self, key: str, *, backend: str, model: str, payload: Json, now: datetime | None = None
    ) -> None:
        self._conn.execute(
            "INSERT INTO cache (cache_key, backend, model, payload, created_at) VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(cache_key) DO UPDATE SET backend = excluded.backend,"
            " model = excluded.model, payload = excluded.payload, created_at = excluded.created_at",
            (key, backend, model, json.dumps(payload), _stamp(now)),
        )

    def rows(self, run_id: str) -> list[CallRow]:
        found = self._conn.execute(
            "SELECT id, agent, backend, model, cache_key, status, tokens_in, tokens_out,"
            " latency_ms, cost_usd_equiv, quota_spent, detail FROM calls WHERE run_id = ?"
            " ORDER BY id",
            (run_id,),
        ).fetchall()
        return [
            CallRow(
                id=row["id"],
                agent=row["agent"],
                backend=row["backend"],
                model=row["model"],
                cache_key=row["cache_key"],
                status=row["status"],
                tokens_in=row["tokens_in"],
                tokens_out=row["tokens_out"],
                latency_ms=row["latency_ms"],
                cost_usd_equiv=row["cost_usd_equiv"],
                quota_spent=row["quota_spent"],
                detail=row["detail"],
            )
            for row in found
        ]

    def record(
        self,
        *,
        run_id: str,
        incident_id: str,
        agent: str,
        backend: str,
        model: str,
        cache_key: str,
        status: CallStatus,
        usage: Mapping[str, int] | None = None,
        latency_ms: float = 0.0,
        cost_usd_equiv: float = 0.0,
        detail: str = "",
        now: datetime | None = None,
    ) -> int:
        """One row for a call that never touched the network, such as a cache hit."""
        tokens = usage or {}
        cursor = self._conn.execute(
            "INSERT INTO calls (ts, run_id, incident_id, agent, backend, model, cache_key, status,"
            " tokens_in, tokens_out, latency_ms, cost_usd_equiv, quota_spent, detail)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)",
            (
                _stamp(now),
                run_id,
                incident_id,
                agent,
                backend,
                model,
                cache_key,
                status.value,
                int(tokens.get("input_tokens", 0)),
                int(tokens.get("output_tokens", 0)),
                latency_ms,
                cost_usd_equiv,
                detail,
            ),
        )
        return int(cursor.lastrowid or 0)


def _stamp(moment: datetime | None) -> str:
    return (moment or datetime.now(UTC)).astimezone(UTC).isoformat()


__all__ = ["LEDGER_PATH", "CachedReply", "CallRow", "CallStatus", "Ledger"]
