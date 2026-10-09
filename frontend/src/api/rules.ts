import { apiFetch } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type StrategyRule = Schemas["RuleResponse"];
export type RuleScope = Schemas["RuleScope"];
export type RuleType = Schemas["RuleType"];
export type RuleCondition = Schemas["RuleCondition"];

export const RULES_KEY = ["strategy-rules"] as const;

async function readJson<T>(response: Response): Promise<T> {
  return (await response.json()) as T;
}

export async function fetchRules(signal?: AbortSignal): Promise<StrategyRule[]> {
  return readJson(await apiFetch("/api/v1/strategy-rules", { signal: signal ?? null }));
}

export interface RuleCreate {
  scope: RuleScope;
  company_id: string | null;
  lane_id: string | null;
  statement: string;
  rule_type: RuleType;
  condition: RuleCondition | null;
  active: boolean;
}

export async function createRule(body: RuleCreate): Promise<StrategyRule> {
  return readJson(await apiFetch("/api/v1/strategy-rules", { method: "POST", json: body }));
}

export async function patchRule(
  id: string,
  body: Partial<Pick<RuleCreate, "statement" | "rule_type" | "condition" | "active">>,
): Promise<StrategyRule> {
  return readJson(await apiFetch(`/api/v1/strategy-rules/${id}`, { method: "PATCH", json: body }));
}

export async function deleteRule(id: string): Promise<void> {
  await apiFetch(`/api/v1/strategy-rules/${id}`, { method: "DELETE" });
}
