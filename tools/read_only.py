"""Read-only tools over a fixture. One registry, one entry per tool, one result shape.

Every tool returns the text the model sees and stores the same body as evidence, so a
claim's quote is always comparable to `EvidenceItem.content` without rewriting.
"""

from __future__ import annotations

import re
import statistics
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from demo_env.load import LoadedIncident
from demo_env.models import MetricName
from tools.evidence import EvidenceItem, EvidenceKind, EvidenceStore


class ToolError(Exception):
    """Recoverable: the model is told what was wrong and may call again."""


@dataclass(frozen=True)
class ToolSession:
    run_id: str
    incident: LoadedIncident
    evidence: EvidenceStore

    def require_service(self, service: str) -> str:
        known = self.incident.services
        if service not in known:
            raise ToolError(f"unknown service {service!r}; known services: {', '.join(known)}")
        return service


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    args_model: type[BaseModel]
    run: Callable[[ToolSession, Any], EvidenceItem]

    def parameters(self) -> dict[str, Any]:
        schema = self.args_model.model_json_schema()
        schema.pop("title", None)
        return schema

    def invoke(self, session: ToolSession, raw: str) -> str:
        try:
            args = self.args_model.model_validate_json(raw or "{}")
        except ValidationError as error:
            raise ToolError(f"invalid arguments for {self.name}: {error}") from error
        item = self.run(session, args)
        return render_result(item)


def render_result(item: EvidenceItem) -> str:
    return f"[{item.id}] {item.source}\n<untrusted_{item.kind.value}>\n{item.content}\n</untrusted_{item.kind.value}>"


class QueryLogsArgs(BaseModel):
    service: str
    start: datetime
    end: datetime
    pattern: str | None = Field(default=None, description="regex or literal text to keep")
    limit: int = Field(default=50, ge=1, le=200)


def _query_logs(session: ToolSession, args: QueryLogsArgs) -> EvidenceItem:
    service = session.require_service(args.service)
    if args.end <= args.start:
        raise ToolError("end must be after start")
    matcher = _matcher(args.pattern)
    matches = [
        record
        for record in session.incident.logs(service)
        if args.start <= record.entry.ts <= args.end
        and (matcher is None or matcher.search(record.entry.msg) is not None)
    ]
    source = f"logs/{service}.jsonl"
    if not matches:
        return session.evidence.add(
            EvidenceKind.log,
            source,
            f"no log lines for {service} between {args.start.isoformat()} and {args.end.isoformat()}"
            + (f" matching {args.pattern!r}" if args.pattern else ""),
            args.model_dump_json(),
        )
    kept = matches[-args.limit :]
    source = f"{source}:{kept[0].line}-{kept[-1].line}"
    body = "\n".join(
        f"{record.entry.ts.isoformat()} {record.entry.level} {record.entry.msg}" for record in kept
    )
    if len(matches) > len(kept):
        body += f"\n({len(matches) - len(kept)} older matching lines omitted; showing newest {len(kept)})"
    return session.evidence.add(EvidenceKind.log, source, body, args.model_dump_json())


def _matcher(pattern: str | None) -> re.Pattern[str] | None:
    if not pattern:
        return None
    try:
        return re.compile(pattern, re.IGNORECASE)
    except re.error:
        return re.compile(re.escape(pattern), re.IGNORECASE)


class QueryMetricsArgs(BaseModel):
    service: str
    metric: MetricName
    start: datetime
    end: datetime
    step: int = Field(default=60, ge=15, le=600, description="aggregation window in seconds")


def _query_metrics(session: ToolSession, args: QueryMetricsArgs) -> EvidenceItem:
    service = session.require_service(args.service)
    series = session.incident.metrics(service)
    source = f"metrics/{service}.json#{args.metric.value}"
    if series is None or args.metric not in series.series:
        available = session.incident.metric_names(service)
        return session.evidence.add(
            EvidenceKind.metric,
            source,
            f"no {args.metric.value} samples for {service}; available metrics: "
            + (", ".join(name.value for name in available) if available else "none"),
            args.model_dump_json(),
        )
    points = [point for point in series.series[args.metric] if args.start <= point.ts <= args.end]
    if not points:
        return session.evidence.add(
            EvidenceKind.metric,
            source,
            f"no {args.metric.value} samples for {service} in the requested window",
            args.model_dump_json(),
        )
    values = [point.value for point in points]
    mean = statistics.fmean(values)
    spread = statistics.pstdev(values) or 0.0
    spikes = [
        f"{point.ts.strftime('%H:%M')}={point.value}"
        for point in points
        if spread and point.value > mean + 3 * spread
    ][:5]
    lines = [
        f"{args.metric.value} on {service}, {len(points)} samples from "
        f"{points[0].ts.isoformat()} to {points[-1].ts.isoformat()}",
        f"min={min(values)} max={max(values)} mean={round(mean, 2)} "
        f"first={values[0]} last={values[-1]}",
        f"trend={_trend(points)}",
        f"spikes={', '.join(spikes) if spikes else 'none above mean+3sd'}",
        f"series={_downsample(points, args.step)}",
    ]
    return session.evidence.add(
        EvidenceKind.metric, source, "\n".join(lines), args.model_dump_json()
    )


def _trend(points: list[Any]) -> str:
    first, last = points[0].value, points[-1].value
    change = last - first
    if abs(change) <= max(abs(first) * 0.1, 1e-9):
        return "flat"
    direction = "rising" if change > 0 else "falling"
    return f"{direction} {round(first, 2)} -> {round(last, 2)}"


def _downsample(points: list[Any], step_seconds: int) -> str:
    buckets: dict[datetime, list[float]] = {}
    for point in points:
        bucket = point.ts.replace(second=0, microsecond=0) - timedelta(
            seconds=point.ts.second % step_seconds
        )
        buckets.setdefault(bucket, []).append(point.value)
    return " ".join(
        f"{bucket.strftime('%H:%M')}:{round(statistics.fmean(values), 1)}"
        for bucket, values in sorted(buckets.items())
    )


class ListDeploysArgs(BaseModel):
    service: str | None = None
    hours: int = Field(default=24, ge=1, le=720, description="look back this far from the alert")


def _list_recent_deploys(session: ToolSession, args: ListDeploysArgs) -> EvidenceItem:
    if args.service is not None:
        session.require_service(args.service)
    since = session.incident.incident.alert.time - timedelta(hours=args.hours)
    deploys = [
        deploy
        for deploy in session.incident.deploys
        if deploy.ts >= since and (args.service is None or deploy.service == args.service)
    ]
    scope = f" for {args.service}" if args.service else ""
    if not deploys:
        return session.evidence.add(
            EvidenceKind.deploy,
            "deploys.json",
            f"no deploys{scope} in the {args.hours}h before the alert "
            f"(window starts {since.isoformat()})",
            args.model_dump_json(),
        )
    body = "\n".join(
        f"{deploy.deploy_id} {deploy.ts.isoformat()} {deploy.service} {deploy.author} "
        f'"{deploy.summary}"'
        for deploy in sorted(deploys, key=lambda deploy: deploy.ts, reverse=True)
    )
    return session.evidence.add(EvidenceKind.deploy, "deploys.json", body, args.model_dump_json())


class DeployDiffArgs(BaseModel):
    deploy_id: str


def _get_deploy_diff(session: ToolSession, args: DeployDiffArgs) -> EvidenceItem:
    deploy = session.incident.deploy(args.deploy_id)
    if deploy is None:
        known = ", ".join(item.deploy_id for item in session.incident.deploys) or "none"
        raise ToolError(f"unknown deploy {args.deploy_id!r}; known deploys: {known}")
    body = f"{deploy.deploy_id} {deploy.service} {deploy.ts.isoformat()} {deploy.summary}\n{deploy.diff}"
    return session.evidence.add(EvidenceKind.deploy, "deploys.json", body, args.model_dump_json())


TOOLS: dict[str, ToolSpec] = {
    spec.name: spec
    for spec in (
        ToolSpec(
            name="query_logs",
            description=(
                "Search one service's logs in a time window. `pattern` is a regex or literal "
                "substring. Returns the newest matching lines as one evidence item."
            ),
            args_model=QueryLogsArgs,
            run=_query_logs,
        ),
        ToolSpec(
            name="query_metrics",
            description=(
                "Summarise one metric for one service: min, max, mean, trend, spikes and a "
                f"downsampled series. Metrics: {', '.join(name.value for name in MetricName)}."
            ),
            args_model=QueryMetricsArgs,
            run=_query_metrics,
        ),
        ToolSpec(
            name="list_recent_deploys",
            description="List deploys in the hours before the alert, newest first, without diffs.",
            args_model=ListDeploysArgs,
            run=_list_recent_deploys,
        ),
        ToolSpec(
            name="get_deploy_diff",
            description="Fetch one deploy's code diff by deploy id.",
            args_model=DeployDiffArgs,
            run=_get_deploy_diff,
        ),
    )
}


def tool_schemas(names: list[str]) -> list[dict[str, Any]]:
    """Model-facing declarations for the allowlisted tools, in a stable order."""
    return [
        {
            "name": name,
            "description": TOOLS[name].description,
            "parameters": TOOLS[name].parameters(),
        }
        for name in names
    ]


def invoke_tool(session: ToolSession, name: str, raw_args: str) -> str:
    spec = TOOLS.get(name)
    if spec is None:
        raise ToolError(f"unknown tool {name!r}; available: {', '.join(TOOLS)}")
    return spec.invoke(session, raw_args)
