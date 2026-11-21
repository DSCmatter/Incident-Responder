---
id: rb-log-and-spool-growth
title: Logs or spool files slowly fill the disk until sends fail
root_causes: [disk_full]
services: []
---
# Logs or spool files slowly fill the disk until sends fail

## Symptoms
A service that queues work on local disk before sending it (notification, email or webhook senders, print or export jobs) begins failing sends once the spool or log volume fills. Failures above 50% are common because every new message needs space. Disk usage has warned for hours before the failures, so a deploy that happens near the failure time is often a coincidence.

## Checks
1. Call query_metrics for disk_used_pct over the last 12 hours, not only the last hour, and find when the climb started.
2. Call query_logs for disk space warnings that predate the failures and for write errors on the spool or log path.
3. Call list_recent_deploys and compare deploy times with the start of the disk climb. A deploy after the climb started did not cause it.

## Fix
Fix class free_disk with the spool or log path. Do not roll back a deploy that only coincides with the failures.

## Rollback
Deleted spool files cannot be restored; only remove messages already sent or expired. Fix rotation or retention after recovery.
