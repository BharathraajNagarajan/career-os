import { ApiRequestError } from "../api/client";

const REVIEW_ERRORS: Record<string, string> = {
  conflict: "This item changed since you opened it. The list has been refreshed.",
  invalid_transition: "This item has already been decided. The list has been refreshed.",
  no_handler: "This kind of proposal cannot be confirmed yet. You can reject it.",
  invalid_payload: "That edit is not valid for this kind of proposal.",
  not_found: "This item no longer exists. The list has been refreshed.",
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
