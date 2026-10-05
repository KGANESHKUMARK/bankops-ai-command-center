import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Ban,
  Bot,
  CircleCheck,
  CircleDot,
  CircleX,
  FlaskConical,
  Info,
  LoaderCircle,
  Play,
  Power,
  RotateCcw,
  Scale,
  ShieldAlert,
  TriangleAlert,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import { useCallback, useState } from "react";
import { Link, useParams } from "react-router";
import { errorMessage } from "../api/client";
import { endpoints } from "../api/endpoints";
import type { StreamStatus } from "../api/sse";
import type { Action, Diagnosis, Evidence, InvestigationEvent, RunDetail } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { ApprovalControls } from "../components/ApprovalControls";
import {
  ActionStatusBadge,
  ApprovalStatusBadge,
  ClassificationBadge,
  DecisionBadge,
  ModeBadge,
  OutcomeBadge,
  RiskBadge,
  RunStatusBadge,
  SourceBadge,
  VerificationBadge,
} from "../components/badges";
import { Modal } from "../components/Modal";
import { useToast } from "../components/Toast";
import { Badge, Button, Card, EmptyState, ErrorState, JsonBlock, KeyValue, Loading, Notice, ProgressBar, Time, cx } from "../components/ui";
import { formatDateTime, formatDuration, formatUsd, humanize, pct } from "../lib/format";
import { useInvestigationEvents } from "../lib/useInvestigationEvents";

const ACTIVE = new Set(["queued", "running"]);

const EVENT_ICONS: Record<string, [LucideIcon, string]> = {
  status_change: [CircleDot, "text-navy-600"],
  step_started: [Play, "text-sky-600"],
  step_completed: [CircleCheck, "text-emerald-600"],
  step_failed: [CircleX, "text-red-600"],
  tool_call: [Wrench, "text-slate-600"],
  llm_call: [Bot, "text-violet-600"],
  policy_decision: [Scale, "text-amber-700"],
  action_executed: [Power, "text-emerald-700"],
  approval_invalidated: [Ban, "text-slate-500"],
};

const STREAM_LABEL: Record<StreamStatus, [string, string]> = {
  connecting: ["Connecting…", "text-slate-500"],
  live: ["Live (SSE)", "text-emerald-700"],
  reconnecting: ["Reconnecting…", "text-amber-700"],
  polling: ["Polling fallback", "text-amber-700"],
  ended: ["Stream idle", "text-slate-500"],
  error: ["Stream unavailable", "text-red-700"],
};

function Timeline({ events, streamStatus }: { events: InvestigationEvent[]; streamStatus: StreamStatus }) {
  const [label, color] = STREAM_LABEL[streamStatus];
  const last = events[events.length - 1];
  return (
    <Card title="Live agent timeline" description="Every step, tool call, model call and policy decision is traced" actions={<span className={cx("text-xs font-medium", color)}>{label}</span>}>
      <p className="sr-only" aria-live="polite">{last ? `${last.agent ?? "Workflow"}: ${last.message}` : ""}</p>
      {events.length === 0 ? <EmptyState title="Waiting for the first workflow event…" /> : (
        <ol className="max-h-[38rem] space-y-2.5 overflow-y-auto pr-1">
          {events.map((event) => {
            const [Icon, iconColor] = EVENT_ICONS[event.event_type] ?? [Info, "text-slate-500"];
            return (
              <li key={event.seq} className="flex gap-2.5">
                <Icon className={cx("mt-0.5 size-4 shrink-0", iconColor)} aria-hidden />
                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-x-2 text-xs text-slate-500">
                    <span className="font-medium text-slate-700">{event.agent ?? "Workflow"}</span>
                    {event.tool && <code className="text-[11px]">{event.tool}</code>}
                    <span>{humanize(event.event_type)}</span>
                    <span>#{event.seq}</span>
                    {event.duration_ms !== null && <span>{formatDuration(event.duration_ms)}</span>}
                  </div>
                  <p className="break-words text-sm text-slate-800">{event.message}</p>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </Card>
  );
}

function EvidenceList({ evidence, retrieval }: { evidence: Evidence[]; retrieval: RunDetail["state"]["retrieval"] }) {
  return (
    <Card title="Evidence & citations" description="Authorized retrieval only — tenant, classification and per-document role filters are applied before content reaches an agent">
      {retrieval && (
        <div className="mb-4 space-y-2">
          <Notice tone={retrieval.sufficient ? "success" : "warning"} title={retrieval.sufficient ? "Sufficient authorized evidence" : "Evidence insufficient — the workflow abstains from unsupported conclusions"}>
            {retrieval.reason}
          </Notice>
          <p className="text-xs text-slate-600">
            {retrieval.runbook_evidence} runbook chunk(s) cited · top score {retrieval.top_score?.toFixed(3) ?? "—"} ·{" "}
            <strong>{retrieval.excluded_unauthorized}</strong> candidate chunk(s) excluded by authorization filters
            {retrieval.retrieval_failed && " · retrieval error (degraded)"}
          </p>
          <details className="text-xs text-slate-600"><summary className="cursor-pointer font-medium text-navy-700">Retrieval queries</summary><ul className="mt-1 list-disc pl-5">{retrieval.queries.map((q) => <li key={q}>{q}</li>)}</ul></details>
        </div>
      )}
      {evidence.length === 0 ? <EmptyState title="No evidence collected yet" /> : (
        <ul className="space-y-3">
          {evidence.map((item) => (
            <li key={item.label} id={`evidence-${item.label}`} className="rounded-md border border-slate-200 p-3">
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="navy">{item.label}</Badge>
                <Badge>{humanize(item.kind)}</Badge>
                {item.classification && <ClassificationBadge value={item.classification} />}
                {item.injection_detected && <Badge tone="purple" title="Instruction-like text was removed before use">injection neutralized</Badge>}
                {typeof item.score === "number" && <span className="text-xs text-slate-500">score {item.score.toFixed(3)}</span>}
              </div>
              <p className="mt-1.5 text-sm font-medium text-slate-900">{item.title}</p>
              {item.citation && <p className="mt-0.5 font-mono text-[11px] text-slate-500">{item.citation}</p>}
              <p className="mt-1.5 whitespace-pre-wrap text-xs leading-relaxed text-slate-700">{item.excerpt}</p>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function EvidenceChips({ labels, tone }: { labels: string[]; tone: "success" | "danger" }) {
  if (!labels.length) return <span className="text-xs text-slate-400">none</span>;
  return (
    <span className="flex flex-wrap gap-1">
      {labels.map((label) => (
        <a key={label} href={`#evidence-${label}`} className={cx("rounded px-1.5 py-0.5 font-mono text-[11px] ring-1 ring-inset", tone === "success" ? "bg-emerald-50 text-emerald-800 ring-emerald-200" : "bg-red-50 text-red-800 ring-red-200")}>
          {label}
        </a>
      ))}
    </span>
  );
}

function Hypotheses({ diagnosis, source }: { diagnosis: Diagnosis | null; source?: string }) {
  return (
    <Card title="Root-cause hypotheses" description="Ranked by the diagnostic agent; citations are validated by application code" actions={<SourceBadge source={source} />}>
      {!diagnosis ? <EmptyState title="Diagnosis not available yet" /> : (
        <div className="space-y-3">
          {diagnosis.summary && <p className="text-sm text-slate-700">{diagnosis.summary}</p>}
          {diagnosis.abstained && (
            <Notice tone="warning" icon={<TriangleAlert className="size-4" />} title={diagnosis.unavailable ? "AI diagnosis unavailable — no findings were fabricated" : "Abstained: evidence is insufficient for a supported conclusion"}>
              {diagnosis.abstention_reason}
            </Notice>
          )}
          {diagnosis.conflicting_evidence && <Notice tone="warning" title="Conflicting evidence">Top hypotheses are too close to call; no mutating remediation is planned.</Notice>}
          {(diagnosis.invalid_citations_removed ?? 0) > 0 && (
            <Notice tone="danger" title={`${diagnosis.invalid_citations_removed} invalid citation(s) removed`}>The model cited evidence labels that were never retrieved; those claims are treated as unsupported.</Notice>
          )}
          <ol className="space-y-3">
            {diagnosis.hypotheses.map((h, index) => (
              <li key={h.id} className="rounded-md border border-slate-200 p-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="text-xs font-semibold text-slate-500">#{index + 1}</span>
                    <span className="text-sm font-semibold text-slate-900">{h.title}</span>
                    <Badge tone="navy">{humanize(h.root_cause_category)}</Badge>
                    {h.unsupported && <Badge tone="danger">unsupported</Badge>}
                  </div>
                  <span className="text-sm font-semibold tabular-nums text-slate-900" aria-label={`Confidence ${pct(h.confidence)}`}>{pct(h.confidence)}</span>
                </div>
                <div className="mt-1.5 h-1.5 rounded-full bg-slate-100"><div className="h-1.5 rounded-full bg-navy-600" style={{ width: `${h.confidence * 100}%` }} /></div>
                <p className="mt-2 text-sm text-slate-700">{h.description}</p>
                <p className="mt-1.5 text-xs text-slate-600"><strong>Why this confidence:</strong> {h.confidence_rationale}</p>
                <dl className="mt-2 grid gap-2 text-xs sm:grid-cols-2">
                  <div><dt className="font-medium text-slate-600">Supporting evidence</dt><dd className="mt-0.5"><EvidenceChips labels={h.supporting_evidence} tone="success" /></dd></div>
                  <div><dt className="font-medium text-slate-600">Contradicting evidence</dt><dd className="mt-0.5"><EvidenceChips labels={h.contradicting_evidence} tone="danger" /></dd></div>
                </dl>
                {h.further_checks.length > 0 && (
                  <div className="mt-2 text-xs text-slate-600"><span className="font-medium">Further checks:</span><ul className="mt-0.5 list-disc pl-5">{h.further_checks.map((c) => <li key={c}>{c}</li>)}</ul></div>
                )}
              </li>
            ))}
          </ol>
          <p className="text-xs text-slate-500">
            <strong>How confidence is explained:</strong> the agent returns a 0–1 score with a written rationale. Application code then drops
            citations to evidence that was never retrieved, flags hypotheses without valid support, and forces abstention if the top
            hypothesis is unsupported. Remediation is only planned for a supported, non-conflicting top hypothesis.
          </p>
        </div>
      )}
    </Card>
  );
}

function PlanAndPolicy({ run }: { run: RunDetail }) {
  const { plan, governance, policy, sources } = run.state;
  const decisions = new Map((policy?.decisions ?? []).map((d) => [d.step, d]));
  return (
    <>
      <Card title="Recommended remediation" description="Proposals only — allowlisted simulated tools; the model cannot execute anything" actions={<SourceBadge source={sources?.plan} />}>
        {!plan ? <EmptyState title="No plan yet" /> : (
          <div className="space-y-3">
            <p className="text-sm text-slate-700">{plan.summary}</p>
            {plan.actions.map((a) => {
              const outcome = decisions.get(a.step);
              return (
                <div key={a.step} className="rounded-md border border-slate-200 p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge>Step {a.step}</Badge>
                    <code className="font-mono text-sm font-semibold text-slate-900">{a.tool_name}</code>
                    <span className="text-xs text-slate-500">→ {a.target_resource}</span>
                    {outcome && <DecisionBadge value={outcome.decision.decision} />}
                    {outcome && <RiskBadge value={outcome.decision.risk_level} />}
                    {a.depends_on_step && <Badge tone="info">depends on step {a.depends_on_step}</Badge>}
                  </div>
                  <KeyValue items={[
                    ["Rationale", a.rationale],
                    ["Expected effect", a.expected_effect],
                    ["Risks", a.risks],
                    ["Rollback option", a.rollback_option || "None stated"],
                    ["Prerequisites", a.prerequisites.length ? a.prerequisites.join("; ") : "—"],
                    ["Evidence", <EvidenceChips key="ev" labels={a.evidence_refs} tone="success" />],
                  ]} />
                </div>
              );
            })}
            {plan.manual_steps.length > 0 && (
              <div><h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Manual / read-only steps</h3><ul className="mt-1 list-disc pl-5 text-sm text-slate-700">{plan.manual_steps.map((s) => <li key={s}>{s}</li>)}</ul></div>
            )}
            {(policy?.alternatives.length ?? 0) > 0 && (
              <div>
                <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Not recommended (with policy evaluation)</h3>
                <ul className="mt-1 space-y-1.5">
                  {policy?.alternatives.map((alt) => (
                    <li key={alt.tool_name} className="text-sm"><code className="font-mono">{alt.tool_name}</code> <DecisionBadge value={alt.decision} /> <span className="text-slate-600">{alt.reason}</span><p className="text-xs text-slate-500">{alt.explanation}</p></li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </Card>

      <Card title="Governance / risk review" description="ADVISORY ONLY — the deterministic policy engine makes every enforcement decision" actions={<SourceBadge source={sources?.governance} />}>
        {!governance ? <EmptyState title="No review yet" /> : (
          <div className="space-y-2 text-sm text-slate-700">
            <p>{governance.summary}</p>
            {governance.policy_constraints.length > 0 && <div><strong className="text-xs uppercase text-slate-500">Constraints</strong><ul className="list-disc pl-5">{governance.policy_constraints.map((c) => <li key={c}>{c}</li>)}</ul></div>}
            {governance.data_exposure_concerns.length > 0 && <div><strong className="text-xs uppercase text-slate-500">Data exposure</strong><ul className="list-disc pl-5">{governance.data_exposure_concerns.map((c) => <li key={c}>{c}</li>)}</ul></div>}
            {governance.prohibited_actions_detected.length > 0 && <Notice tone="danger" title="Prohibited actions detected in the proposal">{governance.prohibited_actions_detected.join(", ")}</Notice>}
          </div>
        )}
      </Card>

      <Card title="Policy decisions (deterministic)" description={`Evaluated in application code · ${policy?.policy_version ?? run.policy_version ?? ""}`}>
        {!policy || policy.decisions.length === 0 ? <EmptyState title="No actions were submitted to the policy engine" /> : (
          <ul className="space-y-2">
            {policy.decisions.map((d) => (
              <li key={`${d.step}-${d.tool_name}`} className="rounded-md border border-slate-200 p-3">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge>Step {d.step}</Badge><code className="font-mono text-sm">{d.tool_name}</code><DecisionBadge value={d.decision.decision} /><RiskBadge value={d.decision.risk_level} />
                  {d.decision.rule_ids.map((r) => <Badge key={r} tone="navy">{r}</Badge>)}
                </div>
                <p className="mt-1.5 text-sm text-slate-700">{d.decision.explanation}</p>
                {d.decision.required_approver_roles.length > 0 && <p className="mt-1 text-xs text-slate-500">Approver roles: {d.decision.required_approver_roles.map(humanize).join(", ")}</p>}
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}

function PendingApproval({ approvalId }: { approvalId: string }) {
  const approval = useQuery({ queryKey: ["approval", approvalId], queryFn: () => endpoints.approval(approvalId) });
  if (approval.isPending) return <Loading label="Loading approval…" />;
  if (approval.isError) return <ErrorState error={approval.error} />;
  return (
    <div className="mt-2 space-y-2 rounded-md bg-violet-50 p-3">
      <p className="text-xs text-violet-900">
        Requested by <strong>{approval.data.requested_by}</strong> ({humanize(approval.data.requested_by_role)}) · requires {approval.data.required_roles.map(humanize).join(" or ")} · expires <Time value={approval.data.expires_at} />
      </p>
      <ApprovalControls approval={approval.data} />
    </div>
  );
}

function ActionCard({ action }: { action: Action }) {
  return (
    <li className="rounded-md border border-slate-200 p-3">
      <div className="flex flex-wrap items-center gap-2">
        <Badge>Step {action.step_index}</Badge>
        <code className="font-mono text-sm font-semibold text-slate-900">{action.tool_name}</code>
        <ActionStatusBadge value={action.status} />
        <RiskBadge value={action.risk_level} />
        {action.approval && <ApprovalStatusBadge value={action.approval.status} />}
        <Badge tone="warning">SIMULATED</Badge>
        {action.verification_status && action.verification_status !== "not_verified" && <VerificationBadge value={action.verification_status} />}
      </div>
      <p className="mt-1 text-xs text-slate-500">Target {action.target_resource} · idempotency key <code>{action.idempotency_key.slice(0, 16)}…</code>{action.executed_at && <> · executed {formatDateTime(action.executed_at)}</>}</p>
      {action.error_code && <p className="mt-1 text-sm text-red-700">Error: {humanize(action.error_code)}</p>}
      {action.preconditions && action.preconditions.length > 0 && (
        <ul className="mt-2 space-y-0.5 text-xs">
          {action.preconditions.map((p) => (
            <li key={p.name} className="flex items-start gap-1.5">{p.passed ? <CircleCheck className="size-3.5 text-emerald-600" aria-label="passed" /> : <CircleX className="size-3.5 text-red-600" aria-label="failed" />}<span><strong>{humanize(p.name)}</strong> — {p.detail}</span></li>
          ))}
        </ul>
      )}
      {action.result && <details className="mt-2"><summary className="cursor-pointer text-xs font-medium text-navy-700">Simulated result</summary><div className="mt-1"><JsonBlock value={action.result} label="Simulated result" /></div></details>}
      {action.approval?.status === "pending" && <PendingApproval approvalId={action.approval.id} />}
      {action.approval && action.approval.status !== "pending" && action.approval.decided_by && (
        <p className="mt-2 text-xs text-slate-600">Approval {action.approval.status} by <strong>{action.approval.decided_by}</strong> ({action.approval.reason_code}) <Time value={action.approval.decided_at} /></p>
      )}
    </li>
  );
}

function AuditTrail({ runId }: { runId: string }) {
  const audit = useQuery({ queryKey: ["audit", "investigation", runId], queryFn: () => endpoints.audit({ investigation_id: runId, page_size: 100 }) });
  return (
    <Card title="Audit trail" description="Append-only, hash-chained audit events for this investigation">
      {audit.isPending ? <Loading /> : audit.isError ? <ErrorState error={audit.error} /> : audit.data.items.length === 0 ? <EmptyState title="No audit events" /> : (
        <ol className="max-h-80 divide-y divide-slate-100 overflow-y-auto text-sm">
          {audit.data.items.map((e) => (
            <li key={e.id} className="flex flex-wrap items-center justify-between gap-2 py-1.5">
              <span><code className="font-mono text-xs">{e.action}</code> <span className="text-slate-600">by {e.actor ?? "system"}</span></span>
              <span className="flex items-center gap-2 text-xs text-slate-500"><Badge tone={e.outcome === "success" ? "success" : e.outcome === "denied" ? "danger" : "neutral"}>{e.outcome}</Badge><span className="font-mono">{e.hash.slice(0, 10)}</span><Time value={e.occurred_at} /></span>
            </li>
          ))}
        </ol>
      )}
    </Card>
  );
}

export function InvestigationPage() {
  const { runId = "" } = useParams();
  const { can, user } = useAuth();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [confirmCancel, setConfirmCancel] = useState(false);
  const run = useQuery({
    queryKey: ["investigation", runId],
    queryFn: () => endpoints.investigation(runId),
    staleTime: 0,
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && ACTIVE.has(status) ? 2500 : status === "awaiting_approval" ? 5000 : false;
    },
  });
  const refresh = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ["investigation", runId] });
  }, [queryClient, runId]);
  const { events, streamStatus } = useInvestigationEvents(runId, run.data?.status, refresh);
  const resume = useMutation({
    mutationFn: () => endpoints.resumeInvestigation(runId),
    onSuccess: () => { toast("Investigation resumed.", "success"); refresh(); },
    onError: (error) => toast(errorMessage(error), "error"),
  });
  const cancel = useMutation({
    mutationFn: () => endpoints.cancelInvestigation(runId, "Cancelled from the investigation workspace"),
    onSuccess: () => { toast("Investigation cancelled.", "info"); setConfirmCancel(false); refresh(); },
    onError: (error) => toast(errorMessage(error), "error"),
  });

  if (run.isPending) return <Loading label="Loading investigation…" />;
  if (run.isError) return <ErrorState error={run.error} title="Investigation unavailable" onRetry={() => void run.refetch()} />;
  const r = run.data;
  const state = r.state;
  const pendingApprovals = r.actions.filter((a) => a.approval?.status === "pending").length;
  const tokens = r.input_tokens + r.output_tokens;
  const canResume = r.status === "interrupted" || (r.status === "awaiting_approval" && pendingApprovals === 0);
  const canCancel = ["queued", "running", "awaiting_approval"].includes(r.status);
  const degradedReasons = state.degraded_reasons ?? [];

  return (
    <div className="space-y-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-medium uppercase tracking-wide text-slate-500">AI Investigation Workspace</p>
          <h1 className="text-xl font-semibold text-slate-900">
            <Link to={`/incidents/${r.incident_id}`} className="hover:underline">{r.incident_number}</Link> · {r.incident_title}
          </h1>
          <div className="mt-2 flex flex-wrap items-center gap-2">
            <RunStatusBadge value={r.status} />
            <OutcomeBadge value={r.outcome} />
            <RiskBadge value={r.risk_level} />
            <ModeBadge mode={r.model_mode} />
            {r.degraded && <Badge tone="warning">Degraded</Badge>}
            {ACTIVE.has(r.status) && r.current_node && <Badge tone="info"><LoaderCircle className="size-3 animate-spin" aria-hidden /> {humanize(r.current_node)}</Badge>}
          </div>
        </div>
        <div className="flex flex-wrap items-start gap-2">
          {pendingApprovals > 0 && <Link to="/approvals" className="rounded-md border border-violet-300 bg-violet-50 px-3 py-2 text-sm font-medium text-violet-900 hover:bg-violet-100">{pendingApprovals} pending approval(s) →</Link>}
          {canResume && (
            <Button icon={<RotateCcw className="size-4" aria-hidden />} loading={resume.isPending} onClick={() => resume.mutate()}
              disabledReason={can("investigations:resume") ? null : `Your role (${humanize(user?.role)}) cannot resume investigations.`}>
              Resume workflow
            </Button>
          )}
          {canCancel && (
            <Button variant="secondary" icon={<Ban className="size-4" aria-hidden />} onClick={() => setConfirmCancel(true)}
              disabledReason={can("investigations:start") ? null : `Your role (${humanize(user?.role)}) cannot cancel investigations.`}>
              Cancel investigation
            </Button>
          )}
        </div>
      </div>

      {r.model_mode === "MOCK" && (
        <Notice tone="warning" icon={<FlaskConical className="size-4" />} title="MOCK MODE">
          Agent outputs come from a deterministic offline provider driven by the retrieved evidence — they are not real model inference.
        </Notice>
      )}
      {degradedReasons.length > 0 && (
        <Notice tone="warning" icon={<TriangleAlert className="size-4" />} title="Degraded mode during this run">
          {degradedReasons.map(humanize).join("; ")}. Deterministic diagnostics and audit remain available; no findings were fabricated.
        </Notice>
      )}
      {state.abort_reason && <Notice tone="danger" title="Workflow stopped safely">{humanize(state.abort_reason)} ({r.error_code})</Notice>}

      <div className="grid gap-4 md:grid-cols-3">
        <Card title="Workflow bounds" description="Hard limits enforced by the orchestrator">
          {r.limits ? (
            <div className="space-y-3">
              <ProgressBar label="Agent steps" value={r.step_count} max={r.limits.max_steps} />
              <ProgressBar label="Tool calls" value={r.tool_call_count} max={r.limits.max_tool_calls} />
              <ProgressBar label="Tokens (est.)" value={tokens} max={r.limits.token_budget} />
            </div>
          ) : <p className="text-sm text-slate-500">Limits unavailable.</p>}
        </Card>
        <Card title="Run metadata">
          <KeyValue columns={1} items={[
            ["Requested by", r.requested_by],
            ["Started / completed", `${formatDateTime(r.started_at)} → ${formatDateTime(r.completed_at)}`],
            ["Model", `${r.provider ?? "—"} / ${r.model ?? "—"}`],
            ["Estimated cost", <span key="cost">{formatUsd(r.estimated_cost_usd)} <span className="text-xs text-slate-500">(ESTIMATE)</span></span>],
          ]} />
        </Card>
        <Card title="Versions">
          <KeyValue columns={1} items={[
            ["Workflow", r.workflow_version],
            ["Policy", r.policy_version],
            ["Knowledge index", r.index_version],
            ["Prompts", r.prompt_versions ? Object.entries(r.prompt_versions).map(([k, v]) => `${k}@${v}`).join(", ") : "—"],
          ]} />
        </Card>
      </div>

      <div className="grid gap-4 xl:grid-cols-5">
        <div className="space-y-4 xl:col-span-2">
          <Timeline events={events} streamStatus={streamStatus} />
        </div>
        <div className="space-y-4 xl:col-span-3">
          <Card title="Triage" description="Incident facts, severity and missing information" actions={<SourceBadge source={state.sources?.triage} />}>
            {!state.triage ? <EmptyState title="Triage not available yet" /> : (
              <div className="space-y-2 text-sm text-slate-700">
                <p>{state.triage.summary}</p>
                <p><strong>Severity assessment:</strong> {humanize(state.triage.severity_assessment)} — {state.triage.severity_rationale}</p>
                {state.triage.key_facts.length > 0 && <ul className="list-disc pl-5">{state.triage.key_facts.map((f) => <li key={f}>{f}</li>)}</ul>}
                {state.triage.missing_information.length > 0 && <p className="text-xs text-amber-800"><strong>Missing information:</strong> {state.triage.missing_information.join("; ")}</p>}
              </div>
            )}
          </Card>
          <EvidenceList evidence={state.evidence ?? []} retrieval={state.retrieval} />
          <Hypotheses diagnosis={state.diagnosis} source={state.sources?.diagnosis} />
          <PlanAndPolicy run={r} />
          <Card title="Approvals & simulated execution" description="Only allowlisted simulated actions; idempotent, re-checked by policy before execution">
            {r.actions.length === 0 ? <EmptyState title="No actions were proposed or allowed" /> : <ul className="space-y-3">{r.actions.map((a) => <ActionCard key={a.id} action={a} />)}</ul>}
          </Card>
          <Card title="Verification" description="Post-action checks against simulated service state" actions={<SourceBadge source={state.verification ? "deterministic" : undefined} />}>
            {!state.verification ? <EmptyState title="Not verified yet" /> : (
              <div className="space-y-2">
                <VerificationBadge value={state.verification.status} />
                {state.verification.summary && <p className="text-sm text-slate-700">{state.verification.summary}</p>}
                <ul className="space-y-1 text-sm">
                  {state.verification.checks.map((c) => (
                    <li key={c.name} className="flex items-start gap-1.5">{c.passed ? <CircleCheck className="mt-0.5 size-4 text-emerald-600" aria-label="passed" /> : <CircleX className="mt-0.5 size-4 text-red-600" aria-label="failed" />}<span>{c.name}{c.detail && <span className="text-xs text-slate-500"> — {c.detail}</span>}</span></li>
                  ))}
                </ul>
                {(state.verification.residual_risks?.length ?? 0) > 0 && <p className="text-xs text-slate-600"><strong>Residual risks:</strong> {state.verification.residual_risks?.join("; ")}</p>}
              </div>
            )}
          </Card>
          <Card title="Final incident report" actions={state.report?.generated_by ? <Badge tone={state.report.generated_by.startsWith("MOCK") ? "warning" : "neutral"}>{state.report.generated_by}</Badge> : null}>
            {!state.report ? <EmptyState title="The report is composed when the workflow finishes" /> : (
              <article className="space-y-3 text-sm text-slate-700">
                <h3 className="text-base font-semibold text-slate-900">{state.report.title}</h3>
                <p>{state.report.executive_summary}</p>
                {state.report.root_cause && <p><strong>Root cause:</strong> {state.report.root_cause}</p>}
                {[["Findings", state.report.findings], ["Actions taken", state.report.actions_taken], ["Evidence citations", state.report.evidence_citations], ["Limitations", state.report.limitations], ["Next steps", state.report.next_steps]].map(([label, items]) =>
                  (items as string[]).length > 0 && (
                    <div key={label as string}><h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500">{label as string}</h4><ul className="mt-1 list-disc pl-5">{(items as string[]).map((item) => <li key={item}>{item}</li>)}</ul></div>
                  ))}
              </article>
            )}
          </Card>
          {can("audit:read") ? <AuditTrail runId={r.id} /> : (
            <Notice tone="info" icon={<ShieldAlert className="size-4" />}>The audit trail is visible to operations managers, auditors and the demo administrator.</Notice>
          )}
        </div>
      </div>

      <Modal open={confirmCancel} onClose={() => setConfirmCancel(false)} title="Cancel investigation?"
        footer={<><Button variant="secondary" onClick={() => setConfirmCancel(false)}>Keep running</Button><Button variant="danger" loading={cancel.isPending} onClick={() => cancel.mutate()}>Cancel investigation</Button></>}>
        <p>The run is marked cancelled and its pending approvals are cancelled (recorded in the audit log). Simulated actions that already executed are not undone.</p>
      </Modal>
    </div>
  );
}
