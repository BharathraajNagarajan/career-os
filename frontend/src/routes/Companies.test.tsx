import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { Company } from "../api/companies";
import { jsonResponse, mockApi, renderPage } from "../test-utils";
import type { RecordedCall } from "../test-utils";
import { Companies } from "./Companies";
import { company } from "./opportunityFixtures";

function serve(rows: Company[], patch?: (call: RecordedCall) => Response | undefined) {
  return mockApi((call) => {
    if (call.method === "GET" && call.url === "/api/v1/companies") {
      return jsonResponse(rows);
    }
    if (call.method === "PATCH") {
      return patch?.(call);
    }
    return undefined;
  });
}

function patches(calls: RecordedCall[]): RecordedCall[] {
  return calls.filter((call) => call.method === "PATCH");
}

describe("Companies", () => {
  it("lists companies with their editable fields", async () => {
    serve([company()]);

    renderPage(<Companies />);

    const form = await screen.findByRole("form", { name: "Edit Example Corp" });
    expect(within(form).getByLabelText("Name")).toHaveValue("Example Corp");
    expect(within(form).getByLabelText("Strategic priority")).toHaveValue("normal");
    expect(within(form).getByLabelText(/Aliases/)).toHaveValue("Example Co");
    expect(within(form).getByLabelText(/Domains/)).toHaveValue("example.test");
    expect(within(form).getByLabelText("Careers URL")).toHaveValue("https://example.test/careers");
    expect(within(form).getByLabelText("Notes")).toHaveValue("A synthetic note");
    expect(screen.getByText(/added by extraction/)).toBeInTheDocument();
  });

  it("saves a new strategic priority along with the other fields", async () => {
    const calls = serve([company()], () => jsonResponse(company({ strategic_priority: "high" })));
    renderPage(<Companies />);

    fireEvent.change(await screen.findByLabelText("Strategic priority"), {
      target: { value: "high" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save company" }));

    expect(await screen.findByText("Saved.")).toBeInTheDocument();
    const [call] = patches(calls);
    expect(call?.url).toBe("/api/v1/companies/company-1");
    expect(JSON.parse(call?.body as string)).toEqual({
      name: "Example Corp",
      aliases: ["Example Co"],
      domains: ["example.test"],
      careers_url: "https://example.test/careers",
      notes: "A synthetic note",
      strategic_priority: "high",
    });
  });

  it("sends edited aliases, domains and a cleared careers URL", async () => {
    const calls = serve([company()], () => jsonResponse(company()));
    renderPage(<Companies />);

    fireEvent.change(await screen.findByLabelText(/Aliases/), {
      target: { value: "Ex\n\nExample Group" },
    });
    fireEvent.change(screen.getByLabelText(/Domains/), {
      target: { value: "example.test, example.org" },
    });
    fireEvent.change(screen.getByLabelText("Careers URL"), { target: { value: "  " } });
    fireEvent.click(screen.getByRole("button", { name: "Save company" }));

    await waitFor(() => {
      expect(patches(calls)).toHaveLength(1);
    });
    const body = JSON.parse(patches(calls)[0]?.body as string) as Record<string, unknown>;
    expect(body["aliases"]).toEqual(["Ex", "Example Group"]);
    expect(body["domains"]).toEqual(["example.test", "example.org"]);
    expect(body["careers_url"]).toBeNull();
  });

  it("explains a name that is already taken", async () => {
    serve([company()], () => jsonResponse({ error: { code: "company_name_taken" } }, 409));
    renderPage(<Companies />);

    fireEvent.change(await screen.findByLabelText("Name"), { target: { value: "Other Inc" } });
    fireEvent.click(screen.getByRole("button", { name: "Save company" }));

    expect(await screen.findByText("You already have a company with that name.")).toBeInTheDocument();
  });

  it("renders hostile company text as plain text", async () => {
    const hostile = '<img src=x onerror="alert(1)">';
    serve([company({ name: hostile, notes: hostile })]);

    const { container } = renderPage(<Companies />);

    await screen.findByRole("heading", { name: hostile });
    expect(container.querySelector("img")).toBeNull();
  });

  it("says when there are no companies", async () => {
    serve([]);

    renderPage(<Companies />);

    expect(await screen.findByText("No companies yet.")).toBeInTheDocument();
  });
});
