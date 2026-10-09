import { ApiRequestError } from "../api/client";

const GENERIC = "Something went wrong. Please try again.";

export const INVALID_STATE_MESSAGE =
  "That is no longer possible from the current state. The latest state is shown.";

const ERRORS: Record<string, string> = {
  conflict: "This changed since you opened it. Refresh to see the latest version, then try again.",
  invalid_transition: INVALID_STATE_MESSAGE,
  not_found: "This item no longer exists.",
  contact_email_taken: "Another contact already has one of those email addresses.",
  contact_already_merged: "That contact was already merged into another one.",
  cannot_merge_into_self: "Choose a different contact to merge in.",
  snooze_not_in_future: "Choose a snooze time in the future.",
  due_at_required: "This kind of action needs a date and time.",
  occurred_at_in_future: "That date and time is too far in the future.",
  application_required: "Choose an application to record an application event.",
  application_opportunity_mismatch: "That application belongs to a different opportunity.",
  event_type_not_allowed: "That event type cannot be recorded here.",
  kind_not_creatable: "That kind of action cannot be created here.",
  terminal_before_reopen:
    "A closing event cannot be dated before the reopen. Date it after the reopen.",
};

export function relationshipErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    return ERRORS[error.code] ?? (error.status === 422 ? "Check the values you entered." : GENERIC);
  }
  return GENERIC;
}

export function relationshipNeedsRefresh(error: unknown): boolean {
  return (
    error instanceof ApiRequestError &&
    (error.code === "conflict" ||
      error.code === "invalid_transition" ||
      error.code === "contact_already_merged")
  );
}

export function humanizeWord(value: string): string {
  const words = value.toLowerCase().replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

export function splitAddresses(value: string): string[] {
  return value
    .split(/[\s,;]+/)
    .map((part) => part.trim())
    .filter((part) => part !== "");
}
