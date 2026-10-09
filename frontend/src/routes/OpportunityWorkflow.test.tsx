import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, vi } from "vitest";

import type { Application, TimelineEntry } from "../api/applications";
import type { OpportunityDetail as Detail } from "../api/opportunities";
import type { Lane, Resume } from "../api/resumes";
import { jsonResponse, mockApi, renderPage } from "../test-utils";
import type { RecordedCall } from "../test-utils";
import { OpportunityDetail } from "./OpportunityDetail";
import { application, company, detail, entry } from "./opportunityFixtures";
import { todayLocal } from "./workflowDates";

const BASE = "/api/v1/opportunities/opp-1";
const ROUTE = {
  path: "/opportunities/:opportunityId",
  entry: "/opportunities/opp-1",
};

const RESUMES: Resume[] = [
  resume("r1", "Active resume"),
  resume("r2", "Archived resume", { status: "archived", archived: true }),
];
const LANES: Lane[] = [
  lane("l1", "Active lane", "active"),
  lane("l2", "Archived lane", "archived"),
];

function resume(id: string, label: string, overrides: Partial<Resume> = {}): Resume {
  return {
    id,
    label,
    status: "active",
    archived: false,
    lane_id: null,
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

function lane(id: string, name: string, status: Lane["status"]): Lane {
  return {
    id,
    name,
    description: "",
    emphasis_notes: "",
    target_role_labels: [],
    default_resume_id: null,
    status,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
  };
}

interface Server {
  calls: RecordedCall[];
  opportunity: Detail;
  applications: Application[];
  timeline: TimelineEntry[];
}

type Command = (call: RecordedCall, server: Server) => Response | undefined;

function serve(initial: Partial<Server> = {}, command?: Command): Server {
  const server: Server = {
    calls: [],
    opportunity: detail(),
    applications: [],
    timeline: [],
    ...initial,
  };
  server.calls = mockApi((call) => {
    if (call.method === "GET") {
      if (call.url === BASE) {
        return jsonResponse(server.opportunity);
      }
      if (call.url === `${BASE}/timeline`) {
        return jsonResponse(server.timeline);
      }
      if (call.url === `${BASE}/duplicates`) {
        return jsonResponse([]);
      }
      if (call.url.startsWith("/api/v1/applications")) {
        return jsonResponse(server.applications);
      }
      if (call.url === "/api/v1/companies") {
        return jsonResponse([company()]);
      }
      if (call.url.startsWith("/api/v1/contacts") || call.url.startsWith("/api/v1/actions")) {
        return jsonResponse([]);
      }
      if (call.url === "/api/v1/resumes") {
        return jsonResponse(RESUMES);
      }
      if (call.url === "/api/v1/lanes") {
        return jsonResponse(LANES);
      }
    }
    return command?.(call, server);
  });
  return server;
}

function posts(server: Server, suffix: string): RecordedCall[] {
  return server.calls.filter((call) => call.method === "POST" && call.url.endsWith(suffix));
}

function bodyOf(call: RecordedCall | undefined): Record<string, unknown> {
  return JSON.parse(call?.body as string) as Record<string, unknown>;
}

afterEach(() => {
  vi.useRealTimers();
});

describe("decisions", () => {
  it("offers exactly the actions the server allows", async () => {
    serve({
      opportunity: detail({
        status: "saved",
        allowed_actions: ["skip", "apply", "close"],
      }),
    });

    renderPage(<OpportunityDetail />, ROUTE);

    expect(await screen.findByRole("button", { name: "Skip" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Apply" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  });

  it("offers no decision once applied", async () => {
    serve({ opportunity: detail({ status: "applied", allowed_actions: [] }) });

    renderPage(<OpportunityDetail />, ROUTE);

    expect(await screen.findByText(/You applied to this posting/)).toBeInTheDocument();
    for (const name of ["Save", "Skip", "Apply", "Close"]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
  });

  it("saves with the version it saw and shows the new status", async () => {
    const server = serve({}, (call, state) => {
      if (call.method === "POST" && call.url === `${BASE}/save`) {
        state.opportunity = detail({
          status: "saved",
          state_version: 3,
          allowed_actions: ["skip", "apply", "close"],
        });
        return jsonResponse(state.opportunity);
      }
      return undefined;
    });
    renderPage(<OpportunityDetail />, ROUTE);

    fireEvent.click(await screen.findByRole("button", { name: "Save" }));

    expect(await screen.findByText(/Status: saved/)).toBeInTheDocument();
    expect(bodyOf(posts(server, "/save")[0])).toEqual({
      expected_state_version: 2,
      reason: null,
    });
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
  });

  it.each([
    ["Skip", "skip", "Confirm skip"],
    ["Close", "close", "Confirm close"],
  ])("asks for an optional reason before %s", async (button, path, confirm) => {
    const server = serve({}, (call, state) => {
      if (call.method === "POST" && call.url === `${BASE}/${path}`) {
        state.opportunity = detail({ state_version: 3 });
        return jsonResponse(state.opportunity);
      }
      return undefined;
    });
    renderPage(<OpportunityDetail />, ROUTE);

    fireEvent.click(await screen.findByRole("button", { name: button }));
    expect(posts(server, `/${path}`)).toHaveLength(0);
    fireEvent.change(screen.getByLabelText("Reason (optional)"), {
      target: { value: "  not a fit  " },
    });
    fireEvent.click(screen.getByRole("button", { name: confirm }));

    await waitFor(() => {
      expect(posts(server, `/${path}`)).toHaveLength(1);
    });
    expect(bodyOf(posts(server, `/${path}`)[0])).toEqual({
      expected_state_version: 2,
      reason: "not a fit",
    });
  });

  it("allows skipping without a reason and cancelling the prompt", async () => {
    const server = serve({}, () => jsonResponse(detail({ state_version: 3 })));
    renderPage(<OpportunityDetail />, ROUTE);

    fireEvent.click(await screen.findByRole("button", { name: "Skip" }));
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByLabelText("Reason (optional)")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Skip" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm skip" }));

    await waitFor(() => {
      expect(posts(server, "/skip")).toHaveLength(1);
    });
    expect(bodyOf(posts(server, "/skip")[0])["reason"]).toBeNull();
  });

  it("explains a stale version plainly and refreshes on request", async () => {
    const server = serve({}, (call, state) => {
      if (call.method === "POST" && call.url === `${BASE}/save`) {
        state.opportunity = detail({
          status: "skipped",
          state_version: 5,
          allowed_actions: ["save"],
        });
        return jsonResponse({ error: { code: "conflict" } }, 409);
      }
      return undefined;
    });
    renderPage(<OpportunityDetail />, ROUTE);

    fireEvent.click(await screen.findByRole("button", { name: "Save" }));

    expect(await screen.findByText(/This changed since you opened it/)).toBeInTheDocument();
    const before = server.calls.filter((call) => call.url === BASE).length;
    fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
    expect(await screen.findByText(/Status: skipped/)).toBeInTheDocument();
    expect(server.calls.filter((call) => call.url === BASE).length).toBeGreaterThan(before);
  });

  it("explains an invalid transition plainly", async () => {
    serve({}, (call) =>
      call.method === "POST" && call.url === `${BASE}/close`
        ? jsonResponse({ error: { code: "invalid_transition" } }, 409)
        : undefined,
    );
    renderPage(<OpportunityDetail />, ROUTE);

    fireEvent.click(await screen.findByRole("button", { name: "Close" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm close" }));

    expect(
      await screen.findByText(/no longer possible from the current state/),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh" })).toBeInTheDocument();
  });
});

describe("decision flow as used in the browser", () => {
  it("sends the typed Skip reason after a Save, even when the page refetches while the prompt is open", async () => {
    const server = serve({}, (call, state) => {
      if (call.method === "POST" && call.url === `${BASE}/save`) {
        state.opportunity = detail({
          status: "saved",
          state_version: 3,
          allowed_actions: ["skip", "apply", "close"],
        });
        return jsonResponse(state.opportunity);
      }
      if (call.method === "POST" && call.url === `${BASE}/skip`) {
        state.opportunity = detail({
          status: "skipped",
          state_version: 4,
          allowed_actions: ["save", "apply", "close"],
        });
        return jsonResponse(state.opportunity);
      }
      return undefined;
    });
    const { client } = renderPage(<OpportunityDetail />, ROUTE);

    fireEvent.click(await screen.findByRole("button", { name: "Save" }));
    await screen.findByText(/Status: saved/);
    fireEvent.click(screen.getByRole("button", { name: "Skip" }));
    const reason = screen.getByLabelText("Reason (optional)");
    fireEvent.change(reason, { target: { value: "testing skip" } });
    await client.invalidateQueries();
    await waitFor(() => {
      expect(server.calls.filter((call) => call.url === BASE).length).toBeGreaterThan(2);
    });
    expect(screen.getByLabelText("Reason (optional)")).toHaveValue("testing skip");
    fireEvent.click(screen.getByRole("button", { name: "Confirm skip" }));

    await waitFor(() => {
      expect(posts(server, "/skip")).toHaveLength(1);
    });
    expect(bodyOf(posts(server, "/skip")[0])).toEqual({
      expected_state_version: 3,
      reason: "testing skip",
    });
  });
});

describe("apply", () => {
  it("offers active resumes and lanes, a channel and today's date, then shows the application", async () => {
    const server = serve({}, (call, state) => {
      if (call.method === "POST" && call.url === `${BASE}/apply`) {
        state.opportunity = detail({
          status: "applied",
          state_version: 3,
          allowed_actions: [],
        });
        state.applications = [application()];
        state.timeline = [
          entry({
            id: "e1",
            event_type: "APPLICATION_SUBMITTED",
            voidable: false,
          }),
        ];
        return jsonResponse({
          opportunity: state.opportunity,
          application: application(),
        });
      }
      return undefined;
    });
    renderPage(<OpportunityDetail />, ROUTE);

    fireEvent.click(await screen.findByRole("button", { name: "Apply" }));
    const form = await screen.findByRole("form", { name: "Apply" });
    await within(form).findByRole("option", { name: "Active resume" });

    expect(within(form).queryByRole("option", { name: "Archived resume" })).toBeNull();
    expect(within(form).getByRole("option", { name: "Active lane" })).toBeInTheDocument();
    expect(within(form).queryByRole("option", { name: "Archived lane" })).toBeNull();
    expect(within(form).getByLabelText("Applied date")).toHaveValue(todayLocal());
    fireEvent.change(within(form).getByLabelText("Resume"), {
      target: { value: "r1" },
    });
    fireEvent.change(within(form).getByLabelText("Lane"), {
      target: { value: "l1" },
    });
    fireEvent.change(within(form).getByLabelText("Channel"), {
      target: { value: "referral" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Confirm apply" }));

    expect(await screen.findByRole("heading", { name: "Application" })).toBeInTheDocument();
    const body = bodyOf(posts(server, "/apply")[0]);
    expect(body).toMatchObject({
      expected_state_version: 2,
      resume_id: "r1",
      lane_id: "l1",
      channel: "referral",
    });
    expect(Math.abs(Date.parse(body["applied_at"] as string) - Date.now())).toBeLessThan(60_000);
    expect(screen.getByText(/Stage:/)).toHaveTextContent("Applied");
  });

  it("sends no resume or lane when none is chosen, and a past date as noon local", async () => {
    const server = serve({}, () =>
      jsonResponse({
        opportunity: detail({ status: "applied" }),
        application: application(),
      }),
    );
    renderPage(<OpportunityDetail />, ROUTE);

    fireEvent.click(await screen.findByRole("button", { name: "Apply" }));
    fireEvent.change(await screen.findByLabelText("Applied date"), {
      target: { value: "2026-03-04" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Confirm apply" }));

    await waitFor(() => {
      expect(posts(server, "/apply")).toHaveLength(1);
    });
    const body = bodyOf(posts(server, "/apply")[0]);
    expect(body["resume_id"]).toBeNull();
    expect(body["lane_id"]).toBeNull();
    expect(body["channel"]).toBe("other");
    expect(body["applied_at"]).toBe(new Date("2026-03-04T12:00:00").toISOString());
  });

  it("explains an archived resume", async () => {
    serve({}, (call) =>
      call.method === "POST" && call.url === `${BASE}/apply`
        ? jsonResponse({ error: { code: "resume_archived" } }, 422)
        : undefined,
    );
    renderPage(<OpportunityDetail />, ROUTE);

    fireEvent.click(await screen.findByRole("button", { name: "Apply" }));
    fireEvent.click(await screen.findByRole("button", { name: "Confirm apply" }));

    expect(await screen.findByText(/That resume is archived/)).toBeInTheDocument();
  });
});

describe("application", () => {
  const applied = detail({ status: "applied", allowed_actions: [] });

  it("shows nothing before applying", async () => {
    serve();

    renderPage(<OpportunityDetail />, ROUTE);

    await screen.findByRole("heading", { name: "Timeline" });
    expect(screen.queryByRole("heading", { name: "Application" })).toBeNull();
  });

  it("records an event with a backdated time and a note, offering only recordable types", async () => {
    const server = serve({ opportunity: applied, applications: [application()] }, (call, state) => {
      if (call.method === "POST" && call.url === "/api/v1/applications/app-1/events") {
        state.applications = [application({ stage: "assessment", state_version: 2 })];
        return jsonResponse(state.applications[0]);
      }
      return undefined;
    });
    renderPage(<OpportunityDetail />, ROUTE);

    const form = await screen.findByRole("form", { name: "Record event" });
    const options = within(form)
      .getAllByRole("option")
      .map((option) => option.textContent);
    expect(options).toEqual([
      "Application acknowledged",
      "Assessment received",
      "Interview scheduled",
      "Rejected",
      "Withdrawn",
      "Note added",
    ]);
    fireEvent.change(within(form).getByLabelText("Event type"), {
      target: { value: "ASSESSMENT_RECEIVED" },
    });
    fireEvent.change(within(form).getByLabelText("When it happened"), {
      target: { value: "2026-01-05T09:30" },
    });
    fireEvent.change(within(form).getByLabelText("Note (optional)"), {
      target: { value: "  take-home sent  " },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Record event" }));

    await waitFor(() => {
      expect(screen.getByText(/Stage:/)).toHaveTextContent("Assessment");
    });
    const body = bodyOf(server.calls.find((call) => call.url.endsWith("/events")));
    expect(body).toEqual({
      expected_state_version: 1,
      event_type: "ASSESSMENT_RECEIVED",
      occurred_at: new Date("2026-01-05T09:30").toISOString(),
      note: "take-home sent",
    });
  });

  it("keeps the chosen event type after recording, confirms it, and records the same type again", async () => {
    let version = 1;
    const server = serve({ opportunity: applied, applications: [application()] }, (call, state) => {
      if (call.method === "POST" && call.url === "/api/v1/applications/app-1/events") {
        version += 1;
        state.applications = [application({ stage: "interviewing", state_version: version })];
        return jsonResponse(state.applications[0]);
      }
      return undefined;
    });
    renderPage(<OpportunityDetail />, ROUTE);

    const form = await screen.findByRole("form", { name: "Record event" });
    fireEvent.change(within(form).getByLabelText("Event type"), {
      target: { value: "INTERVIEW_SCHEDULED" },
    });
    fireEvent.change(within(form).getByLabelText("Note (optional)"), {
      target: { value: "first note" },
    });
    fireEvent.click(within(form).getByRole("button", { name: "Record event" }));

    expect(await screen.findByText("Recorded: Interview scheduled.")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByLabelText("Event type")).toHaveValue("INTERVIEW_SCHEDULED");
    });
    expect(screen.getByLabelText("Note (optional)")).toHaveValue("");
    fireEvent.click(screen.getByRole("button", { name: "Record event" }));

    await waitFor(() => {
      expect(posts(server, "/events")).toHaveLength(2);
    });
    const [first, second] = posts(server, "/events").map(bodyOf);
    expect(first).toMatchObject({ event_type: "INTERVIEW_SCHEDULED", note: "first note" });
    expect(second).toMatchObject({
      expected_state_version: 2,
      event_type: "INTERVIEW_SCHEDULED",
      note: null,
    });
  });

  it("clears the confirmation on the next change and falls back when the type is no longer offered", async () => {
    serve({ opportunity: applied, applications: [application()] }, (call, state) => {
      if (call.method === "POST" && call.url === "/api/v1/applications/app-1/events") {
        state.applications = [
          application({
            stage: "rejected",
            is_terminal: true,
            state_version: 2,
            recordable_event_types: ["NOTE_ADDED"],
          }),
        ];
        return jsonResponse(state.applications[0]);
      }
      return undefined;
    });
    renderPage(<OpportunityDetail />, ROUTE);

    fireEvent.change(await screen.findByLabelText("Event type"), { target: { value: "REJECTED" } });
    fireEvent.click(screen.getByRole("button", { name: "Record event" }));

    expect(await screen.findByText("Recorded: Rejected.")).toBeInTheDocument();
    await waitFor(() => {
      expect(screen.getByLabelText("Event type")).toHaveValue("NOTE_ADDED");
    });
    fireEvent.change(screen.getByLabelText("Note (optional)"), { target: { value: "x" } });
    expect(screen.queryByText(/^Recorded:/)).toBeNull();
  });

  it("explains a refused event and keeps the form", async () => {
    serve({ opportunity: applied, applications: [application()] }, (call) =>
      call.method === "POST" && call.url.endsWith("/events")
        ? jsonResponse({ error: { code: "occurred_at_in_future" } }, 422)
        : undefined,
    );
    renderPage(<OpportunityDetail />, ROUTE);

    fireEvent.click(await screen.findByRole("button", { name: "Record event" }));

    expect(await screen.findByText(/too far in the future/)).toBeInTheDocument();
    expect(screen.getByRole("form", { name: "Record event" })).toBeInTheDocument();
  });

  it("explains a stale application and refreshes", async () => {
    const server = serve({ opportunity: applied, applications: [application()] }, (call, state) => {
      if (call.method === "POST" && call.url.endsWith("/events")) {
        state.applications = [application({ stage: "interviewing", state_version: 4 })];
        return jsonResponse({ error: { code: "conflict" } }, 409);
      }
      return undefined;
    });
    renderPage(<OpportunityDetail />, ROUTE);

    fireEvent.click(await screen.findByRole("button", { name: "Record event" }));
    fireEvent.click(await screen.findByRole("button", { name: "Refresh" }));

    await waitFor(() => {
      expect(screen.getByText(/Stage:/)).toHaveTextContent("Interviewing");
    });
    expect(
      server.calls.filter((call) => call.url.startsWith("/api/v1/applications?")).length,
    ).toBeGreaterThan(1);
  });

  it("offers Reopen only when closed, and sends the version it saw", async () => {
    const closed = application({
      stage: "rejected",
      is_terminal: true,
      state_version: 5,
      recordable_event_types: ["NOTE_ADDED"],
    });
    const server = serve({ opportunity: applied, applications: [closed] }, (call, state) => {
      if (call.method === "POST" && call.url === "/api/v1/applications/app-1/reopen") {
        state.applications = [application({ stage: "interviewing", state_version: 6 })];
        return jsonResponse(state.applications[0]);
      }
      return undefined;
    });
    renderPage(<OpportunityDetail />, ROUTE);

    expect(await screen.findByText(/\(closed\)/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Reopen" }));

    await waitFor(() => {
      expect(screen.queryByRole("button", { name: "Reopen" })).toBeNull();
    });
    expect(screen.getByText(/Stage:/)).toHaveTextContent("Interviewing");
    expect(bodyOf(server.calls.find((call) => call.url.endsWith("/reopen")))).toEqual({
      expected_state_version: 5,
    });
  });

  it("does not offer Reopen on an open application", async () => {
    serve({ opportunity: applied, applications: [application()] });

    renderPage(<OpportunityDetail />, ROUTE);

    await screen.findByRole("form", { name: "Record event" });
    expect(screen.queryByRole("button", { name: "Reopen" })).toBeNull();
  });
});

describe("timeline", () => {
  const applied = detail({ status: "applied", allowed_actions: [] });

  it("lists entries in the order given, marks voided ones and offers Void only where allowed", async () => {
    const timeline = [
      entry({ id: "e1", event_type: "APPLICATION_SUBMITTED", voidable: false }),
      entry({
        id: "e2",
        event_type: "REJECTED",
        voided: true,
        voidable: false,
      }),
      entry({
        id: "e3",
        event_type: "EVENT_VOIDED",
        voids_event_id: "e2",
        voidable: false,
        note: "entered by mistake",
      }),
      entry({ id: "e4", event_type: "OFFER_RECEIVED", voidable: true }),
    ];
    serve({ opportunity: applied, applications: [application()], timeline });

    renderPage(<OpportunityDetail />, ROUTE);

    const list = await screen.findByRole("list");
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(4);
    expect(items[0]).toHaveTextContent("Application submitted");
    expect(items[1]).toHaveTextContent("Rejected (voided)");
    expect(items[2]).toHaveTextContent("Event voided");
    expect(items[2]).toHaveTextContent("entered by mistake");
    expect(within(items[0] as HTMLElement).queryByRole("button", { name: "Void" })).toBeNull();
    expect(within(items[1] as HTMLElement).queryByRole("button", { name: "Void" })).toBeNull();
    expect(within(items[2] as HTMLElement).queryByRole("button", { name: "Void" })).toBeNull();
    expect(
      within(items[3] as HTMLElement).getByRole("button", { name: "Void" }),
    ).toBeInTheDocument();
  });

  it("voids an entry with an optional reason using the application's version", async () => {
    const server = serve(
      {
        opportunity: applied,
        applications: [application({ state_version: 3 })],
        timeline: [entry({ id: "e4", event_type: "OFFER_RECEIVED", voidable: true })],
      },
      (call, state) => {
        if (call.method === "POST" && call.url === "/api/v1/applications/app-1/events/e4/void") {
          state.timeline = [
            entry({
              id: "e4",
              event_type: "OFFER_RECEIVED",
              voided: true,
              voidable: false,
            }),
          ];
          state.applications = [application({ state_version: 4 })];
          return jsonResponse(state.applications[0]);
        }
        return undefined;
      },
    );
    renderPage(<OpportunityDetail />, ROUTE);

    fireEvent.click(await screen.findByRole("button", { name: "Void" }));
    fireEvent.change(screen.getByLabelText("Reason for voiding (optional)"), {
      target: { value: "typo" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Confirm void" }));

    await waitFor(() => {
      expect(screen.getByRole("listitem")).toHaveTextContent(/Offer received \(voided\)/);
    });
    expect(bodyOf(server.calls.find((call) => call.url.endsWith("/void")))).toEqual({
      expected_state_version: 3,
      reason: "typo",
    });
    expect(screen.queryByRole("button", { name: "Void" })).toBeNull();
  });

  it("explains a refused void", async () => {
    serve(
      {
        opportunity: applied,
        applications: [application()],
        timeline: [entry({ voidable: true })],
      },
      (call) =>
        call.method === "POST" && call.url.endsWith("/void")
          ? jsonResponse({ error: { code: "already_voided" } }, 409)
          : undefined,
    );
    renderPage(<OpportunityDetail />, ROUTE);

    fireEvent.click(await screen.findByRole("button", { name: "Void" }));
    fireEvent.click(screen.getByRole("button", { name: "Confirm void" }));

    expect(await screen.findByText(/already voided/)).toBeInTheDocument();
  });

  it("renders notes as plain text, never as markup", async () => {
    const hostile = '<img src=x onerror="alert(1)"><script>alert(2)</script><b>bold</b>';
    serve({
      opportunity: applied,
      applications: [application()],
      timeline: [entry({ note: hostile })],
    });

    const { container } = renderPage(<OpportunityDetail />, ROUTE);

    expect(await screen.findByText(hostile)).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
    expect(container.querySelector("script")).toBeNull();
    expect(container.querySelector("b")).toBeNull();
  });
});
