import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import { jsonResponse, mockApi, renderPage } from "../test-utils";
import type { RecordedCall } from "../test-utils";
import { application } from "./opportunityFixtures";
import { OpportunityRelationships } from "./OpportunityRelationships";
import { contactSummary, recruitingAction } from "./relationshipFixtures";

function serve(withApplication: boolean): RecordedCall[] {
  return mockApi((call) => {
    if (call.method === "GET" && call.url.startsWith("/api/v1/contacts")) {
      return jsonResponse([contactSummary()]);
    }
    if (call.method === "GET" && call.url.startsWith("/api/v1/actions")) {
      return jsonResponse([recruitingAction({ title: "Prepare questions", kind: "custom" })]);
    }
    if (call.method === "GET" && call.url.startsWith("/api/v1/applications")) {
      return jsonResponse(withApplication ? [application()] : []);
    }
    if (call.method === "POST" && call.url === "/api/v1/interactions") {
      return jsonResponse(
        {
          id: "i1",
          contact_id: "contact-1",
          company_id: null,
          opportunity_id: "opp-1",
          application_id: null,
          channel: "email",
          direction: "outbound",
          occurred_at: "2026-01-01T00:00:00Z",
          summary: null,
          created_at: "2026-01-01T00:00:00Z",
        },
        201,
      );
    }
    return undefined;
  });
}

describe("OpportunityRelationships", () => {
  it("shows linked contacts and open actions for the opportunity", async () => {
    const calls = serve(false);

    renderPage(<OpportunityRelationships opportunityId="opp-1" />);

    expect(await screen.findByRole("link", { name: "Alex Example" })).toHaveAttribute(
      "href",
      "/contacts/contact-1",
    );
    expect(await screen.findByText(/Prepare questions/)).toBeInTheDocument();
    expect(calls.some((call) => call.url === "/api/v1/contacts?opportunity_id=opp-1")).toBe(true);
    expect(
      calls.some(
        (call) =>
          call.url === "/api/v1/actions?status=open&status=snoozed&opportunity_id=opp-1",
      ),
    ).toBe(true);
  });

  it("records an interaction for the opportunity without an application event", async () => {
    const calls = serve(false);
    renderPage(<OpportunityRelationships opportunityId="opp-1" />);

    const form = await screen.findByRole("form", { name: "Record interaction" });
    await within(form).findByRole("option", { name: "Alex Example" });
    expect(within(form).queryByLabelText("Also record on the application")).toBeNull();
    fireEvent.change(within(form).getByLabelText("Contact"), { target: { value: "contact-1" } });
    fireEvent.click(within(form).getByRole("button", { name: "Record interaction" }));

    expect(await screen.findByText("Interaction recorded.")).toBeInTheDocument();
    const post = calls.find((call) => call.method === "POST");
    expect(JSON.parse(post?.body as string)).toMatchObject({
      contact_id: "contact-1",
      opportunity_id: "opp-1",
    });
  });

  it("sends the application and its version when an event is chosen", async () => {
    const calls = serve(true);
    renderPage(<OpportunityRelationships opportunityId="opp-1" />);

    const form = await screen.findByRole("form", { name: "Record interaction" });
    await within(form).findByRole("option", { name: "Alex Example" });
    fireEvent.change(within(form).getByLabelText("Contact"), { target: { value: "contact-1" } });
    fireEvent.change(await within(form).findByLabelText("Also record on the application"), {
      target: { value: "OUTREACH_SENT" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Record interaction" }));

    await waitFor(() => {
      expect(calls.some((call) => call.method === "POST")).toBe(true);
    });
    const post = calls.find((call) => call.method === "POST");
    expect(JSON.parse(post?.body as string)).toMatchObject({
      application_id: application().id,
      application_event_type: "OUTREACH_SENT",
      expected_application_state_version: application().state_version,
    });
    expect(await screen.findByText("Interaction recorded.")).toBeInTheDocument();
    expect(within(form).getByLabelText("Also record on the application")).toHaveValue(
      "OUTREACH_SENT",
    );
  });

  it("explains a stale application version and offers a refresh", async () => {
    mockApi((call) => {
      if (call.method === "GET" && call.url.startsWith("/api/v1/applications")) {
        return jsonResponse([application()]);
      }
      if (call.method === "GET" && call.url.startsWith("/api/v1/actions")) {
        return jsonResponse([]);
      }
      if (call.method === "GET") {
        return jsonResponse([contactSummary()]);
      }
      return jsonResponse({ error: { code: "conflict" } }, 409);
    });
    renderPage(<OpportunityRelationships opportunityId="opp-1" />);

    const form = await screen.findByRole("form", { name: "Record interaction" });
    await within(form).findByRole("option", { name: "Alex Example" });
    fireEvent.change(within(form).getByLabelText("Contact"), { target: { value: "contact-1" } });
    fireEvent.change(await within(form).findByLabelText("Also record on the application"), {
      target: { value: "FOLLOWUP_SENT" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Record interaction" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("This changed since you opened it");
    expect(screen.getByRole("button", { name: "Refresh" })).toBeInTheDocument();
  });
});
