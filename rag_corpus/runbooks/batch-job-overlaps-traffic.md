---
id: rb-batch-job-overlaps-traffic
title: A scheduled export or report job competes with live traffic
root_causes: [capacity]
services: []
---
# A scheduled export or report job competes with live traffic

## Symptoms
Interactive requests slow down while a scheduled batch runs on the same replicas: a monthly or nightly export, report generation, reindex or billing run. Reports, dashboards and other endpoints on that service cross their p95 latency alert (often above 4 s) and CPU is pinned for the length of the job. The slowdown starts when the job starts, and it recurs on the same schedule.

## Checks
1. Call query_logs for job start and progress lines, and match the start time with the latency rise.
2. Call query_metrics for cpu_pct and latency_p95_ms; both rise at the job start.
3. Call query_metrics for req_rate; user traffic is normal, so the extra load is the job.
4. Call list_recent_deploys to rule out a release.

## Fix
Fix class scale_out to add replicas for the duration of the job. Longer term, move the job off peak hours or onto its own workers.

## Rollback
Scale back to the previous replica count after the job finishes.
