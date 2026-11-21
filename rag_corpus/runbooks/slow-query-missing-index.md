---
id: rb-slow-query-missing-index
title: List or search page slow because a query scans the whole table
root_causes: [slow_query]
services: []
---
# List or search page slow because a query scans the whole table

## Symptoms
p95 latency for a list, history or search endpoint climbs to several seconds, and requests start to time out. Database latency rises at the same time. The database slow log shows one query shape repeated many times, filtering or sorting on a column that has no index, so every call reads the whole table. Application CPU and memory are normal; the time is spent waiting on the database.

## Checks
1. Call query_metrics for latency_p95_ms on the API and db_latency_ms on the database service.
2. Call query_logs on the database service for slow query lines and note the repeated statement, its table and its WHERE or ORDER BY columns.
3. Call query_logs on the API for timeout errors on the same endpoint.
4. Call list_recent_deploys to see whether a migration or new query shipped recently.

## Fix
Fix class add_index, with the table and the filtered or sorted columns from the slow statement. Build the index online so writes are not blocked.

## Rollback
Drop the new index if write latency or replication lag rises after the build. The query returns to its previous plan.
