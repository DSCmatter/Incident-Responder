"""Read fixtures from disk. The only module that parses the fixture format."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from demo_env.models import (
    Deploy,
    DeployList,
    Incident,
    IncidentFiles,
    LogLine,
    MetricName,
    MetricSeries,
    Truth,
)

INCIDENTS_DIR = Path(__file__).resolve().parents[1] / "evals" / "incidents"


@dataclass(frozen=True)
class LogRecord:
    line: int
    entry: LogLine


@dataclass(frozen=True)
class LoadedIncident:
    incident: Incident
    truth: Truth
    files: IncidentFiles
    deploys: list[Deploy]

    @property
    def services(self) -> list[str]:
        """The service map handed to triage and used to validate tool arguments."""
        return self.files.services()

    def logs(self, service: str) -> list[LogRecord]:
        path = self.files.logs(service)
        if not path.is_file():
            return []
        records = []
        for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if raw.strip():
                records.append(LogRecord(line=number, entry=LogLine.model_validate_json(raw)))
        return records

    def metrics(self, service: str) -> MetricSeries | None:
        path = self.files.metrics(service)
        return (
            MetricSeries.model_validate_json(path.read_text(encoding="utf-8"))
            if path.is_file()
            else None
        )

    def metric_names(self, service: str) -> list[MetricName]:
        series = self.metrics(service)
        return sorted(series.series) if series else []

    def deploy(self, deploy_id: str) -> Deploy | None:
        return next((deploy for deploy in self.deploys if deploy.deploy_id == deploy_id), None)


def load_incident(directory: Path) -> LoadedIncident:
    files = IncidentFiles(directory)
    incident = Incident.model_validate(
        yaml.safe_load(files.incident_yaml.read_text(encoding="utf-8"))
    )
    truth = Truth.model_validate(yaml.safe_load(files.truth_yaml.read_text(encoding="utf-8")))
    deploys = DeployList.model_validate_json(files.deploys_json.read_text(encoding="utf-8")).deploys
    if incident.id != directory.name.split("_", 1)[0]:
        raise ValueError(
            f"{directory.name}: incident id {incident.id!r} does not match its directory"
        )
    if truth.service not in files.services():
        raise ValueError(f"{directory.name}: truth service {truth.service!r} has no log file")
    return LoadedIncident(incident=incident, truth=truth, files=files, deploys=deploys)


def load_split(split: str, root: Path = INCIDENTS_DIR) -> list[LoadedIncident]:
    incidents = [load_incident(path) for path in sorted(root.iterdir()) if path.is_dir()]
    if split == "all":
        return incidents
    return [loaded for loaded in incidents if loaded.incident.split == split]
