import { apiFetch } from "./client";
import type { components } from "./schema";

export type ReviewItem = components["schemas"]["ReviewItemResponse"];

export const REVIEW_ITEMS_KEY = ["review-items", "pending"] as const;

export async function fetchPendingReviewItems(signal?: AbortSignal): Promise<ReviewItem[]> {
  const response = await apiFetch("/api/v1/review-items?status=pending", {
    signal: signal ?? null,
  });
  return (await response.json()) as ReviewItem[];
}

async function decide(item: ReviewItem, action: string, body: object): Promise<ReviewItem> {
  const response = await apiFetch(`/api/v1/review-items/${item.id}/${action}`, {
    method: "POST",
    json: { expected_state_version: item.state_version, ...body },
  });
  return (await response.json()) as ReviewItem;
}

export function confirmReviewItem(item: ReviewItem): Promise<ReviewItem> {
  return decide(item, "confirm", {});
}

export function editConfirmReviewItem(
  item: ReviewItem,
  payload: Record<string, unknown>,
): Promise<ReviewItem> {
  return decide(item, "edit-confirm", { payload });
}

export function rejectReviewItem(item: ReviewItem, note: string): Promise<ReviewItem> {
  return decide(item, "reject", note.trim() === "" ? {} : { note: note.trim() });
}
