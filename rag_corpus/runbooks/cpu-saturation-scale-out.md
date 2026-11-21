---
id: rb-cpu-saturation-scale-out
title: CPU pegged and latency up under load
root_causes: [capacity]
services: []
---
# CPU pegged and latency up under load

## Symptoms
CPU on every replica of a service sits near 100%, p95 latency rises to several seconds, and requests queue. Memory and disk are normal and no deploy explains it. The work per request has not changed; there is simply more work than the replicas can do.

## Checks
1. Call query_metrics for cpu_pct and latency_p95_ms on the service and check they rise together.
2. Call query_metrics for req_rate. Rising traffic, or extra internal work such as a batch job, explains the load.
3. Call query_logs for slow request or worker saturation warnings.
4. Call list_recent_deploys to rule out a release that made requests more expensive.

## Fix
Fix class scale_out with a replica count that brings CPU under 70% at the current load, for example double the current replicas.

## Rollback
Scale back to the previous replica count once load returns to normal for 30 minutes.
