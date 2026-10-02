import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import type { ReactElement } from "react";
import { MemoryRouter } from "react-router-dom";
import { vi } from "vitest";

export interface RecordedCall {
  method: string;
  url: string;
  body: BodyInit | null | undefined;
}

type Handler = (call: RecordedCall) => Response | undefined;

export function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

export function mockApi(handler: Handler): RecordedCall[] {
  const calls: RecordedCall[] = [];
  vi.spyOn(globalThis, "fetch").mockImplementation((input, init) => {
    const call: RecordedCall = {
      method: (init?.method ?? "GET").toUpperCase(),
      url: typeof input === "string" ? input : input instanceof URL ? input.href : input.url,
      body: init?.body,
    };
    calls.push(call);
    return Promise.resolve(handler(call) ?? jsonResponse({ error: { code: "not_found" } }, 404));
  });
  return calls;
}

export function renderPage(page: ReactElement) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: 0 }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{page}</MemoryRouter>
    </QueryClientProvider>,
  );
}
