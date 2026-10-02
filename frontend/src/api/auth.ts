import { apiFetch } from "./client";
import type { components } from "./schema";

export type Me = components["schemas"]["MeResponse"];
export type SessionSummary = components["schemas"]["SessionResponse"];

export const DELETE_CONFIRMATION = "DELETE MY ACCOUNT";

export async function fetchMe(signal?: AbortSignal): Promise<Me> {
  const response = await apiFetch("/api/v1/auth/me", {
    signal: signal ?? null,
    redirectOnUnauthorized: false,
  });
  return (await response.json()) as Me;
}

export async function fetchSessions(signal?: AbortSignal): Promise<SessionSummary[]> {
  const response = await apiFetch("/api/v1/auth/sessions", { signal: signal ?? null });
  return (await response.json()) as SessionSummary[];
}

export async function revokeSession(sessionId: string): Promise<void> {
  await apiFetch(`/api/v1/auth/sessions/${sessionId}`, { method: "DELETE" });
}

export async function signOut(): Promise<void> {
  await apiFetch("/api/v1/auth/logout", { method: "POST" });
}

export async function requestAccountDeletion(): Promise<void> {
  await apiFetch("/api/v1/account/deletion", {
    method: "POST",
    json: { confirm: DELETE_CONFIRMATION },
  });
}
