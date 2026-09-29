# ADR-002: PostgreSQL as the single system of record

- Status: Proposed
- Date: 2026-09-29
- Source: docs/spec/phase-0-spec.md

## Context

The domain is relational, needs integrity across users, history and search, and should avoid extra services.

## Decision

PostgreSQL 16 stores state, events, jobs, sessions, encrypted credentials and full-text indexes.

## Alternatives considered

MongoDB; SQLite; a dedicated vector database.

## Consequences

One backup and restore story; pgvector remains available without a new service.
