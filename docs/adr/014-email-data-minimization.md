# ADR-014: Email data minimization

- Status: Proposed
- Date: 2026-09-29
- Source: docs/spec/phase-0-spec.md

## Context

Email bodies are highly sensitive and mostly unnecessary after classification.

## Decision

Store message metadata, classification output and extracted facts. Raw bodies are not persisted unless the user confirms an item that needs a sanitized excerpt.

## Alternatives considered

Store full bodies for reprocessing.

## Consequences

Less sensitive data at rest; reprocessing re-fetches from Gmail.
