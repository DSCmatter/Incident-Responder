---
id: rb-missing-environment-variable
title: A release dropped a required setting or secret
root_causes: [bad_deploy, misconfiguration]
services: []
---
# A release dropped a required setting or secret

## Symptoms
After a deploy, calls that depend on one setting fail while the rest of the service works. Typical signs are a downstream URL or host that resolves to an empty value, a blank credential, connection attempts to localhost or a default port, and config warnings at startup. Requests that need that setting fail every time, so the error rate on that path is close to 100% while other endpoints are healthy.

## Checks
1. Call list_recent_deploys and get_deploy_diff for the newest deploy. Look for an environment variable, secret reference or config key that was removed, renamed or set to an empty string in the manifest.
2. Call query_logs around the first start of the new version for startup config warnings.
3. Confirm the failing requests are the ones that use the missing setting, and that unrelated endpoints still succeed.

## Fix
Fix class rollback_deploy to the previous release, which still carries the setting. If no deploy changed it and the value was edited in the config store, use config_change instead with the key and its previous value.

## Rollback
Redeploy the rolled-back release once the manifest restores the setting. Add a startup check that refuses to boot when a required setting is empty.
