# ADR-016: Internship as an engagement type

- Status: Accepted (O-10, revision 3)
- Date: 2026-09-29
- Source: docs/spec/phase-0-spec.md

## Context

Internship evidence must stay distinguishable from full-time employment.

## Decision

Internship is `professional` evidence with `engagement_type = internship`. It is always named as internship and never counts toward years-of-experience requirements; `unspecified` is treated the same way until the user sets it.

## Alternatives considered

A sixth evidence class.

## Consequences

One class for employment; checks must never read class alone.
