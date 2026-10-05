import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router";
import { endpoints } from "../api/endpoints";
import { ModeBadge, OutcomeBadge, RiskBadge, RunStatusBadge } from "../components/badges";
import { Badge, Card, EmptyState, ErrorState, Field, Loading, PageHeader, Pagination, Table, Time, inputClass, td, th } from "../components/ui";
import { humanize } from "../lib/format";

const STATUSES = ["", "queued", "running", "awaiting_approval", "completed", "failed", "cancelled", "interrupted"];
const PAGE_SIZE = 20;

export function InvestigationsPage() {
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const runs = useQuery({
    queryKey: ["investigations", status, page],
    queryFn: () => endpoints.investigations({ status, page, page_size: PAGE_SIZE }),
    placeholderData: keepPreviousData,
    refetchInterval: 10000,
  });
  return (
    <div className="space-y-5">
      <PageHeader title="AI Investigations" description="Bounded LangGraph investigation runs visible to your role. Open a run to see its live timeline, evidence, policy decisions and report."
        actions={<Field label="Status" htmlFor="run-status"><select id="run-status" className={inputClass} value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>{STATUSES.map((s) => <option key={s} value={s}>{s ? humanize(s) : "All"}</option>)}</select></Field>} />
      <Card bodyClassName="px-0 py-0">
        {runs.isPending ? <Loading /> : runs.isError ? <div className="p-5"><ErrorState error={runs.error} onRetry={() => void runs.refetch()} /></div> : runs.data.items.length === 0 ? (
          <div className="p-5"><EmptyState title="No investigations yet"><Link to="/demo" className="text-navy-700 underline">Start a guided scenario</Link></EmptyState></div>
        ) : (
          <>
            <Table label="Investigations">
              <thead className="bg-slate-50"><tr><th className={th}>Incident</th><th className={th}>Status</th><th className={th}>Risk</th><th className={th}>Mode</th><th className={th}>Steps / tools</th><th className={th}>Requested by</th><th className={th}>Created</th></tr></thead>
              <tbody className="divide-y divide-slate-100">
                {runs.data.items.map((run) => (
                  <tr key={run.id} className="hover:bg-slate-50">
                    <td className={td}><Link className="font-medium text-navy-700 hover:underline" to={`/investigations/${run.id}`}>{run.incident_number}</Link><p className="max-w-sm text-xs text-slate-500">{run.incident_title}</p></td>
                    <td className={td}><div className="flex flex-wrap gap-1"><RunStatusBadge value={run.status} /><OutcomeBadge value={run.outcome} />{run.degraded && <Badge tone="warning">Degraded</Badge>}</div></td>
                    <td className={td}><RiskBadge value={run.risk_level} /></td>
                    <td className={td}><ModeBadge mode={run.model_mode} /></td>
                    <td className={`${td} tabular-nums`}>{run.step_count} / {run.tool_call_count}</td>
                    <td className={td}>{run.requested_by}</td>
                    <td className={td}><Time value={run.created_at} /></td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <div className="px-5 pb-3"><Pagination page={page} pageSize={PAGE_SIZE} total={runs.data.total} onPage={setPage} /></div>
          </>
        )}
      </Card>
    </div>
  );
}
