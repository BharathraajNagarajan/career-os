import { screen, within } from "@testing-library/react";

import { jsonResponse, mockApi, renderPage } from "../test-utils";
import { Applications } from "./Applications";
import { application } from "./opportunityFixtures";

describe("Applications", () => {
  it("lists company, title, stage and applied date, linking to the opportunity", async () => {
    mockApi((call) =>
      call.url === "/api/v1/applications"
        ? jsonResponse([
            application(),
            application({
              id: "app-2",
              opportunity_id: "opp-2",
              opportunity_title: null,
              company_name: null,
              stage: "rejected",
              is_terminal: true,
            }),
          ])
        : undefined,
    );

    renderPage(<Applications />);

    const rows = await screen.findAllByRole("row");
    expect(rows).toHaveLength(3);
    const first = within(rows[1] as HTMLElement);
    expect(first.getByText("Example Corp")).toBeInTheDocument();
    expect(first.getByRole("link", { name: "Senior Widget Engineer" })).toHaveAttribute(
      "href",
      "/opportunities/opp-1",
    );
    expect(first.getByText("Applied")).toBeInTheDocument();
    expect(
      first.getByText(new Date("2026-01-02T10:00:00Z").toLocaleDateString()),
    ).toBeInTheDocument();
    const second = within(rows[2] as HTMLElement);
    expect(second.getByRole("link", { name: "Untitled posting" })).toHaveAttribute(
      "href",
      "/opportunities/opp-2",
    );
    expect(second.getByText("Rejected (closed)")).toBeInTheDocument();
  });

  it("says so when there are none", async () => {
    mockApi(() => jsonResponse([]));

    renderPage(<Applications />);

    expect(await screen.findByText("No applications yet.")).toBeInTheDocument();
  });

  it("reports a failed load", async () => {
    mockApi(() => jsonResponse({ error: { code: "boom" } }, 500));

    renderPage(<Applications />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load applications.");
  });
});
