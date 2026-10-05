import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CirclePlay, UserRound } from "lucide-react";
import { Link, useNavigate } from "react-router";
import { errorMessage } from "../api/client";
import { endpoints } from "../api/endpoints";
import type { Scenario } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { IncidentStatusBadge } from "../components/badges";
import { useToast } from "../components/Toast";
import { Badge, Button, Card, EmptyState, ErrorState, Loading, Notice, PageHeader } from "../components/ui";
import { humanize } from "../lib/format";
import { DemoControls } from "./SettingsPage";

const FIVE_MINUTE_SCRIPT = [
  "Overview (30s): synthetic banner, KPIs, MOCK MODE badge, measured AI-quality panel.",
  "Scenario A (2m): as ops.analyst start the statement outage; narrate the live timeline, authorized citations, ranked hypotheses and the deterministic policy decisions.",
  "Approval (1m): sign in as ops.manager, open the Approval Center, show the policy explanation and evidence, approve with explicit confirmation.",
  "Outcome (1m): the workflow resumes — simulated restart, reprocess, verification checks and the final report with citations.",
  "Governance (30s): verify the audit hash chain; show RBAC, the policy catalog and a denied prohibited action in Policy decisions.",
];

function ScenarioCard({ scenario }: { scenario: Scenario }) {
  const { can, user } = useAuth();
  const navigate = useNavigate();
  const toast = useToast();
  const queryClient = useQueryClient();
  const start = useMutation({
    mutationFn: () => endpoints.startInvestigation(scenario.incident_id ?? "", null),
    onSuccess: (run) => {
      void queryClient.invalidateQueries({ queryKey: ["scenarios"] });
      navigate(`/investigations/${run.id}`);
    },
    onError: (error) => toast(errorMessage(error), "error"),
  });
  const resolved = scenario.incident_status === "resolved" || scenario.incident_status === "closed";
  const blocked = !scenario.available || !scenario.incident_id ? "Scenario incident not found in your tenant (reset the demo)."
    : !can("investigations:start") ? `Your role (${humanize(user?.role)}) cannot start investigations — sign in as ${scenario.personas.investigator}.`
      : null;
  return (
    <Card title={scenario.title} description={scenario.summary}
      actions={<><Badge tone="navy">{scenario.incident_number}</Badge>{scenario.incident_status && <IncidentStatusBadge value={scenario.incident_status} />}</>}>
      <div className="space-y-3">
        <p className="flex flex-wrap items-center gap-2 text-xs text-slate-600">
          <UserRound className="size-3.5" aria-hidden /> Investigator <code>{scenario.personas.investigator}</code> · Approver <code>{scenario.personas.approver}</code>
        </p>
        <ol className="list-decimal space-y-1 pl-5 text-sm text-slate-700">{scenario.steps.map((step) => <li key={step}>{step}</li>)}</ol>
        <p className="text-sm text-slate-700"><strong>Expected outcome:</strong> {scenario.expected_outcome}</p>
        {resolved && <Notice tone="info">This incident is already {scenario.incident_status}. Reset the demo for a clean run (you can still start a new investigation).</Notice>}
        <div className="flex flex-wrap items-center gap-3">
          <Button icon={<CirclePlay className="size-4" aria-hidden />} loading={start.isPending} disabledReason={blocked} onClick={() => start.mutate()}>Start scenario</Button>
          {scenario.incident_id && <Link to={`/incidents/${scenario.incident_id}`} className="text-sm font-medium text-navy-700 hover:underline">View incident</Link>}
        </div>
      </div>
    </Card>
  );
}

export function DemoPage() {
  const scenarios = useQuery({ queryKey: ["scenarios"], queryFn: endpoints.scenarios });
  const accounts = useQuery({ queryKey: ["demo-accounts"], queryFn: endpoints.demoAccounts, staleTime: Infinity });
  return (
    <div className="space-y-5">
      <PageHeader title="Guided demo" description="Three end-to-end scenarios that run fully offline in MOCK MODE: investigation, authorized evidence, policy gate, human approval, simulated remediation, verification and audit." />
      <Notice tone="warning" title="SYNTHETIC DEMO DATA">Every bank, customer, account ID, amount, service and log line here is fictional. Remediation only mutates seeded demo state.</Notice>
      {scenarios.isPending ? <Loading /> : scenarios.isError ? <ErrorState error={scenarios.error} onRetry={() => void scenarios.refetch()} /> : scenarios.data.length === 0 ? <EmptyState title="No scenarios configured" /> : (
        <div className="grid gap-4 xl:grid-cols-3">{scenarios.data.map((scenario) => <ScenarioCard key={scenario.key} scenario={scenario} />)}</div>
      )}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="5-minute walkthrough">
          <ol className="list-decimal space-y-1.5 pl-5 text-sm text-slate-700">{FIVE_MINUTE_SCRIPT.map((step) => <li key={step}>{step}</li>)}</ol>
          <p className="mt-3 text-xs text-slate-500">Switch personas with <em>Sign out</em> in the header. Separation of duties: a requester can never approve their own high-risk action.</p>
        </Card>
        <Card title="Demo accounts" description="Local-only accounts; password is DEMO_PASSWORD from .env (see README)">
          {accounts.isPending ? <Loading /> : accounts.isError ? <ErrorState error={accounts.error} /> : (
            <ul className="grid gap-1 text-sm sm:grid-cols-2">{accounts.data.map((a) => <li key={a.username}><code className="font-mono">{a.username}</code> <span className="text-xs text-slate-500">{humanize(a.role)} · {a.tenant_id}</span></li>)}</ul>
          )}
        </Card>
      </div>
      <DemoControls />
    </div>
  );
}
