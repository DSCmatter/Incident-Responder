---
id: rb-tls-certificate-expired
title: All TLS handshakes fail at once because a certificate expired
root_causes: [cert_expiry]
services: []
---
# All TLS handshakes fail at once because a certificate expired

## Symptoms
Every request that crosses one TLS connection fails from an exact moment, often 00:00 UTC, and the success rate of the affected flow (card charges, partner calls, logins) falls to 0%. Clients report handshake failures or certificate errors. There is no gradual onset, no deploy and no resource pressure. The remaining validity of the certificate reached zero at that moment.

## Checks
1. Call query_metrics for cert_days_left on the service; a value at or below zero confirms it.
2. Call query_logs for handshake, certificate or x509 errors and note when the first one appears.
3. Call list_recent_deploys to rule out a release at the same time.

## Fix
Fix class rotate_cert on the service whose serving or client certificate expired.

## Rollback
If the new certificate is rejected, reinstall the previous chain while the issuer reissues. An expired certificate cannot be restored as a fix.
