import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { ContactDetail as Detail } from "../api/contacts";
import { jsonResponse, mockApi, renderPage } from "../test-utils";
import type { RecordedCall } from "../test-utils";
import { ContactDetail } from "./ContactDetail";
import { contactDetail, contactSummary, recruitingAction } from "./relationshipFixtures";

const ROUTE = { path: "/contacts/:contactId", entry: "/contacts/contact-1" };

interface Server {
  calls: RecordedCall[];
  contact: Detail;
}

function serve(initial: Partial<Detail> = {}, command?: (call: RecordedCall) => Response | undefined) {
  const server: Server = { calls: [], contact: contactDetail(initial) };
  server.calls = mockApi((call) => {
    if (call.method === "GET" && call.url === "/api/v1/contacts/contact-1") {
      return jsonResponse(server.contact);
    }
    if (call.method === "GET" && call.url === "/api/v1/contacts") {
      return jsonResponse([
        contactSummary(),
        contactSummary({ id: "contact-2", full_name: "Sam Example", updated_at: "2026-01-03T00:00:00Z" }),
      ]);
    }
    if (call.method === "GET" && call.url === "/api/v1/companies") {
      return jsonResponse([
        {
          id: "company-1",
          name: "Example Corp",
          normalized_name: "example",
          aliases: [],
          domains: [],
          careers_url: null,
          strategic_priority: "normal",
          notes: "",
          origin: "user",
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        },
      ]);
    }
    if (call.method === "GET") {
      return jsonResponse([]);
    }
    return command?.(call);
  });
  return server;
}

function posts(server: Server): RecordedCall[] {
  return server.calls.filter((call) => call.method !== "GET");
}

describe("ContactDetail", () => {
  it("shows the fields, each address with its source, and the interactions", async () => {
    serve({
      emails: [
        { address: "alex@example.test", source: "manual", added_at: "2026-01-01T00:00:00Z" },
        { address: "alex@mail.example.test", source: "gmail", added_at: "2026-01-01T00:00:00Z" },
      ],
      interactions: [
        {
          id: "i1",
          contact_id: "contact-1",
          company_id: null,
          opportunity_id: null,
          application_id: null,
          channel: "linkedin",
          direction: "outbound",
          occurred_at: "2026-01-01T10:00:00Z",
          summary: "Sent a note",
          created_at: "2026-01-01T10:00:00Z",
        },
      ],
      actions: [recruitingAction({ title: "Reply soon", kind: "reply" })],
    });

    renderPage(<ContactDetail />, ROUTE);

    expect(await screen.findByRole("heading", { name: "Alex Example" })).toBeInTheDocument();
    const sources = screen.getByRole("list", { name: "Email sources" });
    expect(within(sources).getByText(/alex@example.test/)).toHaveTextContent("source: manual");
    expect(within(sources).getByText(/alex@mail.example.test/)).toHaveTextContent("source: gmail");
    expect(screen.getByText("Sent a note")).toBeInTheDocument();
    expect(screen.getByText(/Reply soon/)).toBeInTheDocument();
  });

  it("saves edits with the version it loaded and shows a confirmation", async () => {
    const server = serve({}, () => jsonResponse(contactDetail({ headline: "Lead recruiter" })));
    renderPage(<ContactDetail />, ROUTE);

    fireEvent.change(await screen.findByLabelText("Headline"), {
      target: { value: "Lead recruiter" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save contact" }));

    expect(await screen.findByText("Saved.")).toBeInTheDocument();
    const patch = posts(server).find((call) => call.method === "PATCH");
    expect(JSON.parse(patch?.body as string)).toMatchObject({
      expected_updated_at: "2026-01-02T00:00:00.123456Z",
      headline: "Lead recruiter",
      emails: ["alex@example.test"],
    });
  });

  it("offers a refresh after a conflict and reloads", async () => {
    const server = serve({}, () => jsonResponse({ error: { code: "conflict" } }, 409));
    renderPage(<ContactDetail />, ROUTE);

    fireEvent.click(await screen.findByRole("button", { name: "Save contact" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("This changed since you opened it");
    const before = server.calls.filter((call) => call.url === "/api/v1/contacts/contact-1").length;
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => {
      expect(
        server.calls.filter((call) => call.url === "/api/v1/contacts/contact-1").length,
      ).toBeGreaterThan(before);
    });
  });

  it("links a company with its relation", async () => {
    const server = serve({}, () =>
      jsonResponse(
        contactDetail({
          companies: [
            {
              company_id: "company-1",
              company_name: "Example Corp",
              relation: "recruiter",
              title: null,
              is_current: true,
            },
          ],
        }),
      ),
    );
    renderPage(<ContactDetail />, ROUTE);

    const form = await screen.findByRole("form", { name: "Link company" });
    await within(form).findByRole("option", { name: "Example Corp" });
    fireEvent.change(within(form).getByLabelText("Company"), { target: { value: "company-1" } });
    fireEvent.change(within(form).getByLabelText("Relation"), { target: { value: "recruiter" } });
    fireEvent.click(within(form).getByRole("button", { name: "Link company" }));

    expect(await screen.findByText(/Example Corp – Recruiter/)).toBeInTheDocument();
    const post = posts(server)[0];
    expect(post?.url).toBe("/api/v1/contacts/contact-1/companies/company-1");
    expect(JSON.parse(post?.body as string)).toEqual({
      relation: "recruiter",
      title: null,
      is_current: true,
    });
  });

  it("asks for confirmation before merging and sends both versions", async () => {
    const server = serve({}, () => jsonResponse(contactDetail()));
    renderPage(<ContactDetail />, ROUTE);

    const select = await screen.findByLabelText("Contact to merge in");
    await within(select).findByRole("option", { name: "Sam Example" });
    fireEvent.change(select, { target: { value: "contact-2" } });
    fireEvent.click(screen.getByRole("button", { name: "Merge…" }));

    expect(posts(server)).toHaveLength(0);
    const group = screen.getByRole("group", { name: "Confirm merge" });
    expect(group).toHaveTextContent("Merge Sam Example into Alex Example?");
    fireEvent.click(within(group).getByRole("button", { name: "Confirm merge" }));

    expect(await screen.findByText("Contacts merged.")).toBeInTheDocument();
    const post = posts(server)[0];
    expect(post?.url).toBe("/api/v1/contacts/contact-1/merge");
    expect(JSON.parse(post?.body as string)).toEqual({
      merged_id: "contact-2",
      expected_survivor_updated_at: "2026-01-02T00:00:00.123456Z",
      expected_merged_updated_at: "2026-01-03T00:00:00Z",
    });
  });

  it("can cancel the merge confirmation without sending anything", async () => {
    const server = serve();
    renderPage(<ContactDetail />, ROUTE);

    const select = await screen.findByLabelText("Contact to merge in");
    await within(select).findByRole("option", { name: "Sam Example" });
    fireEvent.change(select, { target: { value: "contact-2" } });
    fireEvent.click(screen.getByRole("button", { name: "Merge…" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));

    expect(screen.queryByRole("group", { name: "Confirm merge" })).toBeNull();
    expect(posts(server)).toHaveLength(0);
  });

  it("records an interaction and keeps the chosen channel", async () => {
    const server = serve({}, () =>
      jsonResponse(
        {
          id: "i2",
          contact_id: "contact-1",
          company_id: null,
          opportunity_id: null,
          application_id: null,
          channel: "phone",
          direction: "inbound",
          occurred_at: "2026-01-01T10:00:00Z",
          summary: "Called back",
          created_at: "2026-01-01T10:00:00Z",
        },
        201,
      ),
    );
    renderPage(<ContactDetail />, ROUTE);

    const form = await screen.findByRole("form", { name: "Record interaction" });
    fireEvent.change(within(form).getByLabelText("Channel"), { target: { value: "phone" } });
    fireEvent.change(within(form).getByLabelText("Direction"), { target: { value: "inbound" } });
    fireEvent.change(within(form).getByLabelText("Summary"), { target: { value: "Called back" } });
    fireEvent.click(within(form).getByRole("button", { name: "Record interaction" }));

    expect(await screen.findByText("Interaction recorded.")).toBeInTheDocument();
    const post = posts(server).find((call) => call.url === "/api/v1/interactions");
    expect(JSON.parse(post?.body as string)).toMatchObject({
      contact_id: "contact-1",
      channel: "phone",
      direction: "inbound",
      summary: "Called back",
    });
    expect(within(form).getByLabelText("Channel")).toHaveValue("phone");
    expect(within(form).getByLabelText("Direction")).toHaveValue("inbound");
  });

  it("renders hostile text as plain text", async () => {
    const hostile = '<img src=x onerror="alert(1)">';
    serve({ full_name: hostile, notes: hostile, headline: hostile });

    const { container } = renderPage(<ContactDetail />, ROUTE);

    await screen.findByRole("heading", { name: hostile });
    expect(container.querySelector("img")).toBeNull();
  });
});
