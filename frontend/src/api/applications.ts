import { apiFetch } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type Application = Schemas["ApplicationResponse"];
export type ApplicationChannel = Schemas["ApplicationChannel"];
export type ApplicationStage = Schemas["ApplicationStage"];
export type ApplyResponse = Schemas["ApplyResponse"];
export type ApplyRequest = Schemas["ApplyRequest"];
export type TimelineEntry = Schemas["TimelineEntryResponse"];

export const APPLICATIONS_KEY = ["applications"] as const;

export function applicationsForOpportunityKey(opportunityId: string) {
  return ["applications", "opportunity", opportunityId] as const;
}

export function timelineKey(opportunityId: string) {
  return ["opportunity", opportunityId, "timeline"] as const;
}

async function readJson<T>(response: Response): Promise<T> {
  return (await response.json()) as T;
}

export async function fetchApplications(
  opportunityId?: string,
  signal?: AbortSignal,
): Promise<Application[]> {
  const query = opportunityId === undefined ? "" : `?opportunity_id=${opportunityId}`;
  return readJson(await apiFetch(`/api/v1/applications${query}`, { signal: signal ?? null }));
}

export async function fetchTimeline(
  opportunityId: string,
  signal?: AbortSignal,
): Promise<TimelineEntry[]> {
  return readJson(
    await apiFetch(`/api/v1/opportunities/${opportunityId}/timeline`, {
      signal: signal ?? null,
    }),
  );
}

export async function recordApplicationEvent(
  application: Application,
  body: { event_type: string; occurred_at: string; note: string | null },
): Promise<Application> {
  return readJson(
    await apiFetch(`/api/v1/applications/${application.id}/events`, {
      method: "POST",
      json: { expected_state_version: application.state_version, ...body },
    }),
  );
}

export async function voidApplicationEvent(
  application: Application,
  eventId: string,
  reason: string | null,
): Promise<Application> {
  return readJson(
    await apiFetch(`/api/v1/applications/${application.id}/events/${eventId}/void`, {
      method: "POST",
      json: { expected_state_version: application.state_version, reason },
    }),
  );
}

export async function reopenApplication(application: Application): Promise<Application> {
  return readJson(
    await apiFetch(`/api/v1/applications/${application.id}/reopen`, {
      method: "POST",
      json: { expected_state_version: application.state_version },
    }),
  );
}
