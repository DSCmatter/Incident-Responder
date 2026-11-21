"""Aggregation across repeats, per docs/SCENARIOS.md section 5.

An incident's repeat spread is its own max minus min; the aggregate reports the
mean of those per-incident spreads, so one noisy incident stays visible.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from statistics import fmean

from pydantic import BaseModel

from evals.scoring import IncidentScore


class Aggregate(BaseModel):
    incidents: int
    repeats: int
    root_cause_mean: float
    root_cause_spread: float
    fix_mean: float
    citations_mean: float
    recall_mean: float
    unsafe_total: int
    llm_calls_mean: float
    cost_mean: float
    duration_ms_mean: float


def _mean(values: Iterable[float]) -> float:
    materialised = list(values)
    return fmean(materialised) if materialised else 0.0


def _incident_mean(
    groups: dict[str, list[IncidentScore]], value: Callable[[IncidentScore], float]
) -> float:
    return _mean(_mean(value(row) for row in rows) for rows in groups.values())


def aggregate(rows: Sequence[IncidentScore], repeats: int) -> Aggregate:
    groups: dict[str, list[IncidentScore]] = defaultdict(list)
    for row in rows:
        groups[row.incident_id].append(row)
    spreads = [
        max(row.root_cause for row in group) - min(row.root_cause for row in group)
        for group in groups.values()
    ]
    return Aggregate(
        incidents=len(groups),
        repeats=repeats,
        root_cause_mean=_incident_mean(groups, lambda row: row.root_cause),
        root_cause_spread=_mean(spreads),
        fix_mean=_incident_mean(groups, lambda row: row.fix),
        citations_mean=_incident_mean(groups, lambda row: row.citations),
        recall_mean=_incident_mean(groups, lambda row: row.recall),
        unsafe_total=sum(row.unsafe for row in rows),
        llm_calls_mean=_incident_mean(groups, lambda row: row.llm_calls),
        cost_mean=_incident_mean(groups, lambda row: row.cost_usd_equiv),
        duration_ms_mean=_incident_mean(groups, lambda row: row.duration_ms),
    )
