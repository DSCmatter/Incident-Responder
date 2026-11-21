---
id: rb-service-discovery-stale-endpoints
title: Callers route to endpoints that no longer exist
root_causes: [network_dns]
services: []
---
# Callers route to endpoints that no longer exist

## Symptoms
After a dependency redeploys or moves, callers keep sending traffic to its old addresses and get connection refused or timeouts. The dependency itself is healthy at its new address. Caches of DNS or discovery records outlive the change.

## Checks
1. Call query_logs on the caller for the address it connects to and compare it with the dependency's current one.
2. Call query_metrics for error_rate on callers versus the dependency; healthy dependency with failing callers fits stale records.
3. Look for very long DNS TTLs or disabled refresh in the caller's client settings.

## Fix
Fix class restart_service on the callers to drop cached records. Escalate_human if the discovery system itself serves stale data.

## Rollback
Nothing to undo after a restart.
