---
id: rb-upstream-dependency-timeouts
title: Calls to another service time out while the caller is healthy
root_causes: [dependency_failure]
services: []
---
# Calls to another service time out while the caller is healthy

## Symptoms
Requests that need a downstream service fail with timeouts or gateway errors, and the error rate of that operation rises. The calling service has normal CPU, memory and disk, and no recent deploy explains the change. Latency on the failing calls sits exactly at the client timeout.

## Checks
1. Call query_logs on the calling service for timeout, deadline exceeded or upstream errors, and note which host or provider they name.
2. Call query_metrics for cpu_pct and mem_mb on the caller to rule out local exhaustion.
3. Call list_recent_deploys to rule out a release on the caller.
4. If the dependency is ours, check its logs and metrics too; if it is a third party, check its status page.

## Fix
Fix class config_change to lower the client timeout and enable the fallback or queueing path so callers fail fast. If the dependency is outside our control and no fallback exists, escalate_human to the owning team so they contact the provider.

## Rollback
Restore the previous timeout and fallback settings once the dependency recovers.
