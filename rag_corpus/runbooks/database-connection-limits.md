---
id: rb-database-connection-limits
title: Too many clients for the database connection limit
root_causes: [resource_exhaustion]
services: []
---
# Too many clients for the database connection limit

## Symptoms
After scaling a service out, new replicas cannot connect and the database rejects connections with too many clients. Each replica holds a fixed pool, so total pool size across replicas exceeds what the database allows. Some replicas work and others fail every request.

## Checks
1. Call query_logs on the service for connection refused by the database or too many clients.
2. Multiply replicas by pool size and compare with the database connection limit.
3. Call query_metrics for error_rate per service to find which callers are failing.

## Fix
Fix class config_change to lower the per-replica pool size so the total fits, or put a connection pooler in front of the database.

## Rollback
Restore the previous pool size and replica count together.
