import type { RecruitingAction } from "../api/actions";
import type { ContactDetail, ContactSummary } from "../api/contacts";
import type { StrategyRule } from "../api/rules";

const STAMP = "2026-01-01T00:00:00Z";

export function contactSummary(overrides: Partial<ContactSummary> = {}): ContactSummary {
  return {
    id: "contact-1",
    full_name: "Alex Example",
    emails: [{ address: "alex@example.test", source: "manual", added_at: STAMP }],
    headline: "Recruiter",
    source: "manual",
    created_at: STAMP,
    updated_at: "2026-01-02T00:00:00.123456Z",
    ...overrides,
  };
}

export function contactDetail(overrides: Partial<ContactDetail> = {}): ContactDetail {
  return {
    ...contactSummary(),
    linkedin_url: null,
    notes: "",
    companies: [],
    opportunities: [],
    interactions: [],
    actions: [],
    ...overrides,
  };
}

export function recruitingAction(overrides: Partial<RecruitingAction> = {}): RecruitingAction {
  return {
    id: "action-1",
    kind: "follow_up",
    title: "Follow up with Alex Example",
    due_at: null,
    status: "open",
    snoozed_until: null,
    sequence_no: 1,
    opportunity_id: null,
    application_id: null,
    contact_id: null,
    interaction_id: null,
    origin: "user",
    state_version: 1,
    allowed_actions: ["snooze", "complete", "dismiss"],
    created_at: STAMP,
    updated_at: STAMP,
    ...overrides,
  };
}

export function strategyRule(overrides: Partial<StrategyRule> = {}): StrategyRule {
  return {
    id: "rule-1",
    scope: "global",
    company_id: null,
    lane_id: null,
    statement: "No more than two applications a week",
    rule_type: "constraint",
    condition: null,
    active: true,
    created_at: STAMP,
    updated_at: STAMP,
    ...overrides,
  };
}
