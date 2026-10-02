import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { Lane, Resume } from "../api/resumes";
import { jsonResponse, mockApi, renderPage } from "../test-utils";
import { Lanes } from "./Lanes";

const LANE: Lane = {
  id: "lane-1",
  name: "Platform",
  description: "Infrastructure roles",
  emphasis_notes: "Lead with reliability",
  target_role_labels: ["Platform Engineer"],
  default_resume_id: null,
  status: "active",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function resume(id: string, label: string, overrides: Partial<Resume> = {}): Resume {
  return {
    id,
    label,
    status: "active",
    archived: false,
    lane_id: "lane-1",
    original_filename: `${id}.pdf`,
    mime_type: "application/pdf",
    byte_size: 10,
    extraction_status: "succeeded",
    extraction_error_code: null,
    created_at: "2026-01-01T00:00:00Z",
    archived_at: null,
    ...overrides,
  };
}

const RESUMES: Resume[] = [
  resume("r1", "In lane"),
  resume("r2", "Archived in lane", { status: "archived", archived: true }),
  resume("r3", "Elsewhere", { lane_id: "lane-2" }),
  resume("r4", "Unassigned", { lane_id: null }),
];

function serve(lane: Lane = LANE) {
  return mockApi((call) => {
    if (call.url === "/api/v1/lanes" && call.method === "GET") {
      return jsonResponse([lane]);
    }
    if (call.url === "/api/v1/resumes") {
      return jsonResponse(RESUMES);
    }
    if (call.method === "PATCH" || call.method === "POST") {
      return jsonResponse(lane, call.method === "POST" && call.url === "/api/v1/lanes" ? 201 : 200);
    }
    return undefined;
  });
}

describe("Lanes", () => {
  it("lists lanes with their details", async () => {
    serve();

    renderPage(<Lanes />);

    expect(await screen.findByRole("heading", { name: "Platform" })).toBeInTheDocument();
    expect(screen.getByText("Infrastructure roles")).toBeInTheDocument();
    expect(screen.getByText("Roles: Platform Engineer")).toBeInTheDocument();
  });

  it("offers only the lane's own active resumes as a default", async () => {
    serve();

    renderPage(<Lanes />);
    const select = await screen.findByLabelText("Default resume for Platform");

    const options = within(select).getAllByRole("option").map((option) => option.textContent);
    expect(options).toEqual(["No default", "In lane"]);
  });

  it("saves the chosen default resume", async () => {
    const calls = serve();
    renderPage(<Lanes />);
    const select = await screen.findByLabelText("Default resume for Platform");
    await within(select).findByRole("option", { name: "In lane" });

    fireEvent.change(select, { target: { value: "r1" } });

    await waitFor(() => {
      expect(calls.some((call) => call.method === "PATCH")).toBe(true);
    });
    const patch = calls.find((call) => call.method === "PATCH");
    expect(patch?.url).toBe("/api/v1/lanes/lane-1");
    expect(JSON.parse(patch?.body as string)).toEqual({ default_resume_id: "r1" });
  });

  it("creates a lane from the form", async () => {
    const calls = serve();
    renderPage(<Lanes />);
    await screen.findByRole("heading", { name: "Platform" });

    fireEvent.change(screen.getAllByLabelText("Lane name")[0] as HTMLElement, {
      target: { value: "Data" },
    });
    fireEvent.change(screen.getAllByLabelText(/Target role labels/)[0] as HTMLElement, {
      target: { value: "Data Engineer, Analyst" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Create lane" }));

    await waitFor(() => {
      expect(calls.some((call) => call.method === "POST")).toBe(true);
    });
    const post = calls.find((call) => call.method === "POST");
    expect(JSON.parse(post?.body as string)).toEqual({
      name: "Data",
      description: "",
      emphasis_notes: "",
      target_role_labels: ["Data Engineer", "Analyst"],
    });
  });

  it("edits a lane", async () => {
    const calls = serve();
    renderPage(<Lanes />);
    await screen.findByRole("heading", { name: "Platform" });

    fireEvent.click(screen.getByRole("button", { name: "Edit lane" }));
    const name = screen.getAllByLabelText("Lane name")[1] as HTMLElement;
    fireEvent.change(name, { target: { value: "Platform v2" } });
    fireEvent.click(screen.getByRole("button", { name: "Save lane" }));

    await waitFor(() => {
      expect(calls.some((call) => call.method === "PATCH")).toBe(true);
    });
    const body = JSON.parse(calls.find((call) => call.method === "PATCH")?.body as string) as {
      name: string;
    };
    expect(body.name).toBe("Platform v2");
  });

  it("archives and unarchives", async () => {
    const calls = serve();
    renderPage(<Lanes />);
    fireEvent.click(await screen.findByRole("button", { name: "Archive lane" }));

    await waitFor(() => {
      expect(calls.some((call) => call.url === "/api/v1/lanes/lane-1/archive")).toBe(true);
    });
  });

  it("shows a plain message when the lane name is taken", async () => {
    mockApi((call) => {
      if (call.url === "/api/v1/lanes" && call.method === "GET") {
        return jsonResponse([]);
      }
      if (call.url === "/api/v1/resumes") {
        return jsonResponse([]);
      }
      return jsonResponse({ error: { code: "lane_name_taken" } }, 409);
    });
    renderPage(<Lanes />);
    await screen.findByText("No lanes yet.");

    fireEvent.change(screen.getByLabelText("Lane name"), { target: { value: "Platform" } });
    fireEvent.click(screen.getByRole("button", { name: "Create lane" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("already have an active lane");
  });
});
