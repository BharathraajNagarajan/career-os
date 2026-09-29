# ADR-008: Evidence classes with deterministic use checks

- Status: Proposed
- Date: 2026-09-29
- Source: docs/spec/phase-0-spec.md

## Context

The model must not turn learning or internships into full-time professional experience.

## Decision

Claims have four evidence classes (professional, academic_research, project, learning) and, for professional claims, an engagement type (full_time, part_time, contract, internship, unspecified). Gap is a user-marked Skill state. The model can only propose class and engagement type. Outputs are validated against permitted uses, always reading class and engagement type together (INV-16).

## Alternatives considered

A single class per skill; internship as a sixth class.

## Consequences

Prevents evidence inflation; adds a confirmation step for extracted claims.
