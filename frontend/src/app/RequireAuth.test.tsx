import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { vi } from "vitest";

import { RequireAuth } from "./RequireAuth";

function renderGuard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={["/"]}>
        <Routes>
          <Route path="/sign-in" element={<p>Sign-in page</p>} />
          <Route element={<RequireAuth />}>
            <Route index element={<p>Home page</p>} />
          </Route>
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

describe("RequireAuth", () => {
  it("redirects to the sign-in page when there is no session", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ error: { code: "unauthenticated" } }), { status: 401 }),
    );

    renderGuard();

    expect(await screen.findByText("Sign-in page")).toBeInTheDocument();
  });

  it("renders the protected page when the session is valid", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({
          id: "0190f3a0-0000-7000-8000-000000000001",
          primary_email: "persona@example.test",
          display_name: "Persona",
          status: "active",
        }),
        { status: 200 },
      ),
    );

    renderGuard();

    expect(await screen.findByText("Home page")).toBeInTheDocument();
  });

  it("shows an API error instead of the sign-in page when the API is down", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("", { status: 503 }));

    renderGuard();

    expect(await screen.findByRole("alert")).toHaveTextContent("Could not reach the API");
  });
});
