---
id: rb-connection-pool-exhausted
title: Requests wait for a database connection that never frees up
root_causes: [resource_exhaustion]
services: []
---
# Requests wait for a database connection that never frees up

## Symptoms
Requests fail after waiting for a connection from the pool, with errors such as no connections available or pool timeout. Pool usage sits at its maximum while the database itself has spare capacity. Latency jumps to the pool wait timeout and the error rate rises with traffic.

## Checks
1. Call query_logs for pool wait, acquire timeout or no connection available messages.
2. Call query_metrics for db_latency_ms; normal database latency with pool errors means the pool is too small or connections leak.
3. Call query_metrics for req_rate to see whether traffic grew past what the pool size can serve.
4. Call list_recent_deploys for a release that changed connection handling.

## Fix
Fix class config_change to raise the pool size key within the database connection limit. If a deploy introduced a connection leak, rollback_deploy.

## Rollback
Restore the previous pool size if the database reaches its own connection limit.
