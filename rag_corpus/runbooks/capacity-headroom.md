---
id: rb-capacity-headroom
title: Traffic exceeds what the current replicas can serve
root_causes: [capacity]
services: []
---
# Traffic exceeds what the current replicas can serve

## Symptoms
After a marketing push, a seasonal peak or a client retrying more, request rate is well above normal. Latency rises across all endpoints and CPU or worker utilisation is at the limit on every replica. Errors are timeouts and load-shedding responses, not exceptions.

## Checks
1. Call query_metrics for req_rate and compare it with the same time last week.
2. Call query_metrics for cpu_pct and latency_p95_ms across the window.
3. Call query_logs for queue full or shed load messages.

## Fix
Fix class scale_out with enough replicas for the new traffic plus 30% headroom.

## Rollback
Scale back down once req_rate returns to its usual level.
