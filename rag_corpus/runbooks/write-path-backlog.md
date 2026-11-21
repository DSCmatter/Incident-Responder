---
id: rb-write-path-backlog
title: Ingest backlog grows because the writer cannot persist
root_causes: [disk_full]
services: []
---
# Ingest backlog grows because the writer cannot persist

## Symptoms
A consumer, ingest pipeline or writer falls behind: queue lag or backlog climbs into the tens of thousands of events and keeps growing. The writer process is running and receiving events, but each write or commit fails and is retried. Typical cause is a full data, journal or write-ahead log volume; the writer cannot append, so nothing is acknowledged.

## Checks
1. Call query_metrics for disk_used_pct on the writer; a volume at the ceiling explains the stall.
2. Call query_logs on the writer for failed appends, commits, flushes or segment writes, and the directory they name.
3. Call query_metrics for cpu_pct to rule out a writer that is simply too slow, which is a capacity problem instead.

## Fix
Fix class free_disk with the directory that filled, for example archived journal segments that were already shipped. The backlog drains on its own once writes succeed.

## Rollback
Nothing to undo once space is free. Watch the backlog fall and disk_used_pct stay below 80%.
