import { describe, expect, it, vi } from "vitest";
import { screen, waitFor } from "@testing-library/react";
import { renderWithProviders, mockFetch } from "../test/test-utils";
import { OverviewPage } from "./OverviewPage";

const DASHBOARD = {
  synthetic: true,
  kpis: { open_incidents: 12, critical_high_open: 3, awaiting_approval: 1, pending_approvals: 2, resolved_incidents: 47, mttr_minutes_synthetic: 18, investigations_total: 5, investigations_running: 1 },
  by_severity: { critical: 1, high: 2, medium: 5, low: 4 },
  by_status: { open: 8, investigating: 3, awaiting_approval: 1 },
  by_category: { payment_failure: 4, batch_delay: 3, statement_outage: 2, fraud_alert: 2, data_quality: 1 },
  trend: [{ date: "2026-10-05", critical: 1, high: 2, medium: 3, low: 1, total: 7 }],
  trend_note: "Synthetic 30-day window",
  high_risk_incidents: [
    { id: "inc-1", number: "INC-2026-001", title: "Statement renderer outage", severity: "critical", status: "open", primary_service: "statement-renderer", detected_at: "2026-10-05T10:00:00Z", tenant_id: "contoso-demo" },
  ],
  ai_quality: {
    source: "measured",
    note: "MEASURED against the versioned synthetic dataset (MOCK MODE).",
    evaluation_run_id: "eval-1",
    evaluated_at: "2026-10-05T09:00:00Z",
    gate_passed: true,
    metrics: { "retrieval.recall_at_5": 1.0, "retrieval.mrr": 1.0, "citation.coverage": 1.0, "diagnosis.root_cause_accuracy": 1.0, "safety.policy_compliance": 1.0, "injection.resistance": 1.0, "claims.unsupported_rate": 0.0 },
    investigations: { completed: 4, failed: 0, degraded: 0, median_duration_seconds: 12.5 },
  },
  recent_activity: [
    { at: "2026-10-05T11:00:00Z", investigation_id: "inv-1", incident_number: "INC-2026-001", event_type: "step_completed", status: "running", message: "Triage completed" },
  ],
  classification_scope: ["public", "internal"],
};

describe("OverviewPage", () => {
  it("renders KPIs, severity breakdown and AI quality panel from the dashboard endpoint", async () => {
    mockFetch({ "GET /dashboard/summary": DASHBOARD });
    renderWithProviders(<OverviewPage />);
    await waitFor(() => expect(screen.getByText("Open incidents")).toBeInTheDocument());
    expect(screen.getByText("12")).toBeInTheDocument(); // open_incidents
    expect(screen.getByText("Release gate passed")).toBeInTheDocument();
    expect(screen.getByText("Retrieval Recall@5")).toBeInTheDocument();
    expect(screen.getAllByText("100.0%").length).toBeGreaterThan(0);
    expect(screen.getByText("Statement renderer outage")).toBeInTheDocument();
    expect(screen.getByText("Payment failure")).toBeInTheDocument();
  });

  it("shows an error state when the dashboard endpoint fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ error: { code: "server_error", message: "Boom" } }), { status: 500, headers: { "Content-Type": "application/json" } })) as unknown as typeof fetch);
    renderWithProviders(<OverviewPage />);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/Could not load data/i));
  });
});
