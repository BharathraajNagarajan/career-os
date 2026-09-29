import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { vi } from "vitest";

import { HomePlaceholder } from "./HomePlaceholder";

function renderWithClient() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <HomePlaceholder />
    </QueryClientProvider>,
  );
}

describe("HomePlaceholder", () => {
  it("shows the API version when the health check succeeds", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ status: "ok", version: "0.1.0" }), { status: 200 }),
    );

    renderWithClient();

    expect(await screen.findByText("API connected (version 0.1.0)")).toBeInTheDocument();
  });

  it("tells the user how to recover when the API is unreachable", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("", { status: 503 }));

    renderWithClient();

    expect(
      await screen.findByText("API unreachable. Start the backend and reload."),
    ).toBeInTheDocument();
  });
});
