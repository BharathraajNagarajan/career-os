.PHONY: up down check check-backend check-frontend check-secrets

up:
	docker compose -f infra/docker-compose.yml --env-file .env up --build

down:
	docker compose -f infra/docker-compose.yml --env-file .env down

check: check-backend check-frontend check-secrets

check-backend:
	cd backend && uv sync --frozen && uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest

check-frontend:
	cd frontend && npm ci --no-audit --no-fund && npm run lint && npm run typecheck && npm run test && npm run build

check-secrets:
	gitleaks git --config .gitleaks.toml --redact .
