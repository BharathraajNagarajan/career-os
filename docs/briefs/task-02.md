This is the full Task 2 brief. Step 0 (pre-flight) is ALREADY COMPLETE: root .venv deleted, interpreter set to backend\.venv, Docker running, branch task-02-database-foundation created. Confirm you are on that branch, then FIRST save this entire brief verbatim to docs/briefs/task-02.md and commit it on the branch ("docs: Task 2 brief"), so future sessions can recover it from the repository.

You are my hands-on implementation and debugging partner for Career OS, working in C:\Users\bhara\career-os on Windows with Docker Desktop (WSL2). GNU Make is not installed; use docker compose, uv and npm directly. Everything you need is in this brief, the repository, and docs/.

AUTHORIZED SCOPE
Only Phase 1A Task 2: Database foundation, tenancy pattern, events table, job queue. Do NOT start Task 3 (auth, sessions, users API, account deletion). Do NOT add any table other than users, domain_events and jobs.

SOURCE OF TRUTH (read before coding)
- docs/spec/phase-0-spec.md (FROZEN): section 0A (canonical terms), 1.3 (invariants, especially INV-02, INV-04, INV-17, INV-18), 4.1 (conventions), 4.2 (identity tables), 4.5 (DomainEvent), 4.7 (Job), 5.5 (state machine rules), 11 (testing), 14 (Task 2 acceptance criteria)
- docs/adr/005-event-logged-state-not-event-sourcing.md, docs/adr/006-postgres-backed-job-queue-in-house-module.md, docs/adr/003-tenant-isolation-model.md
- docs/checkpoints/task-01.md, README.md, backend/app/ (existing config, logging, worker)
The spec wins over this brief if they disagree. If they disagree, stop and escalate (see ESCALATION).

ROLE AND WORKING RULES
- You own local operations: terminal, Docker/Compose, Git, dependencies, tests, debugging, code edits for this task only.
- Never install anything system-wide (winget, global npm, pip outside uv) without asking me first. Project dependencies via uv add / npm are fine.
- Approve-each-time operations: git push, docker compose down -v, deleting files outside build caches.
- Learning mode: briefly explain meaningful concepts as you work (migrations, transactions, roles/grants, composite FKs, locking/SKIP LOCKED, retries/backoff, idempotency, optimistic concurrency, CI database checks, root causes of errors). Skip explanations for trivial commands.
- Debugging rule: observe → identify the failing layer → root-cause hypothesis → inspect evidence → smallest justified change → rerun the failing check → rerun related checks. Say explicitly when a problem is environmental (Windows, WSL2, Docker, PATH, line endings) rather than application code.
- No code comments; keep code minimal and readable; do not restructure working Task 1 code unless required.

TASK 2 ACCEPTANCE CRITERIA (spec section 14, verbatim intent)
Alembic configured; users, domain_events, jobs created; tenancy helper requires user_id in every repository method; composite-FK convention demonstrated with a failing cross-user insert test; ID re-resolution helper for non-FK references (INV-18); events table insert-only for the app role; state_version convention; worker claims jobs with SKIP LOCKED, retries with backoff, honors unique_key, and loads every entity through the job's user_id; migration drift check in CI.

IMPLEMENTATION DECISIONS ALREADY MADE BY THE PLANNING CHAT (follow these; they translate the spec, they do not change it)

A. Database access
- SQLAlchemy 2 (typed, synchronous) with psycopg 3 (psycopg[binary]). Sync is deliberate: FastAPI sync endpoints run in a threadpool, and the worker is synchronous. Never enable SQL echo; SQL must not appear in logs.
- Session factory in app/core/db.py; one transaction per unit of work; callers own commit/rollback.

B. Two database roles (required for "insert-only for the app role")
- Owner role: POSTGRES_USER from .env. Runs migrations and role bootstrap only. Exposed to the app ONLY as MIGRATION_DATABASE_URL (SecretStr), used by alembic and the bootstrap command, never by the API or worker at runtime.
- App role: fixed name career_os_app (a role name, not user data), password from APP_DB_PASSWORD in .env. The API and worker connect only as this role via DATABASE_URL.
- app/db/bootstrap.py (run as python -m app.db.bootstrap with the owner URL): idempotently create career_os_app if missing, or update its password if it exists, with LOGIN and no other attributes; grant CONNECT on the database and USAGE on schema public. Never log the password.
- Table privileges are granted explicitly inside each migration, so grants are versioned and reviewable:
  - users: SELECT, INSERT, UPDATE (no DELETE; account deletion is a privileged path in Task 3)
  - domain_events: SELECT, INSERT only
  - jobs: SELECT, INSERT, UPDATE, DELETE
- Test: connected as career_os_app, UPDATE and DELETE on domain_events fail with a permission error; INSERT and SELECT succeed.

C. Conventions (spec 4.1) as shared code in app/core/ or app/db/
- IDs: UUIDv7 primary keys generated in Python (new_id() in app/core/ids.py). Use the uuid6 package or a small RFC 9562 implementation. Test version and variant bits and time ordering.
- Ownership: a mixin for user-owned tables with user_id NOT NULL referencing users(id) ON DELETE CASCADE, plus UNIQUE (user_id, id), so children can use composite FKs.
- Timestamps: timestamptz with server_default now().
- Enums: text columns with named CHECK constraints, mirrored by Python StrEnum.
- JSONB: only via typed Pydantic models. Event payload JSON includes schema_version. Readers must be able to upcast historical versions; for Task 2 provide the minimal mechanism (a payload base model carrying schema_version, plus a registry hook) without inventing domain payloads.
- SQLAlchemy MetaData naming convention for constraints and indexes, so migrations are deterministic and the drift check is stable.
- state_version: a mixin plus a helper that performs an optimistic update (UPDATE ... WHERE id = :id AND user_id = :user_id AND state_version = :expected) and raises a typed ConcurrencyConflict on zero rows. Test it against a TEMP table created inside the test; no extra migration tables.

D. Tables (exactly three)
- users (not user-owned): id, primary_email (unique, case-insensitive via lower() unique index), display_name, status CHECK ('active','deletion_requested'), created_at, deleted_at.
- domain_events (user-owned, insert-only for the app role): id, user_id, aggregate_type CHECK ('opportunity','application','recruiting_action','skill','claim','contact','company'), aggregate_id uuid (no FK; polymorphic by design, covered by INV-18), event_type text (open set, validated in code later), occurred_at, recorded_at (default now()), actor CHECK ('user','system','gmail'), source_ref_id uuid NULL (no FK yet; external_refs arrives in Task 12), payload jsonb NOT NULL, voids_event_id uuid NULL, correlation_id uuid NULL. Composite FK (user_id, voids_event_id) REFERENCES domain_events(user_id, id). Index (user_id, aggregate_type, aggregate_id, occurred_at).
- jobs: id, user_id NULL REFERENCES users(id) ON DELETE CASCADE (NULL only for system jobs), kind text, payload jsonb (IDs only, never content or secrets), status CHECK ('queued','running','succeeded','failed'), attempts int default 0, max_attempts int default 5, run_after timestamptz default now(), locked_by text NULL, locked_at timestamptz NULL, unique_key text NULL, last_error_code text NULL, correlation_id uuid NULL, created_at, updated_at, finished_at NULL. Partial UNIQUE index on unique_key WHERE status IN ('queued','running'). Index on (status, run_after).

E. Tenancy helper and INV-18
- A repository base pattern where every read/write method takes user_id as a required keyword-only argument and filters by it. Demonstrate with a DomainEvent repository: append (in the caller's transaction, no commit) and list for an aggregate.
- resolve_owned(session, model, *, user_id, id) and resolve_owned_many(...) return only rows owned by user_id. A foreign or missing ID is treated identically as not found.
- Tests: cross-user voids_event_id insert fails on the composite FK (IntegrityError); resolve_owned of another user's event returns not found; repository methods cannot be called without user_id (type-checked by mypy and asserted at runtime).

F. Job queue (in-house, ADR-006) in app/jobs/
- enqueue(session, *, kind, payload: BaseModel, user_id, unique_key=None, run_after=None, correlation_id=None): inserts in the caller's transaction. With a unique_key matching a queued/running job, it is a no-op that returns the existing job id (ON CONFLICT DO NOTHING, then select).
- Handler registry: kind → (Pydantic payload model, handler). An unknown kind or invalid payload fails permanently with error_code unknown_job_kind or invalid_payload.
- Claim in its own short transaction: UPDATE jobs SET status='running', locked_by, locked_at=now(), attempts=attempts+1 WHERE id = (SELECT id FROM jobs WHERE status='queued' AND run_after <= now() ORDER BY run_after, id FOR UPDATE SKIP LOCKED LIMIT 1) RETURNING ...
- Process in a new transaction: the handler's work and the job's status='succeeded' commit together. On exception: roll back, then in a separate transaction either re-queue with exponential backoff plus jitter (capped) or mark failed when attempts reach max_attempts. Record last_error_code as the exception type name only, never the message.
- Visibility timeout: jobs stuck in running longer than a configurable timeout are re-queued by the worker loop (crash recovery).
- JobContext gives handlers user_id, job_id and correlation_id. Handlers must load entities only through user-scoped repositories with ctx.user_id. Test: a handler given another user's event ID in its payload gets not found.
- Worker loop (app/worker.py): replace the idle loop with claim → process; sleep the poll interval only when no job is found; on SIGTERM, finish the current job, then exit. Keep the existing log events and add job_started, job_succeeded, job_retry_scheduled, job_failed using only allowlisted fields (job_id, job_kind, attempt, error_code, duration_ms, user_id).
- Tests: two concurrent claimers (two sessions/threads) never claim the same job; retry with backoff updates run_after and attempts; max_attempts leads to failed; unique_key dedupes; enqueue rolls back with its transaction; stale running jobs are recovered.
- No scheduler, ticks or cron in Task 2.

G. Settings (app/config.py)
- DATABASE_URL: existing, now the app role URL.
- MIGRATION_DATABASE_URL (SecretStr): only alembic and bootstrap read it; the API and worker must not require it.
- APP_DB_PASSWORD: only bootstrap reads it.
- JOB_VISIBILITY_TIMEOUT_SECONDS, JOB_BACKOFF_BASE_SECONDS, JOB_BACKOFF_MAX_SECONDS, with sensible defaults.
- Update .env.example with placeholder values only, and update the README configuration table.

H. Alembic
- backend/alembic.ini plus backend/alembic/ (env.py, versions/). env.py reads MIGRATION_DATABASE_URL from the environment, never from alembic.ini. target_metadata is the shared MetaData.
- One reviewed migration for the three tables, grants, constraints and indexes. Autogenerate is allowed as a starting point, but read and clean the file; it must be human-reviewable.
- Downgrade must work (drop in dependency order).

I. Compose and Docker
- Add a one-shot migrate service (same image) whose command is inline (no .sh files):
  sh -c "python -m app.db.bootstrap && alembic upgrade head"
  It uses MIGRATION_DATABASE_URL built from POSTGRES_USER/POSTGRES_PASSWORD, plus APP_DB_PASSWORD.
- api and worker depend on migrate with condition: service_completed_successfully, and their DATABASE_URL uses career_os_app and APP_DB_PASSWORD.
- The Dockerfile copies alembic.ini and alembic/.
- The existing postgres volume can stay. Bootstrap is idempotent, so no down -v is needed. Ask before using -v.
- Add APP_DB_PASSWORD to my local .env with a random local-only value, without printing it.

J. Line endings
- Do not add .gitattributes. Do not create .sh files. If a shell script ever becomes genuinely necessary, stop and tell me; the fix would be a narrow `*.sh text eol=lf` rule, added with my approval and reported.

K. Tests and CI
- DB tests run against real Postgres, marked @pytest.mark.db. A session fixture uses an admin URL from TEST_ADMIN_DATABASE_URL to create a fresh database career_os_test_<random>, runs bootstrap and alembic upgrade head, gives tests app-role sessions (plus an owner session only where a test needs it), keeps tests independent, and drops the database at the end.
- Locally: docker compose -f infra/docker-compose.yml --env-file .env up -d postgres, then run pytest with TEST_ADMIN_DATABASE_URL pointing at localhost:5432 using the owner credentials from .env. Never print passwords.
- Non-DB unit tests must still run without Postgres.
- CI backend job: add a postgres:16 service container with a health check; set TEST_ADMIN_DATABASE_URL and APP_DB_PASSWORD (throwaway values defined in the workflow, never real secrets); run ruff, mypy and pytest including DB tests; then a migrations job step: alembic upgrade head on an empty DB → alembic check (drift must be empty) → alembic downgrade base → alembic upgrade head.
- Frontend and secrets jobs stay as they are.

L. Documentation
- docs/architecture/database.md: roles and grants, conventions, composite-FK pattern, INV-18 re-resolution, the job lifecycle (enqueue → claim → process → succeed/retry/fail, visibility timeout), and how to run migrations and DB tests locally. Concise.
- Update README (configuration table, how to run migrations and DB tests).

ACCEPTANCE CHECKS YOU MUST RUN
1. Local stack: docker compose -f infra/docker-compose.yml --env-file .env up --build -d → migrate exits 0; api and worker start; /healthz is 200; worker logs worker_started with no errors.
2. As career_os_app (via psql in the postgres container): \dp domain_events shows only SELECT and INSERT for career_os_app; an UPDATE attempt is denied.
3. Backend: uv run ruff check ., uv run ruff format --check ., uv run mypy, uv run pytest (DB tests included, with Postgres up).
4. Migrations: upgrade head on an empty DB, alembic check clean, downgrade base, upgrade head.
5. Frontend: npm run lint, typecheck, test, build (should be unchanged).
6. Push the branch and confirm GitHub Actions is green for backend (including DB tests and migration checks), frontend and secrets.

ESCALATION
If you find a spec contradiction, a required architecture change, a required scope change, a security issue affecting the frozen design, a schema requirement outside the three approved tables, or a missing prerequisite that changes architecture: STOP that part and report in this format:
PROBLEM / EVIDENCE / WHY THE CURRENT SPEC CANNOT BE FOLLOWED / SMALLEST OPTIONS / RECOMMENDATION / WHAT IS BLOCKED
Continue only with work that does not depend on the outcome. Do not silently redesign.

GIT AND FINISH
- Commit in logical steps on branch task-02-database-foundation, with clear messages.
- Push the branch (ask me first). Open a pull request to main: gh may need gh auth login, which I will run myself if needed; otherwise give me the GitHub compare URL. Do NOT merge; I merge after acceptance.
- Write the checkpoint report to docs/checkpoints/task-02.md, commit and push it on the branch, in this format:
  What was implemented (mapped to each acceptance criterion) / Evidence / Changes outside the expected file set (file, change, reason) or none / Important things I learned (4 to 8 bullets, specific) / Checks run and results (table) / Deviations from the frozen spec or none / Unresolved issues / Git state (branch, commits, PR URL, CI status) / Recommendation: approve or not, with reason
- Then STOP. Do not start Task 3.

Begin: confirm the branch, save this brief to docs/briefs/task-02.md and commit it, then start implementation.
