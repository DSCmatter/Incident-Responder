---
id: pm-2026-07-search-oom
title: "Postmortem: search-api slowdown and OOM restarts, July 2026"
incident: S02
root_cause: resource_exhaustion
services: [search-api]
---
# Postmortem: search-api slowdown and OOM restarts, July 2026

## Summary
Over an afternoon in July 2026, search-api latency rose for three hours until replicas were killed for exceeding their memory limit. A per-request facet cache had no size bound, so memory grew with every distinct query.

## Timeline
11:00 memory began a steady climb on every replica. 13:30 p95 latency crossed 1 s. 14:05 the first replica was OOM killed and restarted. 14:20 on-call restarted all replicas, which reset memory. 16:10 a bounded cache shipped.

## Root cause
An unbounded in-process cache keyed by query text. Garbage collection time grew with the heap, which slowed requests long before the kills.

## Resolution
A rolling restart restored latency for the day. A release with a size-limited cache fixed it.

## Follow-ups
Alert on memory growth rate, not only on the limit. Add heap size to the search dashboard.
