---
id: rb-database-latency-triage
title: Database latency high and API requests time out
root_causes: [slow_query, resource_exhaustion]
services: []
---
# Database latency high and API requests time out

## Symptoms
An API that reads from a database reports p95 latency in seconds and a growing number of timeouts, while its own CPU and memory are fine. Database latency is up. The cause is either one expensive query, which shows up as a repeated statement in the slow log, or too many requests waiting on a small connection pool.

## Checks
1. Call query_metrics for db_latency_ms on the database service and latency_p95_ms on the API.
2. Call query_logs on the database for slow statements. One repeated statement with a full scan points at a missing index.
3. Call query_logs on the API for pool wait or no connection available messages, which point at pool exhaustion instead.

## Fix
For a repeated full scan, fix class add_index with the table and columns. For pool exhaustion, config_change to the pool size key. Do not restart the database to clear a slow query; it comes back with the next request.

## Rollback
Drop the index or restore the previous pool size.
