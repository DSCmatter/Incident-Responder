---
id: rb-certificate-rotation
title: Rotate a serving or client certificate
root_causes: [cert_expiry]
services: []
---
# Rotate a serving or client certificate

## Symptoms
Certificate expiry warnings appear in logs days ahead, cert_days_left trends to zero, and then connections fail with certificate expired or unknown authority errors. Mutual TLS to a payment processor or partner fails in both directions if our client certificate expired.

## Checks
1. Call query_metrics for cert_days_left and note when it crossed zero.
2. Call query_logs for expiry warnings in the days before; they show how long the problem was visible.
3. Confirm which certificate expired: the one we serve, or the one we present as a client.

## Fix
Fix class rotate_cert on the service that holds the certificate. Renewal issues a new certificate and reloads it without a restart where supported.

## Rollback
Keep the old certificate files until the new one serves traffic. Revert only if the new chain is incomplete, and escalate to the PKI owner.
