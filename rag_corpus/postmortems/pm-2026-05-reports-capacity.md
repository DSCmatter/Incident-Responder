---
id: pm-2026-05-reports-capacity
title: "Postmortem: reports slowdown during quarter-end exports, May 2026"
incident: S07
root_cause: capacity
services: [reports-api]
---
# Postmortem: reports slowdown during quarter-end exports, May 2026

## Summary
In May 2026, reports-api dashboards took over 6 s to load for 90 minutes while the quarter-end export ran on the same replicas. CPU was pinned on all replicas for the duration of the export.

## Timeline
08:00 scheduled export started. 08:05 CPU reached 98%. 08:12 p95 latency alert fired. 08:30 on-call matched the start with the export schedule. 08:40 scaled from 4 to 8 replicas and latency recovered. 09:30 export finished and replicas scaled back.

## Root cause
Not enough capacity for the export and interactive traffic at the same time on shared replicas.

## Resolution
Scale out for the export window.

## Follow-ups
Run exports on dedicated workers. Schedule them outside business hours.
