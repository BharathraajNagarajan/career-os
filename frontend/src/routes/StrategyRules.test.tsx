import { fireEvent, screen, waitFor, within } from "@testing-library/react";

import type { StrategyRule } from "../api/rules";
import { jsonResponse, mockApi, renderPage } from "../test-utils";
import type { RecordedCall } from "../test-utils";
import { strategyRule } from "./relationshipFixtures";
import { StrategyRules } from "./StrategyRules";

function serve(rows: StrategyRule[], command?: (call: RecordedCall) => Response | undefined) {
  return mockApi((call) => {
    if (call.method === "GET" && call.url === "/api/v1/strategy-rules") {
      return jsonResponse(rows);
    }
    if (call.method === "GET" && call.url === "/api/v1/companies") {
      return jsonResponse([
        {
          id: "company-1",
          name: "Example Corp",
          normalized_name: "example",
          aliases: [],
          domains: [],
          careers_url: null,
          strategic_priority: "normal",
          notes: "",
          origin: "user",
          created_at: "2026-01-01T00:00:00Z",
          updated_at: "2026-01-01T00:00:00Z",
        },
      ]);
    }
    if (call.method === "GET") {
      return jsonResponse([]);
    }
    return command?.(call);
  });
}

function writes(calls: RecordedCall[]): RecordedCall[] {
  return calls.filter((call) => call.method !== "GET");
}

describe("StrategyRules", () => {
  it("lists rules with their scope and state", async () => {
    serve([
      strategyRule(),
      strategyRule({ id: "rule-2", scope: "company", company_id: "company-1", active: false }),
    ]);

    renderPage(<StrategyRules />);

    expect(await screen.findAllByRole("form", { name: /Edit rule/ })).toHaveLength(2);
    expect(await screen.findByText(/Company – Example Corp – disabled/)).toBeInTheDocument();
    expect(screen.getByText(/Global – enabled/)).toBeInTheDocument();
  });

  it("creates a global rule and confirms", async () => {
    const calls = serve([], () => jsonResponse(strategyRule(), 201));
    renderPage(<StrategyRules />);

    const form = await screen.findByRole("form", { name: "Add rule" });
    fireEvent.change(within(form).getByLabelText("Statement"), {
      target: { value: "Wait two weeks before following up" },
    });
    fireEvent.change(within(form).getByLabelText("Type"), { target: { value: "cooldown" } });
    fireEvent.click(within(form).getByRole("button", { name: "Add rule" }));

    expect(await screen.findByText("Rule added.")).toBeInTheDocument();
    expect(JSON.parse(writes(calls)[0]?.body as string)).toEqual({
      scope: "global",
      company_id: null,
      lane_id: null,
      statement: "Wait two weeks before following up",
      rule_type: "cooldown",
      condition: null,
      active: true,
    });
    expect(within(form).getByLabelText("Type")).toHaveValue("cooldown");
  });

  it("needs a company target for a company-scoped rule", async () => {
    const calls = serve([], () => jsonResponse(strategyRule(), 201));
    renderPage(<StrategyRules />);

    const form = await screen.findByRole("form", { name: "Add rule" });
    fireEvent.change(within(form).getByLabelText("Scope"), { target: { value: "company" } });
    fireEvent.change(within(form).getByLabelText("Statement"), { target: { value: "Prefer them" } });
    expect(within(form).getByRole("button", { name: "Add rule" })).toBeDisabled();
    await within(form).findByRole("option", { name: "Example Corp" });
    fireEvent.change(within(form).getByLabelText("Company"), { target: { value: "company-1" } });
    fireEvent.click(within(form).getByRole("button", { name: "Add rule" }));

    await waitFor(() => {
      expect(writes(calls)).toHaveLength(1);
    });
    expect(JSON.parse(writes(calls)[0]?.body as string)).toMatchObject({
      scope: "company",
      company_id: "company-1",
      lane_id: null,
    });
  });

  it("edits, disables and deletes a rule", async () => {
    const calls = serve([strategyRule()], () => jsonResponse(strategyRule()));
    renderPage(<StrategyRules />);

    const form = await screen.findByRole("form", { name: /Edit rule/ });
    fireEvent.change(within(form).getByLabelText("Statement"), { target: { value: "Changed" } });
    fireEvent.click(within(form).getByRole("button", { name: "Save rule" }));
    await waitFor(() => {
      expect(writes(calls)).toHaveLength(1);
    });
    expect(JSON.parse(writes(calls)[0]?.body as string)).toEqual({
      statement: "Changed",
      rule_type: "constraint",
    });

    fireEvent.click(within(form).getByRole("button", { name: "Disable" }));
    await waitFor(() => {
      expect(writes(calls)).toHaveLength(2);
    });
    expect(JSON.parse(writes(calls)[1]?.body as string)).toEqual({ active: false });

    fireEvent.click(within(form).getByRole("button", { name: "Delete rule" }));
    await waitFor(() => {
      expect(writes(calls)).toHaveLength(3);
    });
    expect(writes(calls)[2]?.method).toBe("DELETE");
    expect(writes(calls)[2]?.url).toBe("/api/v1/strategy-rules/rule-1");
  });

  it("renders hostile statements as plain text", async () => {
    const hostile = '<img src=x onerror="alert(1)">';
    serve([strategyRule({ statement: hostile })]);

    const { container } = renderPage(<StrategyRules />);

    await screen.findByDisplayValue(hostile);
    expect(container.querySelector("img")).toBeNull();
  });
});
