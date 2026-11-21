"""`make rag-recall`: does the right runbook reach the top k for each incident of a split?

The query is what the responder knows before any tool call: the alert summary,
filtered to the alert service, with the incident's own postmortem excluded. The
answer key is `rag_corpus/relevance/<split>.yaml`, kept outside the documents so a
runbook never carries its own label.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import BaseModel, RootModel

from config import REPO_ROOT, load_settings
from demo_env.load import LoadedIncident, load_split
from rag.corpus import CORPUS_DIR, DocKind, corpus_hash, load_chunks
from rag.embed import SentenceTransformerEmbedder
from rag.index import RunbookIndex, load_index

RESULTS_DIR = REPO_ROOT / "evals" / "results"


class Relevance(RootModel[dict[str, list[str]]]):
    """Incident id to the runbook ids a correct retrieval returns."""


class RankedDoc(BaseModel):
    doc_id: str
    source: str
    score: float
    bm25_rank: int | None
    dense_rank: int


class IncidentRecall(BaseModel):
    incident: str
    service: str
    query: str
    excluded: list[str]
    relevant: list[str]
    first_relevant_rank: int | None
    top: list[RankedDoc]

    @property
    def hit(self) -> bool:
        return self.first_relevant_rank is not None


def load_relevance(split: str, corpus_root: Path = CORPUS_DIR) -> Relevance:
    path = corpus_root / "relevance" / f"{split}.yaml"
    relevance = Relevance.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    runbooks = {
        chunk.doc_id for chunk in load_chunks(corpus_root) if chunk.doc_kind is DocKind.runbook
    }
    unknown = sorted({doc for docs in relevance.root.values() for doc in docs} - runbooks)
    if unknown:
        raise ValueError(f"{path}: not runbook ids in the corpus: {unknown}")
    return relevance


def check_recall(
    index: RunbookIndex, incidents: list[LoadedIncident], relevance: Relevance, k: int
) -> list[IncidentRecall]:
    missing = [
        loaded.incident.id for loaded in incidents if loaded.incident.id not in relevance.root
    ]
    if missing:
        raise ValueError(f"relevance has no entry for: {', '.join(missing)}")
    rows = []
    for loaded in incidents:
        incident = loaded.incident
        excluded = [incident.postmortem_id] if incident.postmortem_id else []
        hits = index.search(
            incident.alert.summary, service=incident.alert.service, k=k, exclude=frozenset(excluded)
        )
        relevant = relevance.root[incident.id]
        rank = next(
            (position for position, hit in enumerate(hits, start=1) if hit.doc_id in relevant),
            None,
        )
        rows.append(
            IncidentRecall(
                incident=incident.id,
                service=incident.alert.service,
                query=incident.alert.summary,
                excluded=excluded,
                relevant=relevant,
                first_relevant_rank=rank,
                top=[
                    RankedDoc(
                        doc_id=hit.doc_id,
                        source=hit.source,
                        score=round(hit.score, 4),
                        bm25_rank=hit.bm25_rank,
                        dense_rank=hit.dense_rank,
                    )
                    for hit in hits
                ],
            )
        )
    return rows


def main(split: str = "dev") -> int:
    settings = load_settings()
    embedder = SentenceTransformerEmbedder(settings.rag.embedding)
    index = load_index(embedder)
    k = settings.rag.k
    rows = check_recall(index, load_split(split), load_relevance(split), k)
    index.close()
    hits = sum(row.hit for row in rows)
    for row in rows:
        top = ", ".join(doc.doc_id for doc in row.top)
        print(
            f"{row.incident:<4} {'hit ' if row.hit else 'MISS'} "
            f"rank={row.first_relevant_rank or '-'} {row.service}: {row.query!r} -> {top}"
        )
    print(
        f"recall@{k}: {hits}/{len(rows)} {split} incidents have a relevant runbook in the top {k}"
    )
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(UTC)
    path = RESULTS_DIR / f"rag-recall-{split}-{generated_at.strftime('%Y%m%dT%H%M%SZ')}.json"
    payload = {
        "meta": {
            "generated_at": generated_at.isoformat(),
            "split": split,
            "k": k,
            "embedder": embedder.name,
            "corpus_hash": corpus_hash(),
            "hits": hits,
            "incidents": len(rows),
        },
        "rows": [row.model_dump() | {"hit": row.hit} for row in rows],
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {path.relative_to(REPO_ROOT).as_posix()}")
    return 0
