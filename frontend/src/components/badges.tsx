import { Bot, FlaskConical, LoaderCircle, Lock } from "lucide-react";
import { humanize } from "../lib/format";
import { Badge, type Tone } from "./ui";

const SEVERITY: Record<string, Tone> = { critical: "danger", high: "warning", medium: "info", low: "neutral" };
const INCIDENT_STATUS: Record<string, Tone> = {
  open: "warning", investigating: "info", awaiting_approval: "purple", mitigated: "navy", resolved: "success", closed: "neutral",
};
const RUN_STATUS: Record<string, Tone> = {
  queued: "neutral", running: "info", awaiting_approval: "purple", completed: "success", failed: "danger", cancelled: "neutral", interrupted: "warning",
};
const RISK: Record<string, Tone> = { read_only: "neutral", low: "success", medium: "warning", high: "danger", prohibited: "danger" };
const CLASSIFICATION: Record<string, Tone> = { public: "neutral", internal: "navy", confidential: "warning", restricted: "danger" };
const ACTION_STATUS: Record<string, Tone> = {
  pending_approval: "purple", approved: "info", approved_by_policy: "info", executing: "info", succeeded: "success", failed: "danger",
  rejected: "danger", denied: "danger", cancelled: "neutral", expired: "neutral", invalidated: "neutral", skipped: "neutral", rolled_back: "warning",
};
const APPROVAL_STATUS: Record<string, Tone> = {
  pending: "purple", approved: "success", rejected: "danger", cancelled: "neutral", expired: "neutral", invalidated: "neutral",
};
const OUTCOME: Record<string, Tone> = {
  resolved: "success", partially_resolved: "warning", unresolved: "danger", no_action_taken: "neutral",
  insufficient_evidence: "warning", aborted: "danger", dry_run: "neutral",
};
const VERIFICATION: Record<string, Tone> = {
  resolved: "success", partially_resolved: "warning", unresolved: "danger", error: "danger", not_verified: "neutral",
};

export function SeverityBadge({ value }: { value: string }) {
  return <Badge tone={SEVERITY[value] ?? "neutral"}>{humanize(value)}</Badge>;
}

export function IncidentStatusBadge({ value }: { value: string }) {
  return <Badge tone={INCIDENT_STATUS[value] ?? "neutral"}>{humanize(value)}</Badge>;
}

export function RunStatusBadge({ value }: { value: string }) {
  return (
    <Badge tone={RUN_STATUS[value] ?? "neutral"}>
      {(value === "running" || value === "queued") && <LoaderCircle className="size-3 animate-spin" aria-hidden />}
      {humanize(value)}
    </Badge>
  );
}

export function RiskBadge({ value }: { value?: string | null }) {
  if (!value) return <Badge>Risk n/a</Badge>;
  return <Badge tone={RISK[value] ?? "neutral"}>{value === "prohibited" ? "PROHIBITED" : `${humanize(value)} risk`}</Badge>;
}

export function ClassificationBadge({ value }: { value: string }) {
  return (
    <Badge tone={CLASSIFICATION[value] ?? "neutral"} title={`Data classification: ${value}`}>
      {value === "restricted" && <Lock className="size-3" aria-hidden />}
      {humanize(value)}
    </Badge>
  );
}

export function DecisionBadge({ value }: { value: string }) {
  if (value === "allow") return <Badge tone="success">ALLOW</Badge>;
  if (value === "deny") return <Badge tone="danger">DENY</Badge>;
  return <Badge tone="purple">APPROVAL REQUIRED</Badge>;
}

export function ActionStatusBadge({ value }: { value: string }) {
  return <Badge tone={ACTION_STATUS[value] ?? "neutral"}>{humanize(value)}</Badge>;
}

export function ApprovalStatusBadge({ value }: { value: string }) {
  return <Badge tone={APPROVAL_STATUS[value] ?? "neutral"}>{humanize(value)}</Badge>;
}

export function OutcomeBadge({ value }: { value?: string | null }) {
  if (!value) return null;
  return <Badge tone={OUTCOME[value] ?? "neutral"}>Outcome: {humanize(value)}</Badge>;
}

export function VerificationBadge({ value }: { value?: string | null }) {
  if (!value) return <Badge>Not verified</Badge>;
  return <Badge tone={VERIFICATION[value] ?? "neutral"}>Verification: {humanize(value)}</Badge>;
}

export function ModeBadge({ mode }: { mode?: string | null }) {
  if (!mode) return null;
  if (mode.toUpperCase() === "MOCK") {
    return (
      <Badge tone="warning" title="Deterministic offline mock provider - outputs are not real model inference.">
        <FlaskConical className="size-3" aria-hidden /> MOCK MODE
      </Badge>
    );
  }
  return (
    <Badge tone="navy" title="Responses come from the configured live model provider.">
      <Bot className="size-3" aria-hidden /> LIVE MODEL
    </Badge>
  );
}

const SOURCE_LABEL: Record<string, [string, Tone]> = {
  mock: ["MOCK MODE output", "warning"],
  live_model: ["Live model output", "navy"],
  deterministic: ["Deterministic (no model)", "neutral"],
  unavailable: ["Model unavailable - not generated", "danger"],
};

export function SourceBadge({ source }: { source?: string | null }) {
  if (!source) return null;
  const [label, tone] = SOURCE_LABEL[source] ?? [humanize(source), "neutral" as Tone];
  return <Badge tone={tone}>{label}</Badge>;
}

export function SyntheticBadge() {
  return <Badge tone="neutral" title="Fictional data generated for this demo">SYNTHETIC</Badge>;
}
