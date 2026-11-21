---
id: rb-dns-resolution-failure
title: Name resolution errors across several services
root_causes: [network_dns]
services: []
---
# Name resolution errors across several services

## Symptoms
Several services fail at once to reach their dependencies with errors such as unknown host, name or service not known, or lookup timeouts. Each service's own resources are normal. Calls by IP address still work. The common factor is the resolver or the service discovery layer, not any single application.

## Checks
1. Call query_logs on two or more services for lookup or resolve errors; the same error across services points at DNS.
2. Call query_metrics for error_rate on each affected service and compare onsets; a shared start time fits a resolver fault.
3. Call list_recent_deploys for changes to resolver, mesh or discovery configuration.

## Fix
Fix class restart_service on the resolver or discovery agent if it is stuck. If the fault is in the provider's DNS, escalate_human to the network team.

## Rollback
A restart has nothing to roll back. If a discovery config change caused it, restore the previous config.
