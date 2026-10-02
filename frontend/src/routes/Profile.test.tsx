import { fireEvent, screen, waitFor } from "@testing-library/react";

import type { Profile as ProfileData } from "../api/profile";
import { jsonResponse, mockApi, renderPage } from "../test-utils";
import { Profile } from "./Profile";

const EMPTY: ProfileData = {
  headline: null,
  summary: null,
  current_location: null,
  relocation_preference: "unspecified",
  remote_preference: "no_preference",
  work_authorization: [],
  target_roles: [],
  communication_preferences: { tone: "", length: "", sign_off: "", avoid: [] },
  constraints_updated_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
};

function serve(profile: ProfileData = EMPTY) {
  return mockApi((call) => {
    if (call.url === "/api/v1/profile" && call.method === "GET") {
      return jsonResponse(profile);
    }
    if (call.url === "/api/v1/profile" && call.method === "PUT") {
      return jsonResponse(profile);
    }
    return undefined;
  });
}

describe("Profile", () => {
  it("starts empty with no career defaults", async () => {
    serve();

    renderPage(<Profile />);

    expect(await screen.findByLabelText("Headline")).toHaveValue("");
    expect(screen.queryByLabelText("Role name")).toBeNull();
    expect(screen.queryByLabelText("Country code")).toBeNull();
  });

  it("saves the profile with repeatable work authorization and role rows", async () => {
    const calls = serve();
    renderPage(<Profile />);
    fireEvent.change(await screen.findByLabelText("Headline"), {
      target: { value: "Synthetic Engineer" },
    });
    fireEvent.change(screen.getByLabelText("Relocation"), { target: { value: "open" } });
    fireEvent.click(screen.getByRole("button", { name: "Add authorization" }));
    fireEvent.change(screen.getByLabelText("Country code"), { target: { value: "US" } });
    fireEvent.change(screen.getByLabelText("Status"), { target: { value: "Sample status" } });
    fireEvent.change(screen.getByLabelText("Sponsorship needed"), { target: { value: "no" } });
    fireEvent.click(screen.getByRole("button", { name: "Add role" }));
    fireEvent.change(screen.getByLabelText("Role name"), { target: { value: "Platform Engineer" } });
    fireEvent.change(screen.getByLabelText("Priority"), { target: { value: "high" } });
    fireEvent.change(screen.getByLabelText(/Things to avoid/), {
      target: { value: "jargon\n\nfluff" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save profile" }));

    await waitFor(() => {
      expect(calls.some((call) => call.method === "PUT")).toBe(true);
    });
    const body = JSON.parse(calls.find((call) => call.method === "PUT")?.body as string) as Record<
      string,
      unknown
    >;
    expect(body).toMatchObject({
      headline: "Synthetic Engineer",
      relocation_preference: "open",
      work_authorization: [{ country: "US", status: "Sample status", sponsorship_needed: false }],
      target_roles: [{ name: "Platform Engineer", priority: "high", notes: "" }],
      communication_preferences: { avoid: ["jargon", "fluff"] },
    });
    expect(await screen.findByRole("status")).toHaveTextContent("Saved.");
  });

  it("removes rows", async () => {
    serve({
      ...EMPTY,
      target_roles: [{ name: "Role A", priority: "normal", notes: "" }],
      work_authorization: [{ country: "CA", status: "Sample", sponsorship_needed: null }],
    });
    renderPage(<Profile />);
    await screen.findByDisplayValue("Role A");

    fireEvent.click(screen.getByRole("button", { name: "Remove role" }));
    fireEvent.click(screen.getByRole("button", { name: "Remove authorization" }));

    expect(screen.queryByDisplayValue("Role A")).toBeNull();
    expect(screen.queryByLabelText("Country code")).toBeNull();
  });

  it("reports save failures", async () => {
    mockApi((call) =>
      call.method === "PUT"
        ? jsonResponse({ detail: [] }, 422)
        : jsonResponse(EMPTY),
    );
    renderPage(<Profile />);
    fireEvent.click(await screen.findByRole("button", { name: "Save profile" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not save the profile");
  });
});
