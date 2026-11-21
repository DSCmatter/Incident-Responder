---
id: pm-2026-04-checkout-outage
title: "Postmortem: checkout outage after a release, April 2026"
incident: S01
root_cause: bad_deploy
services: [checkout-api]
---
# Postmortem: checkout outage after a release, April 2026

## Summary
For 34 minutes in April 2026, about 70% of checkout attempts failed. A checkout-api release replaced the deployment manifest from a template that lacked the tax calculation settings, so the service called an empty tax host for every basket with a taxable item.

## Timeline
14:02 release rolled out to all replicas. 14:05 checkout success rate alert fired. 14:18 the on-call engineer matched the error onset to the rollout. 14:31 rollback completed. 14:36 success rate back to normal.

## Root cause
The manifest template used for the release predated the tax provider migration and did not carry its settings. The service started anyway because the setting had a default of an empty string.

## Resolution
Rolled back the deploy. The forward fix restored the settings to the template and was redeployed the next day.

## Follow-ups
Fail startup when a required setting is empty. Add a deploy check that diffs environment keys between releases. Alert on checkout success rate per payment step, not only overall.
