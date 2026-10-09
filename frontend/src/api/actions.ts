import { apiFetch } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type RecruitingAction = Schemas["ActionResponse"];
export type RecruitingActionKind = Schemas["RecruitingActionKind"];
export type RecruitingActionStatus = Schemas["RecruitingActionStatus"];
export type RecruitingActionCommand = Schemas["RecruitingActionCommand"];

export const ACTIONS_KEY = ["actions"] as const;

export function actionsKey(filter: string) {
  return ["actions", filter] as const;
}

async function readJson<T>(response: Response): Promise<T> {
  return (await response.json()) as T;
}

export interface ActionFilter {
  statuses: RecruitingActionStatus[];
  opportunityId?: string;
  contactId?: string;
}

export async function fetchActions(
  filter: ActionFilter,
  signal?: AbortSignal,
): Promise<RecruitingAction[]> {
  const query = new URLSearchParams();
  for (const status of filter.statuses) {
    query.append("status", status);
  }
  if (filter.opportunityId !== undefined) {
    query.set("opportunity_id", filter.opportunityId);
  }
  if (filter.contactId !== undefined) {
    query.set("contact_id", filter.contactId);
  }
  return readJson(await apiFetch(`/api/v1/actions?${query.toString()}`, { signal: signal ?? null }));
}

export interface ActionCreate {
  kind: RecruitingActionKind;
  title: string;
  due_at: string | null;
  opportunity_id?: string;
  contact_id?: string;
}

export async function createAction(body: ActionCreate): Promise<RecruitingAction> {
  return readJson(await apiFetch("/api/v1/actions", { method: "POST", json: body }));
}

export async function snoozeAction(
  action: RecruitingAction,
  until: string,
): Promise<RecruitingAction> {
  return readJson(
    await apiFetch(`/api/v1/actions/${action.id}/snooze`, {
      method: "POST",
      json: { expected_state_version: action.state_version, until },
    }),
  );
}

export async function finishAction(
  action: RecruitingAction,
  command: "complete" | "dismiss",
): Promise<RecruitingAction> {
  return readJson(
    await apiFetch(`/api/v1/actions/${action.id}/${command}`, {
      method: "POST",
      json: { expected_state_version: action.state_version },
    }),
  );
}
