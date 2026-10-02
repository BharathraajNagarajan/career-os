import { vi } from "vitest";

import { ApiRequestError, apiFetch, setUnauthorizedHandler } from "./client";

function mockFetch(response: Response) {
  return vi.spyOn(globalThis, "fetch").mockResolvedValue(response);
}

function sentHeaders(spy: ReturnType<typeof mockFetch>): Headers {
  const init = spy.mock.calls[0]?.[1];
  return new Headers(init?.headers);
}

describe("apiFetch", () => {
  beforeEach(() => {
    document.cookie = "career_os_csrf=token-123; path=/";
  });

  afterEach(() => {
    document.cookie = "career_os_csrf=; path=/; max-age=0";
    setUnauthorizedHandler(() => undefined);
  });

  it("adds the CSRF header from the cookie on mutating requests", async () => {
    const spy = mockFetch(new Response(null, { status: 204 }));

    await apiFetch("/api/v1/auth/logout", { method: "POST" });

    expect(sentHeaders(spy).get("X-CSRF-Token")).toBe("token-123");
  });

  it("does not add the CSRF header on reads", async () => {
    const spy = mockFetch(new Response("[]", { status: 200 }));

    await apiFetch("/api/v1/auth/sessions");

    expect(sentHeaders(spy).has("X-CSRF-Token")).toBe(false);
  });

  it("sends credentials for same-origin requests only", async () => {
    const spy = mockFetch(new Response("{}", { status: 200 }));

    await apiFetch("/api/v1/auth/me");

    expect(spy.mock.calls[0]?.[1]?.credentials).toBe("same-origin");
  });

  it("sends JSON bodies with a content type", async () => {
    const spy = mockFetch(new Response(null, { status: 202 }));

    await apiFetch("/api/v1/account/deletion", { method: "POST", json: { confirm: "x" } });

    expect(sentHeaders(spy).get("Content-Type")).toBe("application/json");
    expect(spy.mock.calls[0]?.[1]?.body).toBe('{"confirm":"x"}');
  });

  it("sends the user to sign in when the API answers 401", async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    mockFetch(new Response(JSON.stringify({ error: { code: "unauthenticated" } }), { status: 401 }));

    await expect(apiFetch("/api/v1/auth/sessions")).rejects.toBeInstanceOf(ApiRequestError);

    expect(handler).toHaveBeenCalledOnce();
  });

  it("lets a caller opt out of the sign-in redirect", async () => {
    const handler = vi.fn();
    setUnauthorizedHandler(handler);
    mockFetch(new Response("{}", { status: 401 }));

    await expect(apiFetch("/api/v1/auth/me", { redirectOnUnauthorized: false })).rejects.toThrow();

    expect(handler).not.toHaveBeenCalled();
  });

  it("surfaces the typed error code", async () => {
    mockFetch(new Response(JSON.stringify({ error: { code: "csrf_failed" } }), { status: 403 }));

    await expect(apiFetch("/api/v1/auth/logout", { method: "POST" })).rejects.toMatchObject({
      status: 403,
      code: "csrf_failed",
    });
  });
});
