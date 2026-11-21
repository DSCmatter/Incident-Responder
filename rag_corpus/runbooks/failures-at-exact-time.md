---
id: rb-failures-at-exact-time
title: Failures that begin at an exact clock time
root_causes: [cert_expiry]
services: []
---
# Failures that begin at an exact clock time

## Symptoms
An outage starts precisely on a boundary such as midnight UTC, the top of an hour or the first day of a month, with success rate dropping to near 0% in one step. Something time-based expired or switched: a certificate, a signing key, a license or an API credential with a fixed end date.

## Checks
1. Call query_metrics for error_rate and find the first minute of failure; an exact boundary is the clue.
2. Call query_metrics for cert_days_left; zero at the same minute means a certificate expired.
3. Call query_logs for the first error and its reason, such as expired, not valid after, or handshake.
4. Call list_recent_deploys to rule out a release at that moment.

## Fix
For an expired certificate, fix class rotate_cert. For an expired credential with no matching tool, escalate_human to the credential owner.

## Rollback
Restore the previous certificate only to recover a broken chain; it stays expired.
