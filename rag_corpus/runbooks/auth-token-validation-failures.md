---
id: rb-auth-token-validation-failures
title: Valid tokens rejected with 401 by an auth service
root_causes: [misconfiguration, cert_expiry]
services: []
---
# Valid tokens rejected with 401 by an auth service

## Symptoms
Login, token introspection or token validation returns 401 for users and services whose tokens are valid. The 401 rate rises above half of requests at one point in time. The auth service is healthy otherwise. Common causes are an issuer, audience or JWKS URL that no longer matches what the identity provider puts in tokens, a clock skew setting, or an expired signing key.

## Checks
1. Call query_logs on the auth service for validation failure reasons; they usually name the claim that failed, such as iss, aud or kid.
2. Compare the expected value in the service config with the value in the rejected tokens.
3. Call list_recent_deploys to see whether the setting came with a deploy or a config edit.
4. Call query_metrics for cert_days_left if the reason mentions a signing key or certificate.

## Fix
Fix class config_change with the issuer, audience or key setting and its correct value. For an expired signing certificate, rotate_cert.

## Rollback
Restore the previous setting if valid tokens are still rejected.
