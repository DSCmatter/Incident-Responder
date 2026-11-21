"""Dev-split builders S04 to S08: dependency, disk, config, capacity and certificate faults.

Same rule as scenarios.py: a careful human can name the cause and the fix from
the evidence alone, and no single log line states the cause.
"""

from __future__ import annotations

import random
from datetime import timedelta

from agents.schemas import FixClass, RootCause
from demo_env.faults.base import Built, capped, make_deploy
from demo_env.faults.render import LogWriter, Timeline, Traffic, alert, curve, dumps_series, utc
from demo_env.models import Incident, MetricName, MetricPoint, MustFind, Truth


def _smtp_noise(writer: LogWriter, timeline: Timeline, minute: float) -> None:
    writer.add(
        "email-sender",
        timeline.at(minute),
        "warn",
        "smtp relay smtp.internal:25 timeout after 5000ms, retrying in 30s",
    )
    writer.add(
        "email-sender",
        timeline.at(minute + 0.5),
        "info",
        "smtp relay accepted 9 messages after retry",
    )


def s04_dependency_timeout() -> Built:
    rng = random.Random(404)
    timeline = Timeline(
        start=utc("2026-11-15T14:00:00Z"),
        step_seconds=60,
        points=90,
        alert_at=utc("2026-11-15T15:22:00Z"),
    )
    writer = LogWriter(rng=rng)
    Traffic(writer, "shipping-api", 2.5, ["/v1/rates", "/v1/labels", "/healthz"]).routine(timeline)
    Traffic(writer, "email-sender", 0.4, ["/send"]).routine(timeline)
    _smtp_noise(writer, timeline, 12)

    onset = 62.0
    for minute in range(1, 89, 6):
        writer.add(
            "shipping-api",
            timeline.at(minute),
            "info",
            f"pool stats: db_conns in_use={rng.randint(3, 6)}/40 heap_mb={rng.randint(205, 232)} "
            f"goroutines={rng.randint(140, 170)}",
        )
    moment = timeline.at(onset)
    while moment <= timeline.end:
        writer.add(
            "shipping-api",
            moment,
            "error",
            f"POST /v1/labels 504 dur_ms={10000 + rng.randint(0, 9)} upstream=parcelhub "
            "url=https://api.parcelhub.example/v3/labels err=context deadline exceeded "
            "(Client.Timeout exceeded while awaiting headers)",
        )
        moment += timedelta(seconds=45 + rng.randint(0, 9))
    for minute in (64, 70, 76, 82, 88):
        writer.add(
            "shipping-api",
            timeline.at(minute),
            "warn",
            f"parcelhub client: {rng.randint(38, 47)} of 50 calls timed out in the last 60s, "
            "retries=2, timeout_ms=10000",
        )

    metrics = {
        "shipping-api": dumps_series(
            "shipping-api",
            timeline,
            {
                MetricName.req_rate: curve(timeline, "flat", base=150, noise=7, rng=rng),
                MetricName.error_rate: curve(
                    timeline,
                    "step",
                    base=0.006,
                    noise=0.002,
                    rng=rng,
                    onset_minutes=onset,
                    peak=0.44,
                    decimals=3,
                ),
                MetricName.latency_p95_ms: curve(
                    timeline, "step", base=210, noise=12, rng=rng, onset_minutes=onset, peak=10000
                ),
                MetricName.cpu_pct: curve(timeline, "flat", base=21, noise=2, rng=rng),
                MetricName.mem_mb: curve(timeline, "flat", base=220, noise=6, rng=rng),
            },
        ),
    }
    deploy = make_deploy(
        rng,
        deploy_id="dpl-c210",
        service="web",
        ts="2026-11-14T16:05:00Z",
        author="marco",
        summary="web: update footer links",
        diff=(
            "--- a/web/templates/footer.html\n"
            "+++ b/web/templates/footer.html\n"
            "@@ -4,3 +4,3 @@\n"
            '-  <a href="/careers">Jobs</a>\n'
            '+  <a href="/careers">Careers</a>\n'
        ),
    )
    return Built(
        incident=Incident(
            id="S04",
            title="Shipping labels fail while the carrier API hangs",
            split="dev",
            difficulty="medium",
            flags=[],
            postmortem_id="pm-2026-06-carrier-timeouts",
            alert=alert(
                "shipping-api", timeline.alert_at, "Shipping label creation error rate above 40%"
            ),
            seed=404,
        ),
        truth=Truth(
            root_cause=RootCause.dependency_failure,
            service="shipping-api",
            summary=(
                "From 15:02 the external carrier API api.parcelhub.example stopped answering "
                "within shipping-api's 10 s client timeout, so label calls return 504; "
                "shipping-api's own CPU, memory and database pool stayed normal."
            ),
            acceptable_fixes=[FixClass.config_change, FixClass.escalate_human],
            must_find=[
                MustFind(file="logs/shipping-api.jsonl", pattern="api.parcelhub.example"),
                MustFind(file="logs/shipping-api.jsonl", pattern="context deadline exceeded"),
            ],
            escalation_ok=True,
        ),
        writer=writer,
        metrics=metrics,
        deploys=[deploy],
    )


def s05_disk_full() -> Built:
    rng = random.Random(505)
    timeline = Timeline(
        start=utc("2026-11-16T02:00:00Z"),
        step_seconds=60,
        points=90,
        alert_at=utc("2026-11-16T03:25:00Z"),
    )
    writer = LogWriter(rng=rng)
    Traffic(writer, "ledger-writer", 3.0, ["/ingest", "/healthz"]).routine(timeline)
    Traffic(writer, "audit-api", 0.8, ["/v1/audit"]).routine(timeline)
    writer.add(
        "audit-api",
        timeline.at(15),
        "warn",
        "client 10.0.3.9 closed connection before response was written",
    )

    full = 58.0
    writer.add(
        "ledger-writer",
        timeline.at(30),
        "warn",
        "disk watcher: /var/lib/ledger 88% used (threshold 85%)",
    )
    writer.add("ledger-writer", timeline.at(45), "warn", "disk watcher: /var/lib/ledger 95% used")
    moment = timeline.at(full)
    batch = 4812
    while moment <= timeline.end:
        writer.add(
            "ledger-writer",
            moment,
            "error",
            f"flush batch {batch} failed: write /var/lib/ledger/wal/000{183 + (batch - 4812) // 9}.log: "
            "no space left on device; batch kept in memory",
        )
        batch += 1
        moment += timedelta(seconds=40 + rng.randint(0, 9))
    writer.add(
        "ledger-writer",
        timeline.at(60),
        "warn",
        "logrotate: compress /var/log/ledger/ledger.log.1 failed: No space left on device",
    )
    for index, minute in enumerate(range(62, 89, 5)):
        writer.add(
            "ledger-writer",
            timeline.at(minute),
            "info",
            f"ingest backlog {8000 + index * 9500} events",
        )
        writer.add(
            "audit-api",
            timeline.at(minute + 1),
            "warn",
            f"ledger ack lag {20 + index * 14}s for /v1/audit writes",
        )

    disk_peak = 71 + (100 - 71) * 89 / full
    metrics = {
        "ledger-writer": dumps_series(
            "ledger-writer",
            timeline,
            {
                MetricName.disk_used_pct: capped(
                    curve(
                        timeline,
                        "ramp",
                        base=71,
                        noise=0.2,
                        rng=rng,
                        onset_minutes=0,
                        peak=disk_peak,
                    ),
                    100.0,
                ),
                MetricName.error_rate: curve(
                    timeline,
                    "step",
                    base=0.002,
                    noise=0.001,
                    rng=rng,
                    onset_minutes=full,
                    peak=0.93,
                    decimals=3,
                ),
                MetricName.latency_p95_ms: curve(
                    timeline, "step", base=40, noise=4, rng=rng, onset_minutes=full, peak=2600
                ),
                MetricName.req_rate: curve(timeline, "flat", base=310, noise=11, rng=rng),
                MetricName.mem_mb: curve(
                    timeline, "step", base=410, noise=8, rng=rng, onset_minutes=full, peak=520
                ),
            },
        ),
    }
    return Built(
        incident=Incident(
            id="S05",
            title="Ledger ingest stalls",
            split="dev",
            difficulty="easy",
            flags=[],
            postmortem_id="pm-2026-02-ledger-disk",
            alert=alert(
                "ledger-writer", timeline.alert_at, "Ledger ingest backlog above 50k events"
            ),
            seed=505,
        ),
        truth=Truth(
            root_cause=RootCause.disk_full,
            service="ledger-writer",
            summary=(
                "The /var/lib/ledger volume filled steadily and reached 100% at 02:58; every WAL "
                "flush then failed with no space left on device and the ingest backlog grew."
            ),
            acceptable_fixes=[FixClass.free_disk],
            must_find=[
                MustFind(file="logs/ledger-writer.jsonl", pattern="no space left on device"),
                MustFind(file="logs/ledger-writer.jsonl", pattern="/var/lib/ledger/wal"),
                MustFind(file="metrics/ledger-writer.json", pattern='"disk_used_pct"'),
            ],
            escalation_ok=False,
        ),
        writer=writer,
        metrics=metrics,
        deploys=[],
    )


def s06_config_typo() -> Built:
    rng = random.Random(606)
    timeline = Timeline(
        start=utc("2026-11-17T10:00:00Z"),
        step_seconds=60,
        points=90,
        alert_at=utc("2026-11-17T10:48:00Z"),
    )
    writer = LogWriter(rng=rng)
    Traffic(writer, "auth-api", 3.0, ["/oauth/token", "/oauth/introspect", "/healthz"]).routine(
        timeline
    )
    Traffic(writer, "login-web", 1.5, ["/login", "/session/refresh"]).routine(timeline)
    Traffic(writer, "email-sender", 0.4, ["/send"]).routine(timeline)
    _smtp_noise(writer, timeline, 22)

    onset = 31.0
    writer.add(
        "auth-api",
        timeline.at(5),
        "info",
        "config watcher: configmap auth-api-config resourceVersion=88107 unchanged",
    )
    writer.add(
        "auth-api",
        timeline.at(onset),
        "info",
        "config watcher: applied configmap auth-api-config resourceVersion=88412 "
        "changed_keys=[OIDC_ISSUER] source=kubectl-apply",
    )
    writer.add(
        "auth-api",
        timeline.at(onset) + timedelta(seconds=1),
        "info",
        "oidc: trusted issuer set to https://login.acme-corp.exmaple",
    )
    moment = timeline.at(onset) + timedelta(seconds=20)
    while moment <= timeline.end:
        writer.add(
            "auth-api",
            moment,
            "error",
            "POST /oauth/introspect 401 err=token issuer mismatch: "
            "want https://login.acme-corp.exmaple got https://login.acme-corp.example",
        )
        moment += timedelta(seconds=40 + rng.randint(0, 9))
    moment = timeline.at(onset) + timedelta(seconds=50)
    while moment <= timeline.end:
        writer.add(
            "login-web",
            moment,
            "warn",
            f"session refresh rejected by auth-api status=401 user=u-{rng.randint(10000, 99999)}",
        )
        moment += timedelta(seconds=90 + rng.randint(0, 20))

    metrics = {
        "auth-api": dumps_series(
            "auth-api",
            timeline,
            {
                MetricName.error_rate: curve(
                    timeline,
                    "step",
                    base=0.004,
                    noise=0.002,
                    rng=rng,
                    onset_minutes=onset,
                    peak=0.68,
                    decimals=3,
                ),
                MetricName.req_rate: curve(timeline, "flat", base=260, noise=10, rng=rng),
                MetricName.latency_p95_ms: curve(timeline, "flat", base=35, noise=3, rng=rng),
                MetricName.cpu_pct: curve(timeline, "flat", base=19, noise=2, rng=rng),
            },
        ),
        "login-web": dumps_series(
            "login-web",
            timeline,
            {
                MetricName.error_rate: curve(
                    timeline,
                    "step",
                    base=0.01,
                    noise=0.003,
                    rng=rng,
                    onset_minutes=onset,
                    peak=0.52,
                    decimals=3,
                ),
            },
        ),
    }
    deploy = make_deploy(
        rng,
        deploy_id="dpl-77e2",
        service="auth-api",
        ts="2026-11-14T09:12:00Z",
        author="sana",
        summary="auth: add client_id to token audit log",
        diff=(
            "--- a/auth/audit.py\n"
            "+++ b/auth/audit.py\n"
            "@@ -11,4 +11,5 @@ def log_token(event):\n"
            '     fields = {"sub": event.sub, "scope": event.scope}\n'
            '+    fields["client_id"] = event.client_id\n'
        ),
    )
    return Built(
        incident=Incident(
            id="S06",
            title="Valid logins rejected",
            split="dev",
            difficulty="medium",
            flags=[],
            postmortem_id="pm-2026-07-auth-issuer",
            alert=alert("auth-api", timeline.alert_at, "Token introspection 401 rate above 50%"),
            seed=606,
        ),
        truth=Truth(
            root_cause=RootCause.misconfiguration,
            service="auth-api",
            summary=(
                "A ConfigMap edit at 10:31 set OIDC_ISSUER to https://login.acme-corp.exmaple, a "
                "typo, so auth-api rejects every valid token with an issuer mismatch. No deploy "
                "was involved."
            ),
            acceptable_fixes=[FixClass.config_change, FixClass.rollback_deploy],
            must_find=[
                MustFind(file="logs/auth-api.jsonl", pattern="issuer mismatch"),
                MustFind(file="logs/auth-api.jsonl", pattern="resourceVersion=88412"),
            ],
            escalation_ok=False,
        ),
        writer=writer,
        metrics=metrics,
        deploys=[deploy],
    )


def s07_cpu_batch_job() -> Built:
    rng = random.Random(707)
    timeline = Timeline(
        start=utc("2026-11-18T08:00:00Z"),
        step_seconds=60,
        points=90,
        alert_at=utc("2026-11-18T09:18:00Z"),
    )
    writer = LogWriter(rng=rng)
    Traffic(
        writer, "reports-api", 3.0, ["/v1/reports/summary", "/v1/reports/daily", "/healthz"]
    ).routine(timeline)
    Traffic(writer, "email-sender", 0.4, ["/send"]).routine(timeline)
    _smtp_noise(writer, timeline, 40)

    onset = 60.0
    writer.add(
        "reports-api",
        timeline.at(5),
        "info",
        "scheduler: next run monthly-export at 2026-11-18T09:00:00Z cron='0 9 18 * *'",
    )
    writer.add(
        "reports-api",
        timeline.at(onset),
        "info",
        "scheduler: started job monthly-export workers=8 est_rows=2100000 replicas=3",
    )
    for index, minute in enumerate(range(65, 89, 5)):
        writer.add(
            "reports-api",
            timeline.at(minute),
            "info",
            f"monthly-export progress {9 + index * 8}% rows={190000 + index * 170000}",
        )
    moment = timeline.at(onset + 1)
    while moment <= timeline.end:
        writer.add(
            "reports-api",
            moment,
            "warn",
            f"request queue depth {rng.randint(300, 520)} exceeds 200; shedding low-priority requests",
        )
        moment += timedelta(seconds=60 + rng.randint(0, 15))
    moment = timeline.at(onset + 2)
    while moment <= timeline.end:
        writer.add(
            "reports-api",
            moment,
            "error",
            "GET /v1/reports/summary 503 dur_ms=5000 err=queue wait timeout",
        )
        moment += timedelta(seconds=50 + rng.randint(0, 10))

    metrics = {
        "reports-api": dumps_series(
            "reports-api",
            timeline,
            {
                MetricName.cpu_pct: capped(
                    curve(
                        timeline, "step", base=38, noise=3, rng=rng, onset_minutes=onset, peak=97
                    ),
                    100.0,
                ),
                MetricName.latency_p95_ms: curve(
                    timeline, "step", base=240, noise=15, rng=rng, onset_minutes=onset, peak=4900
                ),
                MetricName.error_rate: curve(
                    timeline,
                    "step",
                    base=0.008,
                    noise=0.002,
                    rng=rng,
                    onset_minutes=onset,
                    peak=0.21,
                    decimals=3,
                ),
                MetricName.req_rate: curve(timeline, "flat", base=190, noise=8, rng=rng),
                MetricName.mem_mb: curve(timeline, "flat", base=1200, noise=20, rng=rng),
            },
        ),
    }
    return Built(
        incident=Incident(
            id="S07",
            title="Reports slow down during the monthly export",
            split="dev",
            difficulty="medium",
            flags=[],
            postmortem_id="pm-2026-05-reports-capacity",
            alert=alert("reports-api", timeline.alert_at, "Reports p95 latency above 4s"),
            seed=707,
        ),
        truth=Truth(
            root_cause=RootCause.capacity,
            service="reports-api",
            summary=(
                "The monthly export job started at 09:00 on the same three reports-api replicas "
                "that serve traffic and pegged CPU near 97%; request queues overflowed and "
                "requests hit the 5 s queue timeout."
            ),
            acceptable_fixes=[FixClass.scale_out],
            must_find=[
                MustFind(file="logs/reports-api.jsonl", pattern="started job monthly-export"),
                MustFind(file="logs/reports-api.jsonl", pattern="queue depth"),
                MustFind(file="metrics/reports-api.json", pattern='"cpu_pct"'),
            ],
            escalation_ok=False,
        ),
        writer=writer,
        metrics=metrics,
        deploys=[],
    )


def s08_expired_cert() -> Built:
    rng = random.Random(808)
    timeline = Timeline(
        start=utc("2026-11-19T23:00:00Z"),
        step_seconds=60,
        points=90,
        alert_at=utc("2026-11-20T00:20:00Z"),
    )
    writer = LogWriter(rng=rng)
    expiry = utc("2026-11-20T00:00:00Z")
    onset = 60.0
    Traffic(writer, "payments-gw", 2.0, ["/v1/charge", "/healthz"]).routine(timeline, until=onset)
    Traffic(writer, "billing-api", 2.0, ["/v1/invoices", "/healthz"]).routine(timeline)
    Traffic(writer, "email-sender", 0.4, ["/send"]).routine(timeline)
    _smtp_noise(writer, timeline, 18)

    writer.add(
        "payments-gw",
        timeline.at(10),
        "warn",
        "tls: serving certificate CN=payments-gw.internal expires in 0h50m "
        "(notAfter=2026-11-20T00:00:00Z)",
    )
    moment = expiry + timedelta(seconds=11)
    while moment <= timeline.end:
        writer.add(
            "payments-gw",
            moment,
            "warn",
            f"http: TLS handshake error from 10.4.1.{rng.randint(10, 40)}:{rng.randint(40000, 60000)}: "
            "remote error: tls: bad certificate",
        )
        moment += timedelta(seconds=30 + rng.randint(0, 8))
    moment = expiry + timedelta(seconds=14)
    while moment <= timeline.end:
        writer.add(
            "billing-api",
            moment,
            "error",
            f'charge inv-{rng.randint(100000, 999999)} failed: Post "https://payments-gw.internal/v1/charge": '
            "tls: failed to verify certificate: x509: certificate has expired or is not yet "
            f"valid: current time {moment.strftime('%Y-%m-%dT%H:%M:%SZ')} is after 2026-11-20T00:00:00Z",
        )
        moment += timedelta(seconds=35 + rng.randint(0, 8))

    days_left = [
        MetricPoint(ts=moment, value=round((expiry - moment).total_seconds() / 86400, 3))
        for moment in timeline.samples()
    ]
    metrics = {
        "payments-gw": dumps_series(
            "payments-gw",
            timeline,
            {
                MetricName.cert_days_left: days_left,
                MetricName.req_rate: curve(
                    timeline, "step", base=120, noise=2, rng=rng, onset_minutes=onset, peak=0
                ),
                MetricName.cpu_pct: curve(timeline, "flat", base=14, noise=2, rng=rng),
            },
        ),
        "billing-api": dumps_series(
            "billing-api",
            timeline,
            {
                MetricName.error_rate: curve(
                    timeline,
                    "step",
                    base=0.01,
                    noise=0.003,
                    rng=rng,
                    onset_minutes=onset,
                    peak=0.47,
                    decimals=3,
                ),
            },
        ),
    }
    return Built(
        incident=Incident(
            id="S08",
            title="Card charges fail at midnight",
            split="dev",
            difficulty="easy",
            flags=[],
            postmortem_id="pm-2026-01-payments-cert",
            alert=alert(
                "payments-gw", timeline.alert_at, "Card charge success rate at 0% since 00:00 UTC"
            ),
            seed=808,
        ),
        truth=Truth(
            root_cause=RootCause.cert_expiry,
            service="payments-gw",
            summary=(
                "payments-gw's serving certificate expired at 2026-11-20T00:00:00Z; from that "
                "second every client handshake fails, so no charge reaches the gateway."
            ),
            acceptable_fixes=[FixClass.rotate_cert],
            must_find=[
                MustFind(file="logs/billing-api.jsonl", pattern="certificate has expired"),
                MustFind(file="logs/payments-gw.jsonl", pattern="tls: bad certificate"),
            ],
            escalation_ok=False,
        ),
        writer=writer,
        metrics=metrics,
        deploys=[],
    )
