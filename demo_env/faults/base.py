"""What every scenario builder returns, and helpers they share."""

from __future__ import annotations

import random
from dataclasses import dataclass

from demo_env.faults.render import LogWriter, sha, utc
from demo_env.models import Deploy, Incident, MetricPoint, MetricSeries, Truth


@dataclass(frozen=True)
class Built:
    incident: Incident
    truth: Truth
    writer: LogWriter
    metrics: dict[str, MetricSeries]
    deploys: list[Deploy]


def make_deploy(
    rng: random.Random,
    *,
    deploy_id: str,
    service: str,
    ts: str,
    author: str,
    summary: str,
    diff: str,
) -> Deploy:
    return Deploy(
        deploy_id=deploy_id,
        service=service,
        ts=utc(ts),
        commit=sha(rng)[:7],
        author=author,
        summary=summary,
        diff=diff,
    )


def capped(points: list[MetricPoint], high: float) -> list[MetricPoint]:
    """A generated series that cannot pass a ceiling, such as a disk at 100%."""
    return [MetricPoint(ts=point.ts, value=min(point.value, high)) for point in points]
