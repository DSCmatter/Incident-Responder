---
id: rb-circuit-breaker-timeouts
title: Worker threads tied up waiting on a hanging dependency
root_causes: [dependency_failure]
services: []
---
# Worker threads tied up waiting on a hanging dependency

## Symptoms
A dependency stops answering but keeps connections open, so each call waits for the full timeout. The caller's worker threads fill up waiting, its latency rises, and unrelated endpoints on the caller start failing too. The circuit breaker never opens because it counts errors, not slow calls.

## Checks
1. Call query_logs for timeout errors naming one dependency.
2. Call query_metrics for latency_p95_ms on the caller and check that it matches the timeout value.
3. Confirm the caller's cpu_pct is low; threads are blocked, not busy.

## Fix
Fix class config_change to lower the dependency timeout and set the breaker to open on slow calls. Use escalate_human if the dependency belongs to another team or vendor and stays down.

## Rollback
Restore the previous timeout and breaker settings.
