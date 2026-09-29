# ADR-010: No semantic retrieval in Phase 1

- Status: Proposed
- Date: 2026-09-29
- Source: docs/spec/phase-0-spec.md

## Context

Retrieval in Phase 1 is mostly exact and small per user.

## Decision

Skill Inventory aliases, normalized keys and Postgres full-text search. Adopt pgvector only on a measured recall gap.

## Alternatives considered

pgvector now; dedicated vector database.

## Consequences

No embedding cost or pipeline yet; some paraphrase misses.
