---
id: pm-2026-02-orders-scan
title: "Postmortem: orders history timeouts from a full table scan, February 2026"
incident: S03
root_cause: slow_query
services: [orders-api, orders-db]
---
# Postmortem: orders history timeouts from a full table scan, February 2026

## Summary
In February 2026 the order history page timed out for large merchants for about an hour. A new filter by fulfilment status ran without an index on that column, so the database read the whole orders table for every page.

## Timeline
09:40 release added the status filter. 10:15 orders-api p95 crossed 3 s as merchants started their day. 10:30 database latency alert fired. 10:52 the slow statement was identified in the database log. 11:20 an index built online and latency recovered.

## Root cause
A query pattern shipped without a matching index, and the table was large enough that a sequential scan took seconds.

## Resolution
Built a composite index on merchant and status online. No rollback was needed.

## Follow-ups
Run the query plan check in CI for new queries on large tables. Alert on database latency per statement shape.
