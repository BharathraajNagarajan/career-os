import { apiFetch } from "./client";
import type { components } from "./schema";

export type Company = components["schemas"]["CompanyResponse"];
export type CompanyPatch = components["schemas"]["CompanyPatch"];

export const COMPANIES_KEY = ["companies"] as const;

export async function fetchCompanies(signal?: AbortSignal): Promise<Company[]> {
  const response = await apiFetch("/api/v1/companies", { signal: signal ?? null });
  return (await response.json()) as Company[];
}

export async function patchCompany(id: string, patch: CompanyPatch): Promise<Company> {
  const response = await apiFetch(`/api/v1/companies/${id}`, { method: "PATCH", json: patch });
  return (await response.json()) as Company;
}
