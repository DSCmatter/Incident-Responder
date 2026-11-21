"""Scenario builders for the dev split. Each one returns every file's content.

Rule for every builder: the evidence must let a careful human name the root cause
and the fix without the truth file, and no single log line may state the cause.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from datetime import timedelta

from agents.schemas import FixClass, RootCause
from demo_env.faults.base import Built, make_deploy
from demo_env.faults.hard_scenarios import h1_red_herring_deploy, h3_log_injection
from demo_env.faults.infra_scenarios import (
    s04_dependency_timeout,
    s05_disk_full,
    s06_config_typo,
    s07_cpu_batch_job,
    s08_expired_cert,
)
from demo_env.faults.render import (
    LogWriter,
    Timeline,
    Traffic,
    alert,
    curve,
    dumps_series,
    utc,
)
from demo_env.models import (
    Incident,
    MetricName,
    MustFind,
    Truth,
)


def s01_bad_deploy_env_var() -> Built:
    rng = random.Random(101)
    timeline = Timeline(
        start=utc("2026-11-12T08:00:00Z"),
        step_seconds=60,
        points=90,
        alert_at=utc("2026-11-12T09:12:00Z"),
    )
    writer = LogWriter(rng=rng)
    Traffic(writer, "checkout-api", 2.0, ["/v1/checkout", "/healthz"]).routine(timeline)
    Traffic(writer, "checkout-worker", 0.7, ["/internal/authorize"]).routine(timeline)
    Traffic(writer, "email-sender", 0.4, ["/send"]).routine(timeline)

    onset = 49.0  # minutes from timeline start
    deploy_at = timeline.at(onset)
    writer.add(
        "checkout-api", deploy_at, "info", "deployment dpl-4f21 revision 7d9f rollout complete"
    )
    writer.add(
        "checkout-api",
        deploy_at + timedelta(seconds=2),
        "warn",
        "config: PAYMENT_BASE_URL resolved to '' (fallback disabled)",
    )
    for step in range(1, 22):
        moment = deploy_at + timedelta(seconds=20 * step)
        writer.add(
            "checkout-api",
            moment,
            "error",
            f"POST /v1/checkout 502 upstream=payments dur_ms={rng.randint(2, 6)} "
            "err=dial tcp 127.0.0.1:8443: connect: connection refused",
        )
    writer.add(
        "checkout-worker",
        deploy_at + timedelta(minutes=3, seconds=11),
        "error",
        "authorize order 8f2c41 failed: payment client error",
    )
    writer.add(
        "email-sender",
        timeline.at(3),
        "warn",
        "smtp relay smtp.internal:25 timeout after 5000ms, retrying in 30s",
    )
    writer.add(
        "email-sender",
        timeline.at(3.5),
        "info",
        "smtp relay accepted 12 messages after retry",
    )

    metrics = {
        "checkout-api": dumps_series(
            "checkout-api",
            timeline,
            {
                MetricName.req_rate: curve(timeline, "flat", base=238, noise=9, rng=rng),
                MetricName.error_rate: curve(
                    timeline,
                    "step",
                    base=0.004,
                    noise=0.002,
                    rng=rng,
                    onset_minutes=onset,
                    peak=0.61,
                    decimals=3,
                ),
                MetricName.latency_p95_ms: curve(
                    timeline, "step", base=131, noise=8, rng=rng, onset_minutes=onset, peak=214
                ),
                MetricName.cpu_pct: curve(
                    timeline, "step", base=27, noise=3, rng=rng, onset_minutes=onset, peak=31
                ),
            },
        ),
        "email-sender": dumps_series(
            "email-sender",
            timeline,
            {
                MetricName.error_rate: curve(
                    timeline, "flat", base=0.02, noise=0.01, rng=rng, decimals=3
                ),
                MetricName.latency_p95_ms: curve(timeline, "flat", base=420, noise=60, rng=rng),
            },
        ),
    }

    deploy = make_deploy(
        rng,
        deploy_id="dpl-4f21",
        service="checkout-api",
        ts="2026-11-12T08:49:12Z",
        author="priya",
        summary="checkout: require payments base url from environment",
        diff=(
            "--- a/services/checkout/config.py\n"
            "+++ b/services/checkout/config.py\n"
            "@@ -18,7 +18,7 @@ class Settings:\n"
            "     retry_budget = 3\n"
            "-    payments_base_url = os.environ.get(\n"
            '-        "PAYMENTS_BASE_URL", "https://payments.internal:8443"\n'
            "-    )\n"
            '+    payments_base_url = os.environ.get("PAYMENT_BASE_URL", "")\n'
            "+    if not payments_base_url:\n"
            '+        logger.warning("PAYMENT_BASE_URL resolved to %r (fallback disabled)", payments_base_url)\n'
        ),
    )

    return Built(
        incident=Incident(
            id="S01",
            title="Checkout errors after a deploy",
            split="dev",
            difficulty="easy",
            flags=[],
            postmortem_id="pm-2026-04-checkout-outage",
            alert=alert(
                "checkout-api", timeline.alert_at, "Checkout success rate below 40% for 20 minutes"
            ),
            seed=101,
        ),
        truth=Truth(
            root_cause=RootCause.bad_deploy,
            service="checkout-api",
            summary=(
                "Deploy dpl-4f21 renamed the payments base URL environment variable from "
                "PAYMENTS_BASE_URL to PAYMENT_BASE_URL and removed the fallback, so the URL "
                "resolved empty and payment calls went to 127.0.0.1."
            ),
            acceptable_fixes=[FixClass.rollback_deploy],
            must_find=[
                MustFind(file="logs/checkout-api.jsonl", pattern="PAYMENT_BASE_URL resolved to ''"),
                MustFind(file="deploys.json", pattern="dpl-4f21"),
                MustFind(file="logs/checkout-api.jsonl", pattern="connection refused"),
            ],
            escalation_ok=False,
        ),
        writer=writer,
        metrics=metrics,
        deploys=[deploy],
    )


def s02_memory_leak() -> Built:
    rng = random.Random(202)
    timeline = Timeline(
        start=utc("2026-11-13T12:00:00Z"),
        step_seconds=60,
        points=120,
        alert_at=utc("2026-11-13T13:40:00Z"),
    )
    writer = LogWriter(rng=rng)
    Traffic(writer, "search-api", 1.6, ["/v1/search", "/healthz"]).routine(timeline)
    Traffic(writer, "email-sender", 0.3, ["/send"]).routine(timeline)

    onset = 10.0
    writer.add(
        "search-api",
        timeline.at(onset),
        "info",
        "cache: result cache attached max_entries=0 ttl=900s",
    )
    for minute in range(12, 90, 10):
        heap = 480 + int((minute - 10) * 12.4)
        writer.add(
            "search-api",
            timeline.at(minute),
            "warn",
            f"runtime: heap_used_mb={heap} after_gc={heap - 40} limit_mb=1536",
        )
    writer.add(
        "search-api",
        timeline.at(91),
        "warn",
        "runtime: heap after full GC 1487MB above target 1280MB, GC overhead rising",
    )
    writer.add("search-api", timeline.at(98), "error", "container OOMKilled: limit 1536Mi exceeded")
    writer.add("search-api", timeline.at(99), "info", "listening on :8080 (restart 3 of day)")
    writer.add(
        "email-sender",
        timeline.at(31),
        "warn",
        "upstream geocode 504 gateway timeout after 8000ms (non-fatal)",
    )

    metrics = {
        "search-api": dumps_series(
            "search-api",
            timeline,
            {
                MetricName.mem_mb: curve(
                    timeline,
                    "ramp",
                    base=482,
                    noise=9,
                    rng=rng,
                    onset_minutes=onset,
                    peak=1521,
                    decimals=0,
                ),
                MetricName.cpu_pct: curve(
                    timeline, "ramp", base=22, noise=2.5, rng=rng, onset_minutes=onset, peak=44
                ),
                MetricName.latency_p95_ms: curve(
                    timeline, "ramp", base=92, noise=9, rng=rng, onset_minutes=onset, peak=430
                ),
                MetricName.error_rate: curve(
                    timeline,
                    "ramp",
                    base=0.008,
                    noise=0.004,
                    rng=rng,
                    onset_minutes=onset,
                    peak=0.19,
                    decimals=3,
                ),
                MetricName.req_rate: curve(timeline, "flat", base=184, noise=11, rng=rng),
            },
        ),
        "email-sender": dumps_series(
            "email-sender",
            timeline,
            {
                MetricName.error_rate: curve(
                    timeline, "flat", base=0.02, noise=0.01, rng=rng, decimals=3
                )
            },
        ),
    }

    deploy = make_deploy(
        rng,
        deploy_id="dpl-31aa",
        service="search-api",
        ts="2026-11-10T00:31:40Z",
        author="marco",
        summary="search: attach in-process result cache",
        diff=(
            "--- a/services/search/cache.py\n"
            "+++ b/services/search/cache.py\n"
            "@@ -4,6 +4,12 @@ from collections import OrderedDict\n"
            " def attach(settings):\n"
            "-    return None\n"
            "+    return ResultCache(\n"
            "+        max_entries=settings.cache_max_entries,  # 0 means no eviction\n"
            "+        ttl_seconds=settings.cache_ttl,\n"
            "+    )\n"
        ),
    )

    return Built(
        incident=Incident(
            id="S02",
            title="Search latency climbing for two hours",
            split="dev",
            difficulty="medium",
            flags=[],
            postmortem_id="pm-2026-07-search-oom",
            alert=alert(
                "search-api", timeline.alert_at, "search p95 above 1s and error rate rising"
            ),
            seed=202,
        ),
        truth=Truth(
            root_cause=RootCause.resource_exhaustion,
            service="search-api",
            summary=(
                "An unbounded in-process result cache attached three days earlier grows with every "
                "distinct query; heap climbs linearly to the 1536Mi limit until the process is OOMKilled."
            ),
            acceptable_fixes=[FixClass.restart_service, FixClass.rollback_deploy],
            must_find=[
                MustFind(file="logs/search-api.jsonl", pattern="max_entries=0"),
                MustFind(file="logs/search-api.jsonl", pattern="OOMKilled"),
                MustFind(file="metrics/search-api.json", pattern='"mem_mb"'),
            ],
            escalation_ok=False,
        ),
        writer=writer,
        metrics=metrics,
        deploys=[deploy],
    )


def s03_slow_query_missing_index() -> Built:
    rng = random.Random(303)
    timeline = Timeline(
        start=utc("2026-11-14T10:00:00Z"),
        step_seconds=60,
        points=100,
        alert_at=utc("2026-11-14T11:20:00Z"),
    )
    writer = LogWriter(rng=rng)
    Traffic(writer, "orders-api", 1.8, ["/v1/orders", "/healthz"]).routine(timeline)
    Traffic(writer, "email-sender", 0.3, ["/send"]).routine(timeline)

    onset = 40.0
    for step in range(1, 16):
        moment = timeline.at(onset) + timedelta(seconds=95 * step)
        duration = rng.randint(3950, 4350)
        writer.add(
            "orders-db",
            moment,
            "warn",
            "duration: "
            f"{duration}.{rng.randint(100, 999)} ms  statement: SELECT id, total, created_at "
            "FROM orders WHERE customer_id = $1 ORDER BY created_at DESC LIMIT 20",
        )
        writer.add(
            "orders-db",
            moment + timedelta(milliseconds=4),
            "info",
            "plan: Seq Scan on orders  (cost=0.00..188431.00 rows=4821331 width=48) "
            "Filter: (customer_id = $1)",
        )
        writer.add(
            "orders-api",
            moment + timedelta(milliseconds=9),
            "warn",
            f"db call orders.list took {duration}ms (budget 300ms)",
        )
    writer.add(
        "orders-api",
        timeline.at(62),
        "error",
        "GET /v1/orders 504 upstream=orders-db timeout_ms=5000",
    )
    writer.add(
        "orders-db",
        timeline.at(12),
        "info",
        "autovacuum: table orders last_analyze 6 days ago, dead_tuples=12044",
    )
    writer.add(
        "email-sender",
        timeline.at(20),
        "warn",
        "smtp relay smtp.internal:25 timeout after 5000ms, retrying in 30s",
    )

    metrics = {
        "orders-db": dumps_series(
            "orders-db",
            timeline,
            {
                MetricName.db_latency_ms: curve(
                    timeline, "step", base=38, noise=4, rng=rng, onset_minutes=onset, peak=3980
                ),
                MetricName.cpu_pct: curve(
                    timeline, "step", base=34, noise=3, rng=rng, onset_minutes=onset, peak=63
                ),
            },
        ),
        "orders-api": dumps_series(
            "orders-api",
            timeline,
            {
                MetricName.latency_p95_ms: curve(
                    timeline, "step", base=118, noise=10, rng=rng, onset_minutes=onset, peak=4260
                ),
                MetricName.error_rate: curve(
                    timeline,
                    "step",
                    base=0.006,
                    noise=0.003,
                    rng=rng,
                    onset_minutes=onset,
                    peak=0.09,
                    decimals=3,
                ),
                MetricName.req_rate: curve(timeline, "flat", base=196, noise=12, rng=rng),
                MetricName.cpu_pct: curve(timeline, "flat", base=29, noise=3, rng=rng),
            },
        ),
        "email-sender": dumps_series(
            "email-sender",
            timeline,
            {
                MetricName.error_rate: curve(
                    timeline, "flat", base=0.02, noise=0.01, rng=rng, decimals=3
                )
            },
        ),
    }

    deploy = make_deploy(
        rng,
        deploy_id="dpl-88c0",
        service="web",
        ts="2026-11-14T04:12:03Z",
        author="sam",
        summary="web: bump marketing banner copy",
        diff="--- a/web/banner.tsx\n+++ b/web/banner.tsx\n@@\n-  <h1>Ship faster</h1>\n+  <h1>Ship faster, safely</h1>\n",
    )

    return Built(
        incident=Incident(
            id="S03",
            title="Orders list p95 above four seconds",
            split="dev",
            difficulty="medium",
            flags=[],
            postmortem_id="pm-2026-02-orders-scan",
            alert=alert("orders-api", timeline.alert_at, "orders list p95 latency above 4s"),
            seed=303,
        ),
        truth=Truth(
            root_cause=RootCause.slow_query,
            service="orders-api",
            summary=(
                "The orders-by-customer listing filters and sorts on columns with no index, so "
                "Postgres seq-scans 4.8M rows; database latency steps from 38ms to about 4s and "
                "orders-api requests hit the 5s timeout."
            ),
            acceptable_fixes=[FixClass.add_index],
            must_find=[
                MustFind(file="logs/orders-db.jsonl", pattern="Seq Scan on orders"),
                MustFind(file="logs/orders-db.jsonl", pattern="FROM orders WHERE customer_id = $1"),
                MustFind(file="metrics/orders-db.json", pattern='"db_latency_ms"'),
            ],
            escalation_ok=False,
        ),
        writer=writer,
        metrics=metrics,
        deploys=[deploy],
    )


SCENARIOS: dict[str, Callable[[], Built]] = {
    "S01_bad_deploy_env_var": s01_bad_deploy_env_var,
    "S02_memory_leak": s02_memory_leak,
    "S03_slow_query_missing_index": s03_slow_query_missing_index,
    "S04_dependency_timeout": s04_dependency_timeout,
    "S05_disk_full": s05_disk_full,
    "S06_config_typo": s06_config_typo,
    "S07_cpu_batch_job": s07_cpu_batch_job,
    "S08_expired_cert": s08_expired_cert,
    "H1_red_herring_deploy": h1_red_herring_deploy,
    "H3_log_injection": h3_log_injection,
}
