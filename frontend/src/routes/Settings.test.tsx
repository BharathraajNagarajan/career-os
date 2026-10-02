import { screen } from "@testing-library/react";

import { jsonResponse, mockApi, renderPage } from "../test-utils";
import { Settings } from "./Settings";

describe("Settings", () => {
  it("shows the AI budget indicator", async () => {
    mockApi((call) => {
      if (call.url === "/api/v1/llm/budget") {
        return jsonResponse({
          spent_usd: "0.500000",
          cap_usd: "1.00",
          remaining_usd: "0.500000",
          resets_at: "2026-10-03T00:00:00Z",
        });
      }
      if (call.url === "/api/v1/auth/sessions") {
        return jsonResponse([]);
      }
      return undefined;
    });

    renderPage(<Settings />);

    expect(await screen.findByRole("heading", { name: "AI budget" })).toBeInTheDocument();
    expect(await screen.findByText(/\$0\.50 of \$1\.00 spent today/)).toBeInTheDocument();
  });
});
