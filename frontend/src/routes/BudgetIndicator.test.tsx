import { screen } from "@testing-library/react";

import type { Budget } from "../api/llm";
import { jsonResponse, mockApi, renderPage } from "../test-utils";
import { BudgetIndicator } from "./BudgetIndicator";

function serve(budget: Budget) {
  return mockApi((call) =>
    call.url === "/api/v1/llm/budget" ? jsonResponse(budget) : undefined,
  );
}

const RESETS = "2026-10-03T00:00:00Z";

describe("BudgetIndicator", () => {
  it("shows spend against the cap and the reset time", async () => {
    serve({ spent_usd: "0.250000", cap_usd: "1.00", remaining_usd: "0.750000", resets_at: RESETS });

    renderPage(<BudgetIndicator />);

    expect(await screen.findByText(/\$0\.25 of \$1\.00 spent today/)).toBeInTheDocument();
    expect(screen.getByText(/Resets at\s+00:00 UTC/)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(screen.getByLabelText("AI budget used today")).toBeInTheDocument();
  });

  it("shows tiny amounts with enough precision", async () => {
    serve({ spent_usd: "0.000175", cap_usd: "1.00", remaining_usd: "0.999825", resets_at: RESETS });

    renderPage(<BudgetIndicator />);

    expect(await screen.findByText(/\$0\.0002 of \$1\.00/)).toBeInTheDocument();
  });

  it("explains plainly when the budget is exhausted", async () => {
    serve({ spent_usd: "1.000000", cap_usd: "1.00", remaining_usd: "0", resets_at: RESETS });

    renderPage(<BudgetIndicator />);

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("reached today’s AI budget of $1.00");
    expect(alert).toHaveTextContent("until 00:00 UTC");
    expect(alert).toHaveTextContent("Everything else keeps working");
  });

  it("reports a load failure", async () => {
    mockApi(() => jsonResponse({ error: { code: "boom" } }, 500));

    renderPage(<BudgetIndicator />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not load the AI budget.");
  });
});
