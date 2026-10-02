# Task 2 Checkpoint Report: Database Foundation, Tenancy, Events, Job Queue

**What was implemented** (mapped to spec §14, Task 2)

| Acceptance criterion | Implementation |
| --- | --- |
| Alembic configured | `backend/alembic.ini`, `backend/alembic/env.py` (reads `MIGRATION_DATABASE_URL` from the environment only; `target_metadata` is the shared, naming-conventioned `MetaData`). One hand-cleaned migration `0001` with explicit grants and a working downgrade |
| `users`, `domain_events`, `jobs` created | `app/db/models.py`; exactly three tables, columns per brief D and spec 4.2/4.5/4.7 |
| Tenancy helper requires `user_id` in every repository method | `UserScopedRepository` (`app/db/tenancy.py`): keyword-only `user_id`, runtime `require_user_id()` type check, mypy-enforced; `DomainEventRepository.append` (no commit) and `list_for_aggregate` |
| Composite-FK convention with failing cross-user insert test | `UserOwned` mixin + `owned_table_args()` (`UNIQUE (user_id, id)`) + `owned_fk()`; `domain_events (user_id, voids_event_id) -> domain_events (user_id, id)`; test asserts `IntegrityError` naming that FK |
| ID re-resolution helper (INV-18) | `resolve_owned()` / `resolve_owned_many()`; foreign and missing IDs raise the same `NotFound` |
| Events table insert-only for the app role | Two roles: owner (migrations/bootstrap only) and `career_os_app` (LOGIN only). `domain_events` grant is `SELECT, INSERT`; UPDATE, DELETE, TRUNCATE denied (tests + psql) |
| `state_version` convention | `StateVersioned` mixin + `update_versioned()` raising `ConcurrencyConflict`; tested on a TEMP table |
| Worker claims with `SKIP LOCKED`, retries with backoff, honors `unique_key`, loads entities through the job's `user_id` | `app/jobs/` (`queue.py`, `registry.py`, `runner.py`) and `app/worker.py`; visibility-timeout recovery, lease checks, permanent `unknown_job_kind` / `invalid_payload`, `JobContext.require_user_id()` |
| Migration drift check in CI | CI backend job: Postgres 16 service, DB tests, then `upgrade head → alembic check → downgrade base → upgrade head`; plus an in-suite `alembic check` test |

Also: UUIDv7 `new_id()`, `TextEnum` + named CHECKs mirrored by `StrEnum`, `EventPayload` with `schema_version` and a `PayloadRegistry` that requires and applies upcasters, a one-shot Compose `migrate` service, `docs/architecture/database.md`, README updates.

**Evidence**

- Stack: `migrate` exited 0 (`db_bootstrap_completed`, `Running upgrade -> 0001`); `api` healthy; `GET /healthz` → `200 {"status":"ok","version":"0.1.0"}`; worker logged `worker_started` with no errors. Re-running `migrate` on the existing volume exits 0 with no migration applied.
- As `career_os_app` via psql: `\dp domain_events` → `career_os_app=ar/career_os` (INSERT, SELECT only); `UPDATE domain_events …` and `DELETE FROM domain_events` → `ERROR: permission denied for table domain_events`.
- Live worker: a job inserted with an unregistered kind went to `failed | attempts 1 | unknown_job_kind`; logs `job_started` / `job_failed` contained only allowlisted fields. The probe row was deleted afterwards.
- API container environment contains `DATABASE_URL` (app role) and no `POSTGRES_*`, `MIGRATION_DATABASE_URL` or `APP_DB_PASSWORD`.
- Migration cycle on an empty database: upgrade OK, `alembic check` → "No new upgrade operations detected", downgrade leaves only `alembic_version`, upgrade → `0001 (head)`.
- Notable tests: three threads claiming 40 jobs never overlap; a second session skips a row locked by an open claim; a failure stores `RuntimeError` (not the message) and sets `run_after` within the backoff window; the last attempt sets `failed`; a handler given another user's event ID gets `NotFound`; a handler's writes roll back on failure; a recovered job cannot be completed by its old worker (`LEASE_LOST`); SQL and parameters never appear in DEBUG logs.

**Changes outside the expected file set**

| File | Change | Reason |
| --- | --- | --- |
| `backend/app/core/logging.py` | `configure_logging` takes `BaseAppSettings`; pins the `sqlalchemy` logger to WARNING | Lets bootstrap/Alembic log without `DATABASE_URL`; guarantees SQL never reaches logs even at DEBUG |
| `backend/app/config.py` | Split into `BaseAppSettings`, `Settings`, `MigrationSettings`, `BootstrapSettings` | API/worker must not require migration credentials (brief G) |
| `backend/tests/test_worker.py` | `run()` now takes a `step` callable; added tests for idle-only sleep, finish-then-stop, and step errors | The worker loop now does real work |
| `infra/docker-compose.yml` | `api`/`worker` use an explicit variable list instead of `env_file: ../.env` | `env_file` put the owner `POSTGRES_PASSWORD` into the API and worker processes, undermining the two-role design |
| `backend/pyproject.toml` | ruff: ignore N818 (keep brief names such as `ConcurrencyConflict`), S311 in tests, `alembic` as third-party for isort; mypy also checks `alembic/`; `db` marker | Tooling for the new code |
| `app/worker.py`, `app/jobs/runner.py` | Extra log events `worker_step_failed` (error type only) and `job_lease_lost` | The loop survives DB outages; visibility of lease loss |
| `.env` (local, untracked) | Added `APP_DB_PASSWORD` (random, never printed) | Brief I |

**Important things I learned**

- On Windows, `localhost` resolves to `::1` first, while Compose publishes Postgres on `127.0.0.1` only. libpq's IPv6 attempt stalled (Alembic hung beyond 120 s; with `connect_timeout=5` it fell back after 5.1 s, versus 0.02 s for `127.0.0.1`). This is environmental, not app code; local URLs use `127.0.0.1`.
- Postgres roles are cluster-wide, not per database. Bootstrapping a test database `ALTER`s the same `career_os_app` role the dev stack uses, so tests must use the real `APP_DB_PASSWORD`; a random test password would silently break the running API's next login.
- SQLAlchemy's `DBAPIError` embeds the SQL text in its message. The `CREATE/ALTER ROLE … PASSWORD` statement therefore runs on the raw psycopg cursor, and engines use `hide_parameters=True` so bound values (emails, payloads) stay out of exceptions.
- Alembic autogenerate renders a custom `TypeDecorator` as `app.db.base.TextEnum()` (an app import inside a migration). Hand-cleaning it to `sa.Text()` is safe, and `alembic check` stays clean because it compares the decorator's `impl`.
- The naming convention would have produced a 64-character index name for `(user_id, aggregate_type, aggregate_id, occurred_at)`. Postgres truncates identifiers to 63 bytes, which would cause permanent drift, so long names are explicit (`ix_domain_events_aggregate`).
- Compose `env_file` passes every variable in `.env` into the container, so the API could read the owner password; per-service allowlists are what make the role split real.
- Guarding every job status update with `locked_by` and `attempts` turns the visibility timeout into a lease: a slow worker whose job was recovered rolls back instead of double-committing.
- Ruff's isort classifies `alembic` as first-party when a local `alembic/` directory exists, and needs `known-third-party`.

**Checks run and results**

| Check | Result |
| --- | --- |
| `docker compose … up --build -d`: migrate exit 0, api healthy, worker `worker_started` | ✅ |
| `GET /healthz` | ✅ 200 |
| Re-run `migrate` on existing volume (idempotent bootstrap) | ✅ exit 0 |
| psql as `career_os_app`: `\dp domain_events` = SELECT, INSERT only | ✅ `career_os_app=ar` |
| psql as `career_os_app`: UPDATE / DELETE on `domain_events` | ✅ permission denied |
| Live worker processes a job end to end | ✅ `unknown_job_kind` |
| `uv run ruff check .` | ✅ |
| `uv run ruff format --check .` | ✅ 44 files |
| `uv run mypy` (strict, includes `alembic/`) | ✅ 44 files |
| `uv run pytest` with Postgres | ✅ 94 passed |
| `uv run pytest` without `TEST_ADMIN_DATABASE_URL` | ✅ unit tests pass, DB tests skipped |
| Migrations on empty DB: upgrade → check → downgrade → upgrade | ✅ no drift |
| Frontend: lint, typecheck, test, build | ✅ unchanged (3 tests passed, build OK) |
| GitHub Actions run 36978365452 @ `525b597` | ✅ backend (incl. Postgres service, pytest, migration step), frontend, secrets |

**Deviations from the frozen spec**

None to the schema, invariants or architecture. Two implementation interpretations, for your review:

- Spec 11 describes integration tests with "a transaction-per-test Postgres". The concurrency tests need committed rows visible to several sessions, so the harness uses one fresh database per session with an owner-role `TRUNCATE` after each test (brief K: "keeps tests independent").
- Visibility-timeout recovery re-queues stale running jobs, but marks them `failed` (`visibility_timeout`) when they have already used `max_attempts`, so a job that crashes its worker cannot loop forever.

**Unresolved issues**

- `gh` is not authenticated, so I could not open the PR; use the compare URL below. CI status was read through the public GitHub API, and job logs (exact CI test counts) need authentication.
- The CI pytest step does not fail if DB tests are skipped; they run because the workflow sets `TEST_ADMIN_DATABASE_URL`. A guard could be added later if wanted.
- No `.gitattributes` added (rule J); CRLF warnings on commit are the usual `core.autocrlf` notices, and nothing failed.

**Git state**

- Branch: `task-02-database-foundation`, pushed to origin
- Commits: `8c477f3` brief, `4965719` DB foundation, `b61308a` job queue and worker, `525b597` migrate service/CI/docs, plus this report
- PR: not opened (gh unauthenticated). Compare URL: https://github.com/BharathraajNagarajan/career-os/compare/main...task-02-database-foundation?expand=1
- CI on `525b597`: backend ✅, frontend ✅, secrets ✅

**Recommendation: approve Task 2.**

Every Task 2 acceptance criterion has a direct test, plus live evidence for the two that matter most operationally: insert-only events enforced by Postgres privileges, and a worker that claims, retries and fails jobs safely. The local checks and the GitHub Actions run (including DB tests and the migration drift check) are green. The two out-of-scope edits (Compose env allowlist, logging settings base) are small and security-motivated, and the frontend is untouched. Task 3 has not been started.
