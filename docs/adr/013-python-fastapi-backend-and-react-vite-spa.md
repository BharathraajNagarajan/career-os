# ADR-013: Python/FastAPI backend and React/Vite SPA

- Status: Accepted (baseline approval, O-1)
- Date: 2026-09-29
- Source: docs/spec/phase-0-spec.md

## Context

The stack must be fast to build with, strong for AI and document parsing, and understandable.

## Decision

Python 3.12, FastAPI, SQLAlchemy 2, Alembic, Pydantic v2 with uv; React, TypeScript, Vite, TanStack Query, React Router; OpenAPI as the API contract.

## Alternatives considered

TypeScript full stack (Next.js); Django; Java/Spring.

## Consequences

Two languages across tiers, bridged by a generated OpenAPI client.
