---
id: rb-retry-storm
title: Load multiplies after a short blip because clients retry without backoff
root_causes: [misconfiguration]
services: []
---
# Load multiplies after a short blip because clients retry without backoff

## Symptoms
A brief error burst or slowdown is followed by request rate several times above normal, and the service never recovers on its own. Most incoming requests are retries. Logs show the same request ids repeating within milliseconds. CPU is high because of the retries, not real traffic.

## Checks
1. Call query_metrics for req_rate; a jump right after a short error spike, with no matching rise in users, is the sign.
2. Call query_logs for retry attempt counters or repeated request ids.
3. Check the client retry settings: attempts, backoff and jitter. Zero backoff or unlimited attempts makes a storm.

## Fix
Fix class config_change on the calling service to add exponential backoff with jitter and cap attempts. A restart_service of the callers can clear queued retries.

## Rollback
Restore the previous retry settings if legitimate requests start failing without retry.
