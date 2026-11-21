"""Prompts live in agents/prompts/<name>.md; the first line carries the version."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PROMPTS_DIR = Path(__file__).parent / "prompts"


@dataclass(frozen=True, slots=True)
class Prompt:
    version: str
    text: str


def load_prompt(name: str) -> Prompt:
    header, _, body = (PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8").partition("\n")
    key, _, version = header.partition(":")
    if key.strip() != "version" or not version.strip():
        raise ValueError(f"prompts/{name}.md must start with 'version: <id>'")
    return Prompt(version=version.strip(), text=body.strip())
