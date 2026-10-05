import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { endpoints } from "../api/endpoints";
import type { Stats, TraceSpan } from "../api/types";
import { RunStatusBadge } from "../components/badges";
import { Badge, Card, EmptyState, ErrorState, Field, KeyValue, Loading, Notice, PageHeader, Stat, Table, Time, cx, inputClass, td, th } from "../components/ui";
import { formatDuration, formatNumber, formatSeconds, formatUsd, humanize, pct } from "../lib/format";

function StatsCells({ stats, unit = "ms" }: { stats: Stats; unit?: "ms" | "s" }) {
  const fmt = (v: number | null) => (unit === "ms" ? formatDuration(v) : formatSeconds(v));
  return (<><td className={`${td} tabular-nums`}>{stats.count}</td><td className={`${td} tabular-nums`}>{fmt(stats.p50)}</td><td className={`${td} tabular-nums`}>{fmt(stats.p95)}</td><td className={`${td} tabular-nums`}>{fmt(stats.max)}</td></>);
}

function SpanRow({ span, total, depth }: { span: TraceSpan; total: number; depth: number }) {
  const left = total > 0 ? (span.start_ms / total) * 100 : 0;
  const width = total > 0 ? Math.max(0.6, ((span.duration_ms ?? 0) / total) * 100) : 0;
  const color = span.status === "error" || span.status === "failed" || span.status === "deny" ? "bg-red-500" : span.kind === "agent_step" ? "bg-navy-600" : span.kind === "llm_call" ? "bg-violet-500" : span.kind === "policy_decision" ? "bg-amber-500" : "bg-slate-400";
  return (
    <>
      <li className="grid grid-cols-[minmax(0,16rem)_1fr] items-center gap-3 py-1 text-xs">
        <span className="truncate" style={{ paddingLeft: depth * 14 }} title={span.message ?? span.name ?? ""}>
          <span className={cx(depth === 0 && "font-semibold text-slate-900")}>{span.name ?? humanize(span.kind)}</span>
          <span className="ml-1 text-slate-500">{formatDuration(span.duration_ms)}</span>
        </span>
        <span className="relative h-3 rounded bg-slate-100" aria-hidden>
          <span className={cx("absolute top-0 h-3 rounded", color)} style={{ left: `${left}%`, width: `${Math.min(width, 100 - left)}%` }} />
        </span>
      </li>
      {span.children?.map((child, index) => <SpanRow key={`${child.name}-${index}`} span={child} total={total} depth={depth + 1} />)}
    </>
  );
}

function TraceViewer() {
  const runs = useQuery({ queryKey: ["investigations", "trace-picker"], queryFn: () => endpoints.investigations({ page_size: 25 }) });
  const [runId, setRunId] = useState("");
  const selected = runId || runs.data?.items[0]?.id || "";
  const trace = useQuery({ queryKey: ["trace", selected], queryFn: () => endpoints.trace(selected), enabled: !!selected });
  const spans = trace.data?.spans ?? [];
  const end = spans.reduce((max, s) => Math.max(max, s.start_ms + (s.duration_ms ?? 0), ...(s.children ?? []).map((c) => c.start_ms + (c.duration_ms ?? 0))), 0);
  return (
    <Card title="Investigation trace" description="Agent step spans with nested tool, model and policy events (correlated by investigation and request IDs)"
      actions={runs.data && runs.data.items.length > 0 && (
        <Field label="Investigation" htmlFor="trace-run">
          <select id="trace-run" className={inputClass} value={selected} onChange={(e) => setRunId(e.target.value)}>
            {runs.data.items.map((r) => <option key={r.id} value={r.id}>{r.incident_number} · {r.id.slice(0, 8)} · {r.status}</option>)}
          </select>
        </Field>
      )}>
      {runs.isPending ? <Loading /> : !selected ? <EmptyState title="No investigations to trace yet" /> : trace.isPending ? <Loading /> : trace.isError ? <ErrorState error={trace.error} /> : (
        <div className="space-y-3">
          <div className="flex flex-wrap items-center gap-2 text-xs text-slate-600">
            <RunStatusBadge value={trace.data.status} />
            <span>correlation <code>{trace.data.correlation_id?.slice(0, 12) ?? "—"}</code></span>
            <span>{trace.data.totals.steps} steps · {trace.data.totals.tool_calls} tool calls · {formatNumber(trace.data.totals.input_tokens + trace.data.totals.output_tokens)} tokens · {formatUsd(trace.data.totals.estimated_cost_usd)} (estimate)</span>
            <Link to={`/investigations/${trace.data.investigation_id}`} className="text-navy-700 underline">open workspace</Link>
          </div>
          {spans.length === 0 ? <EmptyState title="No spans recorded" /> : <ul aria-label="Trace spans">{spans.map((s, i) => <SpanRow key={`${s.name}-${i}`} span={s} total={end} depth={0} />)}</ul>}
          <p className="text-xs text-slate-500">Legend: navy = agent step, violet = model call, amber = policy decision, grey = tool call, red = error/deny.</p>
        </div>
      )}
    </Card>
  );
}

export function ObservabilityPage() {
  const summary = useQuery({ queryKey: ["observability"], queryFn: endpoints.observability, refetchInterval: 15000 });
  if (summary.isPending) return <Loading label="Loading observability metrics…" />;
  if (summary.isError) return <ErrorState error={summary.error} onRetry={() => void summary.refetch()} />;
  const s = summary.data;
  const agentData = Object.entries(s.agents).map(([agent, st]) => ({ agent: agent.replace(/ \(.*\)/, ""), p95: st.p95 ?? 0, p50: st.p50 ?? 0 }));
  const activeFaults = Object.entries(s.faults).filter(([, on]) => on).map(([name]) => name);
  return (
    <div className="space-y-5">
      <PageHeader title="Observability" description="Request, workflow, agent, tool, model, retrieval, policy and approval metrics. Token counts and costs are labeled where estimated." />
      {activeFaults.length > 0 && <Notice tone="warning" title="Failure injection active">{activeFaults.map(humanize).join(", ")} — runs will show degraded behavior by design.</Notice>}
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <Stat label="HTTP requests" value={formatNumber(s.http.requests_total)} hint={`p95 ${formatDuration(s.http.latency_ms.p95)} · 5xx ${pct(s.http.error_rate_5xx, 1)}`} />
        <Stat label="Investigations" value={s.workflow.runs} hint={`failure rate ${pct(s.workflow.failure_rate, 1)} · ${s.workflow.degraded_runs} degraded`} />
        <Stat label="LLM calls" value={s.llm.calls} hint={`${s.llm.mock_calls} mock · ${s.llm.errors} errors · ${s.llm.skipped} skipped`} />
        <Stat label="Policy denials" value={s.policy.denials} hint={`${s.policy.decisions} decisions · ${s.policy.approvals_required} required approval`} />
      </div>
      <div className="grid gap-4 xl:grid-cols-3">
        <Card title="Model gateway" description="Provider resilience: timeouts, bounded retries with jitter, circuit breaker">
          <KeyValue columns={1} items={[
            ["Provider / model", `${s.gateway.provider} / ${s.gateway.model}`],
            ["Mode", <Badge key="m" tone={s.gateway.mode === "MOCK" ? "warning" : "navy"}>{s.gateway.mode === "MOCK" ? "MOCK MODE" : s.gateway.mode}</Badge>],
            ["Circuit breaker", <Badge key="cb" tone={s.gateway.circuit_breaker === "closed" ? "success" : "danger"}>{s.gateway.circuit_breaker}</Badge>],
            ["Latency p50 / p95", `${formatDuration(s.llm.latency_ms.p50)} / ${formatDuration(s.llm.latency_ms.p95)}`],
            [`Tokens in / out${s.llm.tokens_estimated ? " (estimated)" : ""}`, `${formatNumber(s.llm.input_tokens)} / ${formatNumber(s.llm.output_tokens)}`],
            ["Cost (ESTIMATE)", formatUsd(s.llm.estimated_cost_usd)],
            ["Error codes", Object.keys(s.llm.error_codes).length ? Object.entries(s.llm.error_codes).map(([k, v]) => `${k}: ${v}`).join(", ") : "none"],
          ]} />
          <p className="mt-3 text-xs text-slate-500">{s.llm.cost_note}</p>
        </Card>
        <Card title="Agent latency (p95)" className="xl:col-span-2">
          {agentData.length === 0 ? <EmptyState title="No agent steps recorded yet" /> : (
            <div role="img" aria-label="Bar chart of p95 latency per agent" className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={agentData} layout="vertical" margin={{ left: 40, right: 16 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" horizontal={false} />
                  <XAxis type="number" tick={{ fontSize: 11, fill: "#64748b" }} unit=" ms" />
                  <YAxis type="category" dataKey="agent" width={170} tick={{ fontSize: 11, fill: "#334155" }} />
                  <Tooltip />
                  <Bar dataKey="p95" name="p95 ms" fill="#2f5186" />
                  <Bar dataKey="p50" name="p50 ms" fill="#9ab1d6" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </Card>
      </div>
      <div className="grid gap-4 xl:grid-cols-2">
        <Card title="Agents" bodyClassName="px-0 py-0">
          <Table label="Agent latency">
            <thead className="bg-slate-50"><tr><th className={th}>Agent</th><th className={th}>Count</th><th className={th}>p50</th><th className={th}>p95</th><th className={th}>Max</th></tr></thead>
            <tbody className="divide-y divide-slate-100">{Object.entries(s.agents).map(([agent, st]) => <tr key={agent}><td className={`${td} text-xs`}>{agent}</td><StatsCells stats={st} /></tr>)}</tbody>
          </Table>
        </Card>
        <Card title="Tools" bodyClassName="px-0 py-0">
          <Table label="Tool latency">
            <thead className="bg-slate-50"><tr><th className={th}>Tool</th><th className={th}>Count</th><th className={th}>p50</th><th className={th}>p95</th><th className={th}>Max</th><th className={th}>Errors</th></tr></thead>
            <tbody className="divide-y divide-slate-100">{Object.entries(s.tools).map(([tool, st]) => <tr key={tool}><td className={`${td} font-mono text-xs`}>{tool}</td><StatsCells stats={st} /><td className={`${td} tabular-nums ${st.errors ? "text-red-700" : ""}`}>{st.errors}</td></tr>)}</tbody>
          </Table>
        </Card>
      </div>
      <div className="grid gap-4 xl:grid-cols-3">
        <Card title="Workflow">
          <KeyValue columns={1} items={[
            ["Runs by status", Object.entries(s.workflow.by_status).map(([k, v]) => `${humanize(k)}: ${v}`).join(", ") || "—"],
            ["Duration p50 / p95", `${formatSeconds(s.workflow.duration_seconds.p50)} / ${formatSeconds(s.workflow.duration_seconds.p95)}`],
            ["Failure rate", pct(s.workflow.failure_rate, 1)],
            ["Degraded runs", s.workflow.degraded_runs],
          ]} />
        </Card>
        <Card title="Retrieval">
          <KeyValue columns={1} items={[
            ["Queries", s.retrieval.queries],
            ["Latency p50 / p95", `${formatDuration(s.retrieval.latency_ms.p50)} / ${formatDuration(s.retrieval.latency_ms.p95)}`],
            ["Sufficiency rate", pct(s.retrieval.sufficiency_rate)],
            ["Avg results / errors", `${s.retrieval.avg_results ?? "—"} / ${s.retrieval.errors}`],
          ]} />
        </Card>
        <Card title="Approvals & HTTP">
          <KeyValue columns={1} items={[
            ["Pending approvals", s.approvals.pending],
            ["Approval wait p50 / p95", `${formatSeconds(s.approvals.wait_seconds.p50)} / ${formatSeconds(s.approvals.wait_seconds.p95)}`],
            ["HTTP latency p50 / p95 / p99", `${formatDuration(s.http.latency_ms.p50)} / ${formatDuration(s.http.latency_ms.p95)} / ${formatDuration(s.http.latency_ms.p99)}`],
            ["HTTP 4xx / 5xx", `${s.http.errors_4xx} / ${s.http.errors_5xx}`],
          ]} />
          <p className="mt-2 text-xs text-slate-500">{s.http.scope}</p>
        </Card>
      </div>
      <TraceViewer />
      <Card title="Recent errors and denials" bodyClassName="px-0 py-0">
        {s.recent_errors.length === 0 ? <div className="p-5"><EmptyState title="No recent errors" /></div> : (
          <Table label="Recent errors">
            <thead className="bg-slate-50"><tr><th className={th}>When</th><th className={th}>Where</th><th className={th}>Status</th><th className={th}>Message</th></tr></thead>
            <tbody className="divide-y divide-slate-100">
              {s.recent_errors.map((e) => (
                <tr key={`${e.investigation_id}-${e.seq}`}>
                  <td className={td}><Time value={e.at} /></td>
                  <td className={`${td} text-xs`}>{e.agent}{e.tool && <code className="ml-1">{e.tool}</code>}<p><Link className="text-navy-700 underline" to={`/investigations/${e.investigation_id}`}>run {e.investigation_id.slice(0, 8)}</Link></p></td>
                  <td className={td}><Badge tone="danger">{e.status}</Badge></td>
                  <td className={`${td} text-xs`}>{e.message}</td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}
