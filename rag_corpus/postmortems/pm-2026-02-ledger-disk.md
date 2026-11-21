---
id: pm-2026-02-ledger-disk
title: "Postmortem: ledger ingest stalled on a full volume, February 2026"
incident: S05
root_cause: disk_full
services: [ledger-writer]
---
# Postmortem: ledger ingest stalled on a full volume, February 2026

## Summary
In February 2026 ledger-writer stopped committing entries for 50 minutes overnight. Its data volume filled because the archiver that ships old segments to object storage had been failing silently for a week.

## Timeline
Days before: archiver uploads failed on an expired storage token. 02:10 the volume reached 100%. 02:15 ingest backlog alert fired. 02:40 on-call found write failures and the full volume. 03:00 shipped segments deleted, writes resumed and the backlog drained by 03:30.

## Root cause
A full data volume. Retention relied on the archiver, which had no alert of its own.

## Resolution
Freed space by deleting segments already present in object storage, then renewed the archiver token.

## Follow-ups
Alert at 80% disk used. Alert when the archiver has not shipped a segment for an hour.
