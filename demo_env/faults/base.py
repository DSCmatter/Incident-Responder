"""What every scenario builder returns, and helpers they share."""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from demo_env.faults.render import Curve, LogWriter, Timeline, curve, sha, utc
from demo_env.models import Deploy, Incident, LogLevel, MetricPoint, MetricSeries, Truth


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


@dataclass(frozen=True)
class Curves:
    """Metric series on one timeline and one rng, so a builder names only the shape."""

    timeline: Timeline
    rng: random.Random

    def flat(self, base: float, noise: float, *, decimals: int = 1) -> list[MetricPoint]:
        return curve(self.timeline, "flat", base=base, noise=noise, rng=self.rng, decimals=decimals)

    def shaped(
        self,
        shape: Curve,
        base: float,
        noise: float,
        *,
        onset: float,
        peak: float,
        decimals: int = 1,
    ) -> list[MetricPoint]:
        return curve(
            self.timeline,
            shape,
            base=base,
            noise=noise,
            rng=self.rng,
            onset_minutes=onset,
            peak=peak,
            decimals=decimals,
        )


def repeat(
    writer: LogWriter,
    service: str,
    level: LogLevel,
    *,
    start: datetime,
    end: datetime,
    gap: tuple[int, int],
    message: Callable[[datetime], str],
) -> None:
    """One line every `gap[0]` seconds plus up to `gap[1]` seconds of jitter, from start to end."""
    moment = start
    while moment <= end:
        writer.add(service, moment, level, message(moment))
        moment += timedelta(seconds=gap[0] + writer.rng.randint(0, gap[1]))


def leak_with_restarts(
    timeline: Timeline,
    rng: random.Random,
    *,
    base: float,
    limit: float,
    noise: float,
    restarts: list[float],
) -> list[MetricPoint]:
    """Memory that climbs at one slope until each restart, then starts again from `base`.

    `restarts` are minutes from the timeline start; the first one fixes the slope.
    """
    slope = (limit - base) / restarts[0]
    points = []
    for moment in timeline.samples():
        minute = (moment - timeline.start).total_seconds() / 60
        since = max([0.0, *(at for at in restarts if at <= minute)])
        value = min(base + slope * (minute - since) + rng.gauss(0, noise), limit)
        points.append(MetricPoint(ts=moment, value=round(value, 0)))
    return points
