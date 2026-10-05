import { keepPreviousData, useMutation, useQuery } from "@tanstack/react-query";
import { BadgeCheck, CircleCheck, CircleX, ShieldCheck } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router";
import { errorMessage } from "../api/client";
import { endpoints } from "../api/endpoints";
import { useAuth } from "../auth/AuthContext";
import { ClassificationBadge, DecisionBadge, RiskBadge } from "../components/badges";
import { useToast } from "../components/Toast";
import { Badge, Button, Card, EmptyState, ErrorState, Field, JsonBlock, KeyValue, Loading, Notice, PageHeader, Pagination, TabPanel, Table, Tabs, Time, inputClass, td, th } from "../components/ui";
import { formatDateTime, humanize } from "../lib/format";

function RbacTab() {
  const { can } = useAuth();
  const policies = useQuery({ queryKey: ["governance", "policies"], queryFn: endpoints.policies });
  const users = useQuery({ queryKey: ["governance", "users"], queryFn: endpoints.users, enabled: can("users:read") });
  if (policies.isPending) return <Loading />;
  if (policies.isError) return <ErrorState error={policies.error} />;
  const roles = policies.data.roles;
  return (
    <div className="space-y-4">
      <Card title="Roles" description="Role descriptions and data clearance (highest classification a role may read)">
        <ul className="grid gap-3 md:grid-cols-2">
          {roles.map((r) => (
            <li key={r.role} className="rounded-md border border-slate-200 p-3">
              <div className="flex items-center gap-2"><span className="font-semibold text-slate-900">{humanize(r.role)}</span><ClassificationBadge value={r.clearance} /></div>
              <p className="mt-1 text-xs text-slate-600">{r.description}</p>
            </li>
          ))}
        </ul>
      </Card>
      <Card title="RBAC permission matrix" description="Single source of truth: backend/app/policy/permissions.py — enforced on every endpoint" bodyClassName="px-0 py-0">
        <Table label="RBAC permission matrix">
          <thead className="bg-slate-50"><tr><th className={th}>Permission</th>{roles.map((r) => <th key={r.role} className={`${th} text-center`}>{humanize(r.role)}</th>)}</tr></thead>
          <tbody className="divide-y divide-slate-100">
            {policies.data.permissions.map((p) => (
              <tr key={p}>
                <td className={`${td} font-mono text-xs`}>{p}</td>
                {roles.map((r) => (
                  <td key={r.role} className={`${td} text-center`}>
                    {r.permissions.includes(p) ? <CircleCheck className="mx-auto size-4 text-emerald-600" aria-label="granted" /> : <span className="text-slate-300" aria-label="not granted">—</span>}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </Table>
      </Card>
      <Card title="Users in your tenant" description="No credentials are ever returned" bodyClassName="px-0 py-0">
        {!can("users:read") ? <div className="p-5"><Notice tone="info">Requires users:read.</Notice></div> : users.isPending ? <Loading /> : users.isError ? <div className="p-5"><ErrorState error={users.error} /></div> : (
          <Table label="Users">
            <thead className="bg-slate-50"><tr><th className={th}>User</th><th className={th}>Role</th><th className={th}>Status</th><th className={th}>Last login</th></tr></thead>
            <tbody className="divide-y divide-slate-100">
              {users.data.map((u) => (
                <tr key={u.id}>
                  <td className={td}><span className="font-mono text-xs font-medium">{u.username}</span><p className="text-xs text-slate-500">{u.display_name}</p></td>
                  <td className={td}>{humanize(u.role)}</td>
                  <td className={td}><Badge tone={u.is_active ? "success" : "neutral"}>{u.is_active ? "Active" : "Inactive"}</Badge>{u.is_demo_account && <Badge className="ml-1" tone="warning">demo account</Badge>}</td>
                  <td className={td}><Time value={u.last_login_at} /></td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}

function PoliciesTab() {
  const policies = useQuery({ queryKey: ["governance", "policies"], queryFn: endpoints.policies });
  const classes = useQuery({ queryKey: ["governance", "classifications"], queryFn: endpoints.classifications });
  if (policies.isPending) return <Loading />;
  if (policies.isError) return <ErrorState error={policies.error} />;
  const p = policies.data;
  return (
    <div className="space-y-4">
      <Notice tone="info" icon={<ShieldCheck className="size-4" />} title={`Deterministic policy engine · ${p.policy_version}`}>
        Rules run in application code — never in a prompt — and keep working when the model provider is unavailable.
      </Notice>
      <Card title="Policy rules">
        <ul className="space-y-1.5 text-sm">{p.rules.map((r) => <li key={r.id} className="flex gap-2"><Badge tone="navy">{r.id}</Badge><span className="text-slate-700">{r.description}</span></li>)}</ul>
      </Card>
      <Card title="Action risk catalog" bodyClassName="px-0 py-0">
        <Table label="Action risk catalog">
          <thead className="bg-slate-50"><tr><th className={th}>Tool</th><th className={th}>Risk</th><th className={th}>Approvers</th><th className={th}>Targets</th><th className={th}>Rollback</th></tr></thead>
          <tbody className="divide-y divide-slate-100">
            {p.action_catalog.map((a) => (
              <tr key={a.tool}><td className={td}><code className="text-xs">{a.tool}</code><p className="text-xs text-slate-500">{a.description}</p></td><td className={td}><RiskBadge value={a.risk_level} /></td>
                <td className={`${td} text-xs`}>{a.approver_roles.map(humanize).join(", ") || "—"}</td><td className={`${td} text-xs`}>{a.allowed_targets.join(", ") || "—"}</td><td className={`${td} text-xs`}>{a.rollback_supported ? "Yes" : "No"}</td></tr>
            ))}
          </tbody>
        </Table>
        <div className="border-t border-slate-100 px-5 py-3">
          <h3 className="text-xs font-semibold uppercase tracking-wide text-red-700">Prohibited actions</h3>
          <ul className="mt-1 grid gap-1 text-sm md:grid-cols-2">{p.prohibited_actions.map((x) => <li key={x.tool}><code className="text-xs">{x.tool}</code> — <span className="text-slate-600">{x.reason}</span></li>)}</ul>
        </div>
      </Card>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Approval configuration">
          <KeyValue items={Object.entries(p.configuration).map(([k, v]) => [humanize(k), String(v)])} />
        </Card>
        <Card title="Data classification" description={classes.data?.note}>
          {classes.isPending ? <Loading /> : classes.isError ? <ErrorState error={classes.error} /> : (
            <ul className="space-y-2 text-sm">{classes.data.levels.map((l) => <li key={l.classification} className="flex flex-wrap items-center gap-2"><ClassificationBadge value={l.classification} /><span className="text-slate-600">readable by {l.roles_with_clearance.map(humanize).join(", ")}</span></li>)}</ul>
          )}
        </Card>
      </div>
    </div>
  );
}

function DecisionsTab() {
  const [decision, setDecision] = useState("");
  const [page, setPage] = useState(1);
  const rows = useQuery({ queryKey: ["governance", "decisions", decision, page], queryFn: () => endpoints.policyDecisions({ decision, page, page_size: 25 }), placeholderData: keepPreviousData });
  return (
    <Card title="Recorded policy decisions" description="Every allow / deny / approval-required decision with its rule IDs and explanation" bodyClassName="px-0 py-0"
      actions={<Field label="Decision" htmlFor="d-filter"><select id="d-filter" className={inputClass} value={decision} onChange={(e) => { setDecision(e.target.value); setPage(1); }}><option value="">All</option><option value="allow">Allow</option><option value="deny">Deny</option><option value="require_approval">Approval required</option></select></Field>}>
      {rows.isPending ? <Loading /> : rows.isError ? <div className="p-5"><ErrorState error={rows.error} /></div> : rows.data.items.length === 0 ? <div className="p-5"><EmptyState title="No policy decisions recorded" /></div> : (
        <>
          <Table label="Policy decisions">
            <thead className="bg-slate-50"><tr><th className={th}>When</th><th className={th}>Action</th><th className={th}>Role</th><th className={th}>Decision</th><th className={th}>Explanation</th></tr></thead>
            <tbody className="divide-y divide-slate-100">
              {rows.data.items.map((d) => (
                <tr key={d.id}>
                  <td className={td}><Time value={d.created_at} /></td>
                  <td className={td}><code className="text-xs">{d.action_name}</code><p className="text-xs text-slate-500">{d.resource ?? "—"}</p></td>
                  <td className={`${td} text-xs`}>{humanize(d.subject_role)}</td>
                  <td className={td}><div className="flex flex-wrap gap-1"><DecisionBadge value={d.decision} /><RiskBadge value={d.risk_level} /></div><p className="mt-1 text-xs text-slate-500">{d.rule_ids.join(", ")}</p></td>
                  <td className={`${td} max-w-lg text-xs`}>{d.explanation}{d.investigation_id && <> · <Link className="text-navy-700 underline" to={`/investigations/${d.investigation_id}`}>run</Link></>}</td>
                </tr>
              ))}
            </tbody>
          </Table>
          <div className="px-5 pb-3"><Pagination page={page} pageSize={25} total={rows.data.total} onPage={setPage} /></div>
        </>
      )}
    </Card>
  );
}

function AuditTab() {
  const { can } = useAuth();
  const [outcome, setOutcome] = useState("");
  const [action, setAction] = useState("");
  const [page, setPage] = useState(1);
  const audit = useQuery({
    queryKey: ["audit", outcome, action, page],
    queryFn: () => endpoints.audit({ outcome, action: action.trim(), page, page_size: 25 }),
    enabled: can("audit:read"),
    placeholderData: keepPreviousData,
  });
  const verify = useMutation({ mutationFn: endpoints.auditVerify });
  if (!can("audit:read")) return <Notice tone="info">The audit log requires audit:read.</Notice>;
  return (
    <div className="space-y-4">
      <Card title="Tamper evidence" description="Each audit event stores SHA-256(prev_hash + canonical event). UPDATE/DELETE are blocked by database triggers and the ORM.">
        <div className="flex flex-wrap items-center gap-3">
          <Button icon={<BadgeCheck className="size-4" aria-hidden />} loading={verify.isPending} onClick={() => verify.mutate()}>Verify hash chain</Button>
          {verify.data && (verify.data.valid ? (
            <p role="status" className="flex items-center gap-1.5 text-sm font-medium text-emerald-700"><CircleCheck className="size-4" aria-hidden />Chain valid — {verify.data.checked} events verified · head {verify.data.head_hash?.slice(0, 16)}…</p>
          ) : (
            <p role="alert" className="flex items-center gap-1.5 text-sm font-medium text-red-700"><CircleX className="size-4" aria-hidden />Chain INVALID at event {String(verify.data.first_invalid_event_id)}</p>
          ))}
          {verify.isError && <p role="alert" className="text-sm text-red-700">{errorMessage(verify.error)}</p>}
        </div>
      </Card>
      <Card title="Audit log" bodyClassName="px-0 py-0"
        actions={<div className="flex flex-wrap gap-2">
          <Field label="Action prefix" htmlFor="audit-action"><input id="audit-action" className={inputClass} placeholder="e.g. approval." value={action} onChange={(e) => { setAction(e.target.value.replace(/[^a-z_.]/g, "")); setPage(1); }} /></Field>
          <Field label="Outcome" htmlFor="audit-outcome"><select id="audit-outcome" className={inputClass} value={outcome} onChange={(e) => { setOutcome(e.target.value); setPage(1); }}><option value="">All</option><option value="success">Success</option><option value="denied">Denied</option><option value="failure">Failure</option><option value="info">Info</option></select></Field>
        </div>}>
        {audit.isPending ? <Loading /> : audit.isError ? <div className="p-5"><ErrorState error={audit.error} /></div> : audit.data.items.length === 0 ? <div className="p-5"><EmptyState title="No audit events match" /></div> : (
          <>
            <Table label="Audit events">
              <thead className="bg-slate-50"><tr><th className={th}>#</th><th className={th}>When</th><th className={th}>Actor</th><th className={th}>Action</th><th className={th}>Outcome</th><th className={th}>Resource</th><th className={th}>Hash</th></tr></thead>
              <tbody className="divide-y divide-slate-100">
                {audit.data.items.map((e) => (
                  <tr key={e.id}>
                    <td className={`${td} tabular-nums text-xs`}>{e.id}</td>
                    <td className={`${td} whitespace-nowrap text-xs`}>{formatDateTime(e.occurred_at)}</td>
                    <td className={`${td} text-xs`}>{e.actor ?? "system"}<p className="text-slate-500">{humanize(e.actor_role)}</p></td>
                    <td className={td}><code className="text-xs">{e.action}</code>{e.details && <details><summary className="cursor-pointer text-[11px] text-navy-700">details</summary><JsonBlock value={e.details} /></details>}</td>
                    <td className={td}><Badge tone={e.outcome === "success" ? "success" : e.outcome === "denied" ? "danger" : e.outcome === "failure" ? "warning" : "neutral"}>{e.outcome}</Badge></td>
                    <td className={`${td} text-xs`}>{e.resource_type}{e.resource_id && <p className="font-mono text-slate-500">{e.resource_id.slice(0, 12)}</p>}</td>
                    <td className={`${td} font-mono text-[11px] text-slate-500`}>{e.hash.slice(0, 12)}<p>← {e.prev_hash.slice(0, 12)}</p></td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <div className="px-5 pb-3"><Pagination page={page} pageSize={25} total={audit.data.total} onPage={setPage} /></div>
          </>
        )}
      </Card>
    </div>
  );
}

function VersionsTab() {
  const versions = useQuery({ queryKey: ["governance", "model-versions"], queryFn: endpoints.modelVersions });
  if (versions.isPending) return <Loading />;
  if (versions.isError) return <ErrorState error={versions.error} />;
  const v = versions.data;
  return (
    <div className="space-y-4">
      <Card title="Active AI configuration bundle" description="Prompts, model, embeddings, retrieval, index, workflow, policy and dataset versions hashed together; promotions and evaluations reference this hash">
        <p className="mb-3 font-mono text-xs text-slate-700">{v.active_bundle.hash}</p>
        <JsonBlock value={v.active_bundle.components} label="Bundle components" />
      </Card>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Prompt registry" bodyClassName="px-0 py-0">
          <Table label="Prompts">
            <thead className="bg-slate-50"><tr><th className={th}>Prompt</th><th className={th}>Version</th><th className={th}>Template hash</th></tr></thead>
            <tbody className="divide-y divide-slate-100">{v.prompts.map((p) => <tr key={p.prompt_id}><td className={td}><code className="text-xs">{p.prompt_id}</code><p className="text-xs text-slate-500">{p.description}</p></td><td className={`${td} text-xs`}>{p.version}{p.registered && <Badge className="ml-1" tone="success">registered</Badge>}</td><td className={`${td} font-mono text-[11px]`}>{p.template_hash.slice(0, 16)}</td></tr>)}</tbody>
          </Table>
        </Card>
        <Card title="Model gateway & workflow">
          <KeyValue columns={1} items={[
            ["Provider / model", `${v.gateway.provider} / ${v.gateway.model}`],
            ["Mode", v.gateway.mode],
            ["Circuit breaker", v.gateway.circuit_breaker],
            ["Workflow", v.workflow.version],
            ["Agents", Object.values(v.workflow.agents).join(" → ")],
            ["Evaluation dataset", `${v.dataset.dataset_id} ${v.dataset.version}`],
            ["Release thresholds", v.thresholds_version],
          ]} />
          <p className="mt-3 text-xs text-slate-500">Evaluation results and promotions: <Link to="/evaluations" className="text-navy-700 underline">Evaluation & Releases</Link></p>
        </Card>
      </div>
      <Card title="Registered model configurations" bodyClassName="px-0 py-0">
        {v.model_configs.length === 0 ? <div className="p-5"><EmptyState title="No model configurations registered" /></div> : (
          <Table label="Model configurations">
            <thead className="bg-slate-50"><tr><th className={th}>Provider / model</th><th className={th}>Embeddings</th><th className={th}>Config hash</th><th className={th}>Registered</th></tr></thead>
            <tbody className="divide-y divide-slate-100">{v.model_configs.map((m) => <tr key={m.id}><td className={`${td} text-xs`}>{m.provider} / {m.model}</td><td className={`${td} text-xs`}>{m.embedding_provider} / {m.embedding_model} ({m.embedding_dim}d)</td><td className={`${td} font-mono text-[11px]`}>{m.config_hash.slice(0, 16)}</td><td className={td}><Time value={m.created_at} /></td></tr>)}</tbody>
          </Table>
        )}
      </Card>
    </div>
  );
}

function RetentionTab() {
  const { can } = useAuth();
  const toast = useToast();
  const report = useQuery({ queryKey: ["governance", "retention"], queryFn: endpoints.retention });
  const apply = useMutation({
    mutationFn: (dryRun: boolean) => endpoints.applyRetention(dryRun),
    onSuccess: (_, dryRun) => { toast(dryRun ? "Retention dry run complete." : "Retention applied.", "success"); void report.refetch(); },
    onError: (error) => toast(errorMessage(error), "error"),
  });
  if (report.isPending) return <Loading />;
  if (report.isError) return <ErrorState error={report.error} />;
  const blocked = can("retention:manage") ? null : "Requires retention:manage (demo administrator).";
  return (
    <Card title="Retention & deletion" description="Soft-deleted documents and expired records are purged after their retention period; audit events are never deleted by retention.">
      <JsonBlock value={report.data} label="Retention report" />
      <div className="mt-4 flex flex-wrap gap-3">
        <Button variant="secondary" loading={apply.isPending && apply.variables === true} disabledReason={blocked} onClick={() => apply.mutate(true)}>Dry run</Button>
        <Button variant="danger" loading={apply.isPending && apply.variables === false} disabledReason={blocked} onClick={() => apply.mutate(false)}>Apply retention</Button>
      </div>
      {apply.data && <div className="mt-4"><JsonBlock value={apply.data} label="Retention result" /></div>}
    </Card>
  );
}

export function GovernancePage() {
  const [tab, setTab] = useState("rbac");
  return (
    <div className="space-y-4">
      <PageHeader title="Governance Center" description="RBAC, deterministic policy rules, data classification, recorded policy decisions, the append-only audit log, and prompt/model versions." />
      <Tabs label="Governance sections" active={tab} onChange={setTab} tabs={[
        { id: "rbac", label: "Users & roles" }, { id: "policies", label: "Policies & classification" }, { id: "decisions", label: "Policy decisions" },
        { id: "audit", label: "Audit log" }, { id: "versions", label: "Prompt & model versions" }, { id: "retention", label: "Retention" },
      ]} />
      <TabPanel id={tab}>
        {tab === "rbac" && <RbacTab />}
        {tab === "policies" && <PoliciesTab />}
        {tab === "decisions" && <DecisionsTab />}
        {tab === "audit" && <AuditTab />}
        {tab === "versions" && <VersionsTab />}
        {tab === "retention" && <RetentionTab />}
      </TabPanel>
    </div>
  );
}
