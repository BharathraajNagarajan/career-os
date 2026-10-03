import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, vi } from "vitest";

import type { Opportunity } from "../api/opportunities";
import { jsonResponse, mockApi, renderPage } from "../test-utils";
import type { RecordedCall } from "../test-utils";
import { MAX_POLLS, Opportunities, POLL_INTERVAL_MS } from "./Opportunities";
import { summary } from "./opportunityFixtures";

const LIST = "/api/v1/opportunities";
const INGEST = "/api/v1/opportunities/ingest";

function serve(
  list: () => Opportunity[],
  ingest?: (call: RecordedCall) => Response | undefined,
): RecordedCall[] {
  return mockApi((call) => {
    if (call.method === "GET" && call.url === LIST) {
      return jsonResponse(list());
    }
    if (call.method === "POST" && call.url === INGEST) {
      return ingest?.(call);
    }
    return undefined;
  });
}

afterEach(() => {
  vi.useRealTimers();
});

describe("Opportunities", () => {
  it("lists company, title, status, priority and extraction state", async () => {
    serve(() => [
      summary({ priority: "high" }),
      summary({
        id: "opp-2",
        company: null,
        title: null,
        extraction_status: "failed",
        extraction_error_code: "llm_budget_exhausted",
      }),
    ]);

    renderPage(<Opportunities />);

    const link = await screen.findByRole("link", { name: "Senior Widget Engineer" });
    expect(link).toHaveAttribute("href", "/opportunities/opp-1");
    expect(screen.getByText("Example Corp")).toBeInTheDocument();
    expect(screen.getByText("high")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Untitled posting" })).toHaveAttribute(
      "href",
      "/opportunities/opp-2",
    );
    expect(screen.getByText(/today's AI budget is used up/)).toBeInTheDocument();
  });

  it("pastes a job description with an optional source URL and clears the form", async () => {
    let rows: Opportunity[] = [];
    const calls = serve(
      () => rows,
      () => {
        rows = [summary({ extraction_status: "pending", title: null })];
        return jsonResponse(rows[0], 202);
      },
    );
    renderPage(<Opportunities />);
    await screen.findByText("No opportunities yet.");

    fireEvent.change(screen.getByLabelText("Job description"), {
      target: { value: "Synthetic job description text" },
    });
    fireEvent.change(screen.getByLabelText(/Source URL/), {
      target: { value: " https://example.test/jobs/1 " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Add and extract" }));

    expect(await screen.findByText("Added. Extraction is running.")).toBeInTheDocument();
    const post = calls.find((call) => call.method === "POST");
    expect(JSON.parse(post?.body as string)).toEqual({
      jd_text: "Synthetic job description text",
      source_url: "https://example.test/jobs/1",
    });
    expect(screen.getByLabelText("Job description")).toHaveValue("");
    expect(await screen.findByText("Extracting fields from the job description…")).toBeInTheDocument();
  });

  it("sends no source URL when the field is blank", async () => {
    const calls = serve(
      () => [],
      () => jsonResponse(summary(), 202),
    );
    renderPage(<Opportunities />);
    await screen.findByText("No opportunities yet.");

    fireEvent.change(screen.getByLabelText("Job description"), { target: { value: "Some text" } });
    fireEvent.click(screen.getByRole("button", { name: "Add and extract" }));

    await waitFor(() => {
      expect(calls.some((call) => call.method === "POST")).toBe(true);
    });
    const post = calls.find((call) => call.method === "POST");
    expect(JSON.parse(post?.body as string)).toEqual({ jd_text: "Some text", source_url: null });
  });

  it("explains a duplicate paste and links to the existing posting", async () => {
    serve(
      () => [],
      () => jsonResponse({ error: { code: "duplicate_jd", opportunity_id: "opp-9" } }, 409),
    );
    renderPage(<Opportunities />);
    await screen.findByText("No opportunities yet.");

    fireEvent.change(screen.getByLabelText("Job description"), { target: { value: "Same text" } });
    fireEvent.click(screen.getByRole("button", { name: "Add and extract" }));

    expect(
      await screen.findByText(/You have already added this exact job description/),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open it" })).toHaveAttribute(
      "href",
      "/opportunities/opp-9",
    );
  });

  it("explains validation failures plainly", async () => {
    serve(
      () => [],
      () => jsonResponse({ error: { code: "jd_too_short" } }, 422),
    );
    renderPage(<Opportunities />);
    await screen.findByText("No opportunities yet.");

    fireEvent.change(screen.getByLabelText("Job description"), { target: { value: "x" } });
    fireEvent.click(screen.getByRole("button", { name: "Add and extract" }));

    expect(await screen.findByText(/too short to be a job description/)).toBeInTheDocument();
  });

  it("polls while an extraction is pending and stops once it finishes", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "setInterval", "clearTimeout", "clearInterval"] });
    let reads = 0;
    const calls = serve(() => {
      reads += 1;
      return [summary({ extraction_status: reads < 3 ? "pending" : "succeeded" })];
    });
    renderPage(<Opportunities />);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 6);
    });

    expect(screen.getByText("Extraction finished.")).toBeInTheDocument();
    expect(calls.filter((call) => call.url === LIST)).toHaveLength(3);
  });

  it("gives up polling after a bounded number of attempts", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "setInterval", "clearTimeout", "clearInterval"] });
    const calls = serve(() => [summary({ extraction_status: "pending" })]);
    renderPage(<Opportunities />);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * (MAX_POLLS + 20));
    });

    const reads = calls.filter((call) => call.url === LIST);
    expect(reads.length).toBeLessThanOrEqual(MAX_POLLS + 2);
    expect(reads.length).toBeGreaterThan(5);
  });

  it("renders hostile titles and company names as plain text", async () => {
    const hostile = '<img src=x onerror="alert(1)"><script>alert(2)</script>';
    serve(() => [
      summary({
        title: hostile,
        company: { id: "c", name: hostile, strategic_priority: "normal" },
      }),
    ]);

    const { container } = renderPage(<Opportunities />);

    await screen.findByRole("link", { name: hostile });
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
  });
});
