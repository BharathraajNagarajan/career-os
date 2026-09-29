# ADR-018: Home built on attention providers

- Status: Proposed
- Date: 2026-09-29
- Source: docs/spec/phase-0-spec.md

## Context

Home must be useful early and grow without a redesign.

## Decision

Modules publish typed attention items; Home ranks them deterministically and serves them from one aggregated endpoint.

## Alternatives considered

A bespoke dashboard per phase.

## Consequences

The early Home is the final Home; Gmail and future modules plug in.
