import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { RecruitingAction } from "../api/actions";
import { jsonResponse, mockApi, renderPage } from "../test-utils";
import type { RecordedCall } from "../test-utils";
import { Actions } from "./Actions";
import { recruitingAction } from "./relationshipFixtures";

function serve(
  rows: RecruitingAction[],
  command?: (call: RecordedCall) => Response | undefined,
): RecordedCall[] {
  return mockApi((call) => {
    if (call.method === "GET" && call.url.startsWith("/api/v1/actions")) {
      return jsonResponse(rows);
    }
    return command?.(call);
  });
}

function writes(calls: RecordedCall[]): RecordedCall[] {
  return calls.filter((call) => call.method !== "GET");
}

describe("Actions", () => {
  it("asks for open actions first and switches filters", async () => {
    const calls = serve([recruitingAction()]);
    renderPage(<Actions />);

    expect(await screen.findByText("Follow up with Alex Example")).toBeInTheDocument();
    expect(calls[0]?.url).toBe("/api/v1/actions?status=open");

    fireEvent.click(screen.getByRole("button", { name: "Snoozed" }));
    await waitFor(() => {
      expect(calls.some((call) => call.url === "/api/v1/actions?status=snoozed")).toBe(true);
    });
    fireEvent.click(screen.getByRole("button", { name: "Done" }));
    await waitFor(() => {
      expect(
        calls.some(
          (call) => call.url === "/api/v1/actions?status=done&status=dismissed&status=superseded",
        ),
      ).toBe(true);
    });
  });

  it("offers only the buttons the server allows", async () => {
    serve([recruitingAction({ status: "snoozed", allowed_actions: ["complete", "dismiss"] })]);

    renderPage(<Actions />);

    await screen.findByRole("button", { name: "Complete" });
    expect(screen.getByRole("button", { name: "Dismiss" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Snooze" })).toBeNull();
  });

  it("completes an action with its state version", async () => {
    const calls = serve([recruitingAction({ state_version: 3 })], () =>
      jsonResponse(recruitingAction({ status: "done", state_version: 4, allowed_actions: [] })),
    );
    renderPage(<Actions />);

    fireEvent.click(await screen.findByRole("button", { name: "Complete" }));

    await waitFor(() => {
      expect(writes(calls)).toHaveLength(1);
    });
    const [call] = writes(calls);
    expect(call?.url).toBe("/api/v1/actions/action-1/complete");
    expect(JSON.parse(call?.body as string)).toEqual({ expected_state_version: 3 });
  });

  it("snoozes until the chosen date and time", async () => {
    const calls = serve([recruitingAction()], () =>
      jsonResponse(recruitingAction({ status: "snoozed" })),
    );
    renderPage(<Actions />);

    fireEvent.click(await screen.findByRole("button", { name: "Snooze" }));
    const form = screen.getByRole("form", { name: "Snooze Follow up with Alex Example" });
    expect(within(form).getByRole("button", { name: "Confirm snooze" })).toBeDisabled();
    fireEvent.change(within(form).getByLabelText("Snooze until"), {
      target: { value: "2099-01-01T09:30" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Confirm snooze" }));

    await waitFor(() => {
      expect(writes(calls)).toHaveLength(1);
    });
    const [call] = writes(calls);
    expect(call?.url).toBe("/api/v1/actions/action-1/snooze");
    const body = JSON.parse(call?.body as string) as { expected_state_version: number; until: string };
    expect(body.expected_state_version).toBe(1);
    expect(new Date(body.until).getTime()).toBe(new Date("2099-01-01T09:30").getTime());
  });

  it("shows a conflict with a refresh that reloads the list", async () => {
    const calls = serve([recruitingAction()], () =>
      jsonResponse({ error: { code: "conflict" } }, 409),
    );
    renderPage(<Actions />);

    fireEvent.click(await screen.findByRole("button", { name: "Dismiss" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("This changed since you opened it");
    const loads = calls.filter((call) => call.method === "GET").length;
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    await waitFor(() => {
      expect(calls.filter((call) => call.method === "GET").length).toBeGreaterThan(loads);
    });
  });

  it("explains an invalid transition and offers a refresh", async () => {
    serve([recruitingAction()], () => jsonResponse({ error: { code: "invalid_transition" } }, 409));
    renderPage(<Actions />);

    fireEvent.click(await screen.findByRole("button", { name: "Complete" }));

    expect(await screen.findByRole("alert")).toHaveTextContent("no longer possible");
    expect(screen.getByRole("button", { name: "Refresh" })).toBeInTheDocument();
  });

  it("requires a date for an interview and keeps the choices after adding", async () => {
    const calls = serve([], () => jsonResponse(recruitingAction(), 201));
    renderPage(<Actions />);

    const form = await screen.findByRole("form", { name: "Add action" });
    fireEvent.change(within(form).getByLabelText("Kind"), { target: { value: "attend_interview" } });
    fireEvent.change(within(form).getByLabelText("Title"), { target: { value: "Interview" } });
    fireEvent.change(within(form).getByLabelText("Due or scheduled for"), { target: { value: "" } });
    expect(within(form).getByRole("button", { name: "Add action" })).toBeDisabled();
    fireEvent.change(within(form).getByLabelText("Due or scheduled for"), {
      target: { value: "2099-02-03T10:00" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Add action" }));

    expect(await screen.findByText("Action added.")).toBeInTheDocument();
    const [call] = writes(calls);
    expect(JSON.parse(call?.body as string)).toMatchObject({
      kind: "attend_interview",
      title: "Interview",
    });
    expect(within(form).getByLabelText("Kind")).toHaveValue("attend_interview");
  });

  it("renders hostile titles as plain text", async () => {
    const hostile = '<img src=x onerror="alert(1)">';
    serve([recruitingAction({ title: hostile })]);

    const { container } = renderPage(<Actions />);

    await screen.findByText(hostile);
    expect(container.querySelector("img")).toBeNull();
  });
});
