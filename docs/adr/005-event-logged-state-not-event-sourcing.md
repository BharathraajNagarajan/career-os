# ADR-005: Event-logged state, not event sourcing

- Status: Proposed
- Date: 2026-09-29
- Source: docs/spec/phase-0-spec.md

## Context

History must be preserved while current state stays fast to read; users and Gmail can both be wrong.

## Decision

Every state change writes an immutable DomainEvent in the same transaction as the materialized state. Projections are pure and recomputable. Corrections are new events (void, reopen), never edits or deletes.

## Alternatives considered

Mutable status plus audit table; full event sourcing.

## Consequences

Authoritative history with simple reads; account deletion needs a privileged path.
