import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, CircleX, FlaskConical, Undo2 } from "lucide-react";
import { useState } from "react";
import { errorMessage } from "../api/client";
import { endpoints } from "../api/endpoints";
import type { EvaluationDetail, EvaluationRun, Promotion } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { ModeBadge } from "../components/badges";
import { Modal } from "../components/Modal";
import { useToast } from "../components/Toast";
import { Badge, Button, Card, EmptyState, ErrorState, Field, JsonBlock, Loading, Notice, PageHeader, Pagination, Table, Time, cx, inputClass, td, th } from "../components/ui";
import { formatDuration, formatMetric, humanize } from "../lib/format";

interface Rule {
  op: string;
  value: number;
  required: boolean;
}

const ENVIRONMENTS = ["development", "staging", "production_ready"] as const;

function rulesOf(run: EvaluationRun): Record<string, Rule> {
  const thresholds = run.thresholds as { rules?: Record<string, Rule> } | null;
  return thresholds?.rules ?? {};
}

function passes(value: unknown, rule: Rule): boolean | null {
  if (typeof value !== "number") return null;
  switch (rule.op) {
    case ">=": return value >= rule.value;
    case "<=": return value <= rule.value;
    case "==": return value === rule.value;
    case ">": return value > rule.value;
    case "<": return value < rule.value;
    default: return null;
  }
}

function MetricsTable({ run, previous }: { run: EvaluationDetail; previous: EvaluationRun | null }) {
  const rules = rulesOf(run);
  const names = [...new Set([...Object.keys(run.metrics), ...Object.keys(rules)])].filter((n) => n !== "gate.warnings").sort();
  return (
    <Table label="Metrics versus release thresholds">
      <thead className="bg-slate-50"><tr><th className={th}>Metric</th><th className={th}>Measured</th><th className={th}>Threshold</th><th className={th}>Gate</th><th className={th}>Δ vs previous</th></tr></thead>
      <tbody className="divide-y divide-slate-100">
        {names.map((name) => {
          const value = run.metrics[name];
          const rule = rules[name];
          const ok = rule ? passes(value, rule) : null;
          const prev = previous?.metrics[name];
          const delta = typeof value === "number" && typeof prev === "number" ? value - prev : null;
          return (
            <tr key={name}>
              <td className={`${td} font-mono text-xs`}>{name}</td>
              <td className={`${td} tabular-nums`}>{formatMetric(value)}</td>
              <td className={`${td} text-xs`}>{rule ? `${rule.op} ${rule.value}${rule.required ? " (required)" : " (warning)"}` : "—"}</td>
              <td className={td}>
                {ok === null ? (rule ? <Badge tone="danger">not measured</Badge> : <span className="text-xs text-slate-400">info</span>)
                  : ok ? <Badge tone="success">pass</Badge> : <Badge tone={rule?.required ? "danger" : "warning"}>{rule?.required ? "FAIL" : "warn"}</Badge>}
              </td>
              <td className={cx(td, "tabular-nums text-xs", delta !== null && delta !== 0 && (delta > 0 ? "text-emerald-700" : "text-red-700"))}>
                {delta === null ? "—" : delta === 0 ? "0" : `${delta > 0 ? "+" : ""}${Number.isInteger(delta) ? delta : delta.toFixed(3)}`}
              </td>
            </tr>
          );
        })}
      </tbody>
    </Table>
  );
}

function RunDetail({ runId, runs }: { runId: string; runs: EvaluationRun[] }) {
  const [caseType, setCaseType] = useState("");
  const detail = useQuery({ queryKey: ["evaluation", runId], queryFn: () => endpoints.evaluation(runId) });
  if (detail.isPending) return <Loading label="Loading evaluation run…" />;
  if (detail.isError) return <ErrorState error={detail.error} />;
  const run = detail.data;
  const index = runs.findIndex((r) => r.id === run.id);
  const previous = runs.slice(index + 1).find((r) => r.status === "completed" && r.dataset_version === run.dataset_version) ?? null;
  const warnings = (run.metrics["gate.warnings"] as string[] | undefined) ?? [];
  const caseTypes = [...new Set(run.cases.map((c) => c.case_type))].sort();
  const cases = run.cases.filter((c) => !caseType || c.case_type === caseType);
  return (
    <div className="space-y-4">
      <Card title={`Evaluation ${run.id.slice(0, 8)}`} description={run.measurement_note}
        actions={<><ModeBadge mode={run.model_mode} /><Badge tone={run.gate_passed ? "success" : "danger"}>{run.gate_passed ? "Release gate PASSED" : "Release gate FAILED"}</Badge></>}>
        <div className="space-y-3">
          <p className="text-xs text-slate-600">
            Dataset <strong>{run.dataset_id} {run.dataset_version}</strong> · {run.provider}/{run.model} · bundle <code>{run.bundle_hash?.slice(0, 16)}</code> · {formatDuration(run.duration_ms)} ·{" "}
            {run.is_model_assisted ? "includes model-assisted (LLM-as-judge) scores — not ground truth" : "deterministic scoring only (no LLM-as-judge)"}
          </p>
          {(run.gate_failures?.length ?? 0) > 0 && <Notice tone="danger" title="Blocking gate failures">{run.gate_failures?.join("; ")}</Notice>}
          {warnings.length > 0 && <Notice tone="warning" title="Non-blocking warnings">{warnings.join("; ")}</Notice>}
          {previous ? <p className="text-xs text-slate-500">Regression comparison against run {previous.id.slice(0, 8)} (<Time value={previous.created_at} />).</p> : <p className="text-xs text-slate-500">No earlier completed run on this dataset version to compare against.</p>}
        </div>
      </Card>
      <Card title="Metrics vs release thresholds" bodyClassName="px-0 py-0"><MetricsTable run={run} previous={previous} /></Card>
      <Card title={`Per-case results (${run.cases.length})`} bodyClassName="px-0 py-0"
        actions={<Field label="Case type" htmlFor="case-type"><select id="case-type" className={inputClass} value={caseType} onChange={(e) => setCaseType(e.target.value)}><option value="">All</option>{caseTypes.map((t) => <option key={t} value={t}>{humanize(t)}</option>)}</select></Field>}>
        <div className="max-h-[32rem] overflow-y-auto">
          <Table label="Evaluation cases">
            <thead className="sticky top-0 bg-slate-50"><tr><th className={th}>Case</th><th className={th}>Type</th><th className={th}>Result</th><th className={th}>Details</th></tr></thead>
            <tbody className="divide-y divide-slate-100">
              {cases.map((c) => (
                <tr key={`${c.case_type}-${c.case_id}`}>
                  <td className={`${td} font-mono text-xs`}>{c.case_id}</td>
                  <td className={`${td} text-xs`}>{humanize(c.case_type)}</td>
                  <td className={td}>{c.passed ? <CircleCheck className="size-4 text-emerald-600" aria-label="passed" /> : <CircleX className="size-4 text-red-600" aria-label="failed" />}</td>
                  <td className={td}><details><summary className="cursor-pointer text-xs text-navy-700">inspect</summary><JsonBlock value={{ metrics: c.metrics, details: c.details }} /></details></td>
                </tr>
              ))}
            </tbody>
          </Table>
        </div>
      </Card>
    </div>
  );
}

function Promotions({ runs }: { runs: EvaluationRun[] }) {
  const { can, user } = useAuth();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [rollbackTarget, setRollbackTarget] = useState<Promotion | null>(null);
  const [reason, setReason] = useState("");
  const promotions = useQuery({ queryKey: ["promotions"], queryFn: endpoints.promotions });
  const latestPassing = runs.find((r) => r.status === "completed" && r.gate_passed && r.bundle_hash === promotions.data?.current_bundle_hash) ?? null;
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["promotions"] });
  const promote = useMutation({
    mutationFn: (env: string) => endpoints.promote(env, latestPassing?.id ?? "", null),
    onSuccess: (p) => { toast(p.status === "promoted" ? `Promoted to ${humanize(p.to_env)} (simulated).` : `Promotion blocked: ${p.gate_failures.join("; ")}`, p.status === "promoted" ? "success" : "error"); refresh(); },
    onError: (error) => toast(errorMessage(error), "error"),
  });
  const rollback = useMutation({
    mutationFn: () => endpoints.rollbackPromotion(rollbackTarget?.id ?? "", reason.trim()),
    onSuccess: () => { toast("Environment rolled back to its previous bundle (simulated).", "success"); setRollbackTarget(null); refresh(); },
    onError: (error) => toast(errorMessage(error), "error"),
  });
  if (promotions.isPending) return <Loading />;
  if (promotions.isError) return <ErrorState error={promotions.error} />;
  const envs = promotions.data.environments;
  const manageBlocked = can("promotions:manage") ? null : `Requires promotions:manage (your role: ${humanize(user?.role)}).`;
  return (
    <Card title="Simulated promotion workflow" description={promotions.data.note}>
      <p className="mb-3 text-xs text-slate-600">Current bundle <code>{promotions.data.current_bundle_hash.slice(0, 16)}</code> · latest passing evaluation of this bundle: {latestPassing ? <code>{latestPassing.id.slice(0, 8)}</code> : "none — run an evaluation first"}</p>
      <ol className="grid gap-3 md:grid-cols-3">
        {ENVIRONMENTS.map((env, i) => {
          const active = envs[env];
          const previousEnv = i > 0 ? envs[ENVIRONMENTS[i - 1]] : null;
          const reasonBlocked = manageBlocked ?? (!latestPassing ? "Needs a passing evaluation of the current bundle."
            : i > 0 && previousEnv?.bundle_hash !== promotions.data.current_bundle_hash ? `Promote to ${humanize(ENVIRONMENTS[i - 1])} first.`
              : active?.bundle_hash === promotions.data.current_bundle_hash ? "Current bundle is already active here." : null);
          return (
            <li key={env} className="rounded-md border border-slate-200 p-3">
              <p className="text-sm font-semibold text-slate-900">{humanize(env)}</p>
              {active ? <p className="mt-1 text-xs text-slate-600">Active bundle <code>{active.bundle_hash.slice(0, 12)}</code> · <Time value={active.created_at} /></p> : <p className="mt-1 text-xs text-slate-500">No active bundle</p>}
              <div className="mt-3 flex flex-wrap gap-2">
                <Button size="sm" loading={promote.isPending && promote.variables === env} disabledReason={reasonBlocked} onClick={() => promote.mutate(env)}>Promote here</Button>
                {active && <Button size="sm" variant="secondary" icon={<Undo2 className="size-3.5" aria-hidden />} disabledReason={manageBlocked} onClick={() => { setReason(""); setRollbackTarget(active); }}>Roll back</Button>}
              </div>
            </li>
          );
        })}
      </ol>
      <h3 className="mt-5 text-xs font-semibold uppercase tracking-wide text-slate-500">History</h3>
      {promotions.data.history.length === 0 ? <p className="mt-1 text-sm text-slate-500">No promotions yet.</p> : (
        <ul className="mt-2 divide-y divide-slate-100 text-sm">
          {promotions.data.history.map((p) => (
            <li key={p.id} className="flex flex-wrap items-center justify-between gap-2 py-1.5">
              <span><Badge tone={p.status === "promoted" ? "success" : p.status === "blocked" ? "danger" : "warning"}>{humanize(p.status)}</Badge> <span className="ml-1">{p.from_env ? `${humanize(p.from_env)} → ` : ""}{humanize(p.to_env)}</span> <code className="ml-1 text-xs">{p.bundle_hash.slice(0, 10)}</code></span>
              <span className="text-xs text-slate-500">{p.gate_failures.length > 0 && <span className="mr-2 text-red-700">{p.gate_failures[0]}</span>}<Time value={p.created_at} /></span>
            </li>
          ))}
        </ul>
      )}
      <Modal open={rollbackTarget !== null} onClose={() => setRollbackTarget(null)} title={`Roll back ${humanize(rollbackTarget?.to_env)}`}
        footer={<><Button variant="secondary" onClick={() => setRollbackTarget(null)}>Back</Button><Button variant="danger" loading={rollback.isPending} disabledReason={reason.trim().length < 3 ? "Enter a reason (3+ characters)." : null} onClick={() => rollback.mutate()}>Confirm rollback</Button></>}>
        <p>The environment reverts to its previously active bundle. This is a simulated release record — nothing is deployed.</p>
        <Field label="Reason" htmlFor="promo-reason"><input id="promo-reason" className={inputClass} maxLength={300} value={reason} onChange={(e) => setReason(e.target.value)} /></Field>
      </Modal>
    </Card>
  );
}

export function EvaluationsPage() {
  const { can, user } = useAuth();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<string | null>(null);
  const [includeWorkflow, setIncludeWorkflow] = useState(true);
  const runs = useQuery({ queryKey: ["evaluations", page], queryFn: () => endpoints.evaluations({ page, page_size: 10 }), placeholderData: keepPreviousData });
  const run = useMutation({
    mutationFn: () => endpoints.runEvaluation(includeWorkflow),
    onSuccess: (result) => {
      toast(`Evaluation ${result.gate_passed ? "passed" : "failed"} the release gate.`, result.gate_passed ? "success" : "error");
      setSelected(result.id);
      void queryClient.invalidateQueries({ queryKey: ["evaluations"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
      void queryClient.invalidateQueries({ queryKey: ["promotions"] });
    },
    onError: (error) => toast(errorMessage(error), "error"),
  });
  const items = runs.data?.items ?? [];
  const current = selected ?? items[0]?.id ?? null;

  return (
    <div className="space-y-5">
      <PageHeader title="Evaluation & Releases" description="Reproducible evaluation on a versioned synthetic dataset. Metrics are MEASURED by executing the real retrieval, validation, policy and workflow code (workflow cases run in dry-run mode)."
        actions={
          <div className="flex flex-wrap items-start gap-3">
            <label className="mt-2 flex items-center gap-2 text-sm text-slate-700"><input type="checkbox" className="size-4" checked={includeWorkflow} onChange={(e) => setIncludeWorkflow(e.target.checked)} />Include workflow cases</label>
            <Button icon={<FlaskConical className="size-4" aria-hidden />} loading={run.isPending} onClick={() => run.mutate()}
              disabledReason={can("evaluations:run") ? null : `Requires evaluations:run (your role: ${humanize(user?.role)}).`}>Run evaluation</Button>
          </div>
        } />
      <Notice tone="warning" title="How to read these numbers">
        In MOCK MODE the deterministic provider was written alongside this dataset, so high scores verify pipeline logic (retrieval, citation validation,
        policy enforcement, injection defenses, workflow bounds) — not LLM quality. Re-run with a live provider to measure a real model.
      </Notice>
      <Card title="Evaluation runs" bodyClassName="px-0 py-0">
        {runs.isPending ? <Loading /> : runs.isError ? <div className="p-5"><ErrorState error={runs.error} /></div> : items.length === 0 ? (
          <div className="p-5"><EmptyState title="No evaluation runs yet">Run the harness to measure the current configuration bundle.</EmptyState></div>
        ) : (
          <>
            <Table label="Evaluation runs">
              <thead className="bg-slate-50"><tr><th className={th}>Run</th><th className={th}>Dataset</th><th className={th}>Mode</th><th className={th}>Gate</th><th className={th}>Duration</th><th className={th}>Created</th></tr></thead>
              <tbody className="divide-y divide-slate-100">
                {items.map((r) => (
                  <tr key={r.id} className={cx("cursor-pointer hover:bg-slate-50", current === r.id && "bg-navy-50")} onClick={() => setSelected(r.id)}>
                    <td className={td}><button type="button" className="font-mono text-xs font-medium text-navy-700 hover:underline" onClick={() => setSelected(r.id)}>{r.id.slice(0, 8)}</button></td>
                    <td className={`${td} text-xs`}>{r.dataset_id} {r.dataset_version}</td>
                    <td className={td}><ModeBadge mode={r.model_mode} /></td>
                    <td className={td}>{r.status !== "completed" ? <Badge tone="danger">{humanize(r.status)}</Badge> : <Badge tone={r.gate_passed ? "success" : "danger"}>{r.gate_passed ? "passed" : `failed (${r.gate_failures?.length ?? 0})`}</Badge>}</td>
                    <td className={`${td} text-xs`}>{formatDuration(r.duration_ms)}</td>
                    <td className={td}><Time value={r.created_at} /></td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <div className="px-5 pb-3"><Pagination page={page} pageSize={10} total={runs.data.total} onPage={setPage} /></div>
          </>
        )}
      </Card>
      {current && <RunDetail runId={current} runs={items} />}
      <Promotions runs={items} />
    </div>
  );
}
