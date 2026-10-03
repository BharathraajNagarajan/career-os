# Career OS

A personal career operating system: it keeps structured, evidence-backed state about a job search so that past context informs future decisions without sending a user's whole history to a model.

Created by Bharathraaj Nagarajan

## Status

Phase 1A, Task 6 (JD ingestion, extraction, companies, duplicates and priorities; builds on the model gateway of Task 5). The frozen specification is [docs/spec/phase-0-spec.md](docs/spec/phase-0-spec.md); decisions are recorded in [docs/adr](docs/adr/README.md).

## Architecture in one paragraph

A modular monolith: one Python codebase running an API process (FastAPI) and a worker process, a React SPA, PostgreSQL as the system of record (including the job queue), and object storage for immutable artifacts. Gmail and the LLM sit behind adapters. See section 2 of the specification.

## Repository layout

```
backend/    Python API and worker (FastAPI, uv, pytest, ruff, mypy)
frontend/   React SPA (Vite, TypeScript, TanStack Query, React Router, Vitest, ESLint)
infra/      Dockerfile and docker-compose.yml for local development
docs/       Frozen specification, ADRs, architecture notes, threat model
```

## Prerequisites

- Docker with Compose v2, for the one-command local stack
- For running without Docker: Python 3.12 with [uv](https://docs.astral.sh/uv/), Node.js 22, and PostgreSQL 16
- [gitleaks](https://github.com/gitleaks/gitleaks) 8.30+ for local secret scanning, optionally through [pre-commit](https://pre-commit.com/)

## Run everything with Docker

```bash
cp .env.example .env
# edit .env: set POSTGRES_PASSWORD and APP_DB_PASSWORD to two different URL-safe local values,
# SESSION_SECRET to 32+ random characters, and your Google OAuth client ID and secret (see docs/architecture/auth.md)
docker compose -f infra/docker-compose.yml --env-file .env up --build
```

(`make up` runs the same command where GNU Make is installed.)

This starts Postgres, runs the one-shot `migrate` service (creates the `career_os_app` role and applies Alembic migrations), then starts the API on http://localhost:8000, the worker, and the frontend on http://localhost:5173. The API and worker connect as `career_os_app`, never as the database owner. All ports bind to 127.0.0.1 only. The API reloads on backend changes and the frontend uses Vite hot reload.

- API health: http://localhost:8000/healthz
- API docs (non-production only): http://localhost:8000/docs

Stop with `docker compose -f infra/docker-compose.yml --env-file .env down` (or `make down`).

## Run without Docker

```bash
cd backend
uv sync
export MIGRATION_DATABASE_URL=postgresql://career_os:ownerpassword@127.0.0.1:5432/career_os
export APP_DB_PASSWORD=apppassword
uv run python -m app.db.bootstrap && uv run alembic upgrade head
export DATABASE_URL=postgresql://career_os_app:apppassword@127.0.0.1:5432/career_os
uv run uvicorn app.main:create_app --factory --reload --no-access-log
uv run python -m app.worker
```

```bash
cd frontend
npm ci
npm run dev
```

The Vite dev server proxies `/api` and `/healthz` to `VITE_API_PROXY_TARGET` (default `http://localhost:8000`).

## Configuration

Settings come only from environment variables; the application never reads a `.env` file itself (Docker Compose passes `.env` into the containers). See [.env.example](.env.example).

| Variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | required (API, worker) | PostgreSQL URL for the `career_os_app` role; never logged |
| `MIGRATION_DATABASE_URL` | required (migrations only) | Owner URL used only by `app.db.bootstrap` and Alembic; the API and worker never receive it |
| `APP_DB_PASSWORD` | required (bootstrap, Compose) | Password for `career_os_app`, at least 12 URL-safe characters |
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | required (Compose) | Database name and owner credentials for the Postgres container |
| `ENVIRONMENT` | `local` | `local`, `test` or `production`; production disables API docs |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `LOG_JSON` | `true` | JSON logs; `false` for human-readable console output |
| `CORS_ALLOWED_ORIGINS` | `[]` | JSON list of allowed browser origins |
| `WORKER_POLL_INTERVAL_SECONDS` | `5` | Worker sleep when no job is ready |
| `JOB_VISIBILITY_TIMEOUT_SECONDS` | `900` | A running job older than this is re-queued (crash recovery) |
| `JOB_BACKOFF_BASE_SECONDS` | `10` | First retry delay; doubles per attempt, with jitter |
| `JOB_BACKOFF_MAX_SECONDS` | `3600` | Retry delay cap |
| `SESSION_SECRET` | required (API) | At least 32 characters; keys the CSRF HMAC and the pre-auth cookie encryption; never logged |
| `SESSION_IDLE_TIMEOUT_HOURS` | `168` | A session unused for longer than this is rejected |
| `SESSION_ABSOLUTE_TIMEOUT_HOURS` | `720` | Maximum session lifetime; also the cookie `Max-Age` |
| `SESSION_COOKIE_SECURE` | `true` | `Secure` flag on cookies; browsers accept it on `http://localhost`, so keep `true` locally (set `false` only if a browser rejects the cookie) |
| `APP_BASE_URL` | `http://localhost:5173` | Public origin; the Google redirect URI is this plus `/api/v1/auth/google/callback` |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` | required for sign-in (API) | Google OAuth web client; the secret is never logged. Not passed to the worker |
| `TEST_ADMIN_DATABASE_URL` | unset | Owner URL for database tests; unset skips tests marked `db` |
| `REQUIRE_DB_TESTS` | unset | Set to `1` (CI does) to fail the test run instead of skipping database tests when `TEST_ADMIN_DATABASE_URL` is missing |
| `LLM_DAILY_COST_CAP_USD` | `1.00` | Per-user daily model cost cap (spec 13.1); enforced by the model gateway from `llm_runs` totals (UTC day) |
| `LLM_PROVIDER` | `fake` | `fake` or `anthropic`. Nothing calls a real API unless this is `anthropic` |
| `ANTHROPIC_API_KEY` | unset (API, worker only) | Required when `LLM_PROVIDER=anthropic`; startup fails otherwise. Never logged |
| `LLM_MODEL_FAST`, `LLM_MODEL_REASONING` | `fake-fast`, `fake-reasoning` | Model ids for the two tiers. Startup fails if either has no price |
| `LLM_MODEL_PRICES` | fake prices | JSON map of model id to `input_usd_per_mtok` and `output_usd_per_mtok`; assumptions until verified against your billing |
| `LLM_REQUEST_TIMEOUT_SECONDS` | `60` | Per provider call |
| `LLM_DEFAULT_MAX_OUTPUT_TOKENS` | `1024` | Default output ceiling for callers that do not pass one |
| `ARTIFACT_STORAGE_DIR` | `/srv/artifacts` | Directory of the filesystem artifact store (API and worker only; Compose mounts the `artifact-data` volume here). An S3-compatible adapter replaces it at deployment |
| `RESUME_MAX_BYTES` | `5242880` | Largest accepted resume upload (5 MiB); larger uploads get 413 |
| `RESUME_MAX_PAGES` | `10` | Largest accepted PDF page count; more pages fail parsing with `too_many_pages` |
| `PARSE_TIMEOUT_SECONDS` | `30` | Hard limit for the resume parsing child process; exceeding it fails parsing with `parse_timeout` |
| `EXTRACTED_TEXT_MAX_CHARS` | `200000` | Extracted resume text is truncated to this many characters |
| `JD_MIN_CHARS` | `200` | Shortest accepted pasted job description (after trimming); shorter gets 422 `jd_too_short` |
| `JD_MAX_CHARS` | `50000` | Longest accepted pasted job description (at most 200000); longer gets 422 `jd_too_long` |
| `JD_EXTRACTION_MAX_OUTPUT_TOKENS` | `6000` | Output ceiling for the one extraction call per pasted job description |

## Opportunities and job descriptions

Paste a job description on the Opportunities page (optionally with the source URL, which is stored and shown as text but never fetched). The text is kept as an immutable artifact, and the pasting itself authorizes one model call that extracts the company, title, team, job ID, location, workplace type and the requirement lines. Each requirement keeps the posting's exact wording (anything the model invented is dropped), and every extracted value stays editable; extraction only fills fields that are still empty and never retries by itself. Companies are matched by domain, name or alias, possible duplicates are listed on each posting, and priority is yours to set on postings and companies. With the default fake provider the extraction returns placeholder values, so no real call is made. See [docs/architecture/opportunities.md](docs/architecture/opportunities.md).

## Database, migrations and database tests

See [docs/architecture/database.md](docs/architecture/database.md) for roles and grants, conventions, tenancy rules and the job lifecycle.

```bash
docker compose -f infra/docker-compose.yml --env-file .env run --rm migrate   # bootstrap role + alembic upgrade head

docker compose -f infra/docker-compose.yml --env-file .env up -d postgres
cd backend
export TEST_ADMIN_DATABASE_URL=postgresql://<POSTGRES_USER>:<POSTGRES_PASSWORD>@127.0.0.1:5432/<POSTGRES_DB>
export APP_DB_PASSWORD=<value from .env>
uv run pytest
```

Database tests create and drop their own `career_os_test_<random>` database. Use `127.0.0.1` rather than `localhost` on Windows (see the architecture note).

## Authentication

Google OpenID Connect sign-in (authorization code flow with PKCE, state and nonce), hashed server-side sessions with idle and absolute expiry, CSRF double-submit tokens on mutations, session revocation and account deletion. Only `openid email profile` is requested at sign-in. See [docs/architecture/auth.md](docs/architecture/auth.md) for the flow, cookie flags, deletion path and Google Cloud setup. Every new route needs an entry in the isolation harness (`backend/tests/db/test_isolation.py`).

The API contract is [backend/openapi.json](backend/openapi.json); regenerate it with `cd backend && uv run python -m app.openapi_export openapi.json`, then the frontend types with `cd frontend && npm run generate:api`. CI fails if either is out of date.

## Profile, resumes and lanes

One profile per user (constraints, target roles, communication preferences), immutable resume uploads (PDF and DOCX, sniffed by content, size limited, deduplicated by SHA-256) with text and outline extraction in the worker and no model call, and resume lanes. Originals are stored under `ARTIFACT_STORAGE_DIR` and are never rewritten; the UI offers no way to edit a resume file. See [docs/architecture/artifacts.md](docs/architecture/artifacts.md).

## Model gateway and review items

All model work goes through one internal gateway: tiers and prices from configuration, versioned prompts, a recorded `llm_runs` row per call, one repair retry for invalid structured output, and a per-user daily cost cap that reserves the worst case before a call and settles the real cost after. The review framework holds proposals until the user confirms, edits or rejects them, and confirming runs the same command a manual action would. The first producer is JD extraction (below); resume extraction arrives in Task 9. See [docs/architecture/llm.md](docs/architecture/llm.md) and [docs/architecture/review.md](docs/architecture/review.md). The Anthropic placeholders in `.env.example` are commented out; copy them in only when you want a real call.

## Logging

Logs are structured JSON with an allowlist of field names ([backend/app/core/logging.py](backend/app/core/logging.py)). Fields not on the list are dropped and counted, and every value, message and exception text passes through redaction for email addresses, bearer tokens, JWTs, Google tokens, connection strings and long secret-like strings. Request logs record the route template, never the raw path. Career and email content must never be logged.

## Checks

Where GNU Make is installed:

```bash
make check           # everything below
make check-backend   # ruff check, ruff format --check, mypy (strict), pytest
make check-frontend  # eslint, tsc, vitest, vite build
make check-secrets   # gitleaks over the full git history
```

Without Make, run the commands from the [Makefile](Makefile) directly (`cd backend && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest`, and the `npm run` scripts in `frontend/`).

CI runs the same three jobs on every push and pull request, with a PostgreSQL 16 service for database tests and a migration check (upgrade, `alembic check`, downgrade, upgrade) ([.github/workflows/ci.yml](.github/workflows/ci.yml)). To scan before each commit, run `pre-commit install`.

## Working rules

- The specification is frozen. Implementation follows it; a genuine contradiction, missing prerequisite, security issue or impossible requirement stops the affected work and is raised with the smallest proposed correction and an ADR.
- No creator career data in code, prompts, schemas, seeds, fixtures or defaults. The only static creator-specific string is the attribution above.
- No secrets in the repository.
