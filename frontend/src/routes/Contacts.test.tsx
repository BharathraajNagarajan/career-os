import { fireEvent, screen, waitFor } from "@testing-library/react";

import type { ContactSummary } from "../api/contacts";
import { jsonResponse, mockApi, renderPage } from "../test-utils";
import type { RecordedCall } from "../test-utils";
import { Contacts } from "./Contacts";
import { contactDetail, contactSummary } from "./relationshipFixtures";

function serve(rows: ContactSummary[], create?: (call: RecordedCall) => Response | undefined) {
  return mockApi((call) => {
    if (call.method === "GET" && call.url.startsWith("/api/v1/contacts")) {
      return jsonResponse(rows);
    }
    if (call.method === "POST" && call.url === "/api/v1/contacts") {
      return create?.(call);
    }
    return undefined;
  });
}

describe("Contacts", () => {
  it("lists contacts with a link, headline and addresses", async () => {
    serve([contactSummary()]);

    renderPage(<Contacts />);

    const link = await screen.findByRole("link", { name: "Alex Example" });
    expect(link).toHaveAttribute("href", "/contacts/contact-1");
    expect(screen.getByText(/Recruiter/)).toBeInTheDocument();
    expect(screen.getByText(/alex@example.test/)).toBeInTheDocument();
  });

  it("searches by the typed text", async () => {
    const calls = serve([contactSummary()]);
    renderPage(<Contacts />);
    await screen.findByRole("link", { name: "Alex Example" });

    fireEvent.change(screen.getByLabelText("Search by name or email"), {
      target: { value: "alex" },
    });

    await waitFor(() => {
      expect(calls.some((call) => call.url === "/api/v1/contacts?q=alex")).toBe(true);
    });
  });

  it("creates a contact from a name and split addresses, then confirms", async () => {
    const calls = serve([], () => jsonResponse(contactDetail(), 201));
    renderPage(<Contacts />);

    fireEvent.change(await screen.findByLabelText("Full name"), {
      target: { value: "  Sam Example " },
    });
    fireEvent.change(screen.getByLabelText(/Email addresses/), {
      target: { value: "sam@example.test, second@example.test" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add contact" }));

    expect(await screen.findByText("Contact added.")).toBeInTheDocument();
    const post = calls.find((call) => call.method === "POST");
    expect(JSON.parse(post?.body as string)).toEqual({
      full_name: "Sam Example",
      emails: ["sam@example.test", "second@example.test"],
      linkedin_url: null,
      headline: null,
      notes: "",
    });
    expect(screen.getByLabelText(/Email addresses/)).toHaveValue(
      "sam@example.test, second@example.test",
    );
  });

  it("explains a taken address", async () => {
    serve([], () => jsonResponse({ error: { code: "contact_email_taken" } }, 409));
    renderPage(<Contacts />);

    fireEvent.change(await screen.findByLabelText("Full name"), { target: { value: "Sam" } });
    fireEvent.click(screen.getByRole("button", { name: "Add contact" }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "Another contact already has one of those email addresses.",
    );
  });

  it("renders hostile names as plain text", async () => {
    const hostile = '<img src=x onerror="alert(1)">';
    serve([contactSummary({ full_name: hostile, headline: hostile })]);

    const { container } = renderPage(<Contacts />);

    await screen.findByRole("link", { name: hostile });
    expect(container.querySelector("img")).toBeNull();
  });
});
