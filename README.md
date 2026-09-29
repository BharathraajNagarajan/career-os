# Career OS

A personal career operating system: it keeps structured, evidence-backed state about a job search so that past context informs future decisions without sending a user's whole history to a model.

Created by Bharathraaj Nagarajan

## Status

Phase 1A, Task 1 (repository scaffold and CI). The frozen specification is [docs/spec/phase-0-spec.md](docs/spec/phase-0-spec.md); decisions are recorded in [docs/adr](docs/adr/README.md).

## Architecture in one paragraph

A modular monolith: one Python codebase running an API process (FastAPI) and a worker process, a React SPA, PostgreSQL as the system of record (including the job queue), and object storage for immutable artifacts. Gmail and the LLM sit behind adapters. See section 2 of the specification.

## Repository layout

```
backend/    Python API and worker (FastAPI, uv, pytest, ruff, mypy)
frontend/   React SPA (Vite, TypeScript, TanStack Query, React Router, Vitest, ESLint)
infra/      Dockerfile and docker-compose.yml for local development
docs/       Frozen specification, ADRs, threat model
```

## Prerequisites

- Docker with Compose v2, for the one-command local stack
- For running without Docker: Python 3.12 with [uv](https://docs.astral.sh/uv/), Node.js 22, and PostgreSQL 16
- [gitleaks](https://github.com/gitleaks/gitleaks) 8.30+ for local secret scanning, optionally through [pre-commit](https://pre-commit.com/)

## Run everything with Docker

```bash
cp .env.example .env
# edit .env and set POSTGRES_PASSWORD to any local value
make up
```

This starts Postgres, the API on http://localhost:8000, the worker, and the frontend on http://localhost:5173. All ports bind to 127.0.0.1 only. The API reloads on backend changes and the frontend uses Vite hot reload.

- API health: http://localhost:8000/healthz
- API docs (non-production only): http://localhost:8000/docs

Stop with `make down`.

## Run without Docker

```bash
cd backend
uv sync
export DATABASE_URL=postgresql://career_os:yourpassword@localhost:5432/career_os
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
| `DATABASE_URL` | required | PostgreSQL connection string; never logged |
| `ENVIRONMENT` | `local` | `local`, `test` or `production`; production disables API docs |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `LOG_JSON` | `true` | JSON logs; `false` for human-readable console output |
| `CORS_ALLOWED_ORIGINS` | `[]` | JSON list of allowed browser origins |
| `WORKER_POLL_INTERVAL_SECONDS` | `5` | Worker loop interval |
| `LLM_DAILY_COST_CAP_USD` | `1.00` | Per-user daily model cost cap (spec 13.1); enforced from Task 5 |

## Logging

Logs are structured JSON with an allowlist of field names ([backend/app/core/logging.py](backend/app/core/logging.py)). Fields not on the list are dropped and counted, and every value, message and exception text passes through redaction for email addresses, bearer tokens, JWTs, Google tokens, connection strings and long secret-like strings. Request logs record the route template, never the raw path. Career and email content must never be logged.

## Checks

```bash
make check           # everything below
make check-backend   # ruff check, ruff format --check, mypy (strict), pytest
make check-frontend  # eslint, tsc, vitest, vite build
make check-secrets   # gitleaks over the full git history
```

CI runs the same three jobs on every push and pull request ([.github/workflows/ci.yml](.github/workflows/ci.yml)). To scan before each commit, run `pre-commit install`.

## Working rules

- The specification is frozen. Implementation follows it; a genuine contradiction, missing prerequisite, security issue or impossible requirement stops the affected work and is raised with the smallest proposed correction and an ADR.
- No creator career data in code, prompts, schemas, seeds, fixtures or defaults. The only static creator-specific string is the attribution above.
- No secrets in the repository.
