# ADR-007: Model gateway with single vendor adapter and daily cost cap

- Status: Accepted (baseline approval, O-5)
- Date: 2026-09-29
- Source: docs/spec/phase-0-spec.md

## Context

Domain code must not depend on one LLM vendor, and model cost must be bounded per user.

## Decision

An internal `ModelGateway` interface for structured output and streaming, one vendor adapter (Anthropic) and a deterministic fake. Model tiers and per-model prices are configuration. Every call reserves worst-case cost against `LLM_DAILY_COST_CAP_USD` (default 1.00 per user per UTC day), settles actual cost after, and is refused with `llm_budget_exhausted` if it would not fit. Enforced only in the gateway. Configuration key shipped in Task 1; enforcement in Task 5.

## Alternatives considered

LangChain or LlamaIndex; a multi-provider router; no cap.

## Consequences

Provider independence at low cost; no silent overage; the cap value is revised from measured usage.
