# ADR-001: Modular monolith with API and worker processes

- Status: Proposed
- Date: 2026-09-29
- Source: docs/spec/phase-0-spec.md

## Context

Career OS must stay understandable for one owner while supporting future modules and multiple users.

## Decision

One Python codebase with two entry points, `app.main:create_app` (API) and `app.worker` (worker), sharing domain services. Module boundaries are enforced by package layout and, later, import rules.

## Alternatives considered

Microservices; serverless functions; a single process running background threads.

## Consequences

Simple deploy and debugging. Splitting later requires disciplined module boundaries now.
