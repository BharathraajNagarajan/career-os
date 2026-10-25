import { ApiRequestError } from "../api/client";
import type { Badge, Claim, EngagementType, EvidenceClass, SkillSummary } from "../api/evidence";

export const CLASS_OPTIONS: { value: EvidenceClass; label: string }[] = [
  { value: "professional", label: "Professional" },
  { value: "academic_research", label: "Academic / Research" },
  { value: "project", label: "Project" },
  { value: "learning", label: "Learning" },
];

export const ENGAGEMENT_OPTIONS: { value: EngagementType; label: string }[] = [
  { value: "full_time", label: "Full-time" },
  { value: "part_time", label: "Part-time" },
  { value: "contract", label: "Contract" },
  { value: "internship", label: "Internship" },
  { value: "unspecified", label: "Type not specified" },
];

export function classLabel(value: EvidenceClass): string {
  return CLASS_OPTIONS.find((option) => option.value === value)?.label ?? value;
}

export function engagementLabel(value: EngagementType): string {
  return ENGAGEMENT_OPTIONS.find((option) => option.value === value)?.label ?? value;
}

export function classificationLabel(
  evidenceClass: EvidenceClass,
  engagementType: EngagementType | null,
): string {
  if (evidenceClass === "professional" && engagementType !== null) {
    return `Professional (${engagementLabel(engagementType)})`;
  }
  return classLabel(evidenceClass);
}

export function badgeLabel(badge: Badge): string {
  const label = classificationLabel(badge.evidence_class, badge.engagement_type);
  return badge.confirmed ? label : `${label} (unverified)`;
}

export function headlineLabel(headline: SkillSummary["headline"]): string {
  switch (headline.category) {
    case "gap":
      return "Gap (marked by you)";
    case "not_recorded":
      return "Not recorded";
    case "unverified":
      return "Unverified evidence";
    default:
      return classificationLabel(headline.category, headline.engagement_type);
  }
}

export const CATEGORY_OPTIONS = [
  ...CLASS_OPTIONS,
  { value: "gap", label: "Gap" },
  { value: "not_recorded", label: "Not recorded" },
] as const;

const GENERIC = "Something went wrong. Please try again.";

const ERRORS: Record<string, string> = {
  conflict: "This changed since you opened it. Refresh to see the latest version, then try again.",
  not_found: "This item no longer exists.",
  skill_exists: "You already have a skill or alias with that name.",
  invalid_name: "Enter a name with at least one letter or number.",
  skill_merged: "That skill was merged into another one.",
  invalid_state: "That is no longer possible from the current state.",
  gap_refused_evidence_exists:
    "This skill has confirmed evidence, so it cannot be marked as a gap. Reject or downgrade that evidence first.",
  gap_marked:
    "This skill is marked as a gap. Clear the gap first, or add this as Learning evidence.",
  merge_same_skill: "Choose a different skill to merge in.",
  alias_limit_exceeded: "Merging would give the skill too many aliases.",
  confirmation_required: "Confirm the change to continue.",
  unchanged: "That is already the current classification.",
  engagement_type_required: "Choose the engagement type for professional evidence.",
  engagement_type_only_professional: "Only professional evidence has an engagement type.",
  invalid_source: "Add a valid source: your own words or an http(s) project link.",
  source_required: "Add at least one source for this evidence.",
  dates_out_of_order: "The end date cannot be before the start date.",
  claim_rejected: "That evidence was rejected, so it can no longer change.",
  target_missing: "The resume this came from no longer exists.",
  extraction_pending: "Evidence is already being extracted from this resume.",
  extraction_exists: "Evidence was already extracted from this resume.",
  resume_not_parsed: "This resume is still being read. Try again in a moment.",
  resume_unreadable: "No text could be read from this resume, so evidence cannot be extracted.",
  resume_archived: "Unarchive this resume before extracting evidence.",
  invalid_payload: "That edit is not valid for this kind of proposal.",
  invalid_transition: "This item has already been decided.",
};

export function evidenceErrorMessage(error: unknown): string {
  if (error instanceof ApiRequestError) {
    return ERRORS[error.code] ?? (error.status === 422 ? "Check the values you entered." : GENERIC);
  }
  return GENERIC;
}

export function evidenceNeedsRefresh(error: unknown): boolean {
  return error instanceof ApiRequestError && error.code === "conflict";
}

const EXTRACTION_FAILURES: Record<string, string> = {
  llm_budget_exhausted: "Today's model budget is used up. Try again after it resets.",
  llm_output_invalid: "The model's answer could not be used. Try again.",
  llm_provider_error: "The model service did not respond. Try again.",
  resume_unreadable: "No text could be read from this resume.",
  resume_text_missing: "No text could be read from this resume.",
};

export function extractionFailureMessage(code: string | null | undefined): string {
  return EXTRACTION_FAILURES[code ?? ""] ?? "Evidence extraction failed. You can try again.";
}

export function dateRange(dates: {
  start_date: string | null;
  end_date: string | null;
}): string | null {
  if (dates.start_date === null && dates.end_date === null) {
    return null;
  }
  return `${dates.start_date ?? "?"} to ${dates.end_date ?? "present"}`;
}

export function sourceLabel(source: Claim["sources"][number]): string {
  switch (source.source_type) {
    case "resume":
      return `From resume: ${source.resume_label ?? "a resume"}`;
    case "user_assertion":
      return `Your words: ${source.assertion_text ?? ""}`;
    case "project_url":
      return `Project link: ${source.url ?? ""}`;
    default:
      return "From a stored document";
  }
}
