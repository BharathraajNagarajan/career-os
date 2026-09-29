# ADR-012: Company is a per-user entity

- Status: Accepted (baseline approval, O-7)
- Date: 2026-09-29
- Source: docs/spec/phase-0-spec.md

## Context

Shared company records could leak information across users.

## Decision

Companies are owned by one user; no global company directory in Phase 1.

## Alternatives considered

Global canonical companies with per-user overlays.

## Consequences

No cross-user leakage; duplicate canonicalization per user.
