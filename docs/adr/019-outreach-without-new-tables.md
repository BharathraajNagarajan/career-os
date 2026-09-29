# ADR-019: Outreach without new tables

- Status: Proposed
- Date: 2026-09-29
- Source: docs/spec/phase-0-spec.md

## Context

Outreach recommendations and drafts need persistence without new entities.

## Decision

Recommendations are LLM run outputs; drafts live on `outreach` RecruitingActions; sending is always manual.

## Alternatives considered

Separate recommendation and draft tables.

## Consequences

Draft history is recoverable from LLM runs.
