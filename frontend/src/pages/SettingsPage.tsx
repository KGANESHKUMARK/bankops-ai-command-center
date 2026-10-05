import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleCheck, CircleX, RotateCcw } from "lucide-react";
import { useState } from "react";
import { errorMessage } from "../api/client";
import { endpoints } from "../api/endpoints";
import { useAuth } from "../auth/AuthContext";
import { ModeBadge } from "../components/badges";
import { Modal } from "../components/Modal";
import { useToast } from "../components/Toast";
import { Badge, Button, Card, ErrorState, KeyValue, Loading, Notice, PageHeader } from "../components/ui";
import { humanize } from "../lib/format";

function display(value: unknown): string {
  if (Array.isArray(value)) return value.join(", ") || "—";
  if (typeof value === "boolean") return value ? "enabled" : "disabled";
  return value === null || value === undefined ? "—" : String(value);
}

export function DemoControls() {
  const { user } = useAuth();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [confirmReset, setConfirmReset] = useState(false);
  const settings = useQuery({ queryKey: ["settings"], queryFn: endpoints.settings });
  const faults = useQuery({ queryKey: ["faults"], queryFn: endpoints.faults, enabled: Boolean(settings.data?.can_toggle_faults) });
  const reset = useMutation({
    mutationFn: endpoints.resetDemo,
    onSuccess: () => {
      toast("Synthetic demo state reset to the seeded baseline.", "success");
      setConfirmReset(false);
      void queryClient.invalidateQueries();
    },
    onError: (error) => toast(errorMessage(error), "error"),
  });
  const toggle = useMutation({
    mutationFn: ({ name, enabled }: { name: string; enabled: boolean }) => endpoints.setFault(name, enabled),
    onSuccess: (_, { name, enabled }) => {
      toast(`${humanize(name)} ${enabled ? "enabled" : "disabled"}.`, enabled ? "info" : "success");
      void queryClient.invalidateQueries({ queryKey: ["faults"] });
      void queryClient.invalidateQueries({ queryKey: ["observability"] });
    },
    onError: (error) => toast(errorMessage(error), "error"),
  });
  const notAdmin = settings.data && !settings.data.can_reset_demo
    ? settings.data.demo_mode ? `Only the demo administrator can do this (you are ${humanize(user?.role)}).` : "Demo controls are disabled outside local/demo mode."
    : null;
  return (
    <Card title="Demo controls" description="Restricted to demo_admin in local/demo mode; every use is audited">
      <div className="space-y-4">
        <div>
          <Button variant="danger" icon={<RotateCcw className="size-4" aria-hidden />} disabledReason={settings.isPending ? "Loading…" : notAdmin} onClick={() => setConfirmReset(true)}>Reset demo to known state…</Button>
          <p className="mt-1 text-xs text-slate-500">Deletes investigations, approvals and actions for the demo tenants and re-seeds incidents, services and knowledge. Audit events and evaluation history are preserved.</p>
        </div>
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Failure injection</h3>
          {notAdmin ? <p className="mt-1 text-sm text-slate-500">{notAdmin}</p> : faults.isPending ? <Loading /> : faults.isError ? <ErrorState error={faults.error} /> : (
            <ul className="mt-2 space-y-2">
              {Object.entries(faults.data.descriptions).map(([name, description]) => {
                const enabled = faults.data.faults[name];
                return (
                  <li key={name} className="flex flex-wrap items-start justify-between gap-3 rounded-md border border-slate-200 p-3">
                    <div className="min-w-0">
                      <p className="text-sm font-medium text-slate-900">{humanize(name)} {enabled && <Badge tone="warning">ACTIVE</Badge>}</p>
                      <p className="text-xs text-slate-600">{description}</p>
                    </div>
                    <Button size="sm" variant={enabled ? "secondary" : "primary"} loading={toggle.isPending && toggle.variables?.name === name}
                      aria-pressed={enabled} onClick={() => toggle.mutate({ name, enabled: !enabled })}>
                      {enabled ? "Disable" : "Enable"}
                    </Button>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>
      <Modal open={confirmReset} onClose={() => setConfirmReset(false)} title="Reset the synthetic demo?"
        footer={<><Button variant="secondary" onClick={() => setConfirmReset(false)}>Cancel</Button><Button variant="danger" loading={reset.isPending} onClick={() => reset.mutate()}>Reset demo</Button></>}>
        <p>All investigations, approvals and simulated actions for the demo tenants will be removed and the seeded baseline restored. This only affects synthetic demo data.</p>
      </Modal>
    </Card>
  );
}

export function SettingsPage() {
  const settings = useQuery({ queryKey: ["settings"], queryFn: endpoints.settings });
  const ready = useQuery({ queryKey: ["ready"], queryFn: endpoints.ready, refetchInterval: 30000, retry: false });
  const health = useQuery({ queryKey: ["health"], queryFn: endpoints.health, retry: false });
  if (settings.isPending) return <Loading label="Loading configuration…" />;
  if (settings.isError) return <ErrorState error={settings.error} onRetry={() => void settings.refetch()} />;
  const s = settings.data;
  return (
    <div className="space-y-5">
      <PageHeader title="Settings & system status" description="Safe configuration view. Secrets are never returned by the API — only whether they are configured." />
      <div className="flex flex-wrap gap-2">
        <ModeBadge mode={s.model.mode} />
        <Badge tone="navy">Environment: {s.environment}</Badge>
        <Badge tone={s.demo_mode ? "warning" : "neutral"}>Demo mode {s.demo_mode ? "ON" : "OFF"}</Badge>
        <Badge>Version {s.version}</Badge>
        {s.synthetic_data && <Badge tone="warning">SYNTHETIC DATA</Badge>}
      </div>
      {s.model.mock_mode && (
        <Notice tone="warning" title="MOCK MODE">No external model is called and no API key is needed. Outputs are deterministic and clearly labeled; they are not real model inference. Configure an approved OpenAI-compatible provider via environment variables to switch.</Notice>
      )}
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Model provider">
          <KeyValue items={[
            ["Configured provider", s.model.configured_provider],
            ["Active provider / model", `${s.model.provider} / ${s.model.model}`],
            ["Approved models", display(s.model.approved_models)],
            ["Base URL", s.model.base_url_configured ? "configured" : "not set"],
            ["API key", s.model.api_key],
            ["Timeout / retries", `${s.model.timeout_seconds}s / ${s.model.max_retries}`],
            ["Circuit breaker", s.model.circuit_breaker],
            ["LLM-as-judge", s.model.judge_enabled ? "enabled (model-assisted, not ground truth)" : "disabled"],
          ]} />
        </Card>
        <Card title="Embeddings & storage">
          <KeyValue items={[
            ["Embedding provider", s.embedding.provider],
            ["Embedding model", `${s.embedding.model} (${s.embedding.dim}d)`],
            ["Embedding API key", s.embedding.api_key],
            ["Database", s.storage.database],
            ["Vector backend", s.storage.vector_backend],
            ["Index version", s.storage.index_version],
          ]} />
        </Card>
        <Card title="Security">
          <KeyValue items={Object.entries(s.security).map(([k, v]) => [humanize(k), display(v)])} />
        </Card>
        <Card title="Workflow bounds & policy">
          <KeyValue items={[...Object.entries(s.workflow), ...Object.entries(s.policy)].map(([k, v]) => [humanize(k), display(v)])} />
        </Card>
        <Card title="Health & readiness" description="GET /health (liveness) and GET /ready (database, migrations, index, model gateway)">
          <p className="mb-3 text-sm">Liveness: {health.isError ? <Badge tone="danger">unreachable</Badge> : <Badge tone="success">{health.data?.status ?? "…"}</Badge>} · Readiness: <Badge tone={ready.data?.status === "ready" ? "success" : ready.data?.status === "degraded" ? "warning" : "danger"}>{ready.data?.status ?? (ready.isError ? "unreachable" : "…")}</Badge></p>
          <ul className="space-y-1 text-sm">
            {Object.entries(ready.data?.checks ?? {}).map(([name, check]) => (
              <li key={name} className="flex items-center gap-1.5">{check.ok ? <CircleCheck className="size-4 text-emerald-600" aria-label="ok" /> : <CircleX className="size-4 text-red-600" aria-label="failing" />}<span className="font-medium">{humanize(name)}</span></li>
            ))}
          </ul>
        </Card>
        <DemoControls />
      </div>
    </div>
  );
}
