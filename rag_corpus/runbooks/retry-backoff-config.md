---
id: rb-retry-backoff-config
title: Set retry backoff, attempt caps and timeouts safely
root_causes: [misconfiguration]
services: []
---
# Set retry backoff, attempt caps and timeouts safely

## Symptoms
A dependency recovers, but its callers keep it overloaded. Error rate stays high long after the original fault ended. Retries are sent immediately, and every layer retries, so one user request becomes many calls.

## Checks
1. Call query_logs on each caller for retry lines and count attempts per request.
2. Call query_metrics for req_rate on the dependency and compare it with user traffic at the edge.
3. Find the retry, backoff and timeout keys in the caller's config.

## Fix
Fix class config_change: retry only at one layer, set exponential backoff starting at 100 ms with jitter, cap attempts at 3, and keep the timeout below the caller's own deadline.

## Rollback
Restore the previous values and escalate if the dependency is still overloaded.
