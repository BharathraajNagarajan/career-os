import { ApiRequestError } from "../api/client";

const REVIEW_ERRORS: Record<string, string> = {
  conflict: "This item changed since you opened it. The list has been refreshed.",
  invalid_transition: "This item has already been decided. The list has been refreshed.",
  no_handler: "This kind of proposal cannot be confirmed yet. You can reject it.",
  invalid_payload: "That edit is not valid for this kind of proposal.",
  not_found: "This item no longer exists. The list has been refreshed.",
  confirmation_required: "Confirm the change of class before saving.",
  gap_marked:
    "A skill on this item is marked as a gap. Clear the gap first, or make this Learning evidence.",
  target_missing: "The resume this came from no longer exists.",
};

export const REFRESH_CODES = new Set(["conflict", "invalid_transition", "not_found"]);

export function reviewErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    return REVIEW_ERRORS[error.code] ?? "Something went wrong. Please try again.";
  }
  return "Something went wrong. Please try again.";
}

export function shouldRefresh(error: unknown): boolean {
  return error instanceof ApiRequestError && REFRESH_CODES.has(error.code);
}

export function batchFailureMessage(code: string | null): string {
  if (code === "conflict") {
    return "Changed since you opened it.";
  }
  if (code === "invalid_transition") {
    return "Already decided.";
  }
  if (code === "not_found") {
    return "No longer exists.";
  }
  return (code !== null ? REVIEW_ERRORS[code] : undefined) ?? "Could not be confirmed.";
}
