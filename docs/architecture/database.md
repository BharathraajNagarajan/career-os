# Database foundation

PostgreSQL 16 is the system of record and the job queue (ADR-002, ADR-006). Access is SQLAlchemy 2 (typed, synchronous) over psycopg 3. Migrations are Alembic. Spec references: 1.3, 4.1, 4.2, 4.5, 4.7, 5.5, 11.

## Roles and grants

| Role | Used by | Connection setting | Privileges |
| --- | --- | --- | --- |
| Owner (`POSTGRES_USER`) | `python -m app.db.bootstrap`, `alembic` | `MIGRATION_DATABASE_URL` | Owns the schema; runs DDL |
| `career_os_app` | API and worker | `DATABASE_URL` | `LOGIN` only; `CONNECT` on the database, `USAGE` on `public`, plus per-table grants below |

| Table | `career_os_app` privileges | Why |
| --- | --- | --- |
| `users` | SELECT, INSERT, UPDATE | No DELETE: account deletion goes through `delete_user_account()` (below) |
| `auth_identities` | SELECT, INSERT, UPDATE | Provider identities; holds no tokens |
| `sessions` | SELECT, INSERT, UPDATE, DELETE | Hashed session tokens; sign-out and revocation delete rows |
| `domain_events` | SELECT, INSERT | INV-04: append-only is enforced by the database, not by convention |
| `jobs` | SELECT, INSERT, UPDATE, DELETE | Queue bookkeeping |
| `profiles` | SELECT, INSERT, UPDATE | One row per user, created lazily; no DELETE (removed with the account) |
| `artifacts` | SELECT, INSERT, and UPDATE on `extracted_text`, `extraction_status`, `extraction_error_code` only | INV-05: the stored file's identity (`storage_key`, `sha256`, `byte_size`, `mime_type`, `original_filename`) cannot change by privilege. No DELETE |
| `resumes` | SELECT, INSERT, UPDATE | Archive only; no DELETE |
| `resume_lanes` | SELECT, INSERT, UPDATE | Archive only; no DELETE |
| `llm_runs` | SELECT, INSERT, and UPDATE on `status`, `error_code`, `input_tokens`, `output_tokens`, `latency_ms`, `cost_usd`, `output`, `settled_at` only | A run is a record of what was sent and bought: its identity, prompt, model, reservation and manifest cannot change by privilege; only settlement can. No DELETE |
| `review_items` | SELECT, INSERT, and UPDATE on `status`, `decided_at`, `decided_payload`, `decision_note`, `state_version`, `updated_at` only | The proposal (`proposed_payload`, type, source, rationale) is immutable once written. No DELETE |
| `companies` | SELECT, INSERT, UPDATE | Editable by the user; no DELETE (merge, when built, re-points children) |
| `opportunities` | SELECT, INSERT, UPDATE | State machine and editable fields; no DELETE |
| `applications` | SELECT, INSERT, UPDATE | State machine; the stage columns are a cache of the events; no DELETE |
| `contacts` | SELECT, INSERT, UPDATE, DELETE | DELETE exists only so a merge can remove the merged contact after re-pointing its children; history stays in `domain_events` |
| `contact_companies`, `contact_opportunities`, `strategy_rules` | SELECT, INSERT, UPDATE, DELETE | Removing a link or a rule is legitimate |
| `interactions` | SELECT, INSERT, and UPDATE on `contact_id` only | History: the summary cannot change and nothing is deleted; `contact_id` can move only so a merge can re-point rows. No DELETE |
| `recruiting_actions` | SELECT, INSERT, UPDATE | State machine; no DELETE |
| `qualifications` | SELECT, INSERT, DELETE, and UPDATE on `kind`, `ordinal`, `category`, `skill_keys`, `min_years`, `is_hard_constraint`, `updated_at` only | "Verbatim text always kept": `text_verbatim`, `origin`, `llm_run_id`, the parent link and the owner cannot change by privilege. Users may delete a requirement line |

`delete_user_account(target uuid) RETURNS boolean` (migration 0002) is `SECURITY DEFINER`, owned by the migration owner, with `search_path` pinned to `pg_catalog, public`. `EXECUTE` is revoked from `PUBLIC` and granted to `career_os_app`. It deletes the `users` row only when `status = 'deletion_requested'`; `ON DELETE CASCADE` then removes the user's `domain_events`, `jobs`, `auth_identities`, `sessions`, `profiles`, `artifacts`, `resumes`, `resume_lanes`, `llm_runs`, `review_items`, `qualifications`, `applications`, `opportunities`, `companies`, `contacts`, `contact_companies`, `contact_opportunities`, `interactions`, `recruiting_actions` and `strategy_rules`. Stored files are removed earlier by a deletion hook ([artifacts.md](artifacts.md)). See [auth.md](auth.md).

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

## Circular foreign keys (migration 0003)

`resumes.lane_id` references `resume_lanes`, and `resume_lanes.default_resume_id` references `resumes`; both are composite `(user_id, id)` keys, so neither can point at another user's row. Neither table can be created with both constraints inline, so the migration creates `resume_lanes` and `resumes` first and adds `fk_resume_lanes_user_id_default_resume_id_resumes` afterwards with an `ALTER`; the downgrade drops that constraint before the tables. The model marks it `use_alter=True`. All three references between these tables and `artifacts` use `NO ACTION` (see [artifacts.md](artifacts.md) for why, and for what was and was not observed about `RESTRICT`).

## LLM runs and review items (migration 0004)

`llm_runs` is user-owned and settled once: a row is inserted as `reserved` with its worst-case `reserved_cost_usd`, then updated to `succeeded` or `failed` with the real `cost_usd`, tokens and latency. Check constraints keep `status`, `cost_usd` and `settled_at` consistent (a reserved row has neither; a settled row has both), tie `attempt = 2` to a `repair_of_run_id` (composite FK to `llm_runs`, so a repair can only point at the same user's run), and keep `purpose`, `tier` and `provider` to closed lists. The index `(user_id, created_at)` serves the daily-total query. No prompt or model text is stored; `context_manifest` and `output` are typed JSONB, and nullable JSONB columns use `none_as_null` so "no output" is SQL `NULL`, not JSON `null`.

`review_items` is user-owned with a `state_version`. Check constraints make `decided_at` present exactly when the status is not `pending` and allow `decided_payload` only on confirmed items. `llm_run_id` is a composite FK to `llm_runs`. `evidence_ref_id` is a plain uuid with no FK because it will point at tables that do not exist yet; it is always re-resolved through a user-scoped repository before use (INV-18).

## Companies, opportunities and qualifications (migration 0005)

`companies` is unique on `(user_id, normalized_name)` and its `normalized_name` cannot be empty; aliases and domains are `text[]` with no extra index (see [opportunities.md](opportunities.md) for why). `opportunities` has composite foreign keys to `companies` (nullable `company_id` until resolved), `artifacts` (`jd_artifact_id`, unique, so one opportunity per stored JD) and `llm_runs`. A check ties `extraction_error_code` to `extraction_status = 'failed'`. The partial unique index `uq_opportunities_company_external_job_id` on `(user_id, company_id, external_job_id)` applies only where both the job id and the company are present, so postings without either never collide. `locations` is typed JSONB (`{schema_version, items}`) written from a Pydantic model. `status` defaults to `new`; Task 7 moves it through the decision machine ([state-machines.md](state-machines.md)). `latest_evaluation_id` is a plain uuid with **no foreign key yet**: the evaluations table arrives in Task 11, which adds the constraint. `discovered_at` and `content_updated_at` default to the database clock. `qualifications` has composite foreign keys to `opportunities` and `llm_runs`, `origin` (`extracted` or `user`) and checks on `ordinal`, `min_years` (0 to 50) and `text_verbatim` length. A test proves every grant above, including that `text_verbatim` cannot be updated and that neither `companies` nor `opportunities` can be deleted.

## Applications (migration 0006)

`applications` is the only new table in Task 7. Composite foreign keys tie `opportunity_id` (required), `resume_id` and `lane_id` (both nullable) to the same user's rows (INV-02), so a foreign resume or lane cannot be written even by a buggy query. `stage` is checked against the spec's nine stages and `channel` against `company_site`, `job_board`, `referral`, `recruiter`, `email`, `other` (the spec defines no channel list; `other` is the default). A check ties `is_terminal` to the five terminal stages, so the two columns cannot disagree. The partial unique index `uq_applications_open_per_opportunity` on `(user_id, opportunity_id) WHERE NOT is_terminal` is the spec's "one non-terminal application per opportunity" and the race guard for concurrent applies. `stage`, `is_terminal` and `state_version` are a materialized projection of the application's `domain_events`, rewritten in the same transaction as every event. The app role gets SELECT, INSERT and UPDATE and no DELETE; account deletion cascades from `users`. Tests prove every constraint, the index and the grants.

Events written by Task 7 (all in `domain_events`, each with a registered typed payload at `schema_version` 1; no new event table):

| Aggregate | Event types | Written by |
| --- | --- | --- |
| opportunity | `OPPORTUNITY_DECIDED` | Save, Skip, Close, Apply |
| application | `APPLICATION_SUBMITTED` | Apply |
| application | every other type in spec 5.1, including `APPLICATION_REOPENED` and `EVENT_VOIDED` (with `voids_event_id`) | record, void and reopen commands |

See [state-machines.md](state-machines.md) for the rules.

## Contacts, interactions, actions and rules (migration 0007)

Six new tables, all user-owned with composite foreign keys: `contacts`, `contact_companies`, `contact_opportunities`, `interactions`, `recruiting_actions`, `strategy_rules`. Constraints, grants and the reasoning are in [contacts-actions-rules.md](contacts-actions-rules.md). The grants above are the whole privilege story: contacts can be deleted only by the merge; interactions can change only `contact_id`; recruiting actions are never deleted. Tests prove every enum check, composite foreign key, uniqueness rule, grant (including that an interaction summary cannot be updated) and the account-deletion cascade.

Events written by Task 8 (all in `domain_events` with typed payloads at `schema_version` 1, ids and field names only):

| Aggregate | Event types | Written by |
| --- | --- | --- |
| contact | `CONTACT_CREATED`, `CONTACT_EDITED` (field names), `CONTACT_MERGED` (on the survivor), `CONTACT_LINKED`, `CONTACT_UNLINKED` | contact commands |
| recruiting_action | `RECRUITING_ACTION_CREATED`, `_EDITED`, `_SNOOZED`, `_WOKEN`, `_COMPLETED`, `_DISMISSED`, `_SUPERSEDED`, `_RESTORED` | create, edit and every transition, with the actor |

The application note payload (`NOTE_ADDED`, `OUTREACH_SENT` and the other note-shaped types) is now `schema_version` 2 with an optional `interaction_id`; the registered v1 to v2 upcaster keeps older rows loading.

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
