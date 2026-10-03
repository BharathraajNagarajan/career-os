import { apiFetch } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type Opportunity = Schemas["OpportunitySummary"];
export type OpportunityDetail = Schemas["OpportunityDetail"];
export type OpportunityPatch = Schemas["OpportunityPatch"];
export type Qualification = Schemas["QualificationResponse"];
export type QualificationCreate = Schemas["QualificationCreate"];
export type QualificationPatch = Schemas["QualificationPatch"];
export type DuplicateMatch = Schemas["DuplicateMatch"];
export type Priority = Schemas["Priority"];
export type WorkplaceType = Schemas["WorkplaceType"];
export type LocationItem = Schemas["LocationItem"];

export const OPPORTUNITIES_KEY = ["opportunities"] as const;

export function opportunityKey(id: string) {
  return ["opportunity", id] as const;
}

export function duplicatesKey(id: string) {
  return ["opportunity", id, "duplicates"] as const;
}

async function readJson<T>(response: Response): Promise<T> {
  return (await response.json()) as T;
}

export async function fetchOpportunities(signal?: AbortSignal): Promise<Opportunity[]> {
  return readJson(await apiFetch("/api/v1/opportunities", { signal: signal ?? null }));
}

export async function fetchOpportunity(
  id: string,
  signal?: AbortSignal,
): Promise<OpportunityDetail> {
  return readJson(await apiFetch(`/api/v1/opportunities/${id}`, { signal: signal ?? null }));
}

export async function ingestOpportunity(
  jdText: string,
  sourceUrl: string | null,
): Promise<Opportunity> {
  return readJson(
    await apiFetch("/api/v1/opportunities/ingest", {
      method: "POST",
      json: { jd_text: jdText, source_url: sourceUrl },
    }),
  );
}

export async function patchOpportunity(
  id: string,
  patch: OpportunityPatch,
): Promise<OpportunityDetail> {
  return readJson(
    await apiFetch(`/api/v1/opportunities/${id}`, { method: "PATCH", json: patch }),
  );
}

export async function setOpportunityPriority(
  id: string,
  priority: Priority,
): Promise<OpportunityDetail> {
  return readJson(
    await apiFetch(`/api/v1/opportunities/${id}/priority`, {
      method: "PATCH",
      json: { priority },
    }),
  );
}

export async function retryExtraction(id: string): Promise<OpportunityDetail> {
  return readJson(await apiFetch(`/api/v1/opportunities/${id}/extract`, { method: "POST" }));
}

export async function fetchDuplicates(id: string, signal?: AbortSignal): Promise<DuplicateMatch[]> {
  return readJson(
    await apiFetch(`/api/v1/opportunities/${id}/duplicates`, { signal: signal ?? null }),
  );
}

export async function addQualification(
  opportunityId: string,
  body: QualificationCreate,
): Promise<Qualification> {
  return readJson(
    await apiFetch(`/api/v1/opportunities/${opportunityId}/qualifications`, {
      method: "POST",
      json: body,
    }),
  );
}

export async function patchQualification(
  id: string,
  patch: QualificationPatch,
): Promise<Qualification> {
  return readJson(
    await apiFetch(`/api/v1/qualifications/${id}`, { method: "PATCH", json: patch }),
  );
}

export async function deleteQualification(id: string): Promise<void> {
  await apiFetch(`/api/v1/qualifications/${id}`, { method: "DELETE" });
}

export type OpportunityAction = Schemas["OpportunityCommand"];

export async function decideOpportunity(
  detail: OpportunityDetail,
  action: "save" | "skip" | "close",
  reason: string | null,
): Promise<OpportunityDetail> {
  return readJson(
    await apiFetch(`/api/v1/opportunities/${detail.id}/${action}`, {
      method: "POST",
      json: { expected_state_version: detail.state_version, reason },
    }),
  );
}

export async function applyToOpportunity(
  detail: OpportunityDetail,
  body: Omit<Schemas["ApplyRequest"], "expected_state_version">,
): Promise<Schemas["ApplyResponse"]> {
  return readJson(
    await apiFetch(`/api/v1/opportunities/${detail.id}/apply`, {
      method: "POST",
      json: { expected_state_version: detail.state_version, ...body },
    }),
  );
}
