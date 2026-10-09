import { apiFetch } from "./client";
import type { components } from "./schema";

type Schemas = components["schemas"];

export type ContactSummary = Schemas["ContactSummary"];
export type ContactDetail = Schemas["ContactDetail"];
export type ContactCompanyRelation = Schemas["ContactCompanyRelation"];
export type ContactOpportunityRole = Schemas["ContactOpportunityRole"];
export type Interaction = Schemas["InteractionResponse"];
export type InteractionChannel = Schemas["InteractionChannel"];
export type InteractionDirection = Schemas["InteractionDirection"];
export type InteractionCreate = Schemas["InteractionCreate"];

export const CONTACTS_KEY = ["contacts"] as const;

export function contactKey(contactId: string) {
  return ["contacts", contactId] as const;
}

export function contactsForOpportunityKey(opportunityId: string) {
  return ["contacts", "opportunity", opportunityId] as const;
}

async function readJson<T>(response: Response): Promise<T> {
  return (await response.json()) as T;
}

export async function fetchContacts(
  params: { q?: string; opportunityId?: string },
  signal?: AbortSignal,
): Promise<ContactSummary[]> {
  const query = new URLSearchParams();
  if (params.q !== undefined && params.q.trim() !== "") {
    query.set("q", params.q.trim());
  }
  if (params.opportunityId !== undefined) {
    query.set("opportunity_id", params.opportunityId);
  }
  const suffix = query.size === 0 ? "" : `?${query.toString()}`;
  return readJson(await apiFetch(`/api/v1/contacts${suffix}`, { signal: signal ?? null }));
}

export async function fetchContact(contactId: string, signal?: AbortSignal): Promise<ContactDetail> {
  return readJson(await apiFetch(`/api/v1/contacts/${contactId}`, { signal: signal ?? null }));
}

export interface ContactFields {
  full_name: string;
  emails: string[];
  linkedin_url: string | null;
  headline: string | null;
  notes: string;
}

export async function createContact(fields: ContactFields): Promise<ContactDetail> {
  return readJson(await apiFetch("/api/v1/contacts", { method: "POST", json: fields }));
}

export async function patchContact(
  contact: ContactDetail,
  fields: ContactFields,
): Promise<ContactDetail> {
  return readJson(
    await apiFetch(`/api/v1/contacts/${contact.id}`, {
      method: "PATCH",
      json: { expected_updated_at: contact.updated_at, ...fields },
    }),
  );
}

export async function linkCompany(
  contactId: string,
  companyId: string,
  body: { relation: ContactCompanyRelation; title: string | null; is_current: boolean },
): Promise<ContactDetail> {
  return readJson(
    await apiFetch(`/api/v1/contacts/${contactId}/companies/${companyId}`, {
      method: "POST",
      json: body,
    }),
  );
}

export async function unlinkCompany(contactId: string, companyId: string): Promise<ContactDetail> {
  return readJson(
    await apiFetch(`/api/v1/contacts/${contactId}/companies/${companyId}`, { method: "DELETE" }),
  );
}

export async function linkOpportunity(
  contactId: string,
  opportunityId: string,
  role: ContactOpportunityRole,
): Promise<ContactDetail> {
  return readJson(
    await apiFetch(`/api/v1/contacts/${contactId}/opportunities/${opportunityId}`, {
      method: "POST",
      json: { role },
    }),
  );
}

export async function unlinkOpportunity(
  contactId: string,
  opportunityId: string,
  role: ContactOpportunityRole,
): Promise<ContactDetail> {
  return readJson(
    await apiFetch(`/api/v1/contacts/${contactId}/opportunities/${opportunityId}?role=${role}`, {
      method: "DELETE",
    }),
  );
}

export async function mergeContacts(
  survivor: ContactDetail,
  merged: ContactSummary,
): Promise<ContactDetail> {
  return readJson(
    await apiFetch(`/api/v1/contacts/${survivor.id}/merge`, {
      method: "POST",
      json: {
        merged_id: merged.id,
        expected_survivor_updated_at: survivor.updated_at,
        expected_merged_updated_at: merged.updated_at,
      },
    }),
  );
}

export async function createInteraction(body: InteractionCreate): Promise<Interaction> {
  return readJson(await apiFetch("/api/v1/interactions", { method: "POST", json: body }));
}
