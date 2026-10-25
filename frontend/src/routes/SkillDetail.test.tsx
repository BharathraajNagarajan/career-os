import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { SkillDetail as SkillDetailData } from "../api/evidence";
import { jsonResponse, mockApi, renderPage } from "../test-utils";
import type { RecordedCall } from "../test-utils";
import { claim, skillDetail, skillSummary } from "./evidenceFixtures";
import { SkillDetail } from "./SkillDetail";

const ROUTE = { path: "/skills/:skillId", entry: "/skills/skill-1" };

function serve(
  initial: SkillDetailData,
  extra?: (call: RecordedCall, state: { skill: SkillDetailData }) => Response | undefined,
) {
  const state = { skill: initial };
  const calls = mockApi((call) => {
    const custom = extra?.(call, state);
    if (custom) {
      return custom;
    }
    if (call.method === "GET" && call.url === "/api/v1/skills/skill-1") {
      return jsonResponse(state.skill);
    }
    if (call.method === "GET" && call.url === "/api/v1/skills") {
      return jsonResponse([
        skillSummary(),
        skillSummary({ id: "skill-2", canonical_name: "Gadgets", state_version: 4 }),
      ]);
    }
    return undefined;
  });
  return { calls, state };
}

const WITH_CLAIM = skillDetail({
  headline: { category: "professional", engagement_type: "unspecified" },
  categories: ["professional"],
  badges: [
    { evidence_class: "professional", engagement_type: "unspecified", confirmed: true, claim_count: 1 },
  ],
  claims: [
    claim({
      evidence_class: "professional",
      engagement_type: "unspecified",
      organization_label: "Example Corp",
      sources: [
        {
          id: "s1",
          source_type: "resume",
          resume_id: "r1",
          resume_label: "Resume A",
          artifact_id: "a1",
          url: null,
          assertion_text: null,
          locator: null,
          created_at: "2026-01-01T00:00:00Z",
        },
      ],
    }),
  ],
  exposure: [{ resume_id: "r1", label: "Resume A", archived: false, stated: true, mentioned: false }],
});

function posts(calls: RecordedCall[]): RecordedCall[] {
  return calls.filter((call) => call.method !== "GET");
}

describe("SkillDetail", () => {
  it("shows claims with their sources, class, organization and which resumes expose the skill", async () => {
    serve(WITH_CLAIM);

    renderPage(<SkillDetail />, ROUTE);

    expect(await screen.findByRole("heading", { name: "Widgets" })).toBeInTheDocument();
    expect(screen.getByText(/Professional \(Type not specified\) · 1 item/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Built sample widgets" })).toHaveAttribute(
      "href",
      "/claims/claim-1",
    );
    expect(screen.getByText("From resume: Resume A")).toBeInTheDocument();
    expect(screen.getByText(/Example Corp/)).toBeInTheDocument();
    expect(screen.getByText(/text presence, not proof of proficiency/)).toBeInTheDocument();
    expect(screen.getByText(/Resume A · cited by your evidence/)).toBeInTheDocument();
  });

  it("marks a gap and shows the server's refusal when confirmed evidence exists", async () => {
    const { calls } = serve(skillDetail(), (call) =>
      call.method === "POST"
        ? jsonResponse({ error: { code: "gap_refused_evidence_exists" } }, 409)
        : undefined,
    );
    renderPage(<SkillDetail />, ROUTE);

    fireEvent.change(await screen.findByLabelText("Gap note (optional)"), {
      target: { value: " Never used " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Mark as a gap" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "cannot be marked as a gap. Reject or downgrade that evidence first.",
    );
    const [post] = posts(calls);
    expect(post?.url).toBe("/api/v1/skills/skill-1/mark-gap");
    expect(JSON.parse(post?.body as string)).toEqual({
      expected_state_version: 1,
      note: "Never used",
    });
  });

  it("explains that Not recorded is not a gap before the user marks one", async () => {
    serve(skillDetail());

    renderPage(<SkillDetail />, ROUTE);

    expect(await screen.findByText(/A skill with no evidence is Not recorded/)).toBeInTheDocument();
    expect(screen.getByText("Not recorded")).toBeInTheDocument();
  });

  it("clears a gap the user marked", async () => {
    const marked = skillDetail({
      user_marked_gap: true,
      gap_note: "Never used",
      headline: { category: "gap", engagement_type: null },
      categories: ["gap"],
    });
    const { calls } = serve(marked, (call, state) => {
      if (call.method === "POST" && call.url.endsWith("/clear-gap")) {
        state.skill = skillDetail({ state_version: 2 });
        return jsonResponse(state.skill);
      }
      return undefined;
    });
    renderPage(<SkillDetail />, ROUTE);

    expect(await screen.findByText(/You marked this skill as a gap: Never used/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Clear gap" }));

    expect(await screen.findByRole("button", { name: "Mark as a gap" })).toBeInTheDocument();
    expect(JSON.parse(posts(calls)[0]?.body as string)).toEqual({ expected_state_version: 1 });
  });

  it("asks for confirmation naming the old and new class before changing a classification", async () => {
    const { calls, state } = serve(WITH_CLAIM, (call) => {
      if (call.method === "POST" && call.url.endsWith("/classification")) {
        const changed = claim({
          evidence_class: "professional",
          engagement_type: "internship",
          state_version: 2,
        });
        state.skill = { ...WITH_CLAIM, claims: [changed] };
        return jsonResponse(changed);
      }
      return undefined;
    });
    renderPage(<SkillDetail />, ROUTE);

    fireEvent.change(await screen.findByLabelText("Engagement type"), {
      target: { value: "internship" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Change classification" }));

    const dialog = screen.getByRole("alertdialog", { name: "Confirm classification change" });
    expect(dialog).toHaveTextContent("from Professional (Type not specified) to Professional (Internship)");
    expect(posts(calls)).toHaveLength(0);
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm change" }));

    expect(await screen.findByText("Classification changed.")).toBeInTheDocument();
    const [post] = posts(calls);
    expect(post?.url).toBe("/api/v1/claims/claim-1/classification");
    expect(JSON.parse(post?.body as string)).toEqual({
      expected_state_version: 1,
      evidence_class: "professional",
      engagement_type: "internship",
      confirm_change: true,
    });
  });

  it("makes no change when the user cancels the confirmation", async () => {
    const { calls } = serve(WITH_CLAIM);
    renderPage(<SkillDetail />, ROUTE);

    const control = await screen.findByRole("region", {
      name: "Classification of Built sample widgets",
    });
    fireEvent.change(within(control).getByLabelText("Evidence class"), {
      target: { value: "learning" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Change classification" }));
    fireEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "Cancel" }),
    );

    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(posts(calls)).toHaveLength(0);
  });

  it("merges a duplicate into this skill with both versions", async () => {
    const { calls } = serve(skillDetail(), (call) =>
      call.method === "POST" ? jsonResponse(skillDetail({ state_version: 2 })) : undefined,
    );
    renderPage(<SkillDetail />, ROUTE);

    await screen.findByRole("option", { name: "Gadgets" });
    fireEvent.change(screen.getByLabelText("Skill to merge into Widgets"), {
      target: { value: "skill-2" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Merge into Widgets" }));

    expect(await screen.findByText("Skills merged.")).toBeInTheDocument();
    const [post] = posts(calls);
    expect(post?.url).toBe("/api/v1/skills/skill-1/merge");
    expect(JSON.parse(post?.body as string)).toEqual({
      merged_id: "skill-2",
      expected_state_version: 1,
      expected_merged_state_version: 4,
    });
    expect(screen.queryByRole("option", { name: "Widgets" })).toBeNull();
  });

  it("sends edited names and the note, then confirms", async () => {
    const { calls } = serve(skillDetail({ aliases: ["Gizmos"] }), (call) =>
      call.method === "PATCH" ? jsonResponse(skillDetail({ state_version: 2 })) : undefined,
    );
    renderPage(<SkillDetail />, ROUTE);

    fireEvent.change(await screen.findByLabelText("Other names (separated by commas)"), {
      target: { value: "Gizmos, Doohickeys" },
    });
    fireEvent.change(screen.getByLabelText("Your note"), { target: { value: " Core " } });
    fireEvent.click(screen.getByRole("button", { name: "Save skill" }));

    expect(await screen.findByText("Skill saved.")).toBeInTheDocument();
    expect(JSON.parse(posts(calls)[0]?.body as string)).toEqual({
      expected_state_version: 1,
      canonical_name: "Widgets",
      aliases: ["Gizmos", "Doohickeys"],
      user_note: "Core",
    });
  });

  it("refreshes after a stale edit and says what happened", async () => {
    serve(skillDetail(), (call) =>
      call.method === "PATCH" ? jsonResponse({ error: { code: "conflict" } }, 409) : undefined,
    );
    renderPage(<SkillDetail />, ROUTE);

    fireEvent.click(await screen.findByRole("button", { name: "Save skill" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("This changed since you opened it");
  });

  it("needs a source before it adds evidence, then confirms and keeps the choices", async () => {
    const { calls } = serve(skillDetail(), (call) =>
      call.method === "POST" ? jsonResponse(claim(), 201) : undefined,
    );
    renderPage(<SkillDetail />, ROUTE);
    const form = await screen.findByRole("form", { name: "Add evidence for this skill" });

    fireEvent.change(within(form).getByLabelText("Statement"), { target: { value: "Built it" } });
    fireEvent.change(within(form).getByLabelText("Evidence class"), {
      target: { value: "professional" },
    });
    expect(within(form).getByRole("button", { name: "Add evidence" })).toBeDisabled();
    fireEvent.change(within(form).getByLabelText("Engagement type"), {
      target: { value: "internship" },
    });
    fireEvent.change(within(form).getByLabelText("Your own words about this work"), {
      target: { value: " I did it " },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Add evidence" }));

    expect(await screen.findByText("Evidence added.")).toBeInTheDocument();
    expect(JSON.parse(posts(calls)[0]?.body as string)).toEqual({
      statement: "Built it",
      evidence_class: "professional",
      engagement_type: "internship",
      organization_label: null,
      start_date: null,
      end_date: null,
      skill_ids: ["skill-1"],
      sources: [{ source_type: "user_assertion", assertion_text: "I did it" }],
    });
    expect(within(form).getByLabelText("Evidence class")).toHaveValue("professional");
  });

  it("rejects evidence with the version it saw", async () => {
    const { calls } = serve(WITH_CLAIM, (call) =>
      call.method === "POST" ? jsonResponse(claim({ confirmation_status: "rejected" })) : undefined,
    );
    renderPage(<SkillDetail />, ROUTE);

    fireEvent.click(await screen.findByRole("button", { name: "Reject this evidence" }));

    await waitFor(() => {
      expect(posts(calls)).toHaveLength(1);
    });
    expect(posts(calls)[0]?.url).toBe("/api/v1/claims/claim-1/reject");
    expect(JSON.parse(posts(calls)[0]?.body as string)).toEqual({ expected_state_version: 1 });
  });

  it("points a merged skill to the one it was merged into", async () => {
    serve(skillDetail({ merged_into_skill_id: "skill-9" }));

    renderPage(<SkillDetail />, ROUTE);

    expect(
      await screen.findByRole("link", { name: "Open the skill it was merged into" }),
    ).toHaveAttribute("href", "/skills/skill-9");
    expect(screen.queryByRole("button", { name: "Mark as a gap" })).toBeNull();
  });

  it("renders hostile claim text, sources and names as plain text", async () => {
    const hostile = '<img src=x onerror="alert(1)"><script>alert(2)</script>';
    serve(
      skillDetail({
        canonical_name: hostile,
        claims: [
          claim({
            statement: hostile,
            sources: [
              {
                id: "s1",
                source_type: "user_assertion",
                resume_id: null,
                resume_label: null,
                artifact_id: null,
                url: null,
                assertion_text: hostile,
                locator: null,
                created_at: "2026-01-01T00:00:00Z",
              },
            ],
          }),
        ],
      }),
    );

    const { container } = renderPage(<SkillDetail />, ROUTE);

    expect(await screen.findByRole("heading", { name: hostile })).toBeInTheDocument();
    expect(screen.getByText(`Your words: ${hostile}`)).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
  });
});
