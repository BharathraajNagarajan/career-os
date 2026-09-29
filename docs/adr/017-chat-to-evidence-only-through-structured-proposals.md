# ADR-017: Chat-to-evidence only through structured proposals

- Status: Proposed
- Date: 2026-09-29
- Source: docs/spec/phase-0-spec.md

## Context

Clarifications in chat should become durable knowledge without evidence inflation.

## Decision

The model produces a skill-evidence proposal with the user's verbatim words; class and engagement type are unspecified unless stated; the user confirms, edits or rejects it as a ReviewItem.

## Alternatives considered

Letting chat update evidence directly; ignoring chat answers.

## Consequences

Durable learning from chat with provenance.
