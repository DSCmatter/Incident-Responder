---
id: rb-config-change-without-deploy
title: Behaviour changed but nothing was deployed
root_causes: [misconfiguration]
services: []
---
# Behaviour changed but nothing was deployed

## Symptoms
A service changes behaviour at a precise moment with no deploy, no traffic change and normal resources. Requests fail with a consistent reason that mentions a configured value. Config maps, feature flags, secrets and dynamic settings can change without a deploy record.

## Checks
1. Call list_recent_deploys over 24 hours to confirm no release lines up.
2. Call query_logs for the first error after the change and any config reload or watch event just before it.
3. Call query_metrics for error_rate and cpu_pct; a step in errors with flat CPU fits a config change.

## Fix
Fix class config_change with the key and value from before the change.

## Rollback
Reapply the value that was replaced if the restored value causes new errors, and escalate to the owner of the config store.
