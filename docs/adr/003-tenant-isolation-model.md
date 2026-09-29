# ADR-003: Tenant isolation model

- Status: Accepted (baseline approval, O-3)
- Date: 2026-09-29
- Source: docs/spec/phase-0-spec.md

## Context

Multi-user isolation is required from the beginning.

## Decision

Shared schema; `user_id` on every owned row; composite foreign keys; repositories require `user_id`; IDs outside foreign keys are re-resolved per user (INV-18); a route-generated isolation test matrix. Postgres RLS is deferred and revisited before any multi-user beta.

## Alternatives considered

RLS from day one; schema or database per tenant.

## Consequences

Strong and testable; relies on code discipline until RLS.
