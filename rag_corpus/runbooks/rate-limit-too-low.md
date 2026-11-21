---
id: rb-rate-limit-too-low
title: Legitimate users receive 429 after a rate limit change
root_causes: [misconfiguration]
services: []
---
# Legitimate users receive 429 after a rate limit change

## Symptoms
The share of 429 Too Many Requests responses jumps for normal users and partners, though traffic has not grown. The limiter rejects requests at a fraction of usual volume. The change lines up with an edit to a rate limit or quota setting, sometimes shipped in a deploy.

## Checks
1. Call query_logs for rate limited or 429 lines and note the configured limit they report.
2. Call query_metrics for req_rate; normal traffic with many rejections means the limit is wrong, not the load.
3. Call list_recent_deploys and get_deploy_diff for a change to limit or quota keys.

## Fix
Fix class config_change to set the limit back to its previous value. If a deploy carried the change, rollback_deploy.

## Rollback
Lower the limit again only if abusive traffic returns, and per client rather than globally.
