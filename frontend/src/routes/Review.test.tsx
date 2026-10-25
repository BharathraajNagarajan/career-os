import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { ReviewItem } from "../api/review";
import { jsonResponse, mockApi, renderPage } from "../test-utils";
import type { RecordedCall } from "../test-utils";
import { Review } from "./Review";

function item(overrides: Partial<ReviewItem> = {}): ReviewItem {
  return {
    id: "item-1",
    source: "extraction",
    proposal_type: "skill_evidence",
    proposed_payload: { schema_version: 1, name: "Synthetic skill" },
    confidence: 0.8,
    rationale: "Seen in a synthetic note",
    evidence_ref_id: null,
    status: "pending",
    decided_at: null,
    decided_payload: null,
    decision_note: null,
    state_version: 3,
    confirmable: true,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    ...overrides,
  };
}

interface Server {
  calls: RecordedCall[];
  pending: ReviewItem[];
}

function serve(initial: ReviewItem[], decision?: (call: RecordedCall) => Response | undefined) {
  const server: Server = { calls: [], pending: initial };
  server.calls = mockApi((call) => {
    if (call.method === "GET" && call.url === "/api/v1/review-items?status=pending") {
      return jsonResponse(server.pending);
    }
    if (call.method === "POST") {
      return decision?.(call);
    }
    return undefined;
  });
  return server;
}

function posts(server: Server): RecordedCall[] {
  return server.calls.filter((call) => call.method === "POST");
}

describe("Review", () => {
  it("shows pending items with source, type, rationale and confidence", async () => {
    serve([item()]);

    renderPage(<Review />);

    expect(await screen.findByRole("heading", { name: "skill evidence" })).toBeInTheDocument();
    expect(screen.getByText(/Source: extraction/)).toBeInTheDocument();
    expect(screen.getByText(/Confidence: 80%/)).toBeInTheDocument();
    expect(screen.getByText("Seen in a synthetic note")).toBeInTheDocument();
    expect(screen.getByText(/"name": "Synthetic skill"/)).toBeInTheDocument();
  });

  it("renders payload text as plain text, never as markup", async () => {
    const hostile = '<img src=x onerror="alert(1)"><script>alert(2)</script>';
    serve([item({ proposed_payload: { schema_version: 1, name: hostile } })]);

    const { container } = renderPage(<Review />);

    await screen.findByRole("heading", { name: "skill evidence" });
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("pre")?.textContent).toContain(JSON.stringify(hostile));
  });

  it("says when there is nothing to review", async () => {
    serve([]);

    renderPage(<Review />);

    expect(await screen.findByText("Nothing to review.")).toBeInTheDocument();
  });

  it("confirms with the version it saw and then reloads the list", async () => {
    const server = serve([item()], () => {
      server.pending = [];
      return jsonResponse(item({ status: "confirmed", state_version: 4 }));
    });
    renderPage(<Review />);

    fireEvent.click(await screen.findByRole("button", { name: "Confirm" }));

    expect(await screen.findByText("Nothing to review.")).toBeInTheDocument();
    const [call] = posts(server);
    expect(call?.url).toBe("/api/v1/review-items/item-1/confirm");
    expect(JSON.parse(call?.body as string)).toEqual({ expected_state_version: 3 });
  });

  it("sends an edited payload for edit and confirm", async () => {
    const server = serve([item()], () => jsonResponse(item({ status: "confirmed" })));
    renderPage(<Review />);

    fireEvent.click(await screen.findByRole("button", { name: "Edit and confirm" }));
    fireEvent.change(screen.getByLabelText("Edited proposal (JSON)"), {
      target: { value: '{"schema_version": 1, "name": "Edited"}' },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save and confirm" }));

    await waitFor(() => {
      expect(posts(server)).toHaveLength(1);
    });
    const [call] = posts(server);
    expect(call?.url).toBe("/api/v1/review-items/item-1/edit-confirm");
    expect(JSON.parse(call?.body as string)).toEqual({
      expected_state_version: 3,
      payload: { schema_version: 1, name: "Edited" },
    });
  });

  it("blocks an edit that is not a JSON object without calling the server", async () => {
    const server = serve([item()]);
    renderPage(<Review />);

    fireEvent.click(await screen.findByRole("button", { name: "Edit and confirm" }));
    for (const bad of ["{not json", "[1, 2]", "42"]) {
      fireEvent.change(screen.getByLabelText("Edited proposal (JSON)"), { target: { value: bad } });
      fireEvent.click(screen.getByRole("button", { name: "Save and confirm" }));
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "The edit must be a valid JSON object.",
      );
    }

    expect(posts(server)).toHaveLength(0);
  });

  it("rejects with an optional note", async () => {
    const server = serve([item()], () => jsonResponse(item({ status: "rejected" })));
    renderPage(<Review />);

    fireEvent.click(await screen.findByRole("button", { name: "Reject" }));
    fireEvent.change(screen.getByLabelText("Reason (optional)"), {
      target: { value: "  not recruiting " },
    });
    fireEvent.click(screen.getAllByRole("button", { name: "Reject" })[0] as HTMLElement);

    await waitFor(() => {
      expect(posts(server)).toHaveLength(1);
    });
    const [call] = posts(server);
    expect(call?.url).toBe("/api/v1/review-items/item-1/reject");
    expect(JSON.parse(call?.body as string)).toEqual({
      expected_state_version: 3,
      note: "not recruiting",
    });
  });

  it("rejects without a note when none is given", async () => {
    const server = serve([item()], () => jsonResponse(item({ status: "rejected" })));
    renderPage(<Review />);

    fireEvent.click(await screen.findByRole("button", { name: "Reject" }));
    fireEvent.click(screen.getAllByRole("button", { name: "Reject" })[0] as HTMLElement);

    await waitFor(() => {
      expect(posts(server)).toHaveLength(1);
    });
    expect(JSON.parse(posts(server)[0]?.body as string)).toEqual({ expected_state_version: 3 });
  });

  it("shows a plain message and refreshes on a stale-version conflict", async () => {
    const server = serve([item()], () => {
      server.pending = [item({ state_version: 4, rationale: "Fresher rationale" })];
      return jsonResponse({ error: { code: "conflict" } }, 409);
    });
    renderPage(<Review />);

    fireEvent.click(await screen.findByRole("button", { name: "Confirm" }));

    expect(await screen.findByText("Fresher rationale")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "This item changed since you opened it. The list has been refreshed.",
    );
    const lists = server.calls.filter((call) => call.method === "GET");
    expect(lists.length).toBeGreaterThanOrEqual(2);
  });

  it("keeps the notice when the refresh removes the item", async () => {
    const server = serve([item()], () => {
      server.pending = [];
      return jsonResponse({ error: { code: "invalid_transition" } }, 409);
    });
    renderPage(<Review />);

    fireEvent.click(await screen.findByRole("button", { name: "Confirm" }));

    expect(await screen.findByText("Nothing to review.")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent("already been decided");
  });

  it("explains an invalid edit reported by the server", async () => {
    serve([item()], () => jsonResponse({ error: { code: "invalid_payload" } }, 422));
    renderPage(<Review />);

    fireEvent.click(await screen.findByRole("button", { name: "Edit and confirm" }));
    fireEvent.click(screen.getByRole("button", { name: "Save and confirm" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "That edit is not valid for this kind of proposal.",
    );
  });

  it("disables confirm and edit for a type with no handler but still allows reject", async () => {
    serve([item({ confirmable: false, proposal_type: "claim" })]);
    renderPage(<Review />);

    expect(await screen.findByRole("button", { name: "Confirm" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Edit and confirm" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Reject" })).toBeEnabled();
    expect(screen.getByText(/cannot be confirmed yet/)).toBeInTheDocument();
  });
});

function claimItem(id: string, statement: string, overrides: Partial<ReviewItem> = {}): ReviewItem {
  return item({
    id,
    proposal_type: "claim",
    evidence_ref_id: "resume-1",
    proposed_payload: {
      schema_version: 1,
      statement,
      evidence_class: "professional",
      engagement_type: "unspecified",
      start_date: "2021-06-01",
      end_date: null,
      organization_label: "Example Corp",
      skill_names: ["Python", "SQL"],
      resume_id: "resume-1",
      confirm_class_change: false,
    },
    ...overrides,
  });
}

function skillItem(id: string, name: string): ReviewItem {
  return item({
    id,
    proposal_type: "skill",
    evidence_ref_id: "resume-1",
    proposed_payload: { schema_version: 1, name, resume_id: "resume-1" },
  });
}

function serveWithResume(
  initial: ReviewItem[],
  decision?: (call: RecordedCall) => Response | undefined,
) {
  const server: Server = { calls: [], pending: initial };
  server.calls = mockApi((call) => {
    if (call.method === "GET" && call.url === "/api/v1/review-items?status=pending") {
      return jsonResponse(server.pending);
    }
    if (call.method === "GET" && call.url === "/api/v1/resumes") {
      return jsonResponse([{ id: "resume-1", label: "Sample resume" }]);
    }
    if (call.method === "POST") {
      return decision?.(call);
    }
    return undefined;
  });
  return server;
}

describe("Review of extracted evidence", () => {
  it("groups proposals by source resume and shows claims as readable evidence", async () => {
    serveWithResume([
      claimItem("c1", "Built sample widgets"),
      skillItem("s1", "Python"),
      item({ id: "other", proposal_type: "interaction", evidence_ref_id: null }),
    ]);

    renderPage(<Review />);

    const group = await screen.findByRole("region", { name: "From resume: Sample resume" });
    expect(within(group).getByText("Built sample widgets")).toBeInTheDocument();
    expect(
      within(group).getByText("Professional (Type not specified) · Example Corp · 2021-06-01 to present"),
    ).toBeInTheDocument();
    expect(within(group).getByText("Skills: Python, SQL")).toBeInTheDocument();
    expect(screen.getByRole("region", { name: "Other proposals" })).toBeInTheDocument();
  });

  it("confirms several selected items at once and reports a partial failure per item", async () => {
    const server = serveWithResume(
      [claimItem("c1", "First claim"), claimItem("c2", "Second claim"), skillItem("s1", "Python")],
      (call) => {
        if (call.url !== "/api/v1/review-items/batch-confirm") {
          return undefined;
        }
        server.pending = [claimItem("c2", "Second claim")];
        return jsonResponse({
          results: [
            { id: "c1", ok: true, error_code: null, item: item({ id: "c1", status: "confirmed" }) },
            { id: "c2", ok: false, error_code: "gap_marked", item: null },
            { id: "s1", ok: true, error_code: null, item: item({ id: "s1", status: "confirmed" }) },
          ],
        });
      },
    );
    renderPage(<Review />);

    fireEvent.click(await screen.findByRole("checkbox", { name: "Select First claim" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Second claim" }));
    fireEvent.click(screen.getByRole("checkbox", { name: "Select Python" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm selected (3)" }));

    expect(await screen.findByText("Confirmed 2 of 3 selected.")).toBeInTheDocument();
    const failures = screen.getByRole("alert");
    expect(failures).toHaveTextContent("Second claim");
    expect(failures).toHaveTextContent("marked as a gap");
    expect(failures).not.toHaveTextContent("First claim");
    const [post] = server.calls.filter((call) => call.method === "POST");
    expect(JSON.parse(post?.body as string)).toEqual({
      items: [
        { id: "c1", expected_state_version: 3 },
        { id: "c2", expected_state_version: 3 },
        { id: "s1", expected_state_version: 3 },
      ],
    });
    await waitFor(() => {
      expect(screen.queryByText("First claim")).toBeNull();
    });
    expect(screen.getByRole("checkbox", { name: "Select Second claim" })).toBeChecked();
    expect(screen.getByRole("button", { name: "Confirm selected (1)" })).toBeEnabled();
  });

  it("selects every confirmable item of a resume with one click", async () => {
    serveWithResume([claimItem("c1", "First claim"), skillItem("s1", "Python")]);
    renderPage(<Review />);

    fireEvent.click(await screen.findByRole("button", { name: "Select all in From resume: Sample resume" }));

    expect(screen.getByRole("button", { name: "Confirm selected (2)" })).toBeEnabled();
  });

  it("does not confirm anything until the user selects items", async () => {
    const server = serveWithResume([claimItem("c1", "First claim")]);
    renderPage(<Review />);

    expect(await screen.findByRole("button", { name: "Confirm selected (0)" })).toBeDisabled();
    expect(server.calls.filter((call) => call.method === "POST")).toHaveLength(0);
  });

  it("edits a claim without a class change and sends the full corrected payload", async () => {
    const server = serveWithResume([claimItem("c1", "Built sample widgets")], () =>
      jsonResponse(item({ id: "c1", status: "confirmed" })),
    );
    renderPage(<Review />);

    fireEvent.click(await screen.findByRole("button", { name: "Edit and confirm" }));
    fireEvent.change(screen.getByLabelText("Statement"), { target: { value: " Built widgets " } });
    fireEvent.change(screen.getByLabelText("Organization"), { target: { value: "Example Org" } });
    fireEvent.change(screen.getByLabelText("Skills (separated by commas)"), {
      target: { value: "Python, , Testing" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save and confirm" }));

    await waitFor(() => {
      expect(server.calls.filter((call) => call.method === "POST")).toHaveLength(1);
    });
    const [post] = server.calls.filter((call) => call.method === "POST");
    expect(post?.url).toBe("/api/v1/review-items/c1/edit-confirm");
    expect(JSON.parse(post?.body as string)).toEqual({
      expected_state_version: 3,
      payload: {
        schema_version: 1,
        statement: "Built widgets",
        evidence_class: "professional",
        engagement_type: "unspecified",
        start_date: "2021-06-01",
        end_date: null,
        organization_label: "Example Org",
        skill_names: ["Python", "Testing"],
        resume_id: "resume-1",
        confirm_class_change: false,
      },
    });
  });

  it("asks the user to confirm a class change, naming old and new, before sending it", async () => {
    const server = serveWithResume([claimItem("c1", "Built sample widgets")], () =>
      jsonResponse(item({ id: "c1", status: "confirmed" })),
    );
    renderPage(<Review />);

    fireEvent.click(await screen.findByRole("button", { name: "Edit and confirm" }));
    fireEvent.change(screen.getByLabelText("Engagement type"), { target: { value: "full_time" } });
    fireEvent.click(screen.getByRole("button", { name: "Save and confirm" }));

    const dialog = screen.getByRole("alertdialog", { name: "Confirm classification change" });
    expect(dialog).toHaveTextContent(
      "from Professional (Type not specified) to Professional (Full-time)",
    );
    expect(server.calls.filter((call) => call.method === "POST")).toHaveLength(0);
    fireEvent.click(within(dialog).getByRole("button", { name: "Confirm change and save" }));

    await waitFor(() => {
      expect(server.calls.filter((call) => call.method === "POST")).toHaveLength(1);
    });
    const [post] = server.calls.filter((call) => call.method === "POST");
    const sent = JSON.parse(post?.body as string) as { payload: Record<string, unknown> };
    expect(sent.payload.engagement_type).toBe("full_time");
    expect(sent.payload.confirm_class_change).toBe(true);
  });

  it("keeps the proposed class when the user declines the class change", async () => {
    const server = serveWithResume([claimItem("c1", "Built sample widgets")]);
    renderPage(<Review />);

    fireEvent.click(await screen.findByRole("button", { name: "Edit and confirm" }));
    fireEvent.change(screen.getByLabelText("Evidence class"), { target: { value: "learning" } });
    fireEvent.click(screen.getByRole("button", { name: "Save and confirm" }));
    fireEvent.click(screen.getByRole("button", { name: "Keep proposed class" }));

    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(server.calls.filter((call) => call.method === "POST")).toHaveLength(0);
  });

  it("renders hostile claim text as plain text", async () => {
    const hostile = '<img src=x onerror="alert(1)"><script>alert(2)</script>';
    serveWithResume([claimItem("c1", hostile, { rationale: hostile })]);

    const { container } = renderPage(<Review />);

    expect((await screen.findAllByText(hostile)).length).toBeGreaterThan(0);
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
  });

  it("explains the confirmation requirement reported by the server", async () => {
    serveWithResume([claimItem("c1", "Built sample widgets")], () =>
      jsonResponse({ error: { code: "confirmation_required" } }, 422),
    );
    renderPage(<Review />);

    fireEvent.click(await screen.findByRole("button", { name: "Confirm" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Confirm the change of class");
  });
});
