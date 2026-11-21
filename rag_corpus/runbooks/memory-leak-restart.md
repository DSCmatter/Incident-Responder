---
id: rb-memory-leak-restart
title: Memory grows until instances are killed
root_causes: [resource_exhaustion]
services: []
---
# Memory grows until instances are killed

## Symptoms
Resident memory climbs in a straight line for hours and never returns to baseline after traffic drops. As it approaches the container limit, garbage collection pauses get longer, p95 latency rises, and the error rate starts rising when instances are killed for running out of memory and restart. Traffic is flat, so load does not explain it.

## Checks
1. Call query_metrics for mem_mb over the last several hours; a steady rising trend with no plateau is the signature.
2. Call query_metrics for latency_p95_ms and error_rate and check that they worsen as memory nears the limit.
3. Call query_logs for out of memory, killed, heap or restart messages.
4. Call list_recent_deploys over 24 to 48 hours. If the climb started right after a deploy, the release likely introduced the leak.

## Fix
Fix class restart_service clears the leaked memory and buys hours. If a deploy started the growth, rollback_deploy removes the leak itself.

## Rollback
A restart has nothing to roll back; watch mem_mb after it. If memory climbs again at the same rate, schedule the rollback or a code fix and restart again before the limit.
