import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, type RenderOptions } from "@testing-library/react";
import { type ReactNode } from "react";
import { MemoryRouter } from "react-router";
import { vi } from "vitest";
import { AuthProvider } from "../auth/AuthContext";
import { ToastProvider } from "../components/Toast";
import type { User } from "../api/types";

export const ANALYST: User = {
  id: "u-analyst",
  username: "ops.analyst",
  display_name: "Alex Analyst (demo)",
  email: "ops.analyst@contoso.example",
  role: "operations_analyst",
  tenant_id: "contoso-demo",
  tenant_name: "Contoso Federal Bank (SYNTHETIC DEMO)",
  permissions: [
    "actions:read", "actions:request", "actions:verify", "approvals:cancel", "approvals:read",
    "dashboard:read", "diagnostics:run", "evaluations:read", "incidents:read",
    "investigations:read", "investigations:resume", "investigations:start",
    "knowledge:read", "knowledge:search", "observability:read", "settings:read",
  ],
  is_demo_account: true,
};

export const MANAGER: User = {
  ...ANALYST,
  id: "u-manager",
  username: "ops.manager",
  display_name: "Morgan Manager (demo)",
  email: "ops.manager@contoso.example",
  role: "operations_manager",
  permissions: [
    ...ANALYST.permissions,
    "approvals:decide", "knowledge:ingest", "knowledge:manage", "promotions:manage", "retention:manage", "evaluations:run",
  ],
};

export const READONLY: User = {
  ...ANALYST,
  id: "u-readonly",
  username: "readonly.viewer",
  display_name: "Riley Viewer (demo)",
  email: "readonly.viewer@contoso.example",
  role: "read_only",
  permissions: ["dashboard:read", "incidents:read", "investigations:read", "actions:read", "approvals:read", "knowledge:read", "knowledge:search", "governance:read", "audit:read", "users:read", "evaluations:read", "observability:read", "settings:read"],
};

interface RenderWithProvidersOptions extends Omit<RenderOptions, "wrapper"> {
  initialEntries?: string[];
}

export function renderWithProviders(ui: ReactNode, options: RenderWithProvidersOptions = {}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0, staleTime: 0 }, mutations: { retry: false } },
  });
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <QueryClientProvider client={queryClient}>
        <MemoryRouter initialEntries={options.initialEntries ?? ["/"]}>
          <AuthProvider>
            <ToastProvider>{children}</ToastProvider>
          </AuthProvider>
        </MemoryRouter>
      </QueryClientProvider>
    );
  }
  return { ...render(ui, { wrapper: Wrapper }), queryClient };
}

/** Builds a fetch mock that routes by method+path and returns canned responses. */
export function mockFetch(routes: Record<string, unknown>): typeof fetch {
  const handler = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = new URL(typeof input === "string" ? input : input instanceof URL ? input.toString() : input.url, "http://localhost");
    const method = (init?.method ?? "GET").toUpperCase();
    const path = url.pathname.replace(/^\/api/, "");
    const key = `${method} ${path}`;
    const body = routes[key];
    if (body === undefined) {
      return new Response(JSON.stringify({ error: { code: "not_found", message: `No mock for ${key}` } }), { status: 404, headers: { "Content-Type": "application/json" } });
    }
    if (body instanceof Response) return body;
    return new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json", "X-Request-ID": "test-req" } });
  }) as unknown as typeof fetch;
  vi.stubGlobal("fetch", handler);
  return handler;
}
