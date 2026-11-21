"""Heldout base scenarios S09 to S12, both variants of each: connection pool exhaustion,
retry storm, rate limit set too low, and service discovery failure.

Same rule as scenarios.py: a careful human can name the cause and the fix from
the evidence alone, and no single log line states the cause.
"""

from __future__ import annotations

import random
from datetime import timedelta

from agents.schemas import FixClass, RootCause
from demo_env.faults.base import Built, Curves, make_deploy, repeat
from demo_env.faults.render import LogWriter, Timeline, Traffic, alert, dumps_series, utc
from demo_env.models import Incident, MetricName, MustFind, Truth


def s09_hikari_pool_exhausted() -> Built:
    seed = 909
    rng = random.Random(seed)
    timeline = Timeline(
        start=utc("2026-10-21T08:00:00Z"),
        step_seconds=60,
        points=82,
        alert_at=utc("2026-10-21T09:17:00Z"),
    )
    writer = LogWriter(rng=rng)
    curves = Curves(timeline, rng)
    Traffic(
        writer, "accounts-api", 3.0, ["/v1/accounts", "/v1/accounts/balance", "/healthz"]
    ).routine(timeline)
    Traffic(writer, "kyc-worker", 0.8, ["/verify"]).routine(timeline)
    for minute in (13, 44, 69):
        writer.add(
            "kyc-worker",
            timeline.at(minute),
            "error",
            "webhook from idv-provider rejected: signature timestamp outside 300s tolerance",
        )

    onset = 52.0
    writer.add(
        "accounts-api",
        timeline.at(1),
        "info",
        "HikariPool-1 - configuration: maximumPoolSize=10 minimumIdle=10 connectionTimeout=30000",
    )
    for minute in range(5, 81, 5):
        busy = minute >= onset
        active = 10 if busy else rng.randint(3, 7)
        writer.add(
            "accounts-api",
            timeline.at(minute),
            "info",
            f"HikariPool-1 - Pool stats (total=10, active={active}, idle={10 - active}, "
            f"waiting={rng.randint(31, 64) if busy else 0})",
        )
    repeat(
        writer,
        "accounts-api",
        "error",
        start=timeline.at(onset) + timedelta(seconds=35),
        end=timeline.end,
        gap=(30, 12),
        message=lambda _: (
            "GET /v1/accounts/balance 500 SQLTransientConnectionException: HikariPool-1 - "
            "Connection is not available, request timed out after 30000ms"
        ),
    )
    for minute in range(4, 81, 8):
        writer.add(
            "accounts-db",
            timeline.at(minute),
            "info",
            f"stats: connections={rng.randint(28, 31)}/400 active_queries={rng.randint(1, 5)} "
            f"slow_queries=0 avg_query_ms={rng.uniform(2.5, 4.5):.1f}",
        )

    metrics = {
        "accounts-api": dumps_series(
            "accounts-api",
            timeline,
            {
                MetricName.req_rate: curves.shaped("ramp", 214, 8, onset=40, peak=318),
                MetricName.latency_p95_ms: curves.shaped("step", 58, 5, onset=onset, peak=30000),
                MetricName.error_rate: curves.shaped(
                    "step", 0.002, 0.001, onset=onset, peak=0.29, decimals=3
                ),
                MetricName.cpu_pct: curves.flat(33, 3),
            },
        ),
        "accounts-db": dumps_series(
            "accounts-db",
            timeline,
            {
                MetricName.db_latency_ms: curves.flat(4, 0.6),
                MetricName.cpu_pct: curves.flat(22, 2),
            },
        ),
    }
    deploy = make_deploy(
        rng,
        deploy_id="dpl-19d4",
        service="accounts-api",
        ts="2026-10-19T15:40:00Z",
        author="hana",
        summary="accounts-api: return currency code with balance",
        diff=(
            "--- a/accounts/src/main/java/acme/accounts/BalanceView.java\n"
            "+++ b/accounts/src/main/java/acme/accounts/BalanceView.java\n"
            "@@ -9,3 +9,4 @@ public record BalanceView(\n"
            "     long minorUnits,\n"
            "+    String currency,\n"
        ),
    )
    return Built(
        incident=Incident(
            id="S09",
            title="Balance lookups hang through the morning peak",
            split="heldout",
            difficulty="medium",
            flags=[],
            postmortem_id="pm-2026-04-accounts-pool",
            alert=alert("accounts-api", timeline.alert_at, "accounts-api p95 above 10s"),
            seed=seed,
        ),
        truth=Truth(
            root_cause=RootCause.resource_exhaustion,
            service="accounts-api",
            summary=(
                "accounts-api's Hikari pool is capped at 10 connections per replica; as morning "
                "traffic rose it sat at active=10, idle=0 with dozens waiting from 08:52, and "
                "requests time out after 30 s while accounts-db stays at about 4 ms with 30 of "
                "400 connections used."
            ),
            acceptable_fixes=[FixClass.config_change],
            must_find=[
                MustFind(file="logs/accounts-api.jsonl", pattern="Connection is not available"),
                MustFind(file="logs/accounts-api.jsonl", pattern="active=10, idle=0"),
                MustFind(file="metrics/accounts-db.json", pattern="db_latency_ms"),
            ],
            escalation_ok=False,
        ),
        writer=writer,
        metrics=metrics,
        deploys=[deploy],
    )


def s09b_knex_pool_exhausted() -> Built:
    seed = 2909
    rng = random.Random(seed)
    timeline = Timeline(
        start=utc("2026-10-26T18:00:00Z"),
        step_seconds=60,
        points=72,
        alert_at=utc("2026-10-26T19:09:00Z"),
    )
    writer = LogWriter(rng=rng)
    curves = Curves(timeline, rng)
    Traffic(writer, "wallet-api", 2.6, ["/v1/wallet", "/v1/wallet/topup", "/healthz"]).routine(
        timeline
    )
    Traffic(writer, "push-notifier", 0.9, ["/push"]).routine(timeline)
    for minute in (9, 33, 58):
        writer.add(
            "push-notifier",
            timeline.at(minute),
            "error",
            f"APNs 410 Unregistered for device token {rng.getrandbits(40):010x}, removing",
        )

    onset = 41.0
    writer.add(
        "wallet-api",
        timeline.at(2),
        "info",
        "db: knex pool min=2 max=10 acquireConnectionTimeout=2000",
    )
    for minute in range(4, 71, 6):
        busy = minute >= onset
        used = 10 if busy else rng.randint(2, 6)
        writer.add(
            "wallet-api",
            timeline.at(minute),
            "info",
            f"pool: used={used} free={10 - used} pending={rng.randint(90, 160) if busy else 0} max=10",
        )
    repeat(
        writer,
        "wallet-api",
        "error",
        start=timeline.at(onset) + timedelta(seconds=20),
        end=timeline.end,
        gap=(26, 10),
        message=lambda _: (
            "POST /v1/wallet/topup 500 KnexTimeoutError: Knex: Timeout acquiring a connection. "
            "The pool is probably full."
        ),
    )
    for minute in range(3, 71, 9):
        writer.add(
            "wallet-db",
            timeline.at(minute),
            "info",
            f"pgbouncer stats: {rng.randint(21, 29)} xacts/s, {rng.randint(28, 36)} queries/s, "
            f"avg wait {rng.randint(0, 40)} us, cl_active={rng.randint(18, 22)}/200",
        )

    metrics = {
        "wallet-api": dumps_series(
            "wallet-api",
            timeline,
            {
                MetricName.req_rate: curves.shaped("ramp", 172, 7, onset=30, peak=260),
                MetricName.latency_p95_ms: curves.shaped("step", 46, 4, onset=onset, peak=2010),
                MetricName.error_rate: curves.shaped(
                    "step", 0.003, 0.001, onset=onset, peak=0.34, decimals=3
                ),
                MetricName.cpu_pct: curves.flat(29, 2),
                MetricName.mem_mb: curves.flat(260, 5),
            },
        ),
        "wallet-db": dumps_series(
            "wallet-db",
            timeline,
            {MetricName.db_latency_ms: curves.flat(3, 0.5), MetricName.cpu_pct: curves.flat(17, 2)},
        ),
    }
    return Built(
        incident=Incident(
            id="S09b",
            title="Wallet top-ups fail during the evening promotion",
            split="heldout",
            difficulty="medium",
            flags=[],
            postmortem_id="pm-2026-07-wallet-pool",
            alert=alert("wallet-api", timeline.alert_at, "wallet top-up error rate above 30%"),
            seed=seed,
        ),
        truth=Truth(
            root_cause=RootCause.resource_exhaustion,
            service="wallet-api",
            summary=(
                "wallet-api's knex pool is capped at max=10; as promotion traffic rose it ran "
                "with free=0 and over a hundred pending acquires from 18:41, so top-ups fail with "
                "Knex acquire timeouts while wallet-db latency stays near 3 ms."
            ),
            acceptable_fixes=[FixClass.config_change],
            must_find=[
                MustFind(file="logs/wallet-api.jsonl", pattern="Timeout acquiring a connection"),
                MustFind(file="logs/wallet-api.jsonl", pattern="free=0 pending="),
                MustFind(file="metrics/wallet-db.json", pattern="db_latency_ms"),
            ],
            escalation_ok=False,
        ),
        writer=writer,
        metrics=metrics,
        deploys=[],
    )


def s10_bff_retry_storm() -> Built:
    seed = 1010
    rng = random.Random(seed)
    timeline = Timeline(
        start=utc("2026-10-27T11:00:00Z"),
        step_seconds=60,
        points=70,
        alert_at=utc("2026-10-27T12:06:00Z"),
    )
    writer = LogWriter(rng=rng)
    curves = Curves(timeline, rng)
    Traffic(writer, "mobile-bff", 2.4, ["/m/home", "/m/profile", "/healthz"]).routine(timeline)
    Traffic(writer, "profile-api", 1.8, ["/v1/profile", "/healthz"]).routine(timeline)
    Traffic(writer, "web-bff", 1.0, ["/w/home"]).routine(timeline)
    for minute in (12, 35, 61):
        writer.add(
            "web-bff",
            timeline.at(minute),
            "error",
            "session decrypt failed: cookie format v1 no longer supported, forcing re-login",
        )

    blip = 38.0
    writer.add(
        "mobile-bff",
        timeline.at(1),
        "info",
        "httpclient[profile-api] policy: timeout_ms=500 max_retries=6 backoff_ms=0 jitter=off",
    )
    writer.add(
        "profile-api",
        timeline.at(blip),
        "warn",
        "pod profile-api-6f8c drained for node upgrade; 2 of 3 replicas serving",
    )
    writer.add(
        "profile-api",
        timeline.at(blip + 0.75),
        "info",
        "pod profile-api-6f8c ready; 3 of 3 replicas serving",
    )
    repeat(
        writer,
        "mobile-bff",
        "warn",
        start=timeline.at(blip) + timedelta(seconds=5),
        end=timeline.end,
        gap=(20, 10),
        message=lambda _: (
            f"GET profile-api/v1/profile/u-{rng.randint(10000, 99999)} attempt "
            f"{rng.randint(2, 7)} of 7 failed (503), retrying in 0ms"
        ),
    )
    repeat(
        writer,
        "profile-api",
        "error",
        start=timeline.at(blip + 1),
        end=timeline.end,
        gap=(45, 15),
        message=lambda _: (
            f"inbound {rng.randint(2150, 2450)} req/s exceeds 600 req/s soft limit, "
            "shedding with 503"
        ),
    )
    for minute in range(42, 70, 6):
        writer.add(
            "profile-api",
            timeline.at(minute),
            "info",
            f"top callers last 60s: mobile-bff {rng.randint(91, 95)}%, web-bff 4%, admin 1%",
        )

    metrics = {
        "profile-api": dumps_series(
            "profile-api",
            timeline,
            {
                MetricName.req_rate: curves.shaped("step", 382, 14, onset=blip, peak=2310),
                MetricName.error_rate: curves.shaped(
                    "step", 0.002, 0.001, onset=blip, peak=0.66, decimals=3
                ),
                MetricName.latency_p95_ms: curves.shaped("step", 41, 4, onset=blip, peak=480),
                MetricName.cpu_pct: curves.shaped("step", 31, 3, onset=blip, peak=88),
            },
        ),
        "mobile-bff": dumps_series(
            "mobile-bff",
            timeline,
            {
                MetricName.req_rate: curves.flat(338, 12),
                MetricName.error_rate: curves.shaped(
                    "step", 0.004, 0.002, onset=blip, peak=0.41, decimals=3
                ),
            },
        ),
    }
    return Built(
        incident=Incident(
            id="S10",
            title="Profile service overloaded long after a pod came back",
            split="heldout",
            difficulty="medium",
            flags=[],
            postmortem_id="pm-2026-06-profile-retry-storm",
            alert=alert(
                "profile-api", timeline.alert_at, "profile-api 503 rate above 60% for 20 minutes"
            ),
            seed=seed,
        ),
        truth=Truth(
            root_cause=RootCause.misconfiguration,
            service="mobile-bff",
            summary=(
                "A 45-second pod drain on profile-api at 11:38 tripped mobile-bff's retry policy "
                "(6 retries, backoff_ms=0, no jitter); immediate retries multiplied load to about "
                "2300 req/s against a 600 req/s limit and kept it there after the pod returned, "
                "while mobile-bff's own inbound traffic stayed flat."
            ),
            acceptable_fixes=[FixClass.config_change, FixClass.restart_service],
            must_find=[
                MustFind(file="logs/mobile-bff.jsonl", pattern="backoff_ms=0"),
                MustFind(file="logs/mobile-bff.jsonl", pattern="retrying in 0ms"),
                MustFind(file="logs/profile-api.jsonl", pattern="top callers last 60s: mobile-bff"),
                MustFind(file="metrics/profile-api.json", pattern="req_rate"),
            ],
            escalation_ok=False,
        ),
        writer=writer,
        metrics=metrics,
        deploys=[],
    )


def s10b_dispatcher_retry_storm() -> Built:
    seed = 3010
    rng = random.Random(seed)
    timeline = Timeline(
        start=utc("2026-10-28T19:00:00Z"),
        step_seconds=60,
        points=80,
        alert_at=utc("2026-10-28T20:13:00Z"),
    )
    writer = LogWriter(rng=rng)
    curves = Curves(timeline, rng)
    Traffic(writer, "notify-dispatcher", 2.2, ["/dispatch", "/healthz"]).routine(timeline)
    Traffic(writer, "templates-api", 1.6, ["/templates.v1.Render"]).routine(timeline)
    Traffic(writer, "unsubscribe-api", 0.9, ["/u"]).routine(timeline)
    for minute in (17, 49, 71):
        writer.add(
            "unsubscribe-api",
            timeline.at(minute),
            "error",
            f"list-unsubscribe token t-{rng.getrandbits(24):06x} expired (issued 31d ago)",
        )

    blip = 47.0
    writer.add(
        "notify-dispatcher",
        timeline.at(2),
        "info",
        "grpc retry policy templates.v1.Render: maxAttempts=8 initialBackoff=0s "
        "backoffMultiplier=1 retryableStatusCodes=[UNAVAILABLE, DEADLINE_EXCEEDED]",
    )
    writer.add(
        "templates-api",
        timeline.at(blip),
        "warn",
        "leader election: lease lost, renderer cache rebuilding",
    )
    writer.add(
        "templates-api",
        timeline.at(blip) + timedelta(seconds=14),
        "info",
        "leader election: lease acquired, renderer cache warm",
    )
    repeat(
        writer,
        "notify-dispatcher",
        "warn",
        start=timeline.at(blip) + timedelta(seconds=20),
        end=timeline.end,
        gap=(40, 15),
        message=lambda _: (
            f"Render for batch b-{rng.randint(100000, 999999)} exhausted 8 attempts "
            "(last status UNAVAILABLE), requeueing batch"
        ),
    )
    repeat(
        writer,
        "templates-api",
        "error",
        start=timeline.at(blip + 1),
        end=timeline.end,
        gap=(50, 15),
        message=lambda _: (
            f"concurrency limiter rejecting {rng.randint(66, 76)}% of calls: inbound "
            f"{rng.uniform(5.6, 6.2):.1f}k rps against 0.8k baseline"
        ),
    )
    for minute in range(50, 80, 7):
        writer.add(
            "templates-api",
            timeline.at(minute),
            "info",
            f"callers last 60s: notify-dispatcher {rng.randint(96, 99)}%, admin-ui 1%",
        )

    metrics = {
        "templates-api": dumps_series(
            "templates-api",
            timeline,
            {
                MetricName.req_rate: curves.shaped("step", 810, 25, onset=blip, peak=5900),
                MetricName.error_rate: curves.shaped(
                    "step", 0.001, 0.0005, onset=blip, peak=0.71, decimals=3
                ),
                MetricName.cpu_pct: curves.shaped("step", 36, 3, onset=blip, peak=93),
            },
        ),
        "notify-dispatcher": dumps_series(
            "notify-dispatcher",
            timeline,
            {
                MetricName.req_rate: curves.flat(118, 6),
                MetricName.latency_p95_ms: curves.shaped("step", 420, 30, onset=blip, peak=14200),
                MetricName.error_rate: curves.shaped(
                    "step", 0.003, 0.001, onset=blip, peak=0.52, decimals=3
                ),
            },
        ),
    }
    return Built(
        incident=Incident(
            id="S10b",
            title="Notification batches stuck after a renderer hiccup",
            split="heldout",
            difficulty="medium",
            flags=[],
            postmortem_id="pm-2026-09-dispatcher-retries",
            alert=alert(
                "notify-dispatcher", timeline.alert_at, "notify-dispatcher dispatch p95 above 10s"
            ),
            seed=seed,
        ),
        truth=Truth(
            root_cause=RootCause.misconfiguration,
            service="notify-dispatcher",
            summary=(
                "A 14-second leader election on templates-api at 19:47 triggered "
                "notify-dispatcher's gRPC retry policy (8 attempts, initialBackoff=0s, "
                "multiplier 1); zero-backoff retries pushed templates-api from about 0.8k to 5.9k "
                "rps and kept it saturated after it recovered."
            ),
            acceptable_fixes=[FixClass.config_change, FixClass.restart_service],
            must_find=[
                MustFind(file="logs/notify-dispatcher.jsonl", pattern="initialBackoff=0s"),
                MustFind(file="logs/notify-dispatcher.jsonl", pattern="exhausted 8 attempts"),
                MustFind(file="metrics/templates-api.json", pattern="req_rate"),
            ],
            escalation_ok=False,
        ),
        writer=writer,
        metrics=metrics,
        deploys=[],
    )


def s11_gateway_rate_limit() -> Built:
    seed = 1111
    rng = random.Random(seed)
    timeline = Timeline(
        start=utc("2026-10-29T15:00:00Z"),
        step_seconds=60,
        points=68,
        alert_at=utc("2026-10-29T16:02:00Z"),
    )
    writer = LogWriter(rng=rng)
    curves = Curves(timeline, rng)
    Traffic(writer, "public-api", 3.4, ["/v2/orders", "/v2/products", "/healthz"]).routine(timeline)
    Traffic(writer, "developer-portal", 0.6, ["/docs", "/keys"]).routine(timeline)
    Traffic(writer, "webhooks-out", 0.8, ["/deliver"]).routine(timeline)
    for minute in (10, 38, 57):
        writer.add(
            "webhooks-out",
            timeline.at(minute),
            "error",
            "delivery to https://partner.example.test/hook timed out after 10000ms; will retry",
        )

    onset = 31.0
    for minute in range(5, 68, 10):
        writer.add(
            "public-api",
            timeline.at(minute),
            "info",
            f"usage: top key ak-3f2a91 {rng.randint(395, 430)} req/min, ak-77c0e2 "
            f"{rng.randint(180, 215)} req/min",
        )
    writer.add(
        "public-api",
        timeline.at(onset),
        "info",
        "ratelimit: reloaded policy from etcd /config/ratelimit/public-api revision 5512: "
        "tier=standard limit=60/min",
    )
    repeat(
        writer,
        "public-api",
        "warn",
        start=timeline.at(onset) + timedelta(seconds=10),
        end=timeline.end,
        gap=(22, 10),
        message=lambda _: (
            f"GET /v2/orders 429 key={rng.choice(['ak-3f2a91', 'ak-77c0e2'])} tier=standard "
            "used=60/60 window=60s"
        ),
    )
    repeat(
        writer,
        "developer-portal",
        "warn",
        start=timeline.at(onset + 6),
        end=timeline.end,
        gap=(420, 60),
        message=lambda _: (
            f"support ticket from acct-{rng.randint(1000, 9999)}: integration receiving 429 at "
            "normal volume"
        ),
    )

    metrics = {
        "public-api": dumps_series(
            "public-api",
            timeline,
            {
                MetricName.error_rate: curves.shaped(
                    "step", 0.002, 0.001, onset=onset, peak=0.38, decimals=3
                ),
                MetricName.req_rate: curves.flat(412, 14),
                MetricName.latency_p95_ms: curves.flat(72, 6),
                MetricName.cpu_pct: curves.flat(27, 2),
            },
        ),
    }
    deploy = make_deploy(
        rng,
        deploy_id="dpl-5a02",
        service="public-api",
        ts="2026-10-28T13:30:00Z",
        author="omar",
        summary="public-api: document sort parameter on /v2/orders",
        diff=(
            "--- a/public_api/openapi.yaml\n"
            "+++ b/public_api/openapi.yaml\n"
            "@@ -212,2 +212,5 @@ paths:\n"
            "       parameters:\n"
            "+        - name: sort\n"
            "+          in: query\n"
            "+          schema: {type: string, enum: [created, total]}\n"
        ),
    )
    return Built(
        incident=Incident(
            id="S11",
            title="API customers throttled at normal volume",
            split="heldout",
            difficulty="easy",
            flags=[],
            postmortem_id="pm-2026-05-public-api-ratelimit",
            alert=alert("public-api", timeline.alert_at, "public-api 429 share above 30%"),
            seed=seed,
        ),
        truth=Truth(
            root_cause=RootCause.misconfiguration,
            service="public-api",
            summary=(
                "At 15:31 public-api reloaded rate-limit policy revision 5512 from etcd with the "
                "standard tier at 60 requests per minute, far below the 200 to 430 req/min that "
                "its top keys send all afternoon, so legitimate traffic gets 429."
            ),
            acceptable_fixes=[FixClass.config_change, FixClass.rollback_deploy],
            must_find=[
                MustFind(file="logs/public-api.jsonl", pattern="revision 5512"),
                MustFind(file="logs/public-api.jsonl", pattern="used=60/60"),
                MustFind(file="metrics/public-api.json", pattern="error_rate"),
            ],
            escalation_ok=False,
        ),
        writer=writer,
        metrics=metrics,
        deploys=[deploy],
    )


def s11b_search_burst_limit() -> Built:
    seed = 3111
    rng = random.Random(seed)
    timeline = Timeline(
        start=utc("2026-11-02T10:00:00Z"),
        step_seconds=60,
        points=86,
        alert_at=utc("2026-11-02T11:21:00Z"),
    )
    writer = LogWriter(rng=rng)
    curves = Curves(timeline, rng)
    Traffic(writer, "search-gateway", 2.6, ["/v2/search", "/v2/suggest", "/healthz"]).routine(
        timeline
    )
    Traffic(writer, "storefront-web", 1.4, ["/", "/s"]).routine(timeline)
    Traffic(writer, "search-backend", 0.8, ["/query"]).routine(timeline)
    for minute in (19, 46, 77):
        writer.add(
            "storefront-web",
            timeline.at(minute),
            "error",
            "analytics beacon POST https://collect.example.test/b returned 400 invalid schema v7",
        )

    onset = 55.0
    writer.add(
        "search-gateway",
        timeline.at(onset),
        "info",
        "admin: PUT /admin/ratelimits/search actor=ops-bot burst=50 refill_per_s=5 "
        "(was burst=500 refill_per_s=50)",
    )
    repeat(
        writer,
        "search-gateway",
        "warn",
        start=timeline.at(onset) + timedelta(seconds=8),
        end=timeline.end,
        gap=(18, 8),
        message=lambda _: (
            "GET /v2/search 429 x-ratelimit-remaining=0 route=search client=storefront-web"
        ),
    )
    repeat(
        writer,
        "storefront-web",
        "warn",
        start=timeline.at(onset + 1),
        end=timeline.end,
        gap=(150, 40),
        message=lambda _: "search degraded: search-gateway returned 429, showing cached results",
    )
    for minute in range(6, 86, 10):
        qps = rng.randint(570, 610) if minute < onset else rng.randint(310, 345)
        writer.add(
            "search-backend",
            timeline.at(minute),
            "info",
            f"search-backend: qps {qps} p95 {rng.randint(36, 46)}ms heap 61%",
        )

    metrics = {
        "search-gateway": dumps_series(
            "search-gateway",
            timeline,
            {
                MetricName.error_rate: curves.shaped(
                    "step", 0.001, 0.0005, onset=onset, peak=0.45, decimals=3
                ),
                MetricName.req_rate: curves.flat(603, 18),
                MetricName.latency_p95_ms: curves.flat(48, 4),
            },
        ),
        "search-backend": dumps_series(
            "search-backend",
            timeline,
            {
                MetricName.req_rate: curves.shaped("step", 592, 12, onset=onset, peak=331),
                MetricName.latency_p95_ms: curves.flat(41, 3),
                MetricName.cpu_pct: curves.shaped("step", 44, 3, onset=onset, peak=26),
            },
        ),
    }
    return Built(
        incident=Incident(
            id="S11b",
            title="Shoppers see stale search results",
            split="heldout",
            difficulty="medium",
            flags=[],
            postmortem_id="pm-2026-10-search-burst-limit",
            alert=alert("search-gateway", timeline.alert_at, "search-gateway 429 rate above 40%"),
            seed=seed,
        ),
        truth=Truth(
            root_cause=RootCause.misconfiguration,
            service="search-gateway",
            summary=(
                "An admin API change at 10:55 cut the search route's rate limit from burst 500 / "
                "50 per second to burst 50 / 5 per second; search-gateway now answers 429 to "
                "normal storefront traffic while search-backend is healthy and idle."
            ),
            acceptable_fixes=[FixClass.config_change, FixClass.rollback_deploy],
            must_find=[
                MustFind(file="logs/search-gateway.jsonl", pattern="was burst=500"),
                MustFind(file="logs/search-gateway.jsonl", pattern="x-ratelimit-remaining=0"),
                MustFind(file="metrics/search-backend.json", pattern="req_rate"),
            ],
            escalation_ok=False,
        ),
        writer=writer,
        metrics=metrics,
        deploys=[],
    )


def s12_coredns_watch_lost() -> Built:
    seed = 1212
    rng = random.Random(seed)
    timeline = Timeline(
        start=utc("2026-11-03T03:00:00Z"),
        step_seconds=60,
        points=72,
        alert_at=utc("2026-11-03T04:08:00Z"),
    )
    writer = LogWriter(rng=rng)
    curves = Curves(timeline, rng)
    Traffic(writer, "orders-api", 1.8, ["/v1/orders", "/healthz"]).routine(timeline)
    Traffic(writer, "cart-api", 1.6, ["/v1/cart", "/healthz"]).routine(timeline)
    Traffic(writer, "auth-api", 1.2, ["/oauth/token"]).routine(timeline)
    for minute in (7, 36, 63):
        writer.add(
            "auth-api",
            timeline.at(minute),
            "error",
            f"ldap sync: {rng.randint(2, 5)} users skipped, missing mail attribute",
        )

    onset = 40.0
    writer.add(
        "coredns",
        timeline.at(1),
        "info",
        "[INFO] plugin/reload: Running configuration SHA512 = 6a1f0c9e2b",
    )
    for minute in range(5, 40, 9):
        writer.add(
            "coredns",
            timeline.at(minute),
            "info",
            f"[INFO] 10.244.{rng.randint(1, 6)}.{rng.randint(2, 250)}:{rng.randint(30000, 60000)} - "
            f"A IN orders-db.prod.svc.cluster.local. udp NOERROR qr,aa,rd {rng.randint(1, 3)}ms",
        )
    writer.add(
        "coredns",
        timeline.at(onset) - timedelta(seconds=20),
        "error",
        "[ERROR] plugin/kubernetes: Failed to watch *v1.EndpointSlice: the server has asked "
        "for the client to try again later",
    )
    repeat(
        writer,
        "coredns",
        "error",
        start=timeline.at(onset) + timedelta(seconds=5),
        end=timeline.end,
        gap=(35, 15),
        message=lambda _: (
            f"[ERROR] plugin/errors: 2 {rng.choice(['cart-api', 'redis', 'auth-api', 'orders-db'])}"
            ".prod.svc.cluster.local. A: dial tcp 10.96.0.1:443: i/o timeout"
        ),
    )
    writer.add(
        "coredns",
        timeline.at(onset + 3),
        "warn",
        "[WARNING] plugin/health: Local health request to http://:8080/health took more than 1s: 1.4s",
    )
    for service, target in (
        ("orders-api", "cart-api"),
        ("cart-api", "redis"),
        ("auth-api", "orders-db"),
    ):
        repeat(
            writer,
            service,
            "error",
            start=timeline.at(onset) + timedelta(seconds=rng.randint(10, 40)),
            end=timeline.end,
            gap=(55, 20),
            message=lambda _, target=target: (
                f"dial tcp: lookup {target}.prod.svc.cluster.local on 10.96.0.10:53: "
                "server misbehaving"
            ),
        )

    metrics = {
        "coredns": dumps_series(
            "coredns",
            timeline,
            {
                MetricName.latency_p95_ms: curves.shaped("step", 2, 0.4, onset=onset, peak=1900),
                MetricName.error_rate: curves.shaped(
                    "step", 0.0005, 0.0002, onset=onset, peak=0.41, decimals=4
                ),
                MetricName.cpu_pct: curves.shaped("step", 12, 2, onset=onset, peak=29),
            },
        ),
        "orders-api": dumps_series(
            "orders-api",
            timeline,
            {
                MetricName.error_rate: curves.shaped(
                    "step", 0.003, 0.001, onset=onset, peak=0.36, decimals=3
                ),
                MetricName.cpu_pct: curves.flat(21, 2),
            },
        ),
        "cart-api": dumps_series(
            "cart-api",
            timeline,
            {
                MetricName.error_rate: curves.shaped(
                    "step", 0.004, 0.001, onset=onset, peak=0.33, decimals=3
                )
            },
        ),
    }
    return Built(
        incident=Incident(
            id="S12",
            title="Lookups fail across the cluster overnight",
            split="heldout",
            difficulty="medium",
            flags=[],
            postmortem_id="pm-2026-08-coredns-watch",
            alert=alert(
                "orders-api",
                timeline.alert_at,
                "orders-api 5xx above 30%, cart-api and auth-api also erroring",
            ),
            seed=seed,
        ),
        truth=Truth(
            root_cause=RootCause.network_dns,
            service="coredns",
            summary=(
                "At 03:40 CoreDNS lost its Kubernetes EndpointSlice watch and its API calls time "
                "out, so in-cluster lookups fail with server misbehaving across orders-api, "
                "cart-api and auth-api; each service's own resources are normal."
            ),
            acceptable_fixes=[FixClass.restart_service, FixClass.escalate_human],
            must_find=[
                MustFind(file="logs/orders-api.jsonl", pattern="server misbehaving"),
                MustFind(file="logs/coredns.jsonl", pattern="Failed to watch *v1.EndpointSlice"),
                MustFind(file="metrics/coredns.json", pattern="error_rate"),
            ],
            escalation_ok=True,
        ),
        writer=writer,
        metrics=metrics,
        deploys=[],
    )


def s12b_consul_no_leader() -> Built:
    seed = 3212
    rng = random.Random(seed)
    timeline = Timeline(
        start=utc("2026-11-04T12:00:00Z"),
        step_seconds=60,
        points=84,
        alert_at=utc("2026-11-04T13:16:00Z"),
    )
    writer = LogWriter(rng=rng)
    curves = Curves(timeline, rng)
    Traffic(writer, "checkout-api", 2.2, ["/v1/checkout", "/healthz"]).routine(timeline)
    Traffic(writer, "shipping-quotes", 1.1, ["/v1/quote"]).routine(timeline)
    Traffic(writer, "inventory", 1.3, ["/v1/stock"]).routine(timeline)
    for minute in (15, 42, 70):
        writer.add(
            "checkout-api",
            timeline.at(minute),
            "error",
            "receipt printer webhook https://pos.example.test/print returned 401, skipping",
        )

    onset = 51.0
    for minute in range(3, 50, 8):
        writer.add(
            "consul",
            timeline.at(minute),
            "info",
            f"agent: Synced service: service={rng.choice(['inventory', 'pricing', 'checkout-api'])}",
        )
    writer.add(
        "consul",
        timeline.at(onset) - timedelta(seconds=30),
        "warn",
        "raft: heartbeat timeout reached, starting election: last-leader-addr=10.0.5.11:8300",
    )
    repeat(
        writer,
        "consul",
        "warn",
        start=timeline.at(onset),
        end=timeline.end,
        gap=(60, 20),
        message=lambda _: "raft: Election timeout reached, restarting election",
    )
    repeat(
        writer,
        "consul",
        "error",
        start=timeline.at(onset) + timedelta(seconds=10),
        end=timeline.end,
        gap=(40, 15),
        message=lambda _: (
            f"agent.dns: rpc error: No cluster leader, query inventory.service.consul from "
            f"127.0.0.1:{rng.randint(40000, 60000)}"
        ),
    )
    repeat(
        writer,
        "checkout-api",
        "error",
        start=timeline.at(onset) + timedelta(seconds=25),
        end=timeline.end,
        gap=(45, 15),
        message=lambda _: (
            "POST /v1/checkout 503 lookup inventory.service.consul on 127.0.0.1:8600: no such host"
        ),
    )
    repeat(
        writer,
        "shipping-quotes",
        "error",
        start=timeline.at(onset) + timedelta(seconds=40),
        end=timeline.end,
        gap=(70, 20),
        message=lambda _: (
            "consul catalog query for service pricing returned 500: No cluster leader"
        ),
    )

    metrics = {
        "consul": dumps_series(
            "consul",
            timeline,
            {
                MetricName.error_rate: curves.shaped(
                    "step", 0.0003, 0.0001, onset=onset, peak=0.88, decimals=4
                ),
                MetricName.latency_p95_ms: curves.shaped("step", 3, 0.5, onset=onset, peak=2000),
                MetricName.cpu_pct: curves.flat(9, 1.5),
            },
        ),
        "checkout-api": dumps_series(
            "checkout-api",
            timeline,
            {
                MetricName.error_rate: curves.shaped(
                    "step", 0.004, 0.002, onset=onset, peak=0.47, decimals=3
                ),
                MetricName.cpu_pct: curves.flat(26, 2),
            },
        ),
        "inventory": dumps_series(
            "inventory",
            timeline,
            {
                MetricName.req_rate: curves.shaped("step", 160, 6, onset=onset, peak=22),
                MetricName.cpu_pct: curves.flat(18, 2),
            },
        ),
    }
    deploy = make_deploy(
        rng,
        deploy_id="dpl-8b61",
        service="shipping-quotes",
        ts="2026-11-03T17:20:00Z",
        author="ravi",
        summary="shipping-quotes: add pallet size option",
        diff=(
            "--- a/shipping_quotes/sizes.py\n"
            "+++ b/shipping_quotes/sizes.py\n"
            "@@ -3,2 +3,3 @@ SIZES = {\n"
            '     "parcel": (60, 40, 40),\n'
            '+    "pallet": (120, 100, 150),\n'
        ),
    )
    return Built(
        incident=Incident(
            id="S12b",
            title="Checkout cannot find inventory",
            split="heldout",
            difficulty="medium",
            flags=[],
            postmortem_id="pm-2026-01-consul-quorum",
            alert=alert("checkout-api", timeline.alert_at, "checkout-api 503 rate above 40%"),
            seed=seed,
        ),
        truth=Truth(
            root_cause=RootCause.network_dns,
            service="consul",
            summary=(
                "The Consul servers lost their raft leader at 12:51 and keep re-electing, so "
                "Consul DNS and catalog queries fail with No cluster leader; checkout-api and "
                "shipping-quotes cannot resolve inventory or pricing while inventory itself is "
                "healthy but idle."
            ),
            acceptable_fixes=[FixClass.restart_service, FixClass.escalate_human],
            must_find=[
                MustFind(file="logs/consul.jsonl", pattern="No cluster leader"),
                MustFind(file="logs/checkout-api.jsonl", pattern="inventory.service.consul"),
                MustFind(file="metrics/consul.json", pattern="error_rate"),
            ],
            escalation_ok=True,
        ),
        writer=writer,
        metrics=metrics,
        deploys=[deploy],
    )
