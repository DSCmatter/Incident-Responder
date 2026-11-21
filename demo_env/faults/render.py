"""Deterministic renderers shared by every scenario builder.

One timeline, one set of curve shapes, one writer. A scenario says what happens;
this module decides what a log line and a metric sample look like.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from demo_env.models import (
    Alert,
    Deploy,
    DeployList,
    Incident,
    IncidentFiles,
    LogLevel,
    LogLine,
    MetricName,
    MetricPoint,
    MetricSeries,
    Truth,
)

Curve = str  # "flat" | "ramp" | "step" | "spike" | "sawtooth"


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text).replace(tzinfo=UTC)


def stamp(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass(frozen=True)
class Timeline:
    """Metrics cover `points` samples ending just after the alert."""

    start: datetime
    step_seconds: int
    points: int
    alert_at: datetime

    @property
    def end(self) -> datetime:
        return self.start + timedelta(seconds=self.step_seconds * (self.points - 1))

    def samples(self) -> list[datetime]:
        return [self.start + timedelta(seconds=self.step_seconds * i) for i in range(self.points)]

    def at(self, minutes_from_start: float) -> datetime:
        return self.start + timedelta(minutes=minutes_from_start)


def curve(
    timeline: Timeline,
    shape: Curve,
    *,
    base: float,
    noise: float,
    rng: random.Random,
    onset_minutes: float | None = None,
    peak: float | None = None,
    spike_every: int | None = None,
    decimals: int = 1,
) -> list[MetricPoint]:
    """A metric series. `onset_minutes` is when the fault starts, measured from the timeline start."""
    onset = timeline.at(onset_minutes) if onset_minutes is not None else None
    top = peak if peak is not None else base * 2
    points: list[MetricPoint] = []
    for index, moment in enumerate(timeline.samples()):
        value = base + rng.gauss(0, noise)
        if shape != "flat" and onset is not None:
            progress = _progress(moment, timeline, onset)
            if progress > 0:
                faulted = _shape_value(shape, progress, base, top)
                if shape == "sawtooth" and spike_every and index % spike_every == 0:
                    faulted = top
                value = faulted + rng.gauss(0, noise)
        points.append(MetricPoint(ts=moment, value=round(value, decimals)))
    return points


def _progress(moment: datetime, timeline: Timeline, onset: datetime) -> float:
    if moment < onset:
        return 0.0
    span = max((timeline.end - onset).total_seconds(), 1.0)
    return min((moment - onset).total_seconds() / span, 1.0)


def _shape_value(shape: Curve, progress: float, base: float, peak: float) -> float:
    if shape == "ramp":
        return base + (peak - base) * progress
    if shape == "step":
        return peak if progress > 0 else base
    if shape == "spike":
        return peak if 0.1 < progress < 0.55 else base
    if shape == "sawtooth":
        return base + ((peak - base) * (progress % 0.25) / 0.25)
    return base


@dataclass
class LogWriter:
    """Collects lines, sorts them, and writes one JSONL file per service."""

    rng: random.Random
    lines: dict[str, list[LogLine]] = field(default_factory=dict)

    def add(self, service: str, ts: datetime, level: LogLevel, msg: str) -> None:
        self.lines.setdefault(service, []).append(
            LogLine(ts=ts.replace(microsecond=0), level=level, msg=msg)
        )

    def dump(self, files: IncidentFiles) -> None:
        for service, entries in self.lines.items():
            entries.sort(key=lambda entry: entry.ts)
            path = files.logs(service)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                "\n".join(entry.model_dump_json() for entry in entries) + "\n", encoding="utf-8"
            )


class Traffic:
    """Background request logging at a steady rate, with a per-service error budget."""

    def __init__(
        self, writer: LogWriter, service: str, rate_per_minute: float, paths: list[str]
    ) -> None:
        self.writer = writer
        self.service = service
        self.rate = rate_per_minute
        self.paths = paths

    def routine(self, timeline: Timeline, minutes: float = 0, until: float | None = None) -> None:
        end = until if until is not None else (timeline.end - timeline.start).total_seconds() / 60
        moment = minutes
        while moment <= end:
            ts = timeline.at(moment) + timedelta(seconds=self.writer.rng.randint(0, 59))
            self.writer.add(self.service, ts, "info", self._request_line())
            moment += 1.0 / self.rate

    def _request_line(self) -> str:
        rng = self.writer.rng
        path = rng.choice(self.paths)
        status = 200 if rng.random() > 0.02 else rng.choice([200, 200, 304])
        latency = rng.randint(18, 140)
        return (
            f"method=GET path={path} status={status} dur_ms={latency} "
            f"trace={rng.getrandbits(48):012x}"
        )


def write_incident(
    files: IncidentFiles,
    *,
    incident: Incident,
    truth: Truth,
    logs: LogWriter,
    metrics: dict[str, MetricSeries],
    deploys: list[Deploy],
) -> None:
    """Write every file for one incident. Existing files are replaced, never merged."""
    files.directory.mkdir(parents=True, exist_ok=True)
    logs.dump(files)
    for service, series in metrics.items():
        path = files.metrics(service)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(series.model_dump_json(indent=2), encoding="utf-8")
    files.deploys_json.write_text(
        DeployList(deploys=deploys).model_dump_json(indent=2), encoding="utf-8"
    )
    files.incident_yaml.write_text(_yaml(incident.model_dump(mode="json")), encoding="utf-8")
    files.truth_yaml.write_text(_yaml(truth.model_dump(mode="json")), encoding="utf-8")


def _yaml(data: dict) -> str:
    import yaml

    return yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100)


def alert(service: str, at: datetime, summary: str) -> Alert:
    return Alert(time=at, service=service, summary=summary)


def sha(rng: random.Random) -> str:
    return f"{rng.getrandbits(160):040x}"


SIGNED_METRICS = frozenset({MetricName.cert_days_left})


def dumps_series(
    service: str, timeline: Timeline, series: dict[MetricName, list[MetricPoint]]
) -> MetricSeries:
    """Noise can push a near-zero series below zero; only a signed metric may go there."""
    floored = {
        name: points
        if name in SIGNED_METRICS
        else [MetricPoint(ts=p.ts, value=p.value if p.value > 0 else 0.0) for p in points]
        for name, points in series.items()
    }
    return MetricSeries(service=service, step_seconds=timeline.step_seconds, series=floored)
