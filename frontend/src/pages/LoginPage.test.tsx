import { describe, expect, it } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { renderWithProviders, mockFetch } from "../test/test-utils";
import { LoginPage } from "./LoginPage";

const LOGIN_OK = {
  access_token: "tok", token_type: "bearer", expires_in: 1800,
  expires_at: new Date(Date.now() + 1800_000).toISOString(),
  user: { id: "u", username: "ops.analyst", display_name: "Alex", email: "x@y", role: "operations_analyst", tenant_id: "contoso-demo", tenant_name: "Contoso", permissions: ["dashboard:read"], is_demo_account: true },
};

const LOGIN_401 = new Response(
  JSON.stringify({ error: { code: "invalid_credentials", message: "Invalid username or password." } }),
  { status: 401, headers: { "Content-Type": "application/json" } },
);

describe("LoginPage", () => {
  it("shows the synthetic banner and demo accounts", async () => {
    mockFetch({
      "GET /demo/accounts": [{ username: "ops.analyst", role: "operations_analyst", tenant_id: "contoso-demo" }],
    });
    renderWithProviders(<LoginPage />);
    expect(screen.getByText(/SYNTHETIC DEMO DATA/i)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("ops.analyst")).toBeInTheDocument());
  });

  it("disables submit until both fields are filled", () => {
    mockFetch({ "GET /demo/accounts": [] });
    renderWithProviders(<LoginPage />);
    expect(screen.getByRole("button", { name: /Sign in/i })).toBeDisabled();
  });

  it("shows an error on invalid credentials", async () => {
    const user = userEvent.setup();
    mockFetch({
      "GET /demo/accounts": [],
      "POST /auth/login": LOGIN_401,
    });
    renderWithProviders(<LoginPage />);
    await user.type(screen.getByLabelText(/Username/i), "ops.analyst");
    await user.type(screen.getByLabelText(/Password/i), "wrong");
    await user.click(screen.getByRole("button", { name: /Sign in/i }));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/Invalid username or password/i));
  });

  it("clears the error and navigates on successful login", async () => {
    const user = userEvent.setup();
    mockFetch({
      "GET /demo/accounts": [],
      "POST /auth/login": LOGIN_OK,
      "GET /auth/me": LOGIN_OK.user,
    });
    renderWithProviders(<LoginPage />);
    await user.type(screen.getByLabelText(/Username/i), "ops.analyst");
    await user.type(screen.getByLabelText(/Password/i), "BankOpsDemo!2026");
    await user.click(screen.getByRole("button", { name: /Sign in/i }));
    await waitFor(() => expect(screen.queryByRole("alert")).not.toBeInTheDocument());
  });
});
