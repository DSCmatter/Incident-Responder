---
id: pm-2026-07-auth-issuer
title: "Postmortem: valid tokens rejected after an identity provider change, July 2026"
incident: S06
root_cause: misconfiguration
services: [auth-api]
---
# Postmortem: valid tokens rejected after an identity provider change, July 2026

## Summary
In July 2026 auth-api rejected most valid tokens for 25 minutes. During an identity provider migration, the expected audience value was edited in the config map with the old tenant name, so tokens from the new tenant failed validation.

## Timeline
16:02 config map updated by hand. 16:04 401 rate on token validation crossed 50%. 16:12 on-call ruled out a deploy. 16:20 the rejection reason in the auth logs named the audience claim. 16:27 corrected value applied and the 401 rate returned to baseline.

## Root cause
A wrong value in a manually edited config map, with no review and no validation against the provider's metadata.

## Resolution
Config change to the correct audience value.

## Follow-ups
Move auth settings into reviewed config. Validate issuer and audience against the provider's discovery document at startup.
