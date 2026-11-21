---
id: rb-query-plan-regression
title: A query that was fast becomes slow as the table grows
root_causes: [slow_query]
services: []
---
# A query that was fast becomes slow as the table grows

## Symptoms
A page that lists records (orders, invoices, messages) gets slower week by week, then crosses its latency alert. Small accounts are fine and large ones time out. The query planner switched to a sequential scan or an in-memory sort because the table outgrew the available indexes.

## Checks
1. Call query_metrics for db_latency_ms and latency_p95_ms over the last day; a gradual rise rather than a step suggests growth.
2. Call query_logs on the database service for slow statement lines that examine millions of rows.
3. Compare the columns in the slow statement's WHERE and ORDER BY clauses with the indexes the service owns.

## Fix
Fix class add_index covering the filter column first, then the sort column.

## Rollback
Drop the index if it slows writes more than it speeds reads.
