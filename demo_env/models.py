"""The fixture domain: what an incident is, and what its evidence looks like on disk.

Ground truth is data, not code. This module is the single definition of the file
format that the generator writes, the tools read, and the scorer compares against.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agents.schemas import FixClass, RootCause, Severity


class Fixture(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


LogLevel = Literal["debug", "info", "warn", "error"]


class IncidentFlag(StrEnum):
    """Hard-case behaviours. Scenarios, the scorer and the guard branch on these."""

    red_herring = "red_herring"  # a harmless deploy precedes the real fault
    missing_logs = "missing_logs"  # the decisive evidence is metrics, not logs
    injection = "injection"  # a log line contains instructions
    multi_fault = "multi_fault"  # a minor fault hides the primary one
    ambiguous = "ambiguous"  # evidence fits two causes equally
    stale_runbook = "stale_runbook"  # the matching runbook advises the wrong fix


class MetricName(StrEnum):
    """The metric vocabulary. A tool that is asked for anything else is refused."""

    cpu_pct = "cpu_pct"
    mem_mb = "mem_mb"
    req_rate = "req_rate"
    error_rate = "error_rate"
    latency_p95_ms = "latency_p95_ms"
    db_latency_ms = "db_latency_ms"
    disk_used_pct = "disk_used_pct"
    cert_days_left = "cert_days_left"


class Alert(Fixture):
    time: datetime
    service: str
    summary: str


class Incident(Fixture):
    id: str
    title: str
    split: Literal["dev", "heldout"]
    difficulty: Literal["easy", "medium", "hard"]
    flags: list[IncidentFlag] = Field(default_factory=list)
    postmortem_id: str | None = None
    alert: Alert
    seed: int


class MustFind(Fixture):
    file: str
    pattern: str


class Truth(Fixture):
    root_cause: RootCause
    service: str
    summary: str
    acceptable_fixes: list[FixClass]
    must_find: list[MustFind]
    escalation_ok: bool


class LogLine(Fixture):
    """One line in `logs/<service>.jsonl`. The filename owns the service name."""

    ts: datetime
    level: LogLevel
    msg: str


class MetricPoint(Fixture):
    ts: datetime
    value: float


class MetricSeries(Fixture):
    """One `metrics/<service>.json` file."""

    service: str
    step_seconds: int
    series: dict[MetricName, list[MetricPoint]]


class Deploy(Fixture):
    """Full record, including the diff that only `get_deploy_diff` returns."""

    deploy_id: str
    service: str
    ts: datetime
    commit: str
    author: str
    summary: str
    diff: str


class DeployList(Fixture):
    deploys: list[Deploy]


class IncidentFiles:
    """Paths for one incident directory, so nothing else rebuilds them by hand."""

    def __init__(self, directory: Path) -> None:
        self.directory = directory

    @property
    def incident_yaml(self) -> Path:
        return self.directory / "incident.yaml"

    @property
    def truth_yaml(self) -> Path:
        return self.directory / "truth.yaml"

    @property
    def deploys_json(self) -> Path:
        return self.directory / "deploys.json"

    def logs(self, service: str) -> Path:
        return self.directory / "logs" / f"{service}.jsonl"

    def metrics(self, service: str) -> Path:
        return self.directory / "metrics" / f"{service}.json"

    def services(self) -> list[str]:
        log_dir = self.directory / "logs"
        return sorted(path.stem for path in log_dir.glob("*.jsonl")) if log_dir.is_dir() else []


def severity_at_least(value: Severity, floor: Severity) -> bool:
    """sev1 is the most severe, so ordering is inverted against the name."""
    rank = {Severity.sev3: 0, Severity.sev2: 1, Severity.sev1: 2}
    return rank[value] >= rank[floor]
