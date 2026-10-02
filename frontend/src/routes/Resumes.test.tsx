import { act, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { vi } from "vitest";

import type { Lane, Resume } from "../api/resumes";
import { jsonResponse, mockApi, renderPage } from "../test-utils";
import type { RecordedCall } from "../test-utils";
import { MAX_POLLS, POLL_INTERVAL_MS, Resumes } from "./Resumes";

const LANE: Lane = {
  id: "lane-1",
  name: "Platform",
  description: "",
  emphasis_notes: "",
  target_role_labels: [],
  default_resume_id: null,
  status: "active",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function resume(overrides: Partial<Resume> = {}): Resume {
  return {
    id: "resume-1",
    label: "Sample resume",
    status: "active",
    archived: false,
    lane_id: null,
    original_filename: "sample.pdf",
    mime_type: "application/pdf",
    byte_size: 1000,
    extraction_status: "succeeded",
    extraction_error_code: null,
    created_at: "2026-01-01T00:00:00Z",
    archived_at: null,
    ...overrides,
  };
}

function serve(resumes: () => Resume[], extra?: (call: RecordedCall) => Response | undefined) {
  return mockApi((call) => {
    const custom = extra?.(call);
    if (custom) {
      return custom;
    }
    if (call.url === "/api/v1/resumes" && call.method === "GET") {
      return jsonResponse(resumes());
    }
    if (call.url === "/api/v1/lanes") {
      return jsonResponse([LANE]);
    }
    return undefined;
  });
}

describe("Resumes", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("lists resumes with plain-language extraction status and a download link", async () => {
    serve(() => [
      resume(),
      resume({ id: "r2", label: "Pending one", extraction_status: "pending" }),
      resume({
        id: "r3",
        label: "Broken one",
        extraction_status: "failed",
        extraction_error_code: "encrypted",
      }),
    ]);

    renderPage(<Resumes />);

    expect(await screen.findByText("Sample resume")).toBeInTheDocument();
    expect(screen.getByText("Ready")).toBeInTheDocument();
    expect(screen.getByText("Processing…")).toBeInTheDocument();
    expect(screen.getByText("This PDF is password protected.")).toBeInTheDocument();
    const links = screen.getAllByRole("link", { name: "Download" });
    expect(links.map((link) => link.getAttribute("href"))).toEqual([
      "/api/v1/resumes/resume-1/file",
      "/api/v1/resumes/r2/file",
      "/api/v1/resumes/r3/file",
    ]);
  });

  it("never offers to edit, replace or re-upload a resume file", async () => {
    serve(() => [resume(), resume({ id: "r2", label: "Another", archived: true, status: "archived" })]);

    renderPage(<Resumes />);
    await screen.findByText("Sample resume");

    const forbidden = /edit|replace|overwrite|modify|re-?upload|update file|change file/i;
    const items = screen.getAllByRole("listitem");
    expect(items).toHaveLength(2);
    for (const item of items) {
      const actions = [
        ...within(item).queryAllByRole("button"),
        ...within(item).queryAllByRole("link"),
      ].map((element) => element.textContent);
      expect(actions.filter((name) => forbidden.test(name))).toEqual([]);
      expect(item.querySelector("input[type='file']")).toBeNull();
    }
    expect(within(items[0] as HTMLElement).getAllByRole("button").map((b) => b.textContent)).toEqual([
      "Rename",
      "Archive",
    ]);
    expect(
      within(items[1] as HTMLElement).getAllByRole("button").map((b) => b.textContent),
    ).toEqual(["Rename", "Unarchive"]);
    expect(document.querySelectorAll("input[type='file']")).toHaveLength(1);
    expect(screen.queryByRole("button", { name: forbidden })).toBeNull();
  });

  it("only accepts PDF and DOCX in the file picker", async () => {
    serve(() => []);

    renderPage(<Resumes />);

    expect(await screen.findByText("No resumes yet.")).toBeInTheDocument();
    expect(screen.getByLabelText(/Resume file/)).toHaveAttribute("accept", ".pdf,.docx");
  });

  it("uploads the chosen file as multipart form data", async () => {
    const calls = serve(() => [], (call) =>
      call.method === "POST" && call.url === "/api/v1/resumes"
        ? jsonResponse(resume({ extraction_status: "pending" }), 202)
        : undefined,
    );
    renderPage(<Resumes />);
    await screen.findByText("No resumes yet.");

    const file = new File(["%PDF-1.4"], "sample.pdf", { type: "application/pdf" });
    fireEvent.change(screen.getByLabelText(/Resume file/), { target: { files: [file] } });
    fireEvent.submit(screen.getByRole("form", { name: "Upload resume" }));

    await waitFor(() => {
      expect(calls.some((call) => call.method === "POST")).toBe(true);
    });
    const post = calls.find((call) => call.method === "POST");
    expect(post?.body).toBeInstanceOf(FormData);
    expect((post?.body as FormData).get("file")).toBeInstanceOf(File);
  });

  it("explains rejected uploads in plain language", async () => {
    serve(() => [], (call) =>
      call.method === "POST"
        ? jsonResponse({ error: { code: "duplicate_resume", resume_id: "x" } }, 409)
        : undefined,
    );
    renderPage(<Resumes />);
    await screen.findByText("No resumes yet.");

    const file = new File(["%PDF-1.4"], "sample.pdf");
    fireEvent.change(screen.getByLabelText(/Resume file/), { target: { files: [file] } });
    fireEvent.submit(screen.getByRole("form", { name: "Upload resume" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("already uploaded this exact file");
  });

  it("assigns a lane and renames only the label", async () => {
    const calls = serve(() => [resume()], (call) =>
      call.method === "PATCH" ? jsonResponse(resume()) : undefined,
    );
    renderPage(<Resumes />);
    await screen.findByText("Sample resume");

    fireEvent.change(screen.getByLabelText("Lane for Sample resume"), {
      target: { value: "lane-1" },
    });
    await waitFor(() => {
      expect(calls.filter((call) => call.method === "PATCH")).toHaveLength(1);
    });
    fireEvent.click(screen.getByRole("button", { name: "Rename" }));
    fireEvent.change(screen.getByLabelText("Label"), { target: { value: "Renamed" } });
    fireEvent.click(screen.getByRole("button", { name: "Save label" }));

    await waitFor(() => {
      expect(calls.filter((call) => call.method === "PATCH")).toHaveLength(2);
    });
    const bodies = calls
      .filter((call) => call.method === "PATCH")
      .map((call) => JSON.parse(call.body as string) as unknown);
    expect(bodies).toEqual([{ lane_id: "lane-1" }, { label: "Renamed" }]);
  });

  it("polls while a resume is pending and stops once it finishes", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "setInterval", "clearTimeout", "clearInterval"] });
    let reads = 0;
    const calls = serve(() => {
      reads += 1;
      return [resume({ extraction_status: reads < 3 ? "pending" : "succeeded" })];
    });
    renderPage(<Resumes />);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * 6);
    });

    expect(screen.getByText("Ready")).toBeInTheDocument();
    const resumeReads = calls.filter((call) => call.url === "/api/v1/resumes");
    expect(resumeReads).toHaveLength(3);
  });

  it("gives up polling after a bounded number of attempts", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "setInterval", "clearTimeout", "clearInterval"] });
    const calls = serve(() => [resume({ extraction_status: "pending" })]);
    renderPage(<Resumes />);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(POLL_INTERVAL_MS * (MAX_POLLS + 20));
    });

    const resumeReads = calls.filter((call) => call.url === "/api/v1/resumes");
    expect(resumeReads.length).toBeLessThanOrEqual(MAX_POLLS + 2);
    expect(resumeReads.length).toBeGreaterThan(5);
  });
});
