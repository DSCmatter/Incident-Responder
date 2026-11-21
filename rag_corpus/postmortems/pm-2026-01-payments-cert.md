---
id: pm-2026-01-payments-cert
title: "Postmortem: card payments down after a certificate expired, January 2026"
incident: S08
root_cause: cert_expiry
services: [payments-gw]
---
# Postmortem: card payments down after a certificate expired, January 2026

## Summary
In January 2026 every card payment failed for 41 minutes from 00:00 UTC. The client certificate payments-gw presents to the card processor for mutual TLS expired at midnight, and the processor refused every handshake.

## Timeline
Two weeks before: expiry warnings in logs, unread. 00:00 handshakes started failing. 00:06 charge success alert fired. 00:25 on-call found the expiry date. 00:41 a renewed certificate was installed and charges recovered.

## Root cause
Manual certificate renewal with no owner and no alert on remaining validity.

## Resolution
Rotated the certificate.

## Follow-ups
Automated renewal 30 days before expiry. Alert when cert_days_left falls below 14.
