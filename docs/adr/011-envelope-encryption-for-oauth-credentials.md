# ADR-011: Envelope encryption for OAuth credentials

- Status: Proposed
- Date: 2026-09-29
- Source: docs/spec/phase-0-spec.md

## Context

A database leak alone must not expose OAuth tokens.

## Decision

AES-256-GCM with a per-record data key wrapped by a key-encryption key held outside the database (environment secret now, KMS later), versioned for rotation. Only the credential vault decrypts.

## Alternatives considered

Database-level encryption only; plaintext.

## Consequences

Key rotation runbook required.
