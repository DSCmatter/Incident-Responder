---
id: pm-2026-06-carrier-timeouts
title: "Postmortem: shipping label failures during a carrier outage, June 2026"
incident: S04
root_cause: dependency_failure
services: [shipping-api]
---
# Postmortem: shipping label failures during a carrier outage, June 2026

## Summary
In June 2026 a parcel carrier's rating service degraded for two hours. shipping-api waited the full 30 s timeout on every call, so label creation failed for most orders and warehouse staff could not print labels.

## Timeline
08:10 carrier latency rose. 08:25 label error rate alert fired. 08:40 on-call confirmed our own resources were normal and no deploy had happened. 09:00 timeout lowered and the backup carrier enabled for domestic parcels. 10:15 the carrier recovered.

## Root cause
An external dependency outage, made worse by a timeout far longer than the warehouse could tolerate and no automatic failover.

## Resolution
Config change to a 5 s timeout and backup carrier routing. Vendor ticket opened by the logistics team.

## Follow-ups
Automatic failover to the backup carrier on sustained timeouts. Circuit breaker on slow calls.
