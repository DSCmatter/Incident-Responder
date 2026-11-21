---
id: rb-quota-config-change
title: A quota or throttling setting rejects normal traffic
root_causes: [misconfiguration]
services: []
---
# A quota or throttling setting rejects normal traffic

## Symptoms
An API gateway or service starts throttling at a fixed moment. Rejections cluster on the biggest customers first, because they hit a per-client quota that was set in the wrong unit, for example per second instead of per minute.

## Checks
1. Call query_logs for throttle or quota exceeded lines and the client ids they name.
2. Compare the configured quota with each client's normal request rate from query_metrics req_rate.
3. Call list_recent_deploys for a release that touched quota settings.

## Fix
Fix class config_change to correct the unit or value. Use rollback_deploy if the setting shipped with a release.

## Rollback
Restore the previous quota value.
