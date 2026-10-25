import { apiFetch } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type SkillSummary = Schemas["SkillSummary"];
export type SkillDetail = Schemas["SkillDetail"];
export type Claim = Schemas["ClaimResponse"];
export type ClaimCreate = Schemas["ClaimCreate"];
export type SourceCreate = Schemas["SourceCreate"];
export type Badge = Schemas["BadgeResponse"];
export type EvidenceClass = Schemas["EvidenceClass"];
export type EngagementType = Schemas["EngagementType"];
export type SkillCategory = Schemas["SkillSummary"]["categories"][number];

export const SKILLS_KEY = ["skills"] as const;
export const CLAIMS_KEY = ["claims"] as const;

export function skillKey(skillId: string) {
  return ["skills", "detail", skillId] as const;
}

export function claimKey(claimId: string) {
  return ["claims", "detail", claimId] as const;
}

async function readJson<T>(response: Response): Promise<T> {
  return (await response.json()) as T;
}

export interface SkillFilters {
  q: string;
  category: SkillCategory | "";
  engagement: EngagementType | "";
}

export async function fetchSkills(
  filters: SkillFilters,
  signal?: AbortSignal,
): Promise<SkillSummary[]> {
  const query = new URLSearchParams();
  if (filters.q.trim() !== "") {
    query.set("q", filters.q.trim());
  }
  if (filters.category !== "") {
    query.set("category", filters.category);
  }
  if (filters.category === "professional" && filters.engagement !== "") {
    query.set("engagement", filters.engagement);
  }
  const suffix = query.size === 0 ? "" : `?${query.toString()}`;
  return readJson(await apiFetch(`/api/v1/skills${suffix}`, { signal: signal ?? null }));
}

export async function fetchSkill(skillId: string, signal?: AbortSignal): Promise<SkillDetail> {
  return readJson(await apiFetch(`/api/v1/skills/${skillId}`, { signal: signal ?? null }));
}

export async function createSkill(body: Schemas["SkillCreate"]): Promise<SkillDetail> {
  return readJson(await apiFetch("/api/v1/skills", { method: "POST", json: body }));
}

export async function patchSkill(
  skill: { id: string; state_version: number },
  changes: Omit<Schemas["SkillPatch"], "expected_state_version">,
): Promise<SkillDetail> {
  return readJson(
    await apiFetch(`/api/v1/skills/${skill.id}`, {
      method: "PATCH",
      json: { expected_state_version: skill.state_version, ...changes },
    }),
  );
}

export async function mergeSkills(
  survivor: { id: string; state_version: number },
  merged: { id: string; state_version: number },
): Promise<SkillDetail> {
  return readJson(
    await apiFetch(`/api/v1/skills/${survivor.id}/merge`, {
      method: "POST",
      json: {
        merged_id: merged.id,
        expected_state_version: survivor.state_version,
        expected_merged_state_version: merged.state_version,
      },
    }),
  );
}

export async function markGap(
  skill: { id: string; state_version: number },
  note: string,
): Promise<SkillDetail> {
  return readJson(
    await apiFetch(`/api/v1/skills/${skill.id}/mark-gap`, {
      method: "POST",
      json: {
        expected_state_version: skill.state_version,
        note: note.trim() === "" ? null : note.trim(),
      },
    }),
  );
}

export async function clearGap(skill: { id: string; state_version: number }): Promise<SkillDetail> {
  return readJson(
    await apiFetch(`/api/v1/skills/${skill.id}/clear-gap`, {
      method: "POST",
      json: { expected_state_version: skill.state_version },
    }),
  );
}

export interface ClaimFilters {
  status: "confirmed" | "rejected" | "";
  evidenceClass: EvidenceClass | "";
}

export async function fetchClaims(filters: ClaimFilters, signal?: AbortSignal): Promise<Claim[]> {
  const query = new URLSearchParams();
  if (filters.status !== "") {
    query.set("status", filters.status);
  }
  if (filters.evidenceClass !== "") {
    query.set("evidence_class", filters.evidenceClass);
  }
  const suffix = query.size === 0 ? "" : `?${query.toString()}`;
  return readJson(await apiFetch(`/api/v1/claims${suffix}`, { signal: signal ?? null }));
}

export async function fetchClaim(claimId: string, signal?: AbortSignal): Promise<Claim> {
  return readJson(await apiFetch(`/api/v1/claims/${claimId}`, { signal: signal ?? null }));
}

export async function createClaim(body: ClaimCreate): Promise<Claim> {
  return readJson(await apiFetch("/api/v1/claims", { method: "POST", json: body }));
}

export async function patchClaim(
  claim: { id: string; state_version: number },
  changes: Omit<Schemas["ClaimPatch"], "expected_state_version">,
): Promise<Claim> {
  return readJson(
    await apiFetch(`/api/v1/claims/${claim.id}`, {
      method: "PATCH",
      json: { expected_state_version: claim.state_version, ...changes },
    }),
  );
}

export async function changeClassification(
  claim: { id: string; state_version: number },
  evidenceClass: EvidenceClass,
  engagementType: EngagementType | null,
): Promise<Claim> {
  return readJson(
    await apiFetch(`/api/v1/claims/${claim.id}/classification`, {
      method: "POST",
      json: {
        expected_state_version: claim.state_version,
        evidence_class: evidenceClass,
        engagement_type: evidenceClass === "professional" ? engagementType : null,
        confirm_change: true,
      },
    }),
  );
}

export async function rejectClaim(claim: { id: string; state_version: number }): Promise<Claim> {
  return readJson(
    await apiFetch(`/api/v1/claims/${claim.id}/reject`, {
      method: "POST",
      json: { expected_state_version: claim.state_version },
    }),
  );
}

export async function linkSkill(claimId: string, skillId: string): Promise<Claim> {
  return readJson(
    await apiFetch(`/api/v1/claims/${claimId}/skills`, {
      method: "POST",
      json: { skill_id: skillId },
    }),
  );
}

export async function unlinkSkill(claimId: string, skillId: string): Promise<Claim> {
  return readJson(
    await apiFetch(`/api/v1/claims/${claimId}/skills/${skillId}`, { method: "DELETE" }),
  );
}

export async function addSource(claimId: string, source: SourceCreate): Promise<Claim> {
  return readJson(
    await apiFetch(`/api/v1/claims/${claimId}/sources`, { method: "POST", json: source }),
  );
}
