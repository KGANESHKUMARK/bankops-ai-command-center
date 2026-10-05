import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Hourglass, ShieldAlert } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { endpoints } from "../api/endpoints";
import type { ApprovalDetail } from "../api/types";
import { ApprovalControls } from "../components/ApprovalControls";
import { ApprovalStatusBadge, RiskBadge } from "../components/badges";
import { Badge, Card, EmptyState, ErrorState, Field, JsonBlock, Loading, Notice, PageHeader, Pagination, Time, inputClass } from "../components/ui";
import { formatDateTime, humanize } from "../lib/format";

const STATUSES = ["pending", "approved", "rejected", "cancelled", "expired", "invalidated", "all"];
const PAGE_SIZE = 10;

function ApprovalCard({ approval }: { approval: ApprovalDetail }) {
  const action = approval.action;
  const expired = Date.parse(approval.expires_at) <= Date.now();
  return (
    <article className="rounded-lg border border-slate-200 bg-white shadow-sm" aria-label={`Approval for ${action?.tool_name ?? "action"}`}>
      <header className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 px-5 py-3.5">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <RiskBadge value={approval.risk_level} />
            <ApprovalStatusBadge value={approval.status} />
            <Badge tone="warning">SIMULATED ACTION</Badge>
          </div>
          <h2 className="mt-1.5 text-sm font-semibold text-slate-900">
            <code className="font-mono">{action?.tool_name}</code> → {approval.target_resource}
          </h2>
          <p className="text-xs text-slate-600">
            <Link to={`/incidents/${approval.incident_id}`} className="font-medium text-navy-700 hover:underline">{approval.incident_number}</Link> · {approval.incident_title}
          </p>
        </div>
        <div className="text-right text-xs text-slate-500">
          <p>Requested <Time value={approval.created_at} /></p>
          <p className={expired && approval.status === "pending" ? "font-medium text-red-700" : undefined}>
            <Hourglass className="mr-1 inline size-3" aria-hidden />Expires {formatDateTime(approval.expires_at)}
          </p>
        </div>
      </header>
      <div className="grid gap-4 px-5 py-4 lg:grid-cols-2">
        <div className="space-y-3 text-sm">
          <dl className="grid grid-cols-2 gap-2">
            <div><dt className="text-xs text-slate-500">Requester</dt><dd className="font-medium">{approval.requested_by} <span className="text-xs font-normal text-slate-500">({humanize(approval.requested_by_role)})</span></dd></div>
            <div><dt className="text-xs text-slate-500">Approver roles</dt><dd>{approval.required_roles.map(humanize).join(" or ")}</dd></div>
          </dl>
          {action?.rationale && <p className="text-slate-700"><strong>Rationale:</strong> {action.rationale}</p>}
          {action?.expected_effect && <p className="text-slate-700"><strong>Expected effect:</strong> {action.expected_effect}</p>}
          {action?.policy_decision && (
            <Notice tone="purple" icon={<ShieldAlert className="size-4" />} title={`Policy decision ${action.policy_decision.rule_ids.join(", ")}`}>
              {action.policy_decision.explanation}
            </Notice>
          )}
          {action && <details><summary className="cursor-pointer text-xs font-medium text-navy-700">Validated parameters</summary><div className="mt-1"><JsonBlock value={action.parameters} label="Validated parameters" /></div></details>}
          {approval.investigation_id && <Link to={`/investigations/${approval.investigation_id}`} className="inline-block text-sm font-medium text-navy-700 hover:underline">Open investigation workspace →</Link>}
        </div>
        <div className="space-y-2">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Supporting evidence</h3>
          {approval.evidence.length === 0 ? <p className="text-sm text-slate-500">No evidence references were attached to this step.</p> : (
            <ul className="space-y-2">
              {approval.evidence.map((e) => (
                <li key={e.label} className="rounded-md border border-slate-200 p-2.5 text-xs">
                  <p className="font-medium text-slate-900"><Badge tone="navy">{e.label}</Badge> {e.title}</p>
                  {e.citation && <p className="mt-0.5 font-mono text-[11px] text-slate-500">{e.citation}</p>}
                  <p className="mt-1 line-clamp-4 whitespace-pre-wrap text-slate-700">{e.excerpt}</p>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
      <footer className="border-t border-slate-100 px-5 py-3">
        {approval.status === "pending" ? <ApprovalControls approval={approval} /> : (
          <p className="text-sm text-slate-600">
            {humanize(approval.status)}{approval.decided_by && <> by <strong>{approval.decided_by}</strong></>} {approval.decided_at && <Time value={approval.decided_at} />}
            {approval.reason_code && <> · reason <code>{approval.reason_code}</code></>}{approval.comment && <> · “{approval.comment}”</>}
          </p>
        )}
      </footer>
    </article>
  );
}

export function ApprovalsPage() {
  const [status, setStatus] = useState("pending");
  const [page, setPage] = useState(1);
  const approvals = useQuery({
    queryKey: ["approvals", status, page],
    queryFn: () => endpoints.approvals({ status, page, page_size: PAGE_SIZE }),
    refetchInterval: 10000,
    placeholderData: keepPreviousData,
  });
  return (
    <div className="space-y-5">
      <PageHeader
        title="Approval Center"
        description="Human approval for medium/high-risk simulated actions. Requesters cannot approve their own high-risk actions; approvals expire, are bound to the exact action hash and are re-validated before execution."
        actions={
          <Field label="Status" htmlFor="approval-status">
            <select id="approval-status" className={inputClass} value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>
              {STATUSES.map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
            </select>
          </Field>
        }
      />
      {approvals.isPending ? <Loading /> : approvals.isError ? <ErrorState error={approvals.error} onRetry={() => void approvals.refetch()} /> : (
        approvals.data.items.length === 0 ? (
          <Card><EmptyState title={status === "pending" ? "No pending approvals" : "No approvals with this status"}>Start a guided scenario to generate an approval request.</EmptyState></Card>
        ) : (
          <div className="space-y-4">
            {approvals.data.items.map((approval) => <ApprovalCard key={approval.id} approval={approval} />)}
            <Pagination page={page} pageSize={PAGE_SIZE} total={approvals.data.total} onPage={setPage} />
          </div>
        )
      )}
    </div>
  );
}
