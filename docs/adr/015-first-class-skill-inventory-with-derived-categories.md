# ADR-015: First-class Skill Inventory with derived categories

- Status: Proposed
- Date: 2026-09-29
- Source: docs/spec/phase-0-spec.md

## Context

Skills must be known independently of what current resumes say.

## Decision

A per-user `skills` table linked to claims through `claim_skills`. Skill category is derived on read from linked evidence; Not recorded is never treated as Gap.

## Alternatives considered

Skills as free-text tags on claims; a global skill taxonomy.

## Consequences

Evaluations stop inventing gaps; users maintain their own aliases.
