---
id: rb-deploy-regression-rollback
title: Errors or failed transactions right after a release
root_causes: [bad_deploy]
services: []
---
# Errors or failed transactions right after a release

## Symptoms
Success rate on a user-facing flow (checkout, sign-up, payment, search) drops sharply, or the 5xx and error rate jumps, within minutes of a deploy to the same service. The service stays up and health checks may still pass. Errors are steady from the moment the new version takes traffic, not a slow climb. CPU, memory and disk look normal.

## Checks
1. Call list_recent_deploys for the alerting service and note the newest deploy time.
2. Call query_metrics for error_rate on that service and compare the onset with the deploy time. A step change within a few minutes of the rollout points at the release.
3. Call query_logs for warn and error lines from the deploy time onward. Look for a new error that did not exist before the release.
4. Call get_deploy_diff on the suspect deploy and look for removed settings, changed defaults or a new dependency.

## Fix
Fix class rollback_deploy, target the deploy id of the bad release. Rolling back is faster and safer than a forward fix while customers are failing. Open a ticket for the forward fix after recovery.

## Rollback
If the rollback makes things worse, redeploy the same release again and escalate to the owning team. Confirm recovery with error_rate back at its pre-deploy baseline for 10 minutes.
