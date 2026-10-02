# Database foundation

PostgreSQL 16 is the system of record and the job queue (ADR-002, ADR-006). Access is SQLAlchemy 2 (typed, synchronous) over psycopg 3. Migrations are Alembic. Spec references: 1.3, 4.1, 4.2, 4.5, 4.7, 5.5, 11.

## Roles and grants

| Role | Used by | Connection setting | Privileges |
| --- | --- | --- | --- |
| Owner (`POSTGRES_USER`) | `python -m app.db.bootstrap`, `alembic` | `MIGRATION_DATABASE_URL` | Owns the schema; runs DDL |
| `career_os_app` | API and worker | `DATABASE_URL` | `LOGIN` only; `CONNECT` on the database, `USAGE` on `public`, plus per-table grants below |

| Table | `career_os_app` privileges | Why |
| --- | --- | --- |
| `users` | SELECT, INSERT, UPDATE | Account deletion is a privileged path (Task 3) |
| `domain_events` | SELECT, INSERT | INV-04: append-only is enforced by the database, not by convention |
| `jobs` | SELECT, INSERT, UPDATE, DELETE | Queue bookkeeping |

The bootstrap command creates `career_os_app`, or resets its password if it exists, with `LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS`. It is idempotent. Table grants live in the migration that creates each table, so they are versioned and reviewed with the schema. Roles are cluster-wide: bootstrapping any database on the same server, including a test database, sets the same role's password, so every environment on one server must share `APP_DB_PASSWORD`. The password is interpolated into connection URLs and must be URL-safe.

The API and worker never receive owner credentials: Compose passes them an explicit variable list rather than the whole `.env`.

## Conventions (spec 4.1)

| Convention | Implementation |
| --- | --- |
| IDs | UUIDv7 generated in Python by `app.core.ids.new_id()` |
| Ownership | `UserOwned` mixin (`user_id NOT NULL REFERENCES users ON DELETE CASCADE`) plus `owned_table_args()` for `UNIQUE (user_id, id)`; a unit test fails if an owned table lacks it |
| Child references | `owned_fk("parent_id", "parents")` builds `FOREIGN KEY (user_id, parent_id) REFERENCES parents (user_id, id)` |
| Time | `timestamptz`; `server_default now()` for `created_at`, `recorded_at`, `run_after` |
| Enums | `text` + named `CHECK` from `enum_check()`, mirrored by a Python `StrEnum` through the `TextEnum` column type |
| JSONB | Written only from Pydantic models; event payloads extend `EventPayload` and carry `schema_version` |
| Constraint names | `MetaData` naming convention (`pk_`, `uq_`, `ck_`, `fk_`, `ix_`); long names are given explicitly so they stay under 63 bytes and `alembic check` is stable |
| Optimistic concurrency | `StateVersioned` mixin (`state_version`, default 1) and `update_versioned()`, which updates `WHERE id AND user_id AND state_version = expected`, bumps the version and raises `ConcurrencyConflict` on zero rows |

Event payload evolution: `PayloadRegistry.register(event_type, Model, version=N, upcasters={1: f, ...})` requires an upcaster for every older version; `load()` upcasts stored JSON step by step to the current model. Stored events are never rewritten.

## Tenancy and INV-18

- Every repository method takes `user_id` as a required keyword-only argument (`UserScopedRepository`), checks it is a `UUID`, and filters by it.
- Composite foreign keys make cross-user references impossible where an FK exists, e.g. `domain_events (user_id, voids_event_id) -> domain_events (user_id, id)`.
- IDs that are not FK-protected (JSONB, arrays, job payloads, `aggregate_id`, client input) are re-resolved with `resolve_owned()` / `resolve_owned_many()`. A foreign ID and a missing ID both raise the same `NotFound`, so existence never leaks across users.

## Job lifecycle

```
enqueue (caller's transaction) -> queued
claim (own short transaction, FOR UPDATE SKIP LOCKED, attempts += 1) -> running
process (new transaction: handler work + status=succeeded commit together) -> succeeded
  on exception: roll back, then in a separate transaction
    attempts < max_attempts -> queued, run_after = now + backoff
    attempts = max_attempts -> failed
  unknown kind / invalid payload -> failed (unknown_job_kind / invalid_payload)
running longer than JOB_VISIBILITY_TIMEOUT_SECONDS -> queued again (or failed if out of attempts)
```

- `enqueue(session, kind=, payload=, user_id=, unique_key=, run_after=, correlation_id=)` never commits. A `unique_key` that matches a queued or running job returns that job's id (partial unique index plus `ON CONFLICT DO NOTHING`).
- Backoff is `min(max, base * 2^(attempt-1))` with jitter in its upper half.
- `last_error_code` is the exception type name, never the message.
- Status updates check the lease (`locked_by` and `attempts`), so a worker whose job was recovered by the visibility timeout cannot mark it succeeded; its work is rolled back.
- Handlers receive a `JobContext` (`session`, `job_id`, `user_id`, `correlation_id`) and load entities only through user-scoped repositories with `ctx.require_user_id()`.
- Payloads hold IDs only, never content or secrets.
- The worker sleeps `WORKER_POLL_INTERVAL_SECONDS` only when no job was claimed, and on SIGTERM finishes the current job before exiting. Log events: `job_started`, `job_succeeded`, `job_retry_scheduled`, `job_failed`, `job_lease_lost`.

## Running migrations

Compose runs a one-shot `migrate` service before the API and worker start:

```bash
docker compose -f infra/docker-compose.yml --env-file .env up --build -d
docker compose -f infra/docker-compose.yml --env-file .env logs migrate
```

Without Compose, from `backend/` with Postgres reachable:

```bash
export MIGRATION_DATABASE_URL=postgresql://<owner>:<owner-password>@127.0.0.1:5432/career_os
export APP_DB_PASSWORD=<app-password>
uv run python -m app.db.bootstrap
uv run alembic upgrade head
uv run alembic check                       # models and migrations must match
uv run alembic revision --autogenerate -m "describe change"   # then read and clean the file
```

Every new table's migration must include its `GRANT` statements for `career_os_app`.

## Running database tests

Tests marked `db` create a fresh `career_os_test_<random>` database, bootstrap it, run `alembic upgrade head`, give tests app-role sessions (owner sessions only where needed), truncate between tests, and drop the database at the end. Without `TEST_ADMIN_DATABASE_URL` they are skipped and unit tests still run.

```bash
docker compose -f infra/docker-compose.yml --env-file .env up -d postgres
cd backend
export TEST_ADMIN_DATABASE_URL=postgresql://<owner>:<owner-password>@127.0.0.1:5432/career_os
export APP_DB_PASSWORD=<the value in .env>
uv run pytest
```

Use `127.0.0.1`, not `localhost`, on Windows: `localhost` resolves to `::1` first, Compose publishes Postgres on IPv4 only, and the IPv6 attempt stalls before falling back.

CI runs the same tests against a `postgres:16` service, then `upgrade head`, `alembic check`, `downgrade base` and `upgrade head` on an empty database.
