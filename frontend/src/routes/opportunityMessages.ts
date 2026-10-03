import { ApiRequestError } from "../api/client";

const GENERIC = "Something went wrong. Please try again.";

const INGEST_ERRORS: Record<string, string> = {
  duplicate_jd: "You have already added this exact job description.",
  jd_too_short: "That text is too short to be a job description.",
  jd_too_long: "That text is too long. Paste only the job description.",
};

export const CONFLICT_MESSAGE =
  "This posting changed since you opened it. The latest version is shown; apply your edit again.";

const EDIT_ERRORS: Record<string, string> = {
  conflict: CONFLICT_MESSAGE,
  duplicate_job_id: "Another posting at this company already has that job ID.",
  not_found: "This item no longer exists.",
};

const EXTRACTION_ERRORS: Record<string, string> = {
  llm_budget_exhausted:
    "Extraction did not run because today's AI budget is used up. It resets at midnight UTC; you can retry then.",
  llm_output_invalid:
    "The model's answer could not be validated, so nothing was filled in. You can retry.",
  llm_provider_error: "The model service had a problem, so nothing was filled in. You can retry.",
  jd_text_missing: "The stored job description could not be read.",
  stored_output_invalid:
    "A saved model answer could not be read, so nothing was filled in. You can retry.",
};

export function ingestErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 422 && !(error.code in INGEST_ERRORS)) {
      return "Check the job description and the source URL (http or https only).";
    }
    return INGEST_ERRORS[error.code] ?? GENERIC;
  }
  return GENERIC;
}

export function editErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.status === 422) {
      return "Check the values you entered and try again.";
    }
    return EDIT_ERRORS[error.code] ?? GENERIC;
  }
  return GENERIC;
}

export function isConflict(error: unknown): boolean {
  return error instanceof ApiRequestError && error.code === "conflict";
}

export function extractionMessage(status: string, code: string | null): string {
  if (status === "pending") {
    return "Extracting fields from the job description…";
  }
  if (status === "failed") {
    return (
      EXTRACTION_ERRORS[code ?? ""] ?? "Extraction failed, so nothing was filled in. You can retry."
    );
  }
  return "Extraction finished.";
}

export function companyErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    if (error.code === "company_name_taken") {
      return "You already have a company with that name.";
    }
    if (error.status === 422) {
      return "Check the name, domains and careers URL (http or https only).";
    }
  }
  return GENERIC;
}

export const INVALID_TRANSITION_MESSAGE =
  "That is no longer possible from the current state. The latest state is shown.";

const COMMAND_ERRORS: Record<string, string> = {
  conflict: "This changed since you opened it. Refresh to see the latest version, then try again.",
  invalid_transition: INVALID_TRANSITION_MESSAGE,
  not_found: "This item no longer exists.",
  occurred_at_in_future: "That date and time is too far in the future.",
  event_type_not_allowed: "That event type cannot be recorded here.",
  terminal_before_reopen:
    "A closing event cannot be dated before the reopen. Date it after the reopen.",
  cannot_void: "That entry cannot be voided.",
  already_voided: "That entry is already voided.",
  not_terminal: "Only a closed application can be reopened.",
  resume_archived: "That resume is archived. Choose an active one.",
  lane_archived: "That lane is archived. Choose an active one.",
};

export function commandErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    return (
      COMMAND_ERRORS[error.code] ??
      (error.status === 422 ? "Check the values you entered." : GENERIC)
    );
  }
  return GENERIC;
}

export function needsRefresh(error: unknown): boolean {
  return (
    error instanceof ApiRequestError &&
    (error.code === "conflict" ||
      error.code === "invalid_transition" ||
      error.code === "not_terminal" ||
      error.code === "already_voided" ||
      error.code === "cannot_void" ||
      error.code === "event_type_not_allowed")
  );
}

export function humanize(eventType: string): string {
  const words = eventType.toLowerCase().replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}
