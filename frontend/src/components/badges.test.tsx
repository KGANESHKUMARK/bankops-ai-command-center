import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { ActionStatusBadge, ApprovalStatusBadge, ClassificationBadge, DecisionBadge, IncidentStatusBadge, ModeBadge, OutcomeBadge, RiskBadge, RunStatusBadge, SyntheticBadge, VerificationBadge } from "./badges";

describe("badges", () => {
  it("renders a risk badge with the correct tone and label", () => {
    render(<RiskBadge value="high" />);
    expect(screen.getByText("High risk")).toBeInTheDocument();
  });
  it("renders a classification badge", () => {
    render(<ClassificationBadge value="restricted" />);
    expect(screen.getByText("Restricted")).toBeInTheDocument();
  });
  it("renders a synthetic badge", () => {
    render(<SyntheticBadge />);
    expect(screen.getByText(/SYNTHETIC/i)).toBeInTheDocument();
  });
  it("renders a mode badge for MOCK", () => {
    render(<ModeBadge mode="MOCK" />);
    expect(screen.getByText(/MOCK MODE/i)).toBeInTheDocument();
  });
  it("renders a mode badge for a live provider", () => {
    render(<ModeBadge mode="LIVE" />);
    expect(screen.getByText(/LIVE/i)).toBeInTheDocument();
  });
  it("renders incident, run, action, approval, decision and verification badges", () => {
    const { container } = render(
      <>
        <IncidentStatusBadge value="open" />
        <RunStatusBadge value="awaiting_approval" />
        <ActionStatusBadge value="succeeded" />
        <ApprovalStatusBadge value="pending" />
        <DecisionBadge value="deny" />
        <VerificationBadge value="verified_resolved" />
        <OutcomeBadge value="resolved" />
      </>,
    );
    expect(screen.getByText("Open")).toBeInTheDocument();
    expect(screen.getByText(/Awaiting approval/i)).toBeInTheDocument();
    expect(screen.getByText("Succeeded")).toBeInTheDocument();
    expect(screen.getByText("Pending")).toBeInTheDocument();
    expect(container.textContent).toContain("DENY");
    expect(container.textContent).toContain("Verified");
    expect(container.textContent).toContain("Resolved");
  });
});
