import { apiFetch } from "./client";
import type { components } from "./schema";

export type Budget = components["schemas"]["BudgetResponse"];

export async function fetchBudget(signal?: AbortSignal): Promise<Budget> {
  const response = await apiFetch("/api/v1/llm/budget", { signal: signal ?? null });
  return (await response.json()) as Budget;
}
