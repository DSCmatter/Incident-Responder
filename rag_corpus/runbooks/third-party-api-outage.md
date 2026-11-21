---
id: rb-third-party-api-outage
title: An external provider API is slow or down
root_causes: [dependency_failure]
services: []
---
# An external provider API is slow or down

## Symptoms
A feature that calls an external provider (payment processor, shipping carrier for label creation and rates, SMS or email gateway, address validation) starts failing, with its error rate rising above 30 to 50%. Our own services are healthy. Errors are timeouts or 5xx responses from the provider, and they started without any change on our side.

## Checks
1. Call query_logs on the calling service for the provider host and timeout errors.
2. Call query_metrics for latency_p95_ms; it often sits at the configured timeout.
3. Call list_recent_deploys to confirm nothing of ours changed.

## Fix
Fix class config_change to switch to a backup provider, shorten the timeout, or queue requests to retry later. If none of these exist, escalate_human so the vendor contact can open a ticket with the provider.

## Rollback
Switch back to the primary provider and restore the timeout once its success rate holds for 15 minutes.
