import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link, useSearchParams } from "react-router";
import { endpoints } from "../api/endpoints";
import { ClassificationBadge, IncidentStatusBadge, SeverityBadge } from "../components/badges";
import { Card, EmptyState, ErrorState, Field, Loading, PageHeader, Pagination, Table, Time, inputClass, td, th } from "../components/ui";
import { humanize } from "../lib/format";

export const CATEGORIES = [
  "batch_delay", "capacity_warning", "certificate_warning", "config_drift", "data_quality_failure", "duplicate_events",
  "flink_job_failure", "fraud_alert", "hsm_latency", "kafka_consumer_lag", "latency_warning", "mq_queue_backlog",
  "notification_delay", "payment_processing_delay", "snowflake_ingestion_delay", "statement_generation", "vendor_delay",
];
const STATUSES = ["open", "investigating", "awaiting_approval", "mitigated", "resolved", "closed"];
const SEVERITIES = ["critical", "high", "medium", "low"];
const PAGE_SIZE = 20;

export function IncidentsPage() {
  const [params, setParams] = useSearchParams();
  const filters = {
    search: params.get("search") ?? "",
    severity: params.get("severity") ?? "",
    status: params.get("status") ?? "",
    category: params.get("category") ?? "",
    service: params.get("service") ?? "",
    open_only: params.get("open_only") === "true",
    sort: params.get("sort") ?? "detected_desc",
    page: Math.max(1, Number(params.get("page") ?? "1") || 1),
  };
  const [searchText, setSearchText] = useState(filters.search);
  const searchTimer = useRef<number | undefined>(undefined);

  const update = (patch: Record<string, string | null>) => {
    const next = new URLSearchParams(params);
    for (const [key, value] of Object.entries(patch)) {
      if (value === null || value === "" || value === "false") next.delete(key);
      else next.set(key, value);
    }
    if (!("page" in patch)) next.delete("page");
    setParams(next, { replace: true });
  };

  const onSearch = (value: string) => {
    setSearchText(value);
    window.clearTimeout(searchTimer.current);
    searchTimer.current = window.setTimeout(() => update({ search: value.trim() || null }), 300);
  };
  useEffect(() => () => window.clearTimeout(searchTimer.current), []);

  const services = useQuery({ queryKey: ["services"], queryFn: endpoints.services, staleTime: 60000 });
  const incidents = useQuery({
    queryKey: ["incidents", filters],
    queryFn: () => endpoints.incidents({ ...filters, page_size: PAGE_SIZE }),
    placeholderData: keepPreviousData,
  });

  return (
    <div className="space-y-5">
      <PageHeader title="Incident Explorer" description="Search and filter synthetic incidents visible to your role and tenant. Restricted incidents require clearance." />
      <Card title="Filters">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4 xl:grid-cols-7">
          <Field label="Search" htmlFor="f-search" className="xl:col-span-2">
            <div className="relative">
              <Search className="pointer-events-none absolute left-2.5 top-2.5 size-4 text-slate-400" aria-hidden />
              <input id="f-search" className={`${inputClass} pl-8`} placeholder="Number, title or description" value={searchText} maxLength={100} onChange={(e) => onSearch(e.target.value)} />
            </div>
          </Field>
          <Field label="Severity" htmlFor="f-severity">
            <select id="f-severity" className={inputClass} value={filters.severity} onChange={(e) => update({ severity: e.target.value })}>
              <option value="">All</option>
              {SEVERITIES.map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
            </select>
          </Field>
          <Field label="Status" htmlFor="f-status">
            <select id="f-status" className={inputClass} value={filters.status} onChange={(e) => update({ status: e.target.value })}>
              <option value="">All</option>
              {STATUSES.map((s) => <option key={s} value={s}>{humanize(s)}</option>)}
            </select>
          </Field>
          <Field label="Category" htmlFor="f-category">
            <select id="f-category" className={inputClass} value={filters.category} onChange={(e) => update({ category: e.target.value })}>
              <option value="">All</option>
              {CATEGORIES.map((c) => <option key={c} value={c}>{humanize(c)}</option>)}
            </select>
          </Field>
          <Field label="Service" htmlFor="f-service">
            <select id="f-service" className={inputClass} value={filters.service} onChange={(e) => update({ service: e.target.value })}>
              <option value="">All</option>
              {services.data?.map((s) => <option key={s.key} value={s.key}>{s.name}</option>)}
            </select>
          </Field>
          <Field label="Sort" htmlFor="f-sort">
            <select id="f-sort" className={inputClass} value={filters.sort} onChange={(e) => update({ sort: e.target.value })}>
              <option value="detected_desc">Newest first</option>
              <option value="detected_asc">Oldest first</option>
              <option value="severity">Severity</option>
            </select>
          </Field>
        </div>
        <label className="mt-3 inline-flex items-center gap-2 text-sm text-slate-700">
          <input type="checkbox" className="size-4" checked={filters.open_only} onChange={(e) => update({ open_only: e.target.checked ? "true" : null })} />
          Open incidents only
        </label>
      </Card>

      <Card title="Incidents" description={incidents.data ? `${incidents.data.total} matching synthetic incidents` : undefined} bodyClassName="px-0 py-0">
        {incidents.isPending ? <Loading /> : incidents.isError ? (
          <div className="p-5"><ErrorState error={incidents.error} onRetry={() => void incidents.refetch()} /></div>
        ) : incidents.data.items.length === 0 ? (
          <div className="p-5"><EmptyState title="No incidents match these filters">Try clearing a filter.</EmptyState></div>
        ) : (
          <>
            <Table label="Incidents">
              <thead className="bg-slate-50">
                <tr><th className={th}>Incident</th><th className={th}>Severity</th><th className={th}>Status</th><th className={th}>Service</th><th className={th}>Owner</th><th className={th}>Detected</th><th className={th}>Class</th></tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {incidents.data.items.map((incident) => (
                  <tr key={incident.id} className="hover:bg-slate-50">
                    <td className={td}>
                      <Link to={`/incidents/${incident.id}`} className="font-medium text-navy-700 hover:underline">{incident.number}</Link>
                      <p className="max-w-md text-xs text-slate-600">{incident.title}</p>
                    </td>
                    <td className={td}><SeverityBadge value={incident.severity} /></td>
                    <td className={td}><IncidentStatusBadge value={incident.status} /></td>
                    <td className={td}><code className="text-xs">{incident.primary_service ?? "—"}</code></td>
                    <td className={td}>{incident.owner_team}</td>
                    <td className={td}><Time value={incident.detected_at} /></td>
                    <td className={td}><ClassificationBadge value={incident.classification} /></td>
                  </tr>
                ))}
              </tbody>
            </Table>
            <div className="px-5 pb-3"><Pagination page={filters.page} pageSize={PAGE_SIZE} total={incidents.data.total} onPage={(page) => update({ page: String(page) })} /></div>
          </>
        )}
      </Card>
    </div>
  );
}
