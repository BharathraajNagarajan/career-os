import { fireEvent, screen, waitFor } from "@testing-library/react";

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
