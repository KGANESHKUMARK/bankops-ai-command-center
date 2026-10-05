import { beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, buildQuery, errorMessage, readSession, writeSession } from "./client";

describe("buildQuery", () => {
  it("returns empty string for no query", () => {
    expect(buildQuery(undefined)).toBe("");
  });
  it("skips null, undefined and empty-string values", () => {
    expect(buildQuery({ a: "1", b: null, c: undefined, d: "" })).toBe("?a=1");
  });
  it("serializes numbers and booleans", () => {
    expect(buildQuery({ page: 2, active: true })).toBe("?page=2&active=true");
  });
});

describe("session storage", () => {
  beforeEach(() => sessionStorage.clear());

  it("returns null when no session is stored", () => {
    expect(readSession()).toBeNull();
  });
  it("round-trips a session", () => {
    const session = { token: "tok", expiresAt: new Date(Date.now() + 60_000).toISOString(), user: { id: "u", username: "x", display_name: "X", email: "x@demo.local", role: "read_only" as const, permissions: [], tenant_id: "t", tenant_name: "T", is_demo_account: true } };
    writeSession(session);
    expect(readSession()?.token).toBe("tok");
  });
  it("clears an expired session", () => {
    const session = { token: "tok", expiresAt: new Date(Date.now() - 1000).toISOString(), user: { id: "u", username: "x", display_name: "X", email: "x@demo.local", role: "read_only" as const, permissions: [], tenant_id: "t", tenant_name: "T", is_demo_account: true } };
    writeSession(session);
    expect(readSession()).toBeNull();
  });
});

describe("api", () => {
  beforeEach(() => {
    sessionStorage.clear();
    vi.unstubAllGlobals();
  });

  it("throws ApiError on non-2xx with the server envelope", async () => {
    vi.stubGlobal("fetch", vi.fn(async () =>
      new Response(JSON.stringify({ error: { code: "forbidden", message: "Not allowed", request_id: "r1" } }), { status: 403, headers: { "Content-Type": "application/json" } }),
    ));
    await expect(api("/test")).rejects.toMatchObject({ name: "ApiError", status: 403, code: "forbidden", message: "Not allowed", requestId: "r1" });
  });

  it("returns parsed JSON on success", async () => {
    vi.stubGlobal("fetch", vi.fn(async () =>
      new Response(JSON.stringify({ ok: true }), { status: 200, headers: { "Content-Type": "application/json" } }),
    ));
    await expect(api("/test")).resolves.toEqual({ ok: true });
  });

  it("throws a network_error ApiError when fetch rejects", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    await expect(api("/test")).rejects.toMatchObject({ name: "ApiError", status: 0, code: "network_error" });
  });
});

describe("errorMessage", () => {
  it("extracts the message from ApiError", () => {
    expect(errorMessage(new ApiError(403, "forbidden", "Nope"))).toBe("Nope");
  });
  it("extracts the message from a generic Error", () => {
    expect(errorMessage(new Error("Boom"))).toBe("Boom");
  });
  it("returns a fallback for unknown shapes", () => {
    expect(errorMessage("something")).toBe("Unexpected error.");
  });
});
