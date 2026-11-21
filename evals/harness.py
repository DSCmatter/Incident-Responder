"""`make eval SPLIT=...`: load incidents, score one run of each, print and save the table."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

from agents.report import RunReport
from agents.supervisor import Supervisor
from demo_env.load import LoadedIncident, load_split
from evals.aggregate import Aggregate, aggregate
from evals.scoring import IncidentScore, score_report
from evals.stub_agent import StubRunner

RESULTS_DIR = Path(__file__).resolve().parent / "results"

HEADERS = ("incident", "state", "root", "fix", "cite", "recall", "unsafe", "calls", "cost")


class Runner(Protocol):
    def run(self, incident: LoadedIncident) -> RunReport: ...


RUNNERS: dict[str, type[Runner]] = {"stub": StubRunner, "supervisor": Supervisor}


def _runner_for(agent: str) -> Runner:
    try:
        factory = RUNNERS[agent]
    except KeyError:
        available = ", ".join(sorted(RUNNERS))
        raise ValueError(f"unknown agent {agent!r}; available: {available}") from None
    return factory()


def _table_cells(report: RunReport, score: IncidentScore) -> tuple[str, ...]:
    return (
        score.incident_id,
        report.state.value,
        f"{score.root_cause:.2f}",
        f"{score.fix:.2f}",
        f"{score.citations:.2f}",
        f"{score.recall:.2f}",
        str(score.unsafe),
        str(score.llm_calls),
        f"{score.cost_usd_equiv:.6f}",
    )


def _print_table(scored: list[tuple[RunReport, IncidentScore]], summary: Aggregate) -> None:
    rows = [HEADERS, *(_table_cells(report, score) for report, score in scored)]
    widths = [max(len(row[column]) for row in rows) for column in range(len(HEADERS))]
    for row in rows:
        cells = (cell.ljust(width) for cell, width in zip(row, widths, strict=True))
        print("  ".join(cells).rstrip())
    print(
        f"aggregate: incidents={summary.incidents} repeats={summary.repeats} "
        f"root={summary.root_cause_mean:.2f}+-{summary.root_cause_spread:.2f} "
        f"fix={summary.fix_mean:.2f} cite={summary.citations_mean:.2f} "
        f"recall={summary.recall_mean:.2f} unsafe={summary.unsafe_total} "
        f"calls={summary.llm_calls_mean:.2f} cost={summary.cost_mean:.6f} "
        f"duration_ms={summary.duration_ms_mean:.1f}"
    )


def _write_results(
    out_dir: Path,
    split: str,
    agent: str,
    repeats: int,
    rows: list[IncidentScore],
    summary: Aggregate,
) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(UTC)
    path = out_dir / f"{generated_at.strftime('%Y%m%dT%H%M%SZ')}-{split}-{agent}.json"
    payload = {
        "meta": {
            "split": split,
            "repeats": repeats,
            "agent": agent,
            "generated_at": generated_at.isoformat(),
        },
        "rows": [row.model_dump(mode="json") for row in rows],
        "aggregate": summary.model_dump(mode="json"),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {path}")
    return path


def main(
    split: str = "dev", repeats: int = 1, agent: str = "stub", out_dir: Path | None = None
) -> int:
    runner = _runner_for(agent)
    incidents = load_split(split)
    scored: list[tuple[RunReport, IncidentScore]] = []
    for _ in range(repeats):
        for incident in incidents:
            report = runner.run(incident)
            scored.append((report, score_report(report, incident.truth)))
    rows = [score for _, score in scored]
    summary = aggregate(rows, repeats)
    _print_table(scored, summary)
    _write_results(out_dir or RESULTS_DIR, split, agent, repeats, rows, summary)
    return 1 if any(row.unsafe for row in rows) else 0
