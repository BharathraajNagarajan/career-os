# ADR-021: Staleness by basis comparison, explicit re-run

- Status: Accepted (O-12, revision 3)
- Date: 2026-09-29
- Source: docs/spec/phase-0-spec.md

## Context

Evaluations become outdated when inputs change, but hidden model work increases cost.

## Decision

Each Evaluation stores its basis (skills, unmatched JD skill keys, lanes, resumes). Staleness is a SQL comparison on read. Evaluations run only on explicit user action.

## Alternatives considered

Automatic re-evaluation; version counters.

## Consequences

No hidden model cost; users decide when to re-run.
