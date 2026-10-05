import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { endpoints } from "../api/endpoints";
import type { DashboardSummary } from "../api/types";
import { IncidentStatusBadge, SeverityBadge } from "../components/badges";
import { Badge, Card, EmptyState, ErrorState, Loading, PageHeader, Stat, Table, Time, td, th } from "../components/ui";
import { formatSeconds, humanize, pct } from "../lib/format";

const SEVERITY_COLORS = { critical: "#b91c1c", high: "#ea580c", medium: "#41679f", low: "#94a3b8" } as const;

const QUALITY_LABELS: Record<string, string> = {
  "retrieval.recall_at_5": "Retrieval Recall@5",
  "retrieval.mrr": "Retrieval MRR",
  "citation.coverage": "Citation coverage",
  "diagnosis.root_cause_accuracy": "Root-cause accuracy",
  "safety.policy_compliance": "Policy compliance",
  "injection.resistance": "Prompt-injection resistance",
  "claims.unsupported_rate": "Unsupported-claim rate",
};

function TrendChart({ data }: { data: DashboardSummary["trend"] }) {
  const total = data.reduce((sum, day) => sum + day.total, 0);
  const peak = data.reduce((best, day) => (day.total > best.total ? day : best), data[0] ?? { date: "", total: 0 });
  return (
    <figure>
      <div role="img" aria-label={`Bar chart of ${total} synthetic incidents over 30 days; peak of ${peak.total} on ${peak.date}.`} className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <BarChart data={data} margin={{ top: 8, right: 8, bottom: 0, left: -18 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" vertical={false} />
            <XAxis dataKey="date" tickFormatter={(value: string) => value.slice(5)} tick={{ fontSize: 11, fill: "#64748b" }} interval={4} />
            <YAxis allowDecimals={false} tick={{ fontSize: 11, fill: "#64748b" }} />
            <Tooltip />
            <Legend wrapperStyle={{ fontSize: 12 }} />
            {(Object.keys(SEVERITY_COLORS) as (keyof typeof SEVERITY_COLORS)[]).map((severity) => (
              <Bar key={severity} dataKey={severity} stackId="severity" fill={SEVERITY_COLORS[severity]} name={humanize(severity)} />
            ))}
          </BarChart>
        </ResponsiveContainer>
      </div>
      <figcaption className="mt-2 text-xs text-slate-500">{total} incidents in the window · peak {peak.total} on {peak.date || "—"}</figcaption>
    </figure>
  );
}

export function OverviewPage() {
  const query = useQuery({ queryKey: ["dashboard"], queryFn: endpoints.dashboard, refetchInterval: 20000 });
  if (query.isPending) return <Loading label="Loading operations overview…" />;
  if (query.isError) return <ErrorState error={query.error} onRetry={() => void query.refetch()} />;
  const d = query.data;
  const severityTotal = Object.values(d.by_severity).reduce((a, b) => a + b, 0);

  return (
    <div className="space-y-5">
      <PageHeader title="Operations overview" description="Synthetic banking operations incidents, investigation activity and measured AI quality.">
        <p className="mt-1 text-xs text-slate-500">Visible data classifications for your role: {d.classification_scope.join(", ")}</p>
      </PageHeader>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="Open incidents" value={d.kpis.open_incidents} hint={`${d.kpis.awaiting_approval} awaiting approval`} />
        <Stat label="Critical / high open" value={d.kpis.critical_high_open} tone={d.kpis.critical_high_open ? "danger" : undefined} hint="Severity critical or high" />
        <Stat label="Pending approvals" value={d.kpis.pending_approvals} tone={d.kpis.pending_approvals ? "warning" : undefined} hint={<Link className="text-navy-700 underline" to="/approvals">Open Approval Center</Link>} />
        <Stat label="MTTR (synthetic)" value={d.kpis.mttr_minutes_synthetic === null ? "—" : `${d.kpis.mttr_minutes_synthetic} min`} hint={`${d.kpis.resolved_incidents} resolved incidents (seeded history)`} />
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card title="Incident trend (30 days)" description={d.trend_note} className="xl:col-span-2">
          {d.trend.length ? <TrendChart data={d.trend} /> : <EmptyState title="No incidents in the window" />}
        </Card>
        <Card title="Open incidents by severity" description="Current open, investigating, awaiting-approval and mitigated incidents">
          {severityTotal === 0 ? <EmptyState title="No open incidents" /> : (
            <ul className="space-y-3">
              {(["critical", "high", "medium", "low"] as const).map((severity) => {
                const count = d.by_severity[severity] ?? 0;
                return (
                  <li key={severity}>
                    <div className="flex items-center justify-between text-sm"><SeverityBadge value={severity} /><span className="tabular-nums text-slate-700">{count}</span></div>
                    <div className="mt-1 h-1.5 rounded-full bg-slate-100"><div className="h-1.5 rounded-full" style={{ width: `${(count / severityTotal) * 100}%`, backgroundColor: SEVERITY_COLORS[severity] }} /></div>
                  </li>
                );
              })}
            </ul>
          )}
          <h3 className="mt-5 text-xs font-semibold uppercase tracking-wide text-slate-500">Open by category</h3>
          <ul className="mt-2 space-y-1 text-sm">
            {Object.entries(d.by_category).sort((a, b) => b[1] - a[1]).map(([category, count]) => (
              <li key={category} className="flex justify-between"><span className="text-slate-700">{humanize(category)}</span><span className="tabular-nums text-slate-500">{count}</span></li>
            ))}
          </ul>
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-3">
        <Card title="Open high-risk incidents" description="Critical and high severity, oldest first" className="xl:col-span-2" bodyClassName="px-0 py-0">
          {d.high_risk_incidents.length === 0 ? <div className="p-5"><EmptyState title="No open high-risk incidents" /></div> : (
            <Table label="Open high-risk incidents">
              <thead className="bg-slate-50"><tr><th className={th}>Incident</th><th className={th}>Severity</th><th className={th}>Status</th><th className={th}>Service</th><th className={th}>Detected</th></tr></thead>
              <tbody className="divide-y divide-slate-100">
                {d.high_risk_incidents.map((incident) => (
                  <tr key={incident.id}>
                    <td className={td}><Link to={`/incidents/${incident.id}`} className="font-medium text-navy-700 hover:underline">{incident.number}</Link><p className="text-xs text-slate-500">{incident.title}</p></td>
                    <td className={td}><SeverityBadge value={incident.severity} /></td>
                    <td className={td}><IncidentStatusBadge value={incident.status} /></td>
                    <td className={td}><code className="text-xs">{incident.primary_service ?? "—"}</code></td>
                    <td className={td}><Time value={incident.detected_at} /></td>
                  </tr>
                ))}
              </tbody>
            </Table>
          )}
        </Card>

        <Card
          title="AI quality indicators"
          description={d.ai_quality.note}
          actions={d.ai_quality.source === "measured"
            ? <Badge tone={d.ai_quality.gate_passed ? "success" : "danger"}>{d.ai_quality.gate_passed ? "Release gate passed" : "Release gate failed"}</Badge>
            : <Badge>Not measured</Badge>}
        >
          {d.ai_quality.source === "measured" ? (
            <>
              <p className="mb-3 text-xs text-slate-500">MEASURED <Time value={d.ai_quality.evaluated_at} /> · <Link to="/evaluations" className="text-navy-700 underline">evaluation details</Link></p>
              <dl className="space-y-2">
                {Object.entries(d.ai_quality.metrics).map(([key, value]) => (
                  <div key={key} className="flex justify-between gap-2 text-sm">
                    <dt className="text-slate-600">{QUALITY_LABELS[key] ?? key}</dt>
                    <dd className="font-medium tabular-nums text-slate-900">{value === null || value === undefined ? "—" : pct(value, 1)}</dd>
                  </div>
                ))}
              </dl>
            </>
          ) : (
            <p className="text-sm text-slate-600">No evaluation has been run for this tenant yet. <Link to="/evaluations" className="text-navy-700 underline">Run the evaluation harness</Link> to measure retrieval, citation, safety and injection resistance.</p>
          )}
          <h3 className="mt-5 text-xs font-semibold uppercase tracking-wide text-slate-500">Investigations (all time)</h3>
          <dl className="mt-2 grid grid-cols-2 gap-2 text-sm">
            <div><dt className="text-xs text-slate-500">Completed</dt><dd className="font-medium">{d.ai_quality.investigations.completed}</dd></div>
            <div><dt className="text-xs text-slate-500">Failed</dt><dd className="font-medium">{d.ai_quality.investigations.failed}</dd></div>
            <div><dt className="text-xs text-slate-500">Degraded</dt><dd className="font-medium">{d.ai_quality.investigations.degraded}</dd></div>
            <div><dt className="text-xs text-slate-500">Median duration</dt><dd className="font-medium">{formatSeconds(d.ai_quality.investigations.median_duration_seconds)}</dd></div>
          </dl>
        </Card>
      </div>

      <Card title="Recent investigation activity" description="Status changes, policy decisions and simulated executions">
        {d.recent_activity.length === 0 ? (
          <EmptyState title="No investigation activity yet"><Link to="/demo" className="text-navy-700 underline">Start a guided demo scenario</Link></EmptyState>
        ) : (
          <ol className="divide-y divide-slate-100">
            {d.recent_activity.map((item, index) => (
              <li key={`${item.investigation_id}-${index}`} className="flex flex-wrap items-start justify-between gap-2 py-2.5 text-sm">
                <div className="min-w-0">
                  <Link to={`/investigations/${item.investigation_id}`} className="font-medium text-navy-700 hover:underline">{item.incident_number ?? "Investigation"}</Link>
                  <span className="ml-2 text-slate-700">{item.message}</span>
                </div>
                <span className="text-xs text-slate-500"><Badge>{humanize(item.event_type)}</Badge> <Time value={item.at} /></span>
              </li>
            ))}
          </ol>
        )}
      </Card>
    </div>
  );
}
