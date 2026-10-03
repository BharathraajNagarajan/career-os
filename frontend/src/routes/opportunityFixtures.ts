import type { Company } from "../api/companies";
import type { Opportunity, OpportunityDetail, Qualification } from "../api/opportunities";

export function summary(overrides: Partial<Opportunity> = {}): Opportunity {
  return {
    id: "opp-1",
    company: { id: "company-1", name: "Example Corp", strategic_priority: "normal" },
    title: "Senior Widget Engineer",
    status: "new",
    priority: "normal",
    extraction_status: "succeeded",
    extraction_error_code: null,
    workplace_type: "hybrid",
    location_text: "Springfield, IL",
    source_url: null,
    content_updated_at: "2026-01-01T00:00:00Z",
    discovered_at: "2026-01-01T00:00:00Z",
    state_version: 2,
    ...overrides,
  };
}

export function qualification(overrides: Partial<Qualification> = {}): Qualification {
  return {
    id: "qual-1",
    opportunity_id: "opp-1",
    kind: "minimum",
    ordinal: 0,
    text_verbatim: "Proficiency in Python and SQL",
    category: "skill",
    skill_keys: ["python", "sql"],
    min_years: null,
    is_hard_constraint: false,
    origin: "extracted",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

export function detail(overrides: Partial<OpportunityDetail> = {}): OpportunityDetail {
  return {
    ...summary(),
    team: "Platform",
    external_job_id: "EX-1001",
    locations: { schema_version: 1, items: [{ city: "Springfield", region: "IL", country: "US" }] },
    jd_artifact_id: "artifact-1",
    jd_text: "Example Corp is hiring.\nProficiency in Python and SQL",
    llm_run_id: "run-1",
    qualifications: [qualification()],
    ...overrides,
  };
}

export function company(overrides: Partial<Company> = {}): Company {
  return {
    id: "company-1",
    name: "Example Corp",
    normalized_name: "example",
    aliases: ["Example Co"],
    domains: ["example.test"],
    careers_url: "https://example.test/careers",
    strategic_priority: "normal",
    notes: "A synthetic note",
    origin: "extracted",
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}
