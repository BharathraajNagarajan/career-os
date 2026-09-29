# ADR-009: Gmail: read-only scope, 12-hour polling, confirm-all

- Status: Accepted (baseline approval, O-4)
- Date: 2026-09-29
- Source: docs/spec/phase-0-spec.md

## Context

Gmail should remove manual labeling without risking corrupted career state or excess API use.

## Decision

`gmail.readonly` only; bounded backfill; sync about every 12 hours with jitter plus Sync now; capped classification; every finding that creates or changes a record becomes a ReviewItem; raw bodies not stored.

## Alternatives considered

Push notifications; auto-apply for high-confidence findings; broader scopes.

## Consequences

Minimal API activity and one confirmation path; up to 12 hours latency unless the user syncs; public launch needs restricted-scope verification.
