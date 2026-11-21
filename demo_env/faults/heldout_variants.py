"""Heldout second variants S01b to S08b: same root cause as the dev incident, new service,
timing, noise and wording.

Same rule as scenarios.py: a careful human can name the cause and the fix from
the evidence alone, and no single log line states the cause.
"""

from __future__ import annotations

import random
from datetime import timedelta

from agents.schemas import FixClass, RootCause
from demo_env.faults.base import Built, Curves, capped, leak_with_restarts, make_deploy, repeat
from demo_env.faults.render import LogWriter, Timeline, Traffic, alert, dumps_series, utc
from demo_env.models import Incident, MetricName, MetricPoint, MustFind, Truth


def s01b_invoice_env_var() -> Built:
    seed = 2101
    rng = random.Random(seed)
    timeline = Timeline(
        start=utc("2026-10-06T14:00:00Z"),
        step_seconds=60,
        points=75,
        alert_at=utc("2026-10-06T15:05:00Z"),
    )
    writer = LogWriter(rng=rng)
    curves = Curves(timeline, rng)
    Traffic(writer, "invoice-api", 3.2, ["/v1/invoices", "/v1/invoices/pdf", "/healthz"]).routine(
        timeline
    )
    Traffic(writer, "pdf-renderer", 1.1, ["/render"]).routine(timeline)
    for minute in (9, 51):
        writer.add(
            "pdf-renderer",
            timeline.at(minute),
            "error",
            "font cache rebuild failed: mkdir /var/cache/fontconfig: read-only file system; "
            "using bundled fonts",
        )

    onset = 37.0
    rollout = timeline.at(onset)
    writer.add(
        "invoice-api", rollout, "info", "rollout dpl-a63e: 6/6 pods ready (image invoice:4.18.0)"
    )
    writer.add(
        "invoice-api",
        rollout + timedelta(seconds=3),
        "warn",
        "config: LEDGER_DB_DSN not present in environment; ledger writes unavailable",
    )
    repeat(
        writer,
        "invoice-api",
        "error",
        start=rollout + timedelta(seconds=25),
        end=timeline.end,
        gap=(30, 12),
        message=lambda _: (
            f"POST /v1/invoices 500 unhandled KeyError: 'LEDGER_DB_DSN' at ledger/db.py:27 in "
            f"connect() req={rng.getrandbits(32):08x}"
        ),
    )
    repeat(
        writer,
        "pdf-renderer",
        "warn",
        start=rollout + timedelta(minutes=2),
        end=timeline.end,
        gap=(240, 60),
        message=lambda _: (
            f"fetch invoice inv-{rng.randint(100000, 999999)} from invoice-api failed status=500"
        ),
    )

    metrics = {
        "invoice-api": dumps_series(
            "invoice-api",
            timeline,
            {
                MetricName.req_rate: curves.flat(186, 8),
                MetricName.error_rate: curves.shaped(
                    "step", 0.003, 0.002, onset=onset, peak=0.47, decimals=3
                ),
                MetricName.latency_p95_ms: curves.shaped("step", 96, 7, onset=onset, peak=158),
                MetricName.cpu_pct: curves.flat(24, 2),
            },
        ),
        "pdf-renderer": dumps_series(
            "pdf-renderer",
            timeline,
            {MetricName.error_rate: curves.flat(0.012, 0.004, decimals=3)},
        ),
    }
    deploy = make_deploy(
        rng,
        deploy_id="dpl-a63e",
        service="invoice-api",
        ts="2026-10-06T14:36:21Z",
        author="ines",
        summary="invoice-api: load secrets with envFrom instead of per-key env",
        diff=(
            "--- a/deploy/invoice-api/deployment.yaml\n"
            "+++ b/deploy/invoice-api/deployment.yaml\n"
            "@@ -41,9 +41,6 @@ spec:\n"
            "           env:\n"
            "             - name: LOG_LEVEL\n"
            "               value: info\n"
            "-            - name: LEDGER_DB_DSN\n"
            "-              valueFrom:\n"
            "-                secretKeyRef: {name: invoice-db, key: dsn}\n"
            "+          envFrom:\n"
            "+            - secretRef: {name: invoice-secrets}\n"
        ),
    )
    return Built(
        incident=Incident(
            id="S01b",
            title="Invoice creation fails after a manifest change",
            split="heldout",
            difficulty="easy",
            flags=[],
            postmortem_id="pm-2026-03-invoice-env-var",
            alert=alert(
                "invoice-api", timeline.alert_at, "invoice-api 5xx above 40% for 15 minutes"
            ),
            seed=seed,
        ),
        truth=Truth(
            root_cause=RootCause.bad_deploy,
            service="invoice-api",
            summary=(
                "Deploy dpl-a63e at 14:37 replaced the per-key LEDGER_DB_DSN env entry with an "
                "envFrom secret that has no such key, so every invoice write raises "
                "KeyError: 'LEDGER_DB_DSN'."
            ),
            acceptable_fixes=[FixClass.rollback_deploy],
            must_find=[
                MustFind(file="logs/invoice-api.jsonl", pattern="KeyError: 'LEDGER_DB_DSN'"),
                MustFind(file="logs/invoice-api.jsonl", pattern="LEDGER_DB_DSN not present"),
                MustFind(file="deploys.json", pattern="dpl-a63e"),
            ],
            escalation_ok=False,
        ),
        writer=writer,
        metrics=metrics,
        deploys=[deploy],
    )


def s02b_recs_listener_leak() -> Built:
    seed = 2202
    rng = random.Random(seed)
    timeline = Timeline(
        start=utc("2026-10-08T05:00:00Z"),
        step_seconds=60,
        points=118,
        alert_at=utc("2026-10-08T06:52:00Z"),
    )
    writer = LogWriter(rng=rng)
    curves = Curves(timeline, rng)
    Traffic(writer, "recs-api", 2.2, ["/v1/recs/home", "/v1/recs/similar", "/healthz"]).routine(
        timeline
    )
    Traffic(writer, "home-feed", 1.4, ["/v1/feed"]).routine(timeline)
    for minute in (22, 77):
        writer.add(
            "home-feed",
            timeline.at(minute),
            "error",
            f"image proxy: cdn-img.example returned 404 for /p/{rng.getrandbits(24):06x}.webp",
        )

    restarts = [47.0, 104.0]
    base, limit = 700.0, 2010.0

    def uptime(minute: float) -> float:
        return minute - max([0.0, *(at for at in restarts if at <= minute)])

    for minute in range(4, 117, 10):
        writer.add(
            "recs-api",
            timeline.at(minute),
            "info",
            f"catalog-events: {1200 + int(uptime(minute) * 410)} active listeners, "
            f"dispatch queue {rng.randint(0, 4)}",
        )
    for minute in (30, 38, 44, 85, 93, 99):
        heap_mb = min(limit, base + (limit - base) * uptime(minute) / restarts[0])
        writer.add(
            "recs-api",
            timeline.at(minute),
            "warn",
            f"gc: G1 Old Generation pause {rng.randint(900, 1900)}ms, old gen "
            f"{heap_mb * 0.97 / 1000:.2f}GB of 2.00GB after collection",
        )
    for index, minute in enumerate(restarts):
        writer.add(
            "recs-api",
            timeline.at(minute - 0.5),
            "error",
            "Exception in thread grpc-default-executor-41: java.lang.OutOfMemoryError: Java heap space",
        )
        writer.add(
            "recs-api",
            timeline.at(minute),
            "warn",
            f"container recs exited with code 137 (OOMKilled), restartCount={4 + index}",
        )
        writer.add(
            "recs-api",
            timeline.at(minute) + timedelta(seconds=14),
            "info",
            "recs-api started in 11.8s on :8080",
        )
        repeat(
            writer,
            "home-feed",
            "warn",
            start=timeline.at(minute - 6),
            end=timeline.at(minute + 1),
            gap=(55, 20),
            message=lambda _: "recs-api call exceeded 800ms, serving fallback carousel",
        )

    memory = leak_with_restarts(timeline, rng, base=base, limit=limit, noise=11, restarts=restarts)
    latency = [
        MetricPoint(ts=p.ts, value=round(70 + max(0.0, p.value - 1400) * 1.3 + rng.gauss(0, 6), 1))
        for p in memory
    ]
    errors = [
        MetricPoint(
            ts=p.ts,
            value=round(
                0.31
                if any(abs((p.ts - timeline.at(m)).total_seconds()) <= 60 for m in restarts)
                else abs(rng.gauss(0.006, 0.002)),
                3,
            ),
        )
        for p in memory
    ]
    metrics = {
        "recs-api": dumps_series(
            "recs-api",
            timeline,
            {
                MetricName.mem_mb: memory,
                MetricName.latency_p95_ms: latency,
                MetricName.error_rate: errors,
                MetricName.req_rate: curves.flat(152, 7),
            },
        ),
        "home-feed": dumps_series(
            "home-feed",
            timeline,
            {MetricName.latency_p95_ms: curves.flat(240, 18)},
        ),
    }
    deploy = make_deploy(
        rng,
        deploy_id="dpl-0b7d",
        service="recs-api",
        ts="2026-10-07T23:48:00Z",
        author="dmitri",
        summary="recs: refresh catalog listener per request",
        diff=(
            "--- a/recs/src/main/java/acme/recs/RecsHandler.java\n"
            "+++ b/recs/src/main/java/acme/recs/RecsHandler.java\n"
            "@@ -52,6 +52,7 @@ public Response handle(Request req) {\n"
            "     var user = profiles.load(req.userId());\n"
            "+    catalogEvents.subscribe(new CatalogListener(user, cache));\n"
            "     return Response.ok(ranker.rank(user, candidates(user)));\n"
        ),
    )
    return Built(
        incident=Incident(
            id="S02b",
            title="Recommendations restart twice before breakfast",
            split="heldout",
            difficulty="medium",
            flags=[],
            postmortem_id="pm-2026-05-recs-heap",
            alert=alert("recs-api", timeline.alert_at, "recs-api restarted twice in 60 minutes"),
            seed=seed,
        ),
        truth=Truth(
            root_cause=RootCause.resource_exhaustion,
            service="recs-api",
            summary=(
                "Deploy dpl-0b7d subscribes a new catalog listener on every request and never "
                "removes it; heap climbs to the 2 GB limit and recs-api is OOMKilled at 05:47 and "
                "06:44, with GC pauses growing before each kill."
            ),
            acceptable_fixes=[FixClass.restart_service, FixClass.rollback_deploy],
            must_find=[
                MustFind(file="logs/recs-api.jsonl", pattern="java.lang.OutOfMemoryError"),
                MustFind(file="logs/recs-api.jsonl", pattern="OOMKilled"),
                MustFind(file="logs/recs-api.jsonl", pattern="active listeners"),
                MustFind(file="metrics/recs-api.json", pattern="mem_mb"),
            ],
            escalation_ok=False,
        ),
        writer=writer,
        metrics=metrics,
        deploys=[deploy],
    )


def s03b_tickets_full_scan() -> Built:
    seed = 2303
    rng = random.Random(seed)
    timeline = Timeline(
        start=utc("2026-10-09T16:00:00Z"),
        step_seconds=60,
        points=80,
        alert_at=utc("2026-10-09T17:14:00Z"),
    )
    writer = LogWriter(rng=rng)
    curves = Curves(timeline, rng)
    Traffic(writer, "support-api", 2.6, ["/v1/tickets/mine", "/v1/tickets", "/healthz"]).routine(
        timeline
    )
    Traffic(writer, "attachments-svc", 0.9, ["/v1/attachments"]).routine(timeline)
    for minute in (18, 63):
        writer.add(
            "attachments-svc",
            timeline.at(minute),
            "error",
            f"S3 PutObject att-{rng.randint(10000, 99999)} returned 503 SlowDown, retry 1 of 3",
        )

    onset = 44.0
    writer.add(
        "support-db",
        timeline.at(7),
        "info",
        "InnoDB: buffer pool hit rate 998/1000, pages dirty 1.2%",
    )
    repeat(
        writer,
        "support-db",
        "warn",
        start=timeline.at(onset) + timedelta(seconds=40),
        end=timeline.end,
        gap=(80, 15),
        message=lambda _: (
            f"slow query: Query_time={rng.uniform(2.9, 3.3):.3f} Rows_examined=2904113 Rows_sent=25 "
            f"SELECT id, subject, updated_at FROM tickets WHERE assignee_id = {rng.randint(4000, 4999)} "
            "AND status = 'open' ORDER BY updated_at DESC LIMIT 25"
        ),
    )
    for minute in (46, 58, 70):
        writer.add(
            "support-db",
            timeline.at(minute),
            "info",
            "explain: table=tickets type=ALL possible_keys=NULL key=NULL rows=2904113 "
            "Extra=Using where; Using filesort",
        )
    repeat(
        writer,
        "support-api",
        "warn",
        start=timeline.at(onset) + timedelta(seconds=45),
        end=timeline.end,
        gap=(95, 20),
        message=lambda _: (
            f"query tickets.open_for_assignee took {rng.randint(2900, 3300)}ms (slow threshold 250ms)"
        ),
    )
    repeat(
        writer,
        "support-api",
        "error",
        start=timeline.at(onset + 3),
        end=timeline.end,
        gap=(150, 40),
        message=lambda _: "GET /v1/tickets/mine 504 upstream=support-db timeout_ms=3000",
    )

    metrics = {
        "support-db": dumps_series(
            "support-db",
            timeline,
            {
                MetricName.db_latency_ms: curves.shaped("step", 22, 3, onset=onset, peak=3110),
                MetricName.cpu_pct: curves.shaped("step", 30, 3, onset=onset, peak=71),
            },
        ),
        "support-api": dumps_series(
            "support-api",
            timeline,
            {
                MetricName.latency_p95_ms: curves.shaped("step", 140, 11, onset=onset, peak=3050),
                MetricName.error_rate: curves.shaped(
                    "step", 0.004, 0.002, onset=onset, peak=0.07, decimals=3
                ),
                MetricName.req_rate: curves.flat(158, 9),
                MetricName.cpu_pct: curves.flat(26, 2),
            },
        ),
    }
    deploy = make_deploy(
        rng,
        deploy_id="dpl-41f9",
        service="helpdesk-web",
        ts="2026-10-09T11:20:00Z",
        author="ade",
        summary="helpdesk-web: dark mode toggle in settings",
        diff=(
            "--- a/helpdesk-web/src/settings.tsx\n"
            "+++ b/helpdesk-web/src/settings.tsx\n"
            "@@ -12,2 +12,3 @@\n"
            "   <LanguagePicker />\n"
            "+  <ThemeToggle />\n"
        ),
    )
    return Built(
        incident=Incident(
            id="S03b",
            title="Agents wait seconds for their ticket queue",
            split="heldout",
            difficulty="medium",
            flags=[],
            postmortem_id="pm-2026-06-tickets-scan",
            alert=alert("support-api", timeline.alert_at, "support-api p95 latency above 2.5s"),
            seed=seed,
        ),
        truth=Truth(
            root_cause=RootCause.slow_query,
            service="support-api",
            summary=(
                "The open-tickets-by-assignee query has no usable index (type=ALL, key=NULL), so "
                "MySQL examines 2.9M rows per call; support-db latency steps from 22 ms to about 3 s "
                "from 16:44 and support-api requests hit the 3 s timeout."
            ),
            acceptable_fixes=[FixClass.add_index],
            must_find=[
                MustFind(file="logs/support-db.jsonl", pattern="type=ALL"),
                MustFind(file="logs/support-db.jsonl", pattern="FROM tickets WHERE assignee_id"),
                MustFind(file="metrics/support-db.json", pattern="db_latency_ms"),
            ],
            escalation_ok=False,
        ),
        writer=writer,
        metrics=metrics,
        deploys=[deploy],
    )


def s04b_fx_feed_timeout() -> Built:
    seed = 2404
    rng = random.Random(seed)
    timeline = Timeline(
        start=utc("2026-10-12T09:00:00Z"),
        step_seconds=60,
        points=76,
        alert_at=utc("2026-10-12T10:11:00Z"),
    )
    writer = LogWriter(rng=rng)
    curves = Curves(timeline, rng)
    Traffic(writer, "quotes-api", 2.4, ["/v1/quotes", "/healthz"]).routine(timeline)
    Traffic(writer, "checkout-web", 1.3, ["/cart", "/checkout"]).routine(timeline)
    Traffic(writer, "audit-log", 0.6, ["/ingest"]).routine(timeline)
    for minute in (14, 41, 66):
        writer.add(
            "audit-log",
            timeline.at(minute),
            "error",
            "audit sink: batch of 500 rejected with 413 Request Entity Too Large, splitting batch",
        )

    onset = 49.0
    for minute in range(3, 75, 7):
        writer.add(
            "quotes-api",
            timeline.at(minute),
            "info",
            f"runtime: rss_mb={rng.randint(296, 324)} cpu_cores=0.{rng.randint(17, 24)} "
            f"open_fds={rng.randint(170, 205)}/65536 db_pool={rng.randint(2, 6)}/30",
        )
    repeat(
        writer,
        "quotes-api",
        "error",
        start=timeline.at(onset) + timedelta(seconds=8),
        end=timeline.end,
        gap=(35, 15),
        message=lambda _: (
            f"GET /v1/quotes 502 upstream=fxfeed host=rates.fxfeed.example err=read tcp "
            f"10.3.4.12:{rng.randint(40000, 60000)}->203.0.113.40:443: i/o timeout after 3000ms"
        ),
    )
    writer.add(
        "quotes-api",
        timeline.at(onset + 2),
        "warn",
        "circuit fxfeed OPEN after 20 consecutive failures; half-open probe in 30s",
    )
    repeat(
        writer,
        "quotes-api",
        "warn",
        start=timeline.at(onset + 4),
        end=timeline.end,
        gap=(120, 20),
        message=lambda _: (
            "circuit fxfeed half-open probe to rates.fxfeed.example failed: i/o timeout"
        ),
    )
    repeat(
        writer,
        "checkout-web",
        "warn",
        start=timeline.at(onset + 1),
        end=timeline.end,
        gap=(200, 60),
        message=lambda _: "price widget degraded: quotes-api returned 502, showing last known rate",
    )

    metrics = {
        "quotes-api": dumps_series(
            "quotes-api",
            timeline,
            {
                MetricName.req_rate: curves.flat(131, 6),
                MetricName.error_rate: curves.shaped(
                    "step", 0.005, 0.002, onset=onset, peak=0.52, decimals=3
                ),
                MetricName.latency_p95_ms: curves.shaped("step", 88, 7, onset=onset, peak=3010),
                MetricName.cpu_pct: curves.flat(19, 2),
                MetricName.mem_mb: curves.flat(310, 6),
            },
        ),
    }
    return Built(
        incident=Incident(
            id="S04b",
            title="Currency quotes stall at checkout",
            split="heldout",
            difficulty="medium",
            flags=[],
            postmortem_id="pm-2026-08-fxfeed-timeouts",
            alert=alert("quotes-api", timeline.alert_at, "quotes-api 502 rate above 45%"),
            seed=seed,
        ),
        truth=Truth(
            root_cause=RootCause.dependency_failure,
            service="quotes-api",
            summary=(
                "From 09:49 the external rate provider rates.fxfeed.example stopped answering "
                "within quotes-api's 3 s read timeout and the fxfeed circuit opened; quotes-api's "
                "own memory, CPU, file descriptors and DB pool stayed normal."
            ),
            acceptable_fixes=[FixClass.config_change, FixClass.escalate_human],
            must_find=[
                MustFind(file="logs/quotes-api.jsonl", pattern="rates.fxfeed.example"),
                MustFind(file="logs/quotes-api.jsonl", pattern="circuit fxfeed OPEN"),
                MustFind(file="logs/quotes-api.jsonl", pattern="i/o timeout"),
            ],
            escalation_ok=True,
        ),
        writer=writer,
        metrics=metrics,
        deploys=[],
    )


def s05b_upload_volume_full() -> Built:
    seed = 2505
    rng = random.Random(seed)
    timeline = Timeline(
        start=utc("2026-10-14T21:00:00Z"),
        step_seconds=60,
        points=85,
        alert_at=utc("2026-10-14T22:19:00Z"),
    )
    writer = LogWriter(rng=rng)
    curves = Curves(timeline, rng)
    Traffic(writer, "upload-svc", 2.8, ["/v1/uploads", "/v1/uploads/status", "/healthz"]).routine(
        timeline
    )
    Traffic(writer, "media-web", 1.2, ["/upload", "/library"]).routine(timeline)
    Traffic(writer, "thumbnailer", 0.8, ["/thumb"]).routine(timeline)
    for minute in (11, 37, 70):
        writer.add(
            "thumbnailer",
            timeline.at(minute),
            "error",
            f"libvips: VipsJpeg: Premature end of JPEG file (img-{rng.randint(1000, 9999)}), skipped",
        )

    full = 52.0
    writer.add(
        "upload-svc",
        timeline.at(6),
        "info",
        "tmp sweeper: skipped, last successful run 2026-10-11T03:00:00Z",
    )
    writer.add("upload-svc", timeline.at(34), "warn", "df: /srv/uploads 90% used, 12.1GiB free")
    writer.add("upload-svc", timeline.at(46), "warn", "df: /srv/uploads 97% used, 3.4GiB free")
    repeat(
        writer,
        "upload-svc",
        "error",
        start=timeline.at(full) + timedelta(seconds=12),
        end=timeline.end,
        gap=(28, 14),
        message=lambda _: (
            "POST /v1/uploads 507 write chunk failed: ENOSPC: no space left on device, write "
            f"'/srv/uploads/tmp/up-{rng.getrandbits(32):08x}.part'"
        ),
    )
    writer.add(
        "upload-svc",
        timeline.at(55),
        "warn",
        "logrotate: error compressing /srv/uploads/logs/app.log.1: No space left on device",
    )
    repeat(
        writer,
        "media-web",
        "warn",
        start=timeline.at(full + 1),
        end=timeline.end,
        gap=(150, 50),
        message=lambda _: (
            f"upload failed for user u-{rng.randint(10000, 99999)}: upload-svc returned 507"
        ),
    )

    disk_peak = 64 + (100 - 64) * 84 / full
    metrics = {
        "upload-svc": dumps_series(
            "upload-svc",
            timeline,
            {
                MetricName.disk_used_pct: capped(
                    curves.shaped("ramp", 64, 0.2, onset=0, peak=disk_peak), 100.0
                ),
                MetricName.error_rate: curves.shaped(
                    "step", 0.004, 0.002, onset=full, peak=0.71, decimals=3
                ),
                MetricName.latency_p95_ms: curves.shaped("step", 310, 22, onset=full, peak=90),
                MetricName.req_rate: curves.flat(168, 8),
            },
        ),
    }
    deploy = make_deploy(
        rng,
        deploy_id="dpl-7c3b",
        service="media-web",
        ts="2026-10-14T16:02:00Z",
        author="yuki",
        summary="media-web: show upload progress percentage",
        diff=(
            "--- a/media-web/src/Upload.vue\n"
            "+++ b/media-web/src/Upload.vue\n"
            "@@ -30,1 +30,1 @@\n"
            '-  <progress :value="done" />\n'
            '+  <progress :value="done">{{ percent }}%</progress>\n'
        ),
    )
    return Built(
        incident=Incident(
            id="S05b",
            title="Uploads rejected in the evening",
            split="heldout",
            difficulty="easy",
            flags=[],
            postmortem_id="pm-2026-09-upload-volume",
            alert=alert("upload-svc", timeline.alert_at, "upload-svc 507 responses above 60%"),
            seed=seed,
        ),
        truth=Truth(
            root_cause=RootCause.disk_full,
            service="upload-svc",
            summary=(
                "The /srv/uploads volume filled because the tmp sweeper had not run since "
                "2026-10-11; it reached 100% at 21:52 and every chunk write since fails with "
                "ENOSPC, as does log rotation."
            ),
            acceptable_fixes=[FixClass.free_disk],
            must_find=[
                MustFind(file="logs/upload-svc.jsonl", pattern="ENOSPC"),
                MustFind(file="logs/upload-svc.jsonl", pattern="/srv/uploads/tmp"),
                MustFind(file="metrics/upload-svc.json", pattern="disk_used_pct"),
            ],
            escalation_ok=False,
        ),
        writer=writer,
        metrics=metrics,
        deploys=[deploy],
    )


def s06b_body_limit_typo() -> Built:
    seed = 2606
    rng = random.Random(seed)
    timeline = Timeline(
        start=utc("2026-10-15T13:00:00Z"),
        step_seconds=60,
        points=50,
        alert_at=utc("2026-10-15T13:44:00Z"),
    )
    writer = LogWriter(rng=rng)
    curves = Curves(timeline, rng)
    Traffic(writer, "partner-api", 4.0, ["/v1/orders", "/v1/catalog", "/healthz"]).routine(timeline)
    Traffic(writer, "partner-portal", 1.6, ["/orders/new", "/orders"]).routine(timeline)
    Traffic(writer, "webhook-relay", 1.0, ["/deliver"]).routine(timeline)
    for minute in (8, 29, 41):
        writer.add(
            "webhook-relay",
            timeline.at(minute),
            "error",
            "delivery to https://hooks.partner-example.test/acme failed: 410 Gone, endpoint disabled",
        )

    onset = 23.0
    writer.add(
        "partner-api",
        timeline.at(2),
        "info",
        "consul watch: config/partner-api unchanged modify_index=771090",
    )
    writer.add(
        "partner-api",
        timeline.at(2) + timedelta(seconds=1),
        "info",
        "http: request body limit 1048576 bytes",
    )
    writer.add(
        "partner-api",
        timeline.at(onset),
        "info",
        "consul watch: config/partner-api/max_body_size changed modify_index=771204",
    )
    writer.add(
        "partner-api",
        timeline.at(onset) + timedelta(seconds=1),
        "info",
        "http: request body limit 1024 bytes",
    )
    repeat(
        writer,
        "partner-api",
        "error",
        start=timeline.at(onset) + timedelta(seconds=15),
        end=timeline.end,
        gap=(25, 10),
        message=lambda _: (
            f"POST /v1/orders 413 request body {rng.randint(9000, 42000)} bytes exceeds limit 1024"
        ),
    )
    repeat(
        writer,
        "partner-portal",
        "warn",
        start=timeline.at(onset) + timedelta(seconds=40),
        end=timeline.end,
        gap=(90, 30),
        message=lambda _: (
            f"order submit failed for partner p-{rng.randint(1000, 9999)}: partner-api returned 413"
        ),
    )

    metrics = {
        "partner-api": dumps_series(
            "partner-api",
            timeline,
            {
                MetricName.error_rate: curves.shaped(
                    "step", 0.003, 0.001, onset=onset, peak=0.61, decimals=3
                ),
                MetricName.req_rate: curves.flat(242, 10),
                MetricName.latency_p95_ms: curves.flat(64, 5),
                MetricName.cpu_pct: curves.flat(22, 2),
            },
        ),
        "partner-portal": dumps_series(
            "partner-portal",
            timeline,
            {
                MetricName.error_rate: curves.shaped(
                    "step", 0.008, 0.003, onset=onset, peak=0.44, decimals=3
                )
            },
        ),
    }
    deploy = make_deploy(
        rng,
        deploy_id="dpl-e518",
        service="partner-api",
        ts="2026-10-13T10:05:00Z",
        author="kofi",
        summary="partner-api: add request id to access log",
        diff=(
            "--- a/partner_api/access_log.py\n"
            "+++ b/partner_api/access_log.py\n"
            "@@ -8,3 +8,4 @@ def line(request, response):\n"
            "     fields = [request.method, request.path, str(response.status)]\n"
            "+    fields.append(request.headers.get('x-request-id', '-'))\n"
        ),
    )
    return Built(
        incident=Incident(
            id="S06b",
            title="Partner orders rejected as too large",
            split="heldout",
            difficulty="medium",
            flags=[],
            postmortem_id="pm-2026-04-partner-body-limit",
            alert=alert("partner-api", timeline.alert_at, "partner-api 413 rate above 50% on POST"),
            seed=seed,
        ),
        truth=Truth(
            root_cause=RootCause.misconfiguration,
            service="partner-api",
            summary=(
                "A Consul KV edit at 13:23 (modify_index 771204) set max_body_size to 1024 bytes "
                "instead of 1048576, so partner-api rejects every normal order body with 413. The "
                "only deploy was two days earlier and touched the access log."
            ),
            acceptable_fixes=[FixClass.config_change, FixClass.rollback_deploy],
            must_find=[
                MustFind(file="logs/partner-api.jsonl", pattern="exceeds limit 1024"),
                MustFind(file="logs/partner-api.jsonl", pattern="modify_index=771204"),
            ],
            escalation_ok=False,
        ),
        writer=writer,
        metrics=metrics,
        deploys=[deploy],
    )


def s07b_repricing_cronjob() -> Built:
    seed = 2707
    rng = random.Random(seed)
    timeline = Timeline(
        start=utc("2026-10-19T06:00:00Z"),
        step_seconds=60,
        points=90,
        alert_at=utc("2026-10-19T07:24:00Z"),
    )
    writer = LogWriter(rng=rng)
    curves = Curves(timeline, rng)
    Traffic(writer, "pricing-api", 2.6, ["/v1/price", "/v1/price/batch", "/healthz"]).routine(
        timeline
    )
    Traffic(writer, "storefront", 1.2, ["/p", "/search"]).routine(timeline)
    Traffic(writer, "currency-sync", 0.4, ["/sync"]).routine(timeline)
    for minute in (16, 52):
        writer.add(
            "currency-sync",
            timeline.at(minute),
            "error",
            "fx snapshot fetch s3://fx-snapshots/latest.json AccessDenied, keeping previous snapshot",
        )

    onset = 60.0
    writer.add(
        "pricing-api",
        timeline.at(3),
        "info",
        "cronjob reprice-all: next schedule 2026-10-19T07:00:00Z (schedule 0 7 * * *, node pool shared-a)",
    )
    writer.add(
        "pricing-api",
        timeline.at(onset),
        "info",
        "cronjob reprice-all: started pod reprice-all-29110 parallelism=6 node_pool=shared-a",
    )
    for index, minute in enumerate(range(64, 90, 6)):
        writer.add(
            "pricing-api",
            timeline.at(minute),
            "info",
            f"reprice-all: {12 + index * 17}% of 1.8M skus",
        )
    repeat(
        writer,
        "pricing-api",
        "warn",
        start=timeline.at(onset + 1),
        end=timeline.end,
        gap=(60, 10),
        message=lambda _: (
            f"cpu throttled in {rng.randint(62, 81)}% of cfs periods over 60s (limit 2 cores)"
        ),
    )
    repeat(
        writer,
        "pricing-api",
        "error",
        start=timeline.at(onset + 2),
        end=timeline.end,
        gap=(45, 15),
        message=lambda _: "GET /v1/price 504 upstream request timeout after 2000ms",
    )
    repeat(
        writer,
        "storefront",
        "warn",
        start=timeline.at(onset + 3),
        end=timeline.end,
        gap=(180, 40),
        message=lambda _: "price lookup slow, rendering cached price for listing",
    )

    metrics = {
        "pricing-api": dumps_series(
            "pricing-api",
            timeline,
            {
                MetricName.cpu_pct: capped(
                    curves.shaped("step", 41, 3, onset=onset, peak=98), 100.0
                ),
                MetricName.latency_p95_ms: curves.shaped("step", 118, 9, onset=onset, peak=2010),
                MetricName.error_rate: curves.shaped(
                    "step", 0.005, 0.002, onset=onset, peak=0.18, decimals=3
                ),
                MetricName.req_rate: curves.shaped("ramp", 160, 6, onset=20, peak=228),
                MetricName.mem_mb: curves.flat(890, 15),
            },
        ),
    }
    return Built(
        incident=Incident(
            id="S07b",
            title="Prices time out at the start of the morning",
            split="heldout",
            difficulty="medium",
            flags=[],
            postmortem_id="pm-2026-03-pricing-cronjob",
            alert=alert(
                "pricing-api", timeline.alert_at, "pricing-api p95 above 1.5s for 15 minutes"
            ),
            seed=seed,
        ),
        truth=Truth(
            root_cause=RootCause.capacity,
            service="pricing-api",
            summary=(
                "The reprice-all CronJob started at 07:00 on the shared-a node pool that also runs "
                "pricing-api, as morning traffic rose; pricing-api CPU is throttled near 98% and "
                "price requests hit the 2 s upstream timeout."
            ),
            acceptable_fixes=[FixClass.scale_out],
            must_find=[
                MustFind(file="logs/pricing-api.jsonl", pattern="started pod reprice-all"),
                MustFind(file="logs/pricing-api.jsonl", pattern="cpu throttled"),
                MustFind(file="metrics/pricing-api.json", pattern="cpu_pct"),
            ],
            escalation_ok=False,
        ),
        writer=writer,
        metrics=metrics,
        deploys=[],
    )


def s08b_grpc_cert_expiry() -> Built:
    seed = 2808
    rng = random.Random(seed)
    timeline = Timeline(
        start=utc("2026-10-20T13:30:00Z"),
        step_seconds=60,
        points=85,
        alert_at=utc("2026-10-20T14:52:00Z"),
    )
    writer = LogWriter(rng=rng)
    curves = Curves(timeline, rng)
    expiry = utc("2026-10-20T14:30:00Z")
    onset = 60.0
    Traffic(
        writer,
        "inventory-grpc",
        2.4,
        ["/inventory.v1.Stock/Reserve", "/inventory.v1.Stock/Get", "/grpc.health.v1.Health/Check"],
    ).routine(timeline, until=onset)
    Traffic(writer, "warehouse-sync", 1.0, ["/sync"]).routine(timeline)
    Traffic(writer, "order-router", 1.4, ["/v1/route"]).routine(timeline)
    for minute in (21, 47, 73):
        writer.add(
            "order-router",
            timeline.at(minute),
            "error",
            "redis SETEX rl:order-router timed out after 250ms, request allowed without rate check",
        )

    writer.add(
        "inventory-grpc",
        timeline.at(12),
        "warn",
        "certwatch: inventory-grpc.svc.internal expires 2026-10-20T14:30:00Z, 78 minutes left",
    )
    repeat(
        writer,
        "inventory-grpc",
        "warn",
        start=expiry + timedelta(seconds=4),
        end=timeline.end,
        gap=(25, 8),
        message=lambda _: (
            f"tls handshake from 10.2.7.{rng.randint(10, 60)}:{rng.randint(40000, 60000)} failed: "
            "remote error: tls: bad certificate"
        ),
    )
    for service, rpc in (("warehouse-sync", "ReserveStock"), ("order-router", "GetStock")):
        repeat(
            writer,
            service,
            "error",
            start=expiry + timedelta(seconds=6),
            end=timeline.end,
            gap=(40, 12),
            message=lambda _, rpc=rpc: (
                f"{rpc} rpc error: code = Unavailable desc = connection error: transport: "
                "authentication handshake failed: x509: certificate has expired or is not yet valid"
            ),
        )

    days_left = [
        MetricPoint(ts=moment, value=round((expiry - moment).total_seconds() / 86400, 3))
        for moment in timeline.samples()
    ]
    metrics = {
        "inventory-grpc": dumps_series(
            "inventory-grpc",
            timeline,
            {
                MetricName.cert_days_left: days_left,
                MetricName.req_rate: curves.shaped("step", 140, 3, onset=onset, peak=0),
                MetricName.cpu_pct: curves.flat(17, 2),
            },
        ),
        "warehouse-sync": dumps_series(
            "warehouse-sync",
            timeline,
            {
                MetricName.error_rate: curves.shaped(
                    "step", 0.006, 0.002, onset=onset, peak=0.97, decimals=3
                )
            },
        ),
    }
    return Built(
        incident=Incident(
            id="S08b",
            title="Stock reservations fail at half past two",
            split="heldout",
            difficulty="easy",
            flags=[],
            postmortem_id="pm-2026-02-inventory-grpc-cert",
            alert=alert(
                "inventory-grpc", timeline.alert_at, "inventory-grpc request rate at 0 since 14:30"
            ),
            seed=seed,
        ),
        truth=Truth(
            root_cause=RootCause.cert_expiry,
            service="inventory-grpc",
            summary=(
                "inventory-grpc's serving certificate expired at 2026-10-20T14:30:00Z; from that "
                "moment every gRPC client handshake fails, so warehouse-sync and order-router get "
                "no stock answers."
            ),
            acceptable_fixes=[FixClass.rotate_cert],
            must_find=[
                MustFind(
                    file="logs/warehouse-sync.jsonl", pattern="authentication handshake failed"
                ),
                MustFind(file="logs/inventory-grpc.jsonl", pattern="tls: bad certificate"),
                MustFind(file="metrics/inventory-grpc.json", pattern="cert_days_left"),
            ],
            escalation_ok=False,
        ),
        writer=writer,
        metrics=metrics,
        deploys=[],
    )
