import type { Claim, SkillDetail, SkillSummary } from "../api/evidence";

export function skillSummary(overrides: Partial<SkillSummary> = {}): SkillSummary {
  return {
    id: "skill-1",
    canonical_name: "Widgets",
    aliases: [],
    confirmation_status: "confirmed",
    user_marked_gap: false,
    headline: { category: "not_recorded", engagement_type: null },
    categories: ["not_recorded"],
    badges: [],
    latest_end_date: null,
    is_current: false,
    exposure: [],
    merged_into_skill_id: null,
    state_version: 1,
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

export function claim(overrides: Partial<Claim> = {}): Claim {
  return {
    id: "claim-1",
    statement: "Built sample widgets",
    evidence_class: "project",
    engagement_type: null,
    confirmation_status: "confirmed",
    start_date: null,
    end_date: null,
    organization_label: null,
    origin: "user",
    skills: [{ id: "skill-1", canonical_name: "Widgets" }],
    sources: [
      {
        id: "source-1",
        source_type: "user_assertion",
        resume_id: null,
        resume_label: null,
        artifact_id: null,
        url: null,
        assertion_text: "I built them",
        locator: null,
        created_at: "2026-01-01T00:00:00Z",
      },
    ],
    state_version: 1,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

export function skillDetail(overrides: Partial<SkillDetail> = {}): SkillDetail {
  return {
    ...skillSummary(),
    gap_note: null,
    user_note: "",
    origin: "user",
    claims: [],
    created_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}
