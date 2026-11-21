"""The runbook index in SQLite: FTS5 bm25 for the lexical side, stored vectors for the dense side.

Docker (and so pgvector) is not available here, and the corpus is about a hundred
chunks, so dense search is a brute-force cosine over vectors held in memory.

`ensure_index` is idempotent: it rebuilds only when the corpus content hash or the
embedder name differs from what the index stores, and it builds into a temporary
file that replaces the old index in one rename, so a crash mid-build leaves the
previous index intact. `RunbookIndex.open` copies the file into memory, so a later
rebuild never changes an index a run is already using.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from config import REPO_ROOT
from rag.corpus import CORPUS_DIR, Chunk, DocKind, corpus_hash, load_chunks
from rag.embed import Embedder, Vectors

INDEX_PATH = REPO_ROOT / ".state" / "rag.db"
RRF_K = 60

_SCHEMA = """
CREATE TABLE chunks(
    rowid INTEGER PRIMARY KEY,
    doc_id TEXT NOT NULL,
    doc_kind TEXT NOT NULL,
    source TEXT NOT NULL,
    services TEXT NOT NULL,
    text TEXT NOT NULL
);
CREATE VIRTUAL TABLE chunks_fts USING fts5(
    text, content='chunks', content_rowid='rowid', tokenize='porter unicode61'
);
CREATE TABLE vectors(rowid INTEGER PRIMARY KEY REFERENCES chunks(rowid), blob BLOB NOT NULL);
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


@dataclass(frozen=True, slots=True)
class Hit:
    doc_id: str
    source: str
    text: str
    score: float  # dense cosine similarity clamped to [0, 1]; comparable across queries
    bm25_rank: int | None  # 1-based among eligible chunks; None when no query term matched
    dense_rank: int  # 1-based among eligible chunks


class IndexMismatch(RuntimeError):
    """The index on disk was built with a different embedder than the one offered."""


def ensure_index(
    embedder: Embedder, db_path: Path = INDEX_PATH, corpus_root: Path = CORPUS_DIR
) -> bool:
    """Bring the index in line with the corpus. Returns True when it had to build."""
    wanted = {"corpus_hash": corpus_hash(corpus_root), "embedder": embedder.name}
    if _stored_meta(db_path) == wanted:
        return False
    chunks = load_chunks(corpus_root)
    vectors = (
        embedder.embed([chunk.text for chunk in chunks])
        if chunks
        else np.zeros((0, 0), dtype=np.float32)
    )
    db_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = db_path.with_name(db_path.name + ".tmp")
    temporary.unlink(missing_ok=True)
    with closing(sqlite3.connect(temporary)) as db:
        db.executescript(_SCHEMA)
        for rowid, (chunk, vector) in enumerate(zip(chunks, vectors, strict=True), start=1):
            db.execute(
                "INSERT INTO chunks(rowid, doc_id, doc_kind, source, services, text) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    rowid,
                    chunk.doc_id,
                    chunk.doc_kind.value,
                    chunk.source,
                    json.dumps(list(chunk.services)),
                    chunk.text,
                ),
            )
            db.execute(
                "INSERT INTO vectors(rowid, blob) VALUES (?, ?)",
                (rowid, vector.astype(np.float32).tobytes()),
            )
        db.execute("INSERT INTO chunks_fts(rowid, text) SELECT rowid, text FROM chunks")
        db.executemany("INSERT INTO meta(key, value) VALUES (?, ?)", sorted(wanted.items()))
        db.commit()
    os.replace(temporary, db_path)
    return True


def _stored_meta(db_path: Path) -> dict[str, str] | None:
    if not db_path.is_file():
        return None
    try:
        with closing(sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)) as db:
            return dict(db.execute("SELECT key, value FROM meta").fetchall())
    except sqlite3.DatabaseError:
        return None


class RunbookIndex:
    """A read-only, in-memory snapshot of the index plus the embedder for queries."""

    def __init__(self, db: sqlite3.Connection, embedder: Embedder) -> None:
        self._db = db
        self._embedder = embedder
        rows = db.execute(
            "SELECT c.rowid, c.doc_id, c.doc_kind, c.source, c.services, c.text, v.blob "
            "FROM chunks c JOIN vectors v ON v.rowid = c.rowid ORDER BY c.rowid"
        ).fetchall()
        self._position_of = {row[0]: position for position, row in enumerate(rows)}
        self._chunks = [
            Chunk(
                doc_id=row[1],
                doc_kind=DocKind(row[2]),
                source=row[3],
                services=tuple(json.loads(row[4])),
                text=row[5],
            )
            for row in rows
        ]
        self._vectors: Vectors = (
            np.stack([np.frombuffer(row[6], dtype=np.float32) for row in rows])
            if rows
            else np.zeros((0, 0), dtype=np.float32)
        )

    @classmethod
    def open(cls, embedder: Embedder, db_path: Path = INDEX_PATH) -> RunbookIndex:
        stored = _stored_meta(db_path)
        if stored is None:
            raise FileNotFoundError(f"no runbook index at {db_path}; run `make ingest`")
        if stored.get("embedder") != embedder.name:
            raise IndexMismatch(
                f"{db_path} was built with {stored.get('embedder')!r}, not {embedder.name!r}"
            )
        memory = sqlite3.connect(":memory:", check_same_thread=False)
        with closing(sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)) as disk:
            disk.backup(memory)
        return cls(memory, embedder)

    def close(self) -> None:
        self._db.close()

    def search(
        self,
        query: str,
        service: str | None = None,
        k: int = 5,
        exclude: frozenset[str] = frozenset(),
    ) -> list[Hit]:
        """Best chunk per document, ordered by reciprocal rank fusion of bm25 and cosine."""
        eligible = [
            position
            for position, chunk in enumerate(self._chunks)
            if chunk.doc_id not in exclude
            and (service is None or not chunk.services or service in chunk.services)
        ]
        if not eligible or k < 1:
            return []
        similarity = self._vectors[eligible] @ self._embedder.embed([query])[0]
        dense_order = sorted(range(len(eligible)), key=lambda i: (-similarity[i], i))
        dense_rank = {eligible[i]: rank for rank, i in enumerate(dense_order, start=1)}
        cosine = {eligible[i]: float(similarity[i]) for i in range(len(eligible))}
        bm25_rank = self._bm25_ranks(query, set(eligible))

        def fused(position: int) -> float:
            lexical = bm25_rank.get(position)
            return 1 / (RRF_K + dense_rank[position]) + (
                1 / (RRF_K + lexical) if lexical is not None else 0.0
            )

        ordered = sorted(eligible, key=lambda p: (-fused(p), dense_rank[p]))
        hits: list[Hit] = []
        seen: set[str] = set()
        for position in ordered:
            chunk = self._chunks[position]
            if chunk.doc_id in seen:
                continue
            seen.add(chunk.doc_id)
            hits.append(
                Hit(
                    doc_id=chunk.doc_id,
                    source=chunk.source,
                    text=chunk.text,
                    score=min(1.0, max(0.0, cosine[position])),
                    bm25_rank=bm25_rank.get(position),
                    dense_rank=dense_rank[position],
                )
            )
            if len(hits) == k:
                break
        return hits

    def _bm25_ranks(self, query: str, eligible: set[int]) -> dict[int, int]:
        terms = re.findall(r"[a-z0-9]+", query.lower())
        if not terms:
            return {}
        expression = " OR ".join(f'"{term}"' for term in dict.fromkeys(terms))
        rows = self._db.execute(
            "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ? "
            "ORDER BY bm25(chunks_fts), rowid",
            (expression,),
        ).fetchall()
        matched = [
            self._position_of[row[0]] for row in rows if self._position_of[row[0]] in eligible
        ]
        return {position: rank for rank, position in enumerate(matched, start=1)}


def load_index(
    embedder: Embedder, db_path: Path = INDEX_PATH, corpus_root: Path = CORPUS_DIR
) -> RunbookIndex:
    """Build if stale, then open. What the supervisor and the recall check use."""
    ensure_index(embedder, db_path, corpus_root)
    return RunbookIndex.open(embedder, db_path)
