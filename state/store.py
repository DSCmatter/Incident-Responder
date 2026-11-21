"""Persisted run state (DESIGN.md section 6), so a run can pause for approval and resume.

`TRANSITIONS` is the whole state machine: `advance` refuses any move it does not
list, so a run cannot reach `executed` without passing `approved`.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict

from agents.schemas import Approval
from config import REPO_ROOT
from state.states import RunState
from tools.evidence import EvidenceItem, EvidenceKind

RUNS_PATH = REPO_ROOT / ".state" / "runs.db"

_STOPS = frozenset({RunState.failed, RunState.escalated})

TRANSITIONS: dict[RunState, frozenset[RunState]] = {
    RunState.new: frozenset({RunState.triaged}) | _STOPS,
    RunState.triaged: frozenset({RunState.diagnosed}) | _STOPS,
    RunState.diagnosed: frozenset({RunState.verified, RunState.fix_proposed}) | _STOPS,
    RunState.verified: frozenset({RunState.fix_proposed}) | _STOPS,
    RunState.fix_proposed: frozenset({RunState.critiqued, RunState.awaiting_approval}) | _STOPS,
    RunState.critiqued: frozenset({RunState.fix_proposed, RunState.awaiting_approval}) | _STOPS,
    RunState.awaiting_approval: frozenset({RunState.approved, RunState.rejected}),
    RunState.approved: frozenset({RunState.executed, RunState.failed}),
    RunState.executed: frozenset({RunState.done}),
    RunState.rejected: frozenset(),
    RunState.done: frozenset(),
    RunState.escalated: frozenset(),
    RunState.failed: frozenset(),
}

_SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    incident_id TEXT NOT NULL,
    state TEXT NOT NULL,
    stop_reason TEXT,
    payloads TEXT NOT NULL DEFAULT '{}',
    llm_calls INTEGER NOT NULL DEFAULT 0,
    tokens_in INTEGER NOT NULL DEFAULT 0,
    tokens_out INTEGER NOT NULL DEFAULT 0,
    cost_usd_equiv REAL NOT NULL DEFAULT 0,
    duration_ms REAL NOT NULL DEFAULT 0,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS evidence (
    run_id TEXT NOT NULL,
    id TEXT NOT NULL,
    kind TEXT NOT NULL,
    source TEXT NOT NULL,
    content TEXT NOT NULL,
    query TEXT NOT NULL,
    seq INTEGER NOT NULL,
    PRIMARY KEY (run_id, id)
);
CREATE TABLE IF NOT EXISTS approvals (
    run_id TEXT PRIMARY KEY,
    decision TEXT NOT NULL,
    decided_by TEXT NOT NULL,
    note TEXT NOT NULL,
    ts TEXT NOT NULL
);
"""


class IllegalTransition(RuntimeError):
    pass


class UnknownRun(KeyError):
    pass


class RunRecord(BaseModel):
    model_config = ConfigDict(frozen=True)

    run_id: str
    incident_id: str
    state: RunState
    stop_reason: str | None
    payloads: dict[str, Any]
    llm_calls: int
    tokens_in: int
    tokens_out: int
    cost_usd_equiv: float
    duration_ms: float
    started_at: str
    updated_at: str


class RunStore:
    def __init__(self, path: str | Path = RUNS_PATH) -> None:
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    def close(self) -> None:
        self._conn.close()

    def create(self, run_id: str, incident_id: str) -> RunRecord:
        now = _now()
        self._conn.execute(
            "INSERT INTO runs (run_id, incident_id, state, started_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (run_id, incident_id, RunState.new.value, now, now),
        )
        return self.get(run_id)

    def get(self, run_id: str) -> RunRecord:
        row = self._conn.execute("SELECT * FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            raise UnknownRun(run_id)
        return RunRecord(
            run_id=row["run_id"],
            incident_id=row["incident_id"],
            state=RunState(row["state"]),
            stop_reason=row["stop_reason"],
            payloads=json.loads(row["payloads"]),
            llm_calls=row["llm_calls"],
            tokens_in=row["tokens_in"],
            tokens_out=row["tokens_out"],
            cost_usd_equiv=row["cost_usd_equiv"],
            duration_ms=row["duration_ms"],
            started_at=row["started_at"],
            updated_at=row["updated_at"],
        )

    def advance(
        self,
        run_id: str,
        state: RunState,
        *,
        payloads: dict[str, Any] | None = None,
        stop_reason: str | None = None,
    ) -> RunRecord:
        """Move to `state`, merging `payloads` (JSON-ready values) into the stored ones."""
        current = self.get(run_id)
        if state not in TRANSITIONS[current.state]:
            raise IllegalTransition(f"run {run_id}: {current.state.value} -> {state.value}")
        merged = {**current.payloads, **(payloads or {})}
        self._conn.execute(
            "UPDATE runs SET state = ?, payloads = ?, stop_reason = ?, updated_at = ?"
            " WHERE run_id = ?",
            (state.value, json.dumps(merged), stop_reason, _now(), run_id),
        )
        return self.get(run_id)

    def set_totals(
        self,
        run_id: str,
        *,
        llm_calls: int,
        tokens_in: int,
        tokens_out: int,
        cost: float,
        duration_ms: float,
    ) -> None:
        self._conn.execute(
            "UPDATE runs SET llm_calls = ?, tokens_in = ?, tokens_out = ?, cost_usd_equiv = ?,"
            " duration_ms = ? WHERE run_id = ?",
            (llm_calls, tokens_in, tokens_out, cost, duration_ms, run_id),
        )

    def save_evidence(self, run_id: str, items: list[EvidenceItem]) -> None:
        """Idempotent: an id already saved for this run is kept as it was."""
        self._conn.executemany(
            "INSERT OR IGNORE INTO evidence (run_id, id, kind, source, content, query, seq)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            [
                (run_id, item.id, item.kind.value, item.source, item.content, item.query, seq)
                for seq, item in enumerate(items)
            ],
        )

    def evidence(self, run_id: str) -> list[EvidenceItem]:
        rows = self._conn.execute(
            "SELECT id, kind, source, content, query FROM evidence WHERE run_id = ? ORDER BY seq",
            (run_id,),
        ).fetchall()
        return [
            EvidenceItem(
                id=row["id"],
                kind=EvidenceKind(row["kind"]),
                source=row["source"],
                content=row["content"],
                query=row["query"],
            )
            for row in rows
        ]

    def record_approval(self, approval: Approval) -> None:
        """One decision per run. Repeating the same decision is a no-op; a different one fails."""
        existing = self.approval(approval.run_id)
        if existing is not None:
            if existing != approval:
                raise IllegalTransition(f"run {approval.run_id} already has a decision")
            return
        self.get(approval.run_id)
        self._conn.execute(
            "INSERT INTO approvals (run_id, decision, decided_by, note, ts) VALUES (?, ?, ?, ?, ?)",
            (
                approval.run_id,
                approval.decision.value,
                approval.decided_by,
                approval.note,
                _now(),
            ),
        )

    def approval(self, run_id: str) -> Approval | None:
        row = self._conn.execute(
            "SELECT run_id, decision, decided_by, note FROM approvals WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return Approval(
            run_id=row["run_id"],
            decision=row["decision"],
            decided_by=row["decided_by"],
            note=row["note"],
        )


def _now() -> str:
    return datetime.now(UTC).isoformat()
