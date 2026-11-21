---
id: rb-config-typo-rejects-valid-requests
title: Service is up but rejects valid requests after a config edit
root_causes: [misconfiguration]
services: []
---
# Service is up but rejects valid requests after a config edit

## Symptoms
The service starts, passes health checks and answers quickly, but refuses requests that should succeed: 401 or 403 for valid credentials, 400 for well-formed input, or a match rule that never matches. The error rate jumps at one moment and stays flat. No code deploy lines up with the change, because the value was edited in a config map, flag store or settings file.

## Checks
1. Call list_recent_deploys; an empty or unrelated deploy list points away from code.
2. Call query_logs for the rejection reason. Compare the configured value it reports with the value clients send; a single character difference is common.
3. Call query_metrics for error_rate to pin the exact time of the change.

## Fix
Fix class config_change with the key and its correct value. Use rollback_deploy only if a deploy carried the bad value.

## Rollback
Set the key back to the value it had before the fix if errors rise.
