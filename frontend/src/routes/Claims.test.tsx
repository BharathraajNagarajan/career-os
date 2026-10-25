import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { Claim } from "../api/evidence";
import { jsonResponse, mockApi, renderPage } from "../test-utils";
import type { RecordedCall } from "../test-utils";
import { ClaimDetail } from "./ClaimDetail";
import { Claims } from "./Claims";
import { claim, skillSummary } from "./evidenceFixtures";

const ROUTE = { path: "/claims/:claimId", entry: "/claims/claim-1" };

function posts(calls: RecordedCall[]): RecordedCall[] {
  return calls.filter((call) => call.method !== "GET");
}

describe("Claims", () => {
  it("lists evidence with class, organization, dates and sources, and filters by class", async () => {
    const calls = mockApi((call) =>
      call.method === "GET" && call.url.startsWith("/api/v1/claims")
        ? jsonResponse([
            claim({
              evidence_class: "professional",
              engagement_type: "internship",
              organization_label: "Example Corp",
              start_date: "2021-06-01",
              end_date: null,
            }),
          ])
        : undefined,
    );

    renderPage(<Claims />);

    const item = (await screen.findByRole("link", { name: "Built sample widgets" })).closest(
      "li",
    ) as HTMLElement;
    expect(item).toHaveTextContent("Professional (Internship) · Example Corp · 2021-06-01 to present");
    expect(item).toHaveTextContent("Your words: I built them");
    fireEvent.change(screen.getByLabelText("Filter by evidence class"), { target: { value: "project" } });
    await waitFor(() => {
      expect(calls.at(-1)?.url).toBe("/api/v1/claims?evidence_class=project");
    });
  });

  it("shows a rejected claim as rejected", async () => {
    mockApi(() => jsonResponse([claim({ confirmation_status: "rejected" })]));

    renderPage(<Claims />);

    expect(await screen.findByText(/· Rejected/)).toBeInTheDocument();
  });
});

describe("ClaimDetail", () => {
  function serve(initial: Claim, extra?: (call: RecordedCall) => Response | undefined) {
    return mockApi((call) => {
      const custom = extra?.(call);
      if (custom) {
        return custom;
      }
      if (call.method === "GET" && call.url === "/api/v1/claims/claim-1") {
        return jsonResponse(initial);
      }
      if (call.method === "GET" && call.url === "/api/v1/skills") {
        return jsonResponse([
          skillSummary(),
          skillSummary({ id: "skill-2", canonical_name: "Gadgets" }),
        ]);
      }
      return undefined;
    });
  }

  it("edits statement, organization and dates with the version it saw", async () => {
    const calls = serve(claim(), (call) =>
      call.method === "PATCH" ? jsonResponse(claim({ state_version: 2 })) : undefined,
    );
    renderPage(<ClaimDetail />, ROUTE);

    fireEvent.change(await screen.findByLabelText("Statement"), {
      target: { value: " Built better widgets " },
    });
    fireEvent.change(screen.getByLabelText("Organization"), { target: { value: "Example Corp" } });
    fireEvent.change(screen.getByLabelText("Start date"), { target: { value: "2021-01-01" } });
    fireEvent.click(screen.getByRole("button", { name: "Save evidence" }));

    expect(await screen.findByText("Evidence saved.")).toBeInTheDocument();
    expect(JSON.parse(posts(calls)[0]?.body as string)).toEqual({
      expected_state_version: 1,
      statement: "Built better widgets",
      organization_label: "Example Corp",
      start_date: "2021-01-01",
      end_date: null,
    });
  });

  it("links and unlinks skills", async () => {
    const calls = serve(claim(), (call) =>
      call.method === "POST" || call.method === "DELETE" ? jsonResponse(claim()) : undefined,
    );
    renderPage(<ClaimDetail />, ROUTE);

    await screen.findByRole("option", { name: "Gadgets" });
    fireEvent.change(screen.getByLabelText("Link a skill"), { target: { value: "skill-2" } });
    fireEvent.click(screen.getByRole("button", { name: "Link skill" }));
    await waitFor(() => {
      expect(posts(calls)).toHaveLength(1);
    });
    fireEvent.click(screen.getByRole("button", { name: "Unlink Widgets" }));
    await waitFor(() => {
      expect(posts(calls)).toHaveLength(2);
    });

    expect(posts(calls)[0]?.url).toBe("/api/v1/claims/claim-1/skills");
    expect(JSON.parse(posts(calls)[0]?.body as string)).toEqual({ skill_id: "skill-2" });
    expect(posts(calls)[1]?.method).toBe("DELETE");
    expect(posts(calls)[1]?.url).toBe("/api/v1/claims/claim-1/skills/skill-1");
  });

  it("changes the class only after the user confirms old and new values", async () => {
    const calls = serve(claim(), (call) =>
      call.method === "POST"
        ? jsonResponse(claim({ evidence_class: "learning", state_version: 2 }))
        : undefined,
    );
    renderPage(<ClaimDetail />, ROUTE);

    const control = await screen.findByRole("region", {
      name: "Classification of Built sample widgets",
    });
    fireEvent.change(within(control).getByLabelText("Evidence class"), {
      target: { value: "learning" },
    });
    fireEvent.click(within(control).getByRole("button", { name: "Change classification" }));
    expect(screen.getByRole("alertdialog")).toHaveTextContent("from Project to Learning");
    expect(posts(calls)).toHaveLength(0);
    fireEvent.click(screen.getByRole("button", { name: "Confirm change" }));

    await waitFor(() => {
      expect(posts(calls)).toHaveLength(1);
    });
    expect(JSON.parse(posts(calls)[0]?.body as string)).toMatchObject({
      evidence_class: "learning",
      engagement_type: null,
      confirm_change: true,
    });
  });

  it("explains a gap conflict when a class change would contradict a gap marker", async () => {
    serve(claim({ evidence_class: "learning" }), (call) =>
      call.method === "POST" ? jsonResponse({ error: { code: "gap_marked" } }, 409) : undefined,
    );
    renderPage(<ClaimDetail />, ROUTE);

    const control = await screen.findByRole("region", {
      name: "Classification of Built sample widgets",
    });
    fireEvent.change(within(control).getByLabelText("Evidence class"), {
      target: { value: "project" },
    });
    fireEvent.click(within(control).getByRole("button", { name: "Change classification" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm change" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("marked as a gap");
  });

  it("offers nothing to change on rejected evidence", async () => {
    serve(claim({ confirmation_status: "rejected" }));

    renderPage(<ClaimDetail />, ROUTE);

    expect(await screen.findByText(/Rejected/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Change classification" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Save evidence" })).toBeNull();
  });
});
