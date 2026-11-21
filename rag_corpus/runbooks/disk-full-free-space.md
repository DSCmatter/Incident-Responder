---
id: rb-disk-full-free-space
title: A volume reached 100% and writes fail
root_causes: [disk_full]
services: []
---
# A volume reached 100% and writes fail

## Symptoms
A service that writes to local or attached storage starts failing writes with no space left on device or similar I/O errors. Reads may still work. Log rotation and compaction fail too, because they need free space to run. Disk usage on the volume has been rising for hours or days and is now at or near 100%.

## Checks
1. Call query_metrics for disk_used_pct on the service; look for a long rise that ends at the ceiling.
2. Call query_logs for write errors, rotation failures and fsync or flush errors, and note the path they name.
3. Call list_recent_deploys only to rule out a release that changed log levels or retention.

## Fix
Fix class free_disk with the path that filled up, such as an old log, archive, temp or segment directory. Remove data that is already shipped or safe to regenerate, never live data files.

## Rollback
Freed space cannot be put back, so only delete what has a copy elsewhere. If writes keep failing after cleanup, escalate to grow the volume.
