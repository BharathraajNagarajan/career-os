import { apiFetch } from "./client";
import type { components } from "./schema";

export type Resume = components["schemas"]["ResumeSummary"];
export type Lane = components["schemas"]["LaneResponse"];
export type LaneCreate = components["schemas"]["LaneCreate"];
export type LanePatch = components["schemas"]["LanePatch"];

export function resumeFileUrl(resumeId: string): string {
  return `/api/v1/resumes/${resumeId}/file`;
}

async function readJson<T>(response: Response): Promise<T> {
  return (await response.json()) as T;
}

export async function fetchResumes(signal?: AbortSignal): Promise<Resume[]> {
  return readJson(await apiFetch("/api/v1/resumes", { signal: signal ?? null }));
}

export async function uploadResume(file: File): Promise<Resume> {
  const form = new FormData();
  form.append("file", file);
  return readJson(await apiFetch("/api/v1/resumes", { method: "POST", form }));
}

export async function renameResume(resumeId: string, label: string): Promise<Resume> {
  return readJson(
    await apiFetch(`/api/v1/resumes/${resumeId}`, { method: "PATCH", json: { label } }),
  );
}

export async function assignResumeLane(resumeId: string, laneId: string | null): Promise<Resume> {
  return readJson(
    await apiFetch(`/api/v1/resumes/${resumeId}`, { method: "PATCH", json: { lane_id: laneId } }),
  );
}

export async function setResumeArchived(resumeId: string, archived: boolean): Promise<Resume> {
  const action = archived ? "archive" : "unarchive";
  return readJson(await apiFetch(`/api/v1/resumes/${resumeId}/${action}`, { method: "POST" }));
}

export async function fetchLanes(signal?: AbortSignal): Promise<Lane[]> {
  return readJson(await apiFetch("/api/v1/lanes", { signal: signal ?? null }));
}

export async function createLane(lane: LaneCreate): Promise<Lane> {
  return readJson(await apiFetch("/api/v1/lanes", { method: "POST", json: lane }));
}

export async function patchLane(laneId: string, patch: LanePatch): Promise<Lane> {
  return readJson(await apiFetch(`/api/v1/lanes/${laneId}`, { method: "PATCH", json: patch }));
}

export async function setLaneArchived(laneId: string, archived: boolean): Promise<Lane> {
  const action = archived ? "archive" : "unarchive";
  return readJson(await apiFetch(`/api/v1/lanes/${laneId}/${action}`, { method: "POST" }));
}
