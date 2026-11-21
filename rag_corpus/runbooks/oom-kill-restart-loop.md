---
id: rb-oom-kill-restart-loop
title: Instances restart repeatedly after running out of memory
root_causes: [resource_exhaustion]
services: []
---
# Instances restart repeatedly after running out of memory

## Symptoms
Pods or processes are killed by the out of memory killer, restart, and are killed again after a similar interval. Each kill drops in-flight requests, so the error rate shows bursts and latency spikes while instances warm up. Memory per instance follows a saw-tooth that peaks at the limit.

## Checks
1. Call query_logs for OOM, killed, exit code 137 or restart lines on the service.
2. Call query_metrics for mem_mb; the peak of each tooth should sit at the container limit.
3. Call list_recent_deploys to see whether the pattern began with a release or a limit change.

## Fix
Fix class restart_service for a slow leak, which resets every instance at once. If the leak came with a deploy, rollback_deploy. Raising the memory limit only delays the next kill.

## Rollback
Restart again if needed. Keep the previous release ready to redeploy if a rollback is chosen.
