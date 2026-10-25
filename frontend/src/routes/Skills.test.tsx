import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import { jsonResponse, mockApi, renderPage } from "../test-utils";
import type { RecordedCall } from "../test-utils";
import { skillSummary } from "./evidenceFixtures";
import { Skills } from "./Skills";

function serve(
  skills: ReturnType<typeof skillSummary>[],
  extra?: (call: RecordedCall) => Response | undefined,
) {
  return mockApi((call) => {
    const custom = extra?.(call);
    if (custom) {
      return custom;
    }
    if (call.method === "GET" && call.url.startsWith("/api/v1/skills")) {
      return jsonResponse(skills);
    }
    return undefined;
  });
}

const PROFESSIONAL = skillSummary({
  id: "skill-pro",
  canonical_name: "Python",
  headline: { category: "professional", engagement_type: "full_time" },
  categories: ["professional", "project"],
  badges: [
    { evidence_class: "professional", engagement_type: "full_time", confirmed: true, claim_count: 1 },
    { evidence_class: "project", engagement_type: null, confirmed: true, claim_count: 2 },
  ],
  exposure: [
    { resume_id: "r1", label: "Resume A", archived: false, stated: true, mentioned: true },
  ],
});
const INTERN = skillSummary({
  id: "skill-intern",
  canonical_name: "SQL",
  headline: { category: "professional", engagement_type: "internship" },
  categories: ["professional"],
  badges: [
    { evidence_class: "professional", engagement_type: "internship", confirmed: true, claim_count: 1 },
  ],
});
const GAP = skillSummary({
  id: "skill-gap",
  canonical_name: "Rust",
  user_marked_gap: true,
  headline: { category: "gap", engagement_type: null },
  categories: ["gap"],
});
const UNKNOWN = skillSummary({ id: "skill-unknown", canonical_name: "Widgets" });

describe("Skills", () => {
  it("shows the headline, every derived badge and resume exposure for each skill", async () => {
    serve([PROFESSIONAL, INTERN, GAP, UNKNOWN]);

    renderPage(<Skills />);

    const python = (await screen.findByRole("link", { name: "Python" })).closest("li") as HTMLElement;
    expect(python).toHaveTextContent("Professional (Full-time)");
    const badges = within(python).getByRole("list", { name: "Evidence for Python" });
    expect(within(badges).getAllByRole("listitem").map((item) => item.textContent)).toEqual([
      "Professional (Full-time)",
      "Project",
    ]);
    expect(python).toHaveTextContent("Name appears in the text of 1 resume (not proof of proficiency)");
  });

  it("labels an internship distinctly from full-time employment", async () => {
    serve([PROFESSIONAL, INTERN]);

    renderPage(<Skills />);

    const sql = (await screen.findByRole("link", { name: "SQL" })).closest("li") as HTMLElement;
    expect(sql).toHaveTextContent("Professional (Internship)");
    expect(sql).not.toHaveTextContent("Full-time");
  });

  it("shows Not recorded as such and never as a gap", async () => {
    serve([UNKNOWN, GAP]);

    renderPage(<Skills />);

    const widgets = (await screen.findByRole("link", { name: "Widgets" })).closest("li") as HTMLElement;
    expect(widgets).toHaveTextContent("Not recorded");
    expect(widgets).not.toHaveTextContent(/gap/i);
    const rust = screen.getByRole("link", { name: "Rust" }).closest("li") as HTMLElement;
    expect(rust).toHaveTextContent("Gap (marked by you)");
    expect(widgets).toHaveTextContent("Name not found in the text of any resume");
  });

  it("filters by search, category and engagement type through the server", async () => {
    const calls = serve([PROFESSIONAL]);
    renderPage(<Skills />);
    await screen.findByRole("link", { name: "Python" });

    fireEvent.change(screen.getByLabelText("Search skills"), { target: { value: " pyth " } });
    fireEvent.change(screen.getByLabelText("Category"), { target: { value: "professional" } });
    fireEvent.change(await screen.findByLabelText("Engagement type"), {
      target: { value: "internship" },
    });

    await waitFor(() => {
      expect(calls.at(-1)?.url).toBe(
        "/api/v1/skills?q=pyth&category=professional&engagement=internship",
      );
    });
    fireEvent.change(screen.getByLabelText("Category"), { target: { value: "gap" } });
    await waitFor(() => {
      expect(calls.at(-1)?.url).toBe("/api/v1/skills?q=pyth&category=gap");
    });
    expect(screen.queryByLabelText("Engagement type")).toBeNull();
  });

  it("offers the category filters the spec lists, including Gap and Not recorded", async () => {
    serve([]);

    renderPage(<Skills />);

    await screen.findByText("No skills found.");
    const options = within(screen.getByLabelText("Category"))
      .getAllByRole("option")
      .map((option) => option.textContent);
    expect(options).toEqual([
      "All",
      "Professional",
      "Academic / Research",
      "Project",
      "Learning",
      "Gap",
      "Not recorded",
    ]);
  });

  it("adds a skill with aliases and shows a confirmation", async () => {
    const calls = serve([], (call) =>
      call.method === "POST" ? jsonResponse(skillSummary({ canonical_name: "Gadgets" }), 201) : undefined,
    );
    renderPage(<Skills />);
    await screen.findByText("No skills found.");

    fireEvent.change(screen.getByLabelText("Skill name"), { target: { value: " Gadgets " } });
    fireEvent.change(screen.getByLabelText("Other names (separated by commas)"), {
      target: { value: "Gizmos, , Doohickeys" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add skill" }));

    expect(await screen.findByText("Skill added.")).toBeInTheDocument();
    const post = calls.find((call) => call.method === "POST");
    expect(JSON.parse(post?.body as string)).toEqual({
      canonical_name: "Gadgets",
      aliases: ["Gizmos", "Doohickeys"],
      user_note: "",
    });
    expect(screen.getByLabelText("Skill name")).toHaveValue(" Gadgets ");
  });

  it("explains a duplicate name in plain language", async () => {
    serve([], (call) =>
      call.method === "POST" ? jsonResponse({ error: { code: "skill_exists" } }, 409) : undefined,
    );
    renderPage(<Skills />);
    await screen.findByText("No skills found.");

    fireEvent.change(screen.getByLabelText("Skill name"), { target: { value: "Widgets" } });
    fireEvent.click(screen.getByRole("button", { name: "Add skill" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "You already have a skill or alias with that name.",
    );
  });

  it("renders hostile skill names as plain text", async () => {
    const hostile = '<img src=x onerror="alert(1)"><script>alert(2)</script>';
    serve([skillSummary({ canonical_name: hostile })]);

    const { container } = renderPage(<Skills />);

    expect(await screen.findByRole("link", { name: hostile })).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
  });
});
