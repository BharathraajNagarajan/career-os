import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, vi } from "vitest";

import type { DuplicateMatch, OpportunityDetail as Detail } from "../api/opportunities";
import { jsonResponse, mockApi, renderPage } from "../test-utils";
import type { RecordedCall } from "../test-utils";
import { MAX_POLLS, OpportunityDetail, POLL_INTERVAL_MS } from "./OpportunityDetail";
import { company, detail, qualification, summary } from "./opportunityFixtures";

const BASE = "/api/v1/opportunities/opp-1";
const ROUTE = { path: "/opportunities/:opportunityId", entry: "/opportunities/opp-1" };

interface Server {
  calls: RecordedCall[];
  current: Detail;
  duplicates: DuplicateMatch[];
}

type Mutation = (call: RecordedCall, server: Server) => Response | undefined;

function serve(initial: Detail, mutate?: Mutation, duplicates: DuplicateMatch[] = []): Server {
  const server: Server = { calls: [], current: initial, duplicates };
  server.calls = mockApi((call) => {
    if (call.method === "GET" && call.url === BASE) {
      return jsonResponse(server.current);
    }
    if (call.method === "GET" && call.url === `${BASE}/duplicates`) {
      return jsonResponse(server.duplicates);
    }
    if (call.method === "GET" && call.url === `${BASE}/timeline`) {
      return jsonResponse([]);
    }
    if (call.method === "GET" && call.url.startsWith("/api/v1/applications")) {
      return jsonResponse([]);
    }
    if (call.method === "GET" && call.url === "/api/v1/companies") {
      return jsonResponse([company(), company({ id: "company-2", name: "Other Corp" })]);
    }
    return mutate?.(call, server);
  });
  return server;
}

function writes(server: Server, method: string): RecordedCall[] {
  return server.calls.filter((call) => call.method === method);
}

function bodyOf(call: RecordedCall | undefined): unknown {
  return JSON.parse(call?.body as string);
}

afterEach(() => {
  vi.useRealTimers();
});

describe("OpportunityDetail", () => {
  it("shows the posting, its fields and the pasted text", async () => {
    serve(detail({ source_url: "https://example.test/jobs/1" }));

    renderPage(<OpportunityDetail />, ROUTE);

    expect(await screen.findByRole("heading", { name: "Senior Widget Engineer" })).toBeInTheDocument();
    expect(screen.getByLabelText("Title")).toHaveValue("Senior Widget Engineer");
    expect(screen.getByLabelText("Team")).toHaveValue("Platform");
    expect(screen.getByLabelText("Job ID")).toHaveValue("EX-1001");
    expect(screen.getByLabelText("Location")).toHaveValue("Springfield, IL");
    expect(screen.getByLabelText("Workplace type")).toHaveValue("hybrid");
    expect(screen.getByLabelText("City 1")).toHaveValue("Springfield");
    expect(screen.getByLabelText("Country code 1")).toHaveValue("US");
    expect(screen.getByText("Extraction finished.")).toBeInTheDocument();
    expect(screen.getByText(/Example Corp is hiring\./)).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByRole("option", { name: "Other Corp" })).toBeInTheDocument();
    });
    expect(screen.getByLabelText("Company")).toHaveValue("company-1");
  });

  it("renders hostile posting content as plain text and never as links or markup", async () => {
    const hostile = '<img src=x onerror="alert(1)"><script>alert(2)</script>';
    const evilUrl = "javascript:alert(document.cookie)";
    serve(
      detail({
        title: hostile,
        jd_text: `${hostile}\n<a href="https://evil.test">click</a>`,
        source_url: evilUrl,
        qualifications: [qualification({ text_verbatim: hostile })],
      }),
    );

    const { container } = renderPage(<OpportunityDetail />, ROUTE);

    await screen.findByRole("heading", { name: hostile });
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("pre")?.textContent).toBe(
      `${hostile}\n<a href="https://evil.test">click</a>`,
    );
    expect(container.querySelector('a[href*="evil"]')).toBeNull();
    expect(screen.getByText(evilUrl)).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: evilUrl })).toBeNull();
    expect(screen.getByText(hostile, { selector: "td" })).toBeInTheDocument();
  });

  it("saves edited fields with the version it saw and shows the saved result", async () => {
    const server = serve(detail(), (call, state) => {
      if (call.method === "PATCH" && call.url === BASE) {
        state.current = detail({ title: "New title", state_version: 3 });
        return jsonResponse(state.current);
      }
      return undefined;
    });
    renderPage(<OpportunityDetail />, ROUTE);

    fireEvent.change(await screen.findByLabelText("Title"), { target: { value: " New title " } });
    fireEvent.change(screen.getByLabelText("Workplace type"), { target: { value: "remote" } });
    fireEvent.change(screen.getByLabelText("Team"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    expect(await screen.findByRole("heading", { name: "New title" })).toBeInTheDocument();
    expect(bodyOf(writes(server, "PATCH")[0])).toEqual({
      expected_state_version: 2,
      title: "New title",
      team: null,
      external_job_id: "EX-1001",
      location_text: "Springfield, IL",
      locations: {
        schema_version: 1,
        items: [{ city: "Springfield", region: "IL", country: "US" }],
      },
      workplace_type: "remote",
      company_id: "company-1",
      source_url: null,
    });
  });

  it("edits the places and the company", async () => {
    const server = serve(detail(), () => jsonResponse(detail({ state_version: 3 })));
    renderPage(<OpportunityDetail />, ROUTE);
    await screen.findByRole("option", { name: "Other Corp" });

    fireEvent.change(screen.getByLabelText("City 1"), { target: { value: "Shelbyville" } });
    fireEvent.click(screen.getByRole("button", { name: "Add place" }));
    fireEvent.change(screen.getByLabelText("City 2"), { target: { value: "Capital City" } });
    fireEvent.change(screen.getByLabelText("Country code 2"), { target: { value: "ca" } });
    fireEvent.change(screen.getByLabelText("Company"), { target: { value: "company-2" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => {
      expect(writes(server, "PATCH")).toHaveLength(1);
    });
    const body = bodyOf(writes(server, "PATCH")[0]) as Record<string, unknown>;
    expect(body["locations"]).toEqual({
      schema_version: 1,
      items: [
        { city: "Shelbyville", region: "IL", country: "US" },
        { city: "Capital City", region: null, country: "ca" },
      ],
    });
    expect(body["company_id"]).toBe("company-2");
  });

  it("explains a stale version, refreshes, and shows the latest values", async () => {
    const server = serve(detail(), (call) => {
      if (call.method === "PATCH" && call.url === BASE) {
        server.current = detail({ title: "Changed elsewhere", state_version: 5 });
        return jsonResponse({ error: { code: "conflict" } }, 409);
      }
      return undefined;
    });
    renderPage(<OpportunityDetail />, ROUTE);

    fireEvent.change(await screen.findByLabelText("Title"), { target: { value: "My edit" } });
    fireEvent.click(screen.getByRole("button", { name: "Save changes" }));

    expect(await screen.findByText(/changed since you opened it/)).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByLabelText("Title")).toHaveValue("Changed elsewhere");
    });
    expect(server.calls.filter((call) => call.url === BASE && call.method === "GET").length).toBe(2);
  });

  it("explains a job ID that another posting already uses", async () => {
    serve(detail(), () => jsonResponse({ error: { code: "duplicate_job_id" } }, 409));
    renderPage(<OpportunityDetail />, ROUTE);

    fireEvent.click(await screen.findByRole("button", { name: "Save changes" }));

    expect(
      await screen.findByText("Another posting at this company already has that job ID."),
    ).toBeInTheDocument();
  });

  it("changes the priority without touching the other fields", async () => {
    const server = serve(detail(), (call) => {
      if (call.method === "PATCH" && call.url === `${BASE}/priority`) {
        return jsonResponse(detail({ priority: "high", state_version: 3 }));
      }
      return undefined;
    });
    renderPage(<OpportunityDetail />, ROUTE);

    fireEvent.change(await screen.findByLabelText("Priority"), { target: { value: "high" } });

    await waitFor(() => {
      expect(screen.getByLabelText("Priority")).toHaveValue("high");
    });
    expect(bodyOf(writes(server, "PATCH")[0])).toEqual({ priority: "high" });
    expect(writes(server, "PATCH")[0]?.url).toBe(`${BASE}/priority`);
  });

  it("offers a retry only when extraction failed and explains the reason", async () => {
    const server = serve(
      detail({ extraction_status: "failed", extraction_error_code: "llm_budget_exhausted" }),
      (call, state) => {
        if (call.method === "POST" && call.url === `${BASE}/extract`) {
          state.current = detail({ extraction_status: "pending", extraction_error_code: null });
          return jsonResponse(state.current, 202);
        }
        return undefined;
      },
    );
    renderPage(<OpportunityDetail />, ROUTE);

    expect(await screen.findByText(/today's AI budget is used up/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Retry extraction" }));

    expect(
      await screen.findByText("Extracting fields from the job description…"),
    ).toBeInTheDocument();
    expect(writes(server, "POST")[0]?.url).toBe(`${BASE}/extract`);
    expect(screen.queryByRole("button", { name: "Retry extraction" })).toBeNull();
  });

  it.each([
    ["succeeded", null],
    ["pending", null],
  ] as const)("hides the retry button while extraction is %s", async (status, code) => {
    serve(detail({ extraction_status: status, extraction_error_code: code }));

    renderPage(<OpportunityDetail />, ROUTE);

    await screen.findByRole("heading", { name: "Senior Widget Engineer" });
    expect(screen.queryByRole("button", { name: "Retry extraction" })).toBeNull();
  });

  it.each([
    ["llm_output_invalid", /could not be validated/],
    ["llm_provider_error", /model service had a problem/],
    ["something_else", /Extraction failed, so nothing was filled in/],
  ])("shows a plain message for %s", async (code, expected) => {
    serve(detail({ extraction_status: "failed", extraction_error_code: code }));

    renderPage(<OpportunityDetail />, ROUTE);

    expect(await screen.findByText(expected)).toBeInTheDocument();
  });

  it("polls while extraction is pending and shows the result", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "setInterval", "clearTimeout", "clearInterval"] });
    let reads = 0;
    const server = serve(detail({ extraction_status: "pending" }));
    server.calls = mockApi((call) => {
      if (call.method === "GET" && call.url === BASE) {
        reads += 1;
        return jsonResponse(
          detail({ extraction_status: reads < 3 ? "pending" : "succeeded", title: "Extracted" }),
        );
      }
      if (call.url === `${BASE}/duplicates`) {
        return jsonResponse([]);
      }
      if (call.url === "/api/v1/companies") {
        return jsonResponse([]);
      }
      return undefined;
    });
    renderPage(<OpportunityDetail />, ROUTE);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 6);
    });

    expect(screen.getByRole("heading", { name: "Extracted" })).toBeInTheDocument();
    expect(screen.getByText("Extraction finished.")).toBeInTheDocument();
    expect(reads).toBe(3);
  });

  it("gives up polling after a bounded number of attempts", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "setInterval", "clearTimeout", "clearInterval"] });
    const server = serve(detail({ extraction_status: "pending" }));

    renderPage(<OpportunityDetail />, ROUTE);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * (MAX_POLLS + 20));
    });

    const reads = server.calls.filter((call) => call.url === BASE);
    expect(reads.length).toBeLessThanOrEqual(MAX_POLLS + 2);
    expect(reads.length).toBeGreaterThan(5);
  });

  it("shows the original wording read-only and saves the normalized fields", async () => {
    const server = serve(detail(), (call) => {
      if (call.method === "PATCH" && call.url === "/api/v1/qualifications/qual-1") {
        return jsonResponse(qualification({ kind: "preferred" }));
      }
      return undefined;
    });
    renderPage(<OpportunityDetail />, ROUTE);

    const wording = await screen.findByText("Proficiency in Python and SQL", { selector: "td" });
    expect(wording).toBeInTheDocument();
    expect(screen.queryByDisplayValue("Proficiency in Python and SQL")).toBeNull();
    fireEvent.change(screen.getByLabelText("Kind 1"), { target: { value: "preferred" } });
    fireEvent.change(screen.getByLabelText("Skills 1"), { target: { value: "python, go, , " } });
    fireEvent.change(screen.getByLabelText("Minimum years 1"), { target: { value: "3" } });
    fireEvent.click(screen.getByLabelText("Hard constraint 1"));
    fireEvent.click(screen.getByRole("button", { name: "Save requirement 1" }));

    await waitFor(() => {
      expect(writes(server, "PATCH")).toHaveLength(1);
    });
    expect(bodyOf(writes(server, "PATCH")[0])).toEqual({
      kind: "preferred",
      category: "skill",
      skill_keys: ["python", "go"],
      min_years: 3,
      is_hard_constraint: true,
    });
  });

  it("adds a requirement of your own and clears the form", async () => {
    const server = serve(detail(), (call) => {
      if (call.method === "POST" && call.url === `${BASE}/qualifications`) {
        return jsonResponse(qualification({ id: "qual-2", origin: "user" }), 201);
      }
      return undefined;
    });
    renderPage(<OpportunityDetail />, ROUTE);

    fireEvent.change(await screen.findByLabelText("Requirement text"), {
      target: { value: "Comfortable with on-call" },
    });
    fireEvent.change(screen.getByLabelText("New category"), { target: { value: "other" } });
    fireEvent.click(screen.getByRole("button", { name: "Add requirement" }));

    await waitFor(() => {
      expect(screen.getByLabelText("Requirement text")).toHaveValue("");
    });
    expect(bodyOf(writes(server, "POST")[0])).toEqual({
      kind: "minimum",
      category: "other",
      text_verbatim: "Comfortable with on-call",
      skill_keys: [],
      min_years: null,
      is_hard_constraint: false,
    });
  });

  it("deletes a requirement", async () => {
    const server = serve(detail(), (call) => {
      if (call.method === "DELETE") {
        return new Response(null, { status: 204 });
      }
      return undefined;
    });
    renderPage(<OpportunityDetail />, ROUTE);

    fireEvent.click(await screen.findByRole("button", { name: "Delete requirement 1" }));

    await waitFor(() => {
      expect(writes(server, "DELETE")).toHaveLength(1);
    });
    expect(writes(server, "DELETE")[0]?.url).toBe("/api/v1/qualifications/qual-1");
  });

  it("lists possible duplicates with the reason, or says there are none", async () => {
    serve(detail(), undefined, [
      {
        opportunity: summary({ id: "opp-2", title: "Senior Widget Engineer II" }),
        reason: "similar_title",
        similarity: 0.95,
      },
    ]);

    renderPage(<OpportunityDetail />, ROUTE);

    const link = await screen.findByRole("link", { name: "Senior Widget Engineer II" });
    expect(link).toHaveAttribute("href", "/opportunities/opp-2");
    expect(screen.getByText(/Similar title at Example Corp/)).toBeInTheDocument();
  });

  it("says when there are no likely duplicates", async () => {
    serve(detail());

    renderPage(<OpportunityDetail />, ROUTE);

    expect(await screen.findByText("No likely duplicates.")).toBeInTheDocument();
  });

  it("reports a posting that cannot be loaded", async () => {
    mockApi(() => jsonResponse({ error: { code: "not_found" } }, 404));

    renderPage(<OpportunityDetail />, ROUTE);

    expect(await screen.findByText("Could not load this posting.")).toBeInTheDocument();
  });
});
