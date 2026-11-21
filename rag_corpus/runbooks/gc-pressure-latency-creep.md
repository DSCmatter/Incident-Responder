---
id: rb-gc-pressure-latency-creep
title: Latency creeps up for hours with no deploy or traffic change
root_causes: [resource_exhaustion]
services: []
---
# Latency creeps up for hours with no deploy or traffic change

## Symptoms
p95 latency on a service rises slowly over hours (for example from 200 ms to above 1 s) and the error rate starts rising late in the climb. Request rate is flat and no recent deploy lines up with the start. The process spends more and more time in garbage collection, caches or buffers keep growing, or threads pile up.

## Checks
1. Call query_metrics for latency_p95_ms and req_rate; rising latency with flat traffic rules out a load problem.
2. Call query_metrics for mem_mb and cpu_pct. Rising memory with rising CPU from collection work means a leak or an unbounded cache.
3. Call query_logs for long GC pause, heap, cache size or thread pool warnings.

## Fix
Fix class restart_service to reset the process state. Use rollback_deploy only if a deploy lines up with the start of the climb.

## Rollback
Nothing to undo. If latency returns within hours, capture a heap profile before the next restart and escalate to the owning team.
