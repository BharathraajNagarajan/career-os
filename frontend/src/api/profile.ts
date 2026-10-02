import { apiFetch } from "./client";
import type { components } from "./schema";

export type Profile = components["schemas"]["ProfileResponse"];
export type ProfileUpdate = components["schemas"]["ProfileUpdate"];
export type WorkAuthorizationEntry = components["schemas"]["WorkAuthorizationEntry"];
export type TargetRole = components["schemas"]["TargetRole"];

export async function fetchProfile(signal?: AbortSignal): Promise<Profile> {
  const response = await apiFetch("/api/v1/profile", { signal: signal ?? null });
  return (await response.json()) as Profile;
}

export async function saveProfile(update: ProfileUpdate): Promise<Profile> {
  const response = await apiFetch("/api/v1/profile", { method: "PUT", json: update });
  return (await response.json()) as Profile;
}
