import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw, Undo2 } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { errorMessage } from "../api/client";
import { endpoints } from "../api/endpoints";
import type { Action } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { ActionStatusBadge, ApprovalStatusBadge, DecisionBadge, RiskBadge, VerificationBadge } from "../components/badges";
import { Modal } from "../components/Modal";
import { useToast } from "../components/Toast";
import { Badge, Button, Card, EmptyState, ErrorState, Field, JsonBlock, KeyValue, Loading, Notice, PageHeader, Pagination, Table, Time, cx, inputClass, td, th } from "../components/ui";
import { formatDateTime, humanize } from "../lib/format";

const STATUSES = ["", "pending_approval", "approved", "approved_by_policy", "succeeded", "failed", "rejected", "denied", "cancelled", "expired", "invalidated", "skipped", "rolled_back"];
const RISKS = ["", "low", "medium", "high", "prohibited"];
const PAGE_SIZE = 15;

function ActionDetail({ action }: { action: Action }) {
  const { can, user } = useAuth();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [rollbackOpen, setRollbackOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const refresh = () => {
    for (const key of ["actions", "action", "investigation", "incident", "dashboard"]) void queryClient.invalidateQueries({ queryKey: [key] });
  };
  const verify = useMutation({
    mutationFn: () => endpoints.verifyAction(action.id),
    onSuccess: (res) => { toast(`Verification: ${humanize(res.action.verification_status)}`, "success"); refresh(); },
    onError: (error) => toast(errorMessage(error), "error"),
  });
  const rollback = useMutation({
    mutationFn: () => endpoints.rollbackAction(action.id, reason.trim()),
    onSuccess: () => { toast("Simulated rollback completed.", "success"); setRollbackOpen(false); refresh(); },
    onError: (error) => toast(errorMessage(error), "error"),
  });
  const verifiable = ["succeeded", "rolled_back", "failed"].includes(action.status);
  const verifyBlocked = !can("actions:verify") ? `Your role (${humanize(user?.role)}) cannot run verification.`
    : !verifiable ? "Only executed actions can be verified." : null;
  const rollbackBlocked = !can("actions:rollback") ? `Your role (${humanize(user?.role)}) cannot roll back actions.`
    : !action.rollback_supported ? `Rollback not supported: ${action.rollback_note ?? "no state snapshot"}`
      : action.status !== "succeeded" ? `Only succeeded actions can be rolled back (status: ${humanize(action.status)}).` : null;

  return (
    <Card title={<span className="font-mono">{action.tool_name}</span>} description={`Step ${action.step_index} · target ${action.target_resource}`}
      actions={<><Badge tone="warning">SIMULATED</Badge><ActionStatusBadge value={action.status} /></>}>
      <div className="space-y-4">
        <KeyValue items={[
          ["Incident", <Link key="i" className="text-navy-700 underline" to={`/incidents/${action.incident_id}`}>{action.incident_number}</Link>],
          ["Investigation", action.investigation_id ? <Link key="r" className="text-navy-700 underline" to={`/investigations/${action.investigation_id}`}>{action.investigation_id.slice(0, 8)}</Link> : "—"],
          ["Requested by", action.requested_by],
          ["Risk", <RiskBadge key="risk" value={action.risk_level} />],
          ["Policy decision", action.policy_decision ? <DecisionBadge key="d" value={action.policy_decision.decision} /> : "—"],
          ["Approval", action.approval ? <span key="a"><ApprovalStatusBadge value={action.approval.status} /> {action.approval.decided_by && `by ${action.approval.decided_by}`}</span> : action.requires_approval ? "Required" : "Not required (allowed by policy)"],
          ["Executed", formatDateTime(action.executed_at)],
          ["Verification", <VerificationBadge key="v" value={action.verification_status} />],
          ["Idempotency key", <code key="k" className="break-all text-xs">{action.idempotency_key}</code>],
          ["Attempts", action.attempt_count],
        ]} />
        {action.policy_decision && <Notice tone="purple" title={`Policy ${action.policy_decision.rule_ids.join(", ")}`}>{action.policy_decision.explanation}</Notice>}
        {action.preconditions && action.preconditions.length > 0 && (
          <div>
            <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Preconditions</h3>
            <ul className="mt-1 space-y-0.5 text-sm">{action.preconditions.map((p) => <li key={p.name}>{p.passed ? "✓" : "✗"} {humanize(p.name)} — <span className="text-slate-600">{p.detail}</span></li>)}</ul>
          </div>
        )}
        <div className="grid gap-3 md:grid-cols-2">
          <div><h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Parameters</h3><JsonBlock value={action.parameters} label="Parameters" /></div>
          <div><h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Result</h3><JsonBlock value={action.result ?? {}} label="Result" /></div>
        </div>
        {action.verification_detail && <div><h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-slate-500">Verification detail</h3><JsonBlock value={action.verification_detail} label="Verification detail" /></div>}
        <p className="text-xs text-slate-500">Rollback: {action.rollback_supported ? "supported (state snapshot captured before execution)" : "not supported"} — {action.rollback_note}</p>
        <div className="flex flex-wrap gap-3">
          <Button variant="secondary" icon={<RefreshCw className="size-4" aria-hidden />} loading={verify.isPending} disabledReason={verifyBlocked} onClick={() => verify.mutate()}>Re-run verification</Button>
          <Button variant="danger" icon={<Undo2 className="size-4" aria-hidden />} disabledReason={rollbackBlocked} onClick={() => { setReason(""); setConfirmed(false); setRollbackOpen(true); }}>Simulate rollback…</Button>
        </div>
      </div>
      <Modal open={rollbackOpen} onClose={() => !rollback.isPending && setRollbackOpen(false)} title="Simulate rollback"
        footer={<>
          <Button variant="secondary" onClick={() => setRollbackOpen(false)}>Back</Button>
          <Button variant="danger" loading={rollback.isPending} onClick={() => rollback.mutate()}
            disabledReason={reason.trim().length < 3 ? "Enter a reason (at least 3 characters)." : !confirmed ? "Tick the confirmation box." : null}>Confirm rollback</Button>
        </>}>
        <p>Restores the synthetic state snapshot captured before <code>{action.tool_name}</code> ran. {action.rollback_note}</p>
        <Field label="Reason (recorded in the audit log)" htmlFor="rollback-reason">
          <input id="rollback-reason" className={inputClass} maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} />
        </Field>
        <label className="flex items-start gap-2"><input type="checkbox" className="mt-1 size-4" checked={confirmed} onChange={(e) => setConfirmed(e.target.checked)} /><span>I confirm this <strong>simulated</strong> rollback.</span></label>
      </Modal>
    </Card>
  );
}

export function ActionsPage() {
  const [status, setStatus] = useState("");
  const [risk, setRisk] = useState("");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<string | null>(null);
  const catalog = useQuery({ queryKey: ["actions", "catalog"], queryFn: endpoints.actionCatalog, staleTime: 300000 });
  const actions = useQuery({
    queryKey: ["actions", status, risk, page],
    queryFn: () => endpoints.actions({ status, risk_level: risk, page, page_size: PAGE_SIZE }),
    placeholderData: keepPreviousData,
    refetchInterval: 10000,
  });
  const selectedAction = actions.data?.items.find((a) => a.id === selected) ?? null;

  return (
    <div className="space-y-5">
      <PageHeader title="Remediation Center" description="Allowlisted, simulated remediation only. Every action has an idempotency key, a policy decision, preconditions, an approval record when required, an execution outcome and post-action verification." />
      <Card title="Action records" bodyClassName="px-0 py-0"
        actions={<div className="flex flex-wrap gap-2">
          <Field label="Status" htmlFor="a-status"><select id="a-status" className={inputClass} value={status} onChange={(e) => { setStatus(e.target.value); setPage(1); }}>{STATUSES.map((s) => <option key={s} value={s}>{s ? humanize(s) : "All"}</option>)}</select></Field>
          <Field label="Risk" htmlFor="a-risk"><select id="a-risk" className={inputClass} value={risk} onChange={(e) => { setRisk(e.target.value); setPage(1); }}>{RISKS.map((s) => <option key={s} value={s}>{s ? humanize(s) : "All"}</option>)}</select></Field>
        </div>}>
        {actions.isPending ? <Loading /> : actions.isError ? <div className="p-5"><ErrorState error={actions.error} /></div> : actions.data.items.length === 0 ? (
          <div className="p-5"><EmptyState title="No simulated actions yet">Actions appear after an investigation's plan passes the policy gate.</EmptyState></div>
        ) : (
          <>
            <Table label="Simulated actions">
              <thead className="bg-slate-50"><tr><th className={th}>Action</th><th className={th}>Incident</th><th className={th}>Risk</th><th className={th}>Status</th><th className={th}>Approval</th><th className={th}>Verification</th><th className={th}>Created</th></tr></thead>
              <tbody className="divide-y divide-slate-100">
                {actions.data.items.map((a) => (
                  <tr key={a.id} className={cx("cursor-pointer hover:bg-slate-50", selected === a.id && "bg-navy-50")} onClick={() => setSelected(a.id)}>
                    <td className={td}><button type="button" className="text-left font-mono text-xs font-medium text-navy-700 hover:underline" onClick={() => setSelected(a.id)}>{a.tool_name}</button><p className="text-xs text-slate-500">{a.target_resource}</p></td>
                    <td className={td}>{a.incident_number}</td>
                    <td className={td}><RiskBadge value={a.risk_level} /></td>
                    <td className={td}><ActionStatusBadge value={a.status} /></td>
                    <td className={td}>{a.approval ? <ApprovalStatusBadge value={a.approval.status} /> : <span className="text-xs text-slate-500">{a.requires_approval ? "required" : "not required"}</span>}</td>
                    <td className={td}>{a.verification_status && a.verification_status !== "not_verified" ? <VerificationBadge value={a.verification_status} /> : "—"}</td>
                    <td className={td}><Time value={a.created_at} /></td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <div className="px-5 pb-3"><Pagination page={page} pageSize={PAGE_SIZE} total={actions.data.total} onPage={setPage} /></div>
          </>
        )}
      </Card>
      {selectedAction ? <ActionDetail action={selectedAction} /> : <p className="text-sm text-slate-500">Select an action to inspect its policy decision, execution, verification and rollback options.</p>}

      <Card title="Allowlisted tool catalog" description="Typed, Pydantic-validated tools. Unknown tools, unexpected fields and unauthorized targets are rejected." bodyClassName="px-0 py-0">
        {catalog.isPending ? <Loading /> : catalog.isError ? <div className="p-5"><ErrorState error={catalog.error} /></div> : (
          <>
            <Table label="Allowlisted tools">
              <thead className="bg-slate-50"><tr><th className={th}>Tool</th><th className={th}>Risk</th><th className={th}>Allowed targets</th><th className={th}>Approvers</th><th className={th}>Rollback</th></tr></thead>
              <tbody className="divide-y divide-slate-100">
                {catalog.data.tools.map((tool) => (
                  <tr key={tool.name}>
                    <td className={td}><code className="font-mono text-xs font-medium">{tool.name}</code><p className="max-w-md text-xs text-slate-500">{tool.description}</p></td>
                    <td className={td}><RiskBadge value={tool.risk_level} /></td>
                    <td className={td}><span className="text-xs">{tool.allowed_targets.join(", ") || "—"}</span></td>
                    <td className={td}><span className="text-xs">{tool.approver_roles.map(humanize).join(", ") || "—"}</span></td>
                    <td className={td}><span className="text-xs">{tool.rollback_supported ? "Supported" : "No"} — {tool.rollback_note}</span></td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <div className="border-t border-slate-100 px-5 py-4">
              <h3 className="text-xs font-semibold uppercase tracking-wide text-red-700">Prohibited — never executable (policy P-002)</h3>
              <ul className="mt-2 grid gap-1 text-sm md:grid-cols-2">{catalog.data.prohibited.map((p) => <li key={p.name}><code className="font-mono text-xs">{p.name}</code> <span className="text-slate-600">— {p.reason}</span></li>)}</ul>
            </div>
          </>
        )}
      </Card>
    </div>
  );
}
