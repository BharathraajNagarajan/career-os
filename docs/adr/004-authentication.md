# ADR-004: Authentication

- Status: Accepted (baseline approval, O-2)
- Date: 2026-09-29
- Source: docs/spec/phase-0-spec.md

## Context

Users need accounts; Gmail access is a separate, optional grant.

## Decision

Google OIDC sign-in with PKCE, state and nonce; server-side sessions stored hashed in Postgres; httpOnly, Secure, SameSite=Lax cookies; CSRF token on mutations. Gmail uses a separate incremental grant.

## Alternatives considered

Managed auth provider; JWT-only sessions.

## Consequences

No auth vendor; Google-only login at first; Career OS owns session security.
