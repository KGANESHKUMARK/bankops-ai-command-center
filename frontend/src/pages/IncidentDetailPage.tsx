import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowRight, Bot, ShieldAlert } from "lucide-react";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router";
import { errorMessage } from "../api/client";
import { endpoints } from "../api/endpoints";
import type { IncidentDetail } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { ClassificationBadge, IncidentStatusBadge, ModeBadge, OutcomeBadge, RunStatusBadge, SeverityBadge, SyntheticBadge } from "../components/badges";
import { Badge, Button, Card, EmptyState, ErrorState, Field, KeyValue, Loading, PageHeader, Table, Time, cx, inputClass, td, th } from "../components/ui";
import { formatDateTime, humanize } from "../lib/format";

const SERVICE_TONE: Record<string, string> = {
  healthy: "border-emerald-300 bg-emerald-50", degraded: "border-amber-300 bg-amber-50", down: "border-red-300 bg-red-50", unknown: "border-slate-300 bg-slate-50",
};

function DependencyMap({ map }: { map: IncidentDetail["dependency_map"] }) {
  if (!map.nodes.length) return <EmptyState title="No dependency data" />;
  return (
    <div className="space-y-4">
      <ul className="flex flex-wrap gap-2" aria-label="Services">
        {map.nodes.map((node) => (
          <li key={node.key} className={cx("rounded-md border px-2.5 py-1.5 text-xs", SERVICE_TONE[node.status] ?? SERVICE_TONE.unknown, node.focus && "ring-2 ring-navy-400")}>
            <span className="font-mono font-medium text-slate-900">{node.key}</span>
            <span className="ml-1.5 text-slate-600">{humanize(node.status)}</span>
            {node.focus && <span className="sr-only"> (affected by this incident)</span>}
          </li>
        ))}
      </ul>
      <ul className="space-y-1 text-sm" aria-label="Dependencies">
        {map.edges.map((edge) => (
          <li key={`${edge.from}-${edge.to}`} className="flex flex-wrap items-center gap-2">
            <code className="text-xs">{edge.from}</code>
            <ArrowRight className="size-3.5 text-slate-400" aria-label="depends on" />
            <code className="text-xs">{edge.to}</code>
            <Badge>{humanize(edge.type)}</Badge>
          </li>
        ))}
      </ul>
      <p className="text-xs text-slate-500">Service status is live synthetic state; simulated remediation changes it.</p>
    </div>
  );
}

export function IncidentDetailPage() {
  const { incidentId = "" } = useParams();
  const { can, user } = useAuth();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const [notes, setNotes] = useState("");
  const incident = useQuery({ queryKey: ["incident", incidentId], queryFn: () => endpoints.incident(incidentId), refetchInterval: 15000 });
  const start = useMutation({
    mutationFn: () => endpoints.startInvestigation(incidentId, notes.trim() || null),
    onSuccess: (run) => {
      void queryClient.invalidateQueries({ queryKey: ["incident", incidentId] });
      navigate(`/investigations/${run.id}`);
    },
  });

  if (incident.isPending) return <Loading label="Loading incident…" />;
  if (incident.isError) return <ErrorState error={incident.error} title="Incident unavailable" onRetry={() => void incident.refetch()} />;
  const inc = incident.data;
  const running = inc.investigations.find((run) => run.status === "queued" || run.status === "running");
  const startBlocked = !can("investigations:start")
    ? `Your role (${humanize(user?.role)}) cannot start investigations.`
    : !inc.can_investigate ? "Your clearance does not allow investigating this incident."
      : running ? "An investigation is already running for this incident." : null;

  return (
    <div className="space-y-5">
      <PageHeader
        title={<span>{inc.number} · {inc.title}</span>}
        description={inc.description}
        actions={<Link to="/incidents" className="text-sm font-medium text-navy-700 hover:underline">← All incidents</Link>}
      >
        <div className="mt-2 flex flex-wrap gap-2">
          <SeverityBadge value={inc.severity} /><IncidentStatusBadge value={inc.status} /><ClassificationBadge value={inc.classification} /><SyntheticBadge />
          {inc.scenario_key && <Badge tone="navy">Guided scenario: {humanize(inc.scenario_key)}</Badge>}
        </div>
      </PageHeader>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card title="Incident summary" className="xl:col-span-2">
          <KeyValue items={[
            ["Impact", inc.impact],
            ["Customer impact (synthetic)", inc.customer_impact ?? "—"],
            ["Owner team", inc.owner_team],
            ["Primary service", inc.primary_service ? <code>{inc.primary_service}</code> : "—"],
            ["Affected services", inc.affected_services.join(", ") || "—"],
            ["Category", humanize(inc.category)],
            ["Detected", formatDateTime(inc.detected_at)],
            ["Resolved", formatDateTime(inc.resolved_at)],
          ]} />
          {inc.attributes && Object.keys(inc.attributes).length > 0 && (
            <div className="mt-4">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Diagnostic attributes</h3>
              <ul className="mt-1 flex flex-wrap gap-2">
                {Object.entries(inc.attributes).map(([k, v]) => <li key={k}><Badge>{humanize(k)}: {String(v)}</Badge></li>)}
              </ul>
            </div>
          )}
          {inc.resolution_summary && <p className="mt-4 rounded-md bg-emerald-50 p-3 text-sm text-emerald-900">Resolution: {inc.resolution_summary}</p>}
        </Card>

        <Card title="AI investigation" description="Bounded multi-agent workflow with a deterministic policy gate">
          <Field label="Analyst notes (optional — treated as untrusted input)" htmlFor="inv-notes">
            <textarea id="inv-notes" rows={3} maxLength={1000} className={inputClass} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Context for the triage agent" />
          </Field>
          <div className="mt-3">
            <Button icon={<Bot className="size-4" aria-hidden />} loading={start.isPending} disabledReason={startBlocked} onClick={() => start.mutate()}>
              Start AI investigation
            </Button>
          </div>
          {running && <p className="mt-2 text-sm"><Link className="font-medium text-navy-700 underline" to={`/investigations/${running.id}`}>Open the running investigation</Link></p>}
          {start.isError && <p role="alert" className="mt-2 text-sm text-red-700">{errorMessage(start.error)}</p>}
          <p className="mt-3 flex items-start gap-1.5 text-xs text-slate-500">
            <ShieldAlert className="mt-0.5 size-3.5 shrink-0" aria-hidden />
            Starting a new investigation invalidates pending approvals from older plans for this incident.
          </p>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Event timeline">
          {inc.timeline.length === 0 ? <EmptyState title="No timeline events" /> : (
            <ol className="relative space-y-3 border-l border-slate-200 pl-4">
              {inc.timeline.map((event) => (
                <li key={event.id}>
                  <span className="absolute -left-1.5 mt-1.5 size-3 rounded-full border-2 border-white bg-navy-500" aria-hidden />
                  <p className="text-xs text-slate-500">{formatDateTime(event.occurred_at)} · {humanize(event.event_type)} · {event.source}</p>
                  <p className="text-sm text-slate-800">{event.summary}</p>
                </li>
              ))}
            </ol>
          )}
        </Card>
        <Card title="Service dependency map"><DependencyMap map={inc.dependency_map} /></Card>
      </div>

      <Card title="Synthetic logs" description="Untrusted content: instruction-like lines are neutralized before display and before any agent sees them" bodyClassName="px-0 py-0">
        {inc.logs.length === 0 ? <div className="p-5"><EmptyState title="No logs for affected services" /></div> : (
          <div className="max-h-96 overflow-auto">
            <Table label="Synthetic logs">
              <thead className="sticky top-0 bg-slate-50"><tr><th className={th}>Time</th><th className={th}>Level</th><th className={th}>Service</th><th className={th}>Message</th></tr></thead>
              <tbody className="divide-y divide-slate-100 font-mono text-xs">
                {inc.logs.map((line) => (
                  <tr key={line.id}>
                    <td className={`${td} whitespace-nowrap text-xs`}>{formatDateTime(line.ts)}</td>
                    <td className={td}><Badge tone={line.level === "ERROR" ? "danger" : line.level === "WARN" ? "warning" : "neutral"}>{line.level}</Badge></td>
                    <td className={`${td} text-xs`}>{line.service}</td>
                    <td className={`${td} break-all text-xs`}>{line.message}{line.neutralized && <Badge tone="purple" className="ml-2">injection neutralized</Badge>}</td>
                  </tr>
                ))}
              </tbody>
            </Table>
          </div>
        )}
      </Card>

      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Investigation history" bodyClassName="px-0 py-0">
          {inc.investigations.length === 0 ? <div className="p-5"><EmptyState title="No investigations yet" /></div> : (
            <Table label="Investigation history">
              <thead className="bg-slate-50"><tr><th className={th}>Run</th><th className={th}>Status</th><th className={th}>Requested by</th><th className={th}>Created</th></tr></thead>
              <tbody className="divide-y divide-slate-100">
                {inc.investigations.map((run) => (
                  <tr key={run.id}>
                    <td className={td}><Link className="font-mono text-xs font-medium text-navy-700 hover:underline" to={`/investigations/${run.id}`}>{run.id.slice(0, 8)}</Link> <ModeBadge mode={run.model_mode} /></td>
                    <td className={td}><div className="flex flex-wrap gap-1"><RunStatusBadge value={run.status} /><OutcomeBadge value={run.outcome} /></div></td>
                    <td className={td}>{run.requested_by}</td>
                    <td className={td}><Time value={run.created_at} /></td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card>
        <Card title="Related incidents" description="Same category, visible to your role">
          {inc.related_incidents.length === 0 ? <EmptyState title="No related incidents" /> : (
            <ul className="divide-y divide-slate-100">
              {inc.related_incidents.map((related) => (
                <li key={related.id} className="flex flex-wrap items-center justify-between gap-2 py-2 text-sm">
                  <Link to={`/incidents/${related.id}`} className="font-medium text-navy-700 hover:underline">{related.number} · {related.title}</Link>
                  <span className="flex gap-1"><SeverityBadge value={related.severity} /><IncidentStatusBadge value={related.status} /></span>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </div>
  );
}
