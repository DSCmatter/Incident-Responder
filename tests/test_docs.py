"""Every relative markdown link in the repo must resolve to a real file.

A doc link that 404s is invisible until a reader hits it, and the README is the
ten-minute path into the project.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")


def _markdown_files() -> list[Path]:
    return [
        path
        for path in ROOT.rglob("*.md")
        if ".venv" not in path.parts and "node_modules" not in path.parts
    ]


@pytest.mark.parametrize("doc", _markdown_files(), ids=lambda p: p.relative_to(ROOT).as_posix())
def test_relative_links_resolve(doc: Path) -> None:
    broken = []
    for target in LINK.findall(doc.read_text(encoding="utf-8")):
        if "://" in target or target.startswith("#") or target.startswith("mailto:"):
            continue
        path_part = target.split("#", 1)[0]
        if not (doc.parent / path_part).exists():
            broken.append(target)
    assert not broken, f"{doc.relative_to(ROOT)} has broken links: {broken}"
