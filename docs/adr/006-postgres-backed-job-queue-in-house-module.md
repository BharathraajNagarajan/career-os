# ADR-006: Postgres-backed job queue (in-house module)

- Status: Accepted (Task 1)
- Date: 2026-09-29
- Source: docs/spec/phase-0-spec.md

## Context

Parsing, extraction, sync and deletion must run asynchronously, and a job must commit atomically with the state that created it. The spec left the library choice to Task 1: `procrastinate` or a small in-house module.

## Decision

Use a small in-house module over a `jobs` table: SQLAlchemy inserts in the caller's transaction, workers claim with `SELECT ... FOR UPDATE SKIP LOCKED`, retries with backoff, `unique_key` for idempotency, payloads hold IDs only, and the table is managed by Alembic like every other table. Built in Task 2; Task 1 ships the worker process and loop.

## Alternatives considered

`procrastinate` (mature, but its own schema management and connector make same-transaction enqueueing through SQLAlchemy awkward and put a second migration system beside Alembic); Celery or RQ with Redis (new infrastructure); Temporal (far beyond the need).

## Consequences

Roughly a few hundred lines to own and test, fully visible in SQL, one migration system. Throughput ceiling is far above MVP needs; revisit only on measured load.
