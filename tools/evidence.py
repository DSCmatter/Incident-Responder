"""Per-run evidence store: the only place evidence ids are minted.

An agent may cite a claim with an id only if it exists here, which is what makes
the verifier's first check a lookup rather than a judgement call.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict


class EvidenceKind(StrEnum):
    log = "log"
    metric = "metric"
    deploy = "deploy"
    runbook = "runbook"


class EvidenceItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    kind: EvidenceKind
    source: str
    content: str
    query: str


class EvidenceStore:
    """Append-only, one per run. Ids are `ev_<kind>_<n>` with a per-kind counter."""

    def __init__(self) -> None:
        self._items: list[EvidenceItem] = []
        self._by_id: dict[str, EvidenceItem] = {}
        self._counters: dict[EvidenceKind, int] = {}

    def add(self, kind: EvidenceKind, source: str, content: str, query: str) -> EvidenceItem:
        n = self._counters.get(kind, 0) + 1
        self._counters[kind] = n
        item = EvidenceItem(
            id=f"ev_{kind.value}_{n}", kind=kind, source=source, content=content, query=query
        )
        self._items.append(item)
        self._by_id[item.id] = item
        return item

    def get(self, evidence_id: str) -> EvidenceItem | None:
        return self._by_id.get(evidence_id)

    def has(self, evidence_id: str) -> bool:
        return evidence_id in self._by_id

    def ids(self) -> list[str]:
        return [item.id for item in self._items]

    def items(self) -> list[EvidenceItem]:
        return list(self._items)

    def __len__(self) -> int:
        return len(self._items)

    def render(self, ids: list[str]) -> str:
        """The evidence text a verifier or critic sees, wrapped as untrusted data."""
        blocks = []
        for evidence_id in ids:
            item = self._by_id.get(evidence_id)
            if item is None:
                blocks.append(f"[{evidence_id}] (not in store)")
                continue
            blocks.append(f"[{item.id}] source={item.source}\n{item.content}")
        return "<untrusted_evidence>\n" + "\n\n".join(blocks) + "\n</untrusted_evidence>"
