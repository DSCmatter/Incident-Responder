"""The corpus format: one markdown file per runbook or postmortem, YAML front matter on top.

This module is the only parser of `rag_corpus/`. A document becomes one chunk per
`## ` section, and every chunk starts with the document title so a section read on
its own still says what it belongs to. Front matter is metadata and never enters
chunk text.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field

from agents.schemas import RootCause
from config import REPO_ROOT

CORPUS_DIR = REPO_ROOT / "rag_corpus"

# Bump when chunking or index layout changes, so an index built by older code rebuilds.
FORMAT_VERSION = "1"


class DocKind(StrEnum):
    runbook = "runbook"
    postmortem = "postmortem"


DOC_DIRS: dict[DocKind, str] = {DocKind.runbook: "runbooks", DocKind.postmortem: "postmortems"}


class _Meta(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    title: str = Field(min_length=1)
    services: list[str] = Field(default_factory=list)


class RunbookMeta(_Meta):
    """`services: []` means the runbook applies to any service."""

    id: str = Field(pattern=r"^rb-[a-z0-9-]+$")
    root_causes: list[RootCause] = Field(min_length=1)


class PostmortemMeta(_Meta):
    """`id` equals the `postmortem_id` of the incident it describes."""

    id: str = Field(pattern=r"^pm-[a-z0-9-]+$")
    incident: str
    root_cause: RootCause
    services: list[str] = Field(min_length=1)


@dataclass(frozen=True, slots=True)
class Chunk:
    doc_id: str
    doc_kind: DocKind
    source: str  # <kind dir>/<file>#<section anchor>
    services: tuple[str, ...]
    text: str


class CorpusError(ValueError):
    pass


def load_chunks(root: Path = CORPUS_DIR) -> list[Chunk]:
    chunks: list[Chunk] = []
    seen: dict[str, Path] = {}
    for kind, path in _documents(root):
        meta, body = _split_front_matter(path)
        parsed = (RunbookMeta if kind is DocKind.runbook else PostmortemMeta).model_validate(meta)
        expected = f"rb-{path.stem}" if kind is DocKind.runbook else path.stem
        if parsed.id != expected:
            raise CorpusError(f"{path}: id {parsed.id!r} must be {expected!r}")
        if parsed.id in seen:
            raise CorpusError(f"{path}: duplicate id {parsed.id!r} (also in {seen[parsed.id]})")
        seen[parsed.id] = path
        relative = f"{DOC_DIRS[kind]}/{path.name}"
        for heading, text in _sections(path, body):
            chunks.append(
                Chunk(
                    doc_id=parsed.id,
                    doc_kind=kind,
                    source=f"{relative}#{_anchor(heading)}",
                    services=tuple(parsed.services),
                    text=f"{parsed.title}\n{heading}\n{text}",
                )
            )
    return chunks


def corpus_hash(root: Path = CORPUS_DIR) -> str:
    """Content hash of every indexed file plus the format version; order-independent."""
    digest = hashlib.sha256(FORMAT_VERSION.encode())
    for kind, path in _documents(root):
        digest.update(f"{DOC_DIRS[kind]}/{path.name}\0".encode())
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _documents(root: Path) -> list[tuple[DocKind, Path]]:
    return [
        (kind, path)
        for kind, directory in DOC_DIRS.items()
        for path in sorted((root / directory).glob("*.md"))
    ]


def _split_front_matter(path: Path) -> tuple[dict[str, object], str]:
    text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
    if not text.startswith("---\n"):
        raise CorpusError(f"{path}: must start with a '---' front matter line")
    header, separator, body = text[4:].partition("\n---\n")
    if not separator:
        raise CorpusError(f"{path}: front matter has no closing '---' line")
    meta = yaml.safe_load(header)
    if not isinstance(meta, dict):
        raise CorpusError(f"{path}: front matter must be a mapping")
    return meta, body


def _sections(path: Path, body: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, list[str]]] = []
    for line in body.split("\n"):
        if line.startswith("## "):
            sections.append((line[3:].strip(), []))
        elif sections:
            sections[-1][1].append(line)
        elif line.strip() and not line.startswith("# "):
            raise CorpusError(f"{path}: text before the first '## ' section would not be indexed")
    if not sections:
        raise CorpusError(f"{path}: no '## ' sections")
    result = []
    for heading, lines in sections:
        text = "\n".join(lines).strip()
        if not text:
            raise CorpusError(f"{path}: section {heading!r} is empty")
        result.append((heading, text))
    return result


def _anchor(heading: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", heading.lower()).strip("-")
