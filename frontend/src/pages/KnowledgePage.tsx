import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileSearch, RefreshCw, Search, Trash, Upload } from "lucide-react";
import { useRef, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router";
import { ApiError, errorMessage } from "../api/client";
import { endpoints } from "../api/endpoints";
import type { Classification, KnowledgeDocument, SearchResponse } from "../api/types";
import { useAuth } from "../auth/AuthContext";
import { ClassificationBadge, SyntheticBadge } from "../components/badges";
import { Modal } from "../components/Modal";
import { useToast } from "../components/Toast";
import {
  Badge, Button, Card, EmptyState, ErrorState, Field, KeyValue, Loading, Notice, PageHeader, Stat, TabPanel, Table, Tabs, Time, inputClass, td, th,
} from "../components/ui";
import { formatDateTime, formatNumber, humanize, pct } from "../lib/format";

const CLASSIFICATIONS: Classification[] = ["public", "internal", "confidential", "restricted"];
const CLEARANCE: Record<string, number> = { read_only: 1, operations_analyst: 2, operations_manager: 3, auditor: 3, demo_admin: 3 };
const RANK: Record<Classification, number> = { public: 0, internal: 1, confidential: 2, restricted: 3 };
const ROLES = ["demo_admin", "operations_manager", "operations_analyst", "auditor", "read_only"];

function DocumentsTab() {
  const { can, user } = useAuth();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [includeDeleted, setIncludeDeleted] = useState(false);
  const [toDelete, setToDelete] = useState<KnowledgeDocument | null>(null);
  const docs = useQuery({ queryKey: ["knowledge", "documents", includeDeleted], queryFn: () => endpoints.documents({ include_deleted: includeDeleted, page_size: 100 }) });
  const refresh = () => void queryClient.invalidateQueries({ queryKey: ["knowledge"] });
  const reindex = useMutation({
    mutationFn: (id: string) => endpoints.reindex(id),
    onSuccess: (doc) => { toast(`Re-indexed ${doc.doc_key} (${doc.chunk_count} chunks).`, "success"); refresh(); },
    onError: (error) => toast(errorMessage(error), "error"),
  });
  const remove = useMutation({
    mutationFn: (id: string) => endpoints.deleteDocument(id),
    onSuccess: (doc) => { toast(`Soft-deleted ${doc.doc_key}; chunks purged from the index.`, "success"); setToDelete(null); refresh(); },
    onError: (error) => toast(errorMessage(error), "error"),
  });
  const manageBlocked = can("knowledge:manage") ? null : `Requires knowledge:manage (your role: ${humanize(user?.role)})`;

  if (docs.isPending) return <Loading />;
  if (docs.isError) return <ErrorState error={docs.error} onRetry={() => void docs.refetch()} />;
  return (
    <Card title={`${docs.data.total} documents visible to your role`} description="Only documents your tenant, clearance and role allow are listed — the same filters apply to retrieval." bodyClassName="px-0 py-0"
      actions={can("knowledge:manage") && (
        <label className="flex items-center gap-2 text-xs text-slate-700"><input type="checkbox" className="size-4" checked={includeDeleted} onChange={(e) => setIncludeDeleted(e.target.checked)} />Include deleted</label>
      )}>
      {docs.data.items.length === 0 ? <div className="p-5"><EmptyState title="No documents" /></div> : (
        <Table label="Knowledge documents">
          <thead className="bg-slate-50"><tr><th className={th}>Document</th><th className={th}>Class</th><th className={th}>Status</th><th className={th}>Chunks</th><th className={th}>Flags</th><th className={th}>Updated</th><th className={th}>Actions</th></tr></thead>
          <tbody className="divide-y divide-slate-100">
            {docs.data.items.map((doc) => (
              <tr key={doc.id}>
                <td className={td}>
                  <Link to={`/knowledge/${doc.id}`} className="font-medium text-navy-700 hover:underline">{doc.title}</Link>
                  <p className="text-xs text-slate-500"><code>{doc.doc_key}</code> v{doc.version} · {doc.source_type} · {formatNumber(doc.byte_size)} bytes</p>
                </td>
                <td className={td}><ClassificationBadge value={doc.classification} /></td>
                <td className={td}>
                  <Badge tone={doc.status === "indexed" ? (doc.index_current ? "success" : "warning") : doc.status === "failed" ? "danger" : "neutral"}>{humanize(doc.status)}{doc.status === "indexed" && !doc.index_current && " (stale)"}</Badge>
                  {doc.status_detail && <p className="mt-1 max-w-xs text-xs text-slate-500">{doc.status_detail}</p>}
                </td>
                <td className={`${td} tabular-nums`}>{doc.chunk_count}</td>
                <td className={td}>
                  {doc.injection_flag_count > 0 ? <Badge tone="purple" title="Instruction-like content was neutralized at ingestion">{doc.injection_flag_count} injection flag(s)</Badge> : <span className="text-xs text-slate-400">none</span>}
                  {doc.tags.includes("unverified") && <Badge tone="warning" className="ml-1">unverified source</Badge>}
                </td>
                <td className={td}><Time value={doc.updated_at} /></td>
                <td className={td}>
                  {doc.deleted_at ? <span className="text-xs text-slate-500">Deleted · retained until {formatDateTime(doc.retention_until)}</span> : (
                    <div className="flex flex-wrap gap-2">
                      <Button size="sm" variant="secondary" icon={<RefreshCw className="size-3.5" aria-hidden />} loading={reindex.isPending && reindex.variables === doc.id} disabledReason={manageBlocked} onClick={() => reindex.mutate(doc.id)}>Re-index</Button>
                      <Button size="sm" variant="danger" icon={<Trash className="size-3.5" aria-hidden />} disabledReason={manageBlocked} onClick={() => setToDelete(doc)}>Delete…</Button>
                    </div>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </Table>
      )}
      <Modal open={toDelete !== null} onClose={() => setToDelete(null)} title="Soft-delete document?"
        footer={<><Button variant="secondary" onClick={() => setToDelete(null)}>Keep</Button><Button variant="danger" loading={remove.isPending} onClick={() => toDelete && remove.mutate(toDelete.id)}>Delete document</Button></>}>
        <p><strong>{toDelete?.title}</strong> will be removed from retrieval immediately (chunks purged). Its text is retained until the retention period ends, then purged by the retention job. The deletion is audited.</p>
      </Modal>
    </Card>
  );
}

function SearchTab() {
  const [query, setQuery] = useState("document renderer unavailable statement batch failed");
  const [mode, setMode] = useState("hybrid");
  const [topK, setTopK] = useState(5);
  const [classes, setClasses] = useState<string[]>([]);
  const [tags, setTags] = useState("");
  const search = useMutation({
    mutationFn: () => endpoints.search({ query: query.trim(), top_k: topK, mode, classifications: classes, tags: tags.split(",").map((t) => t.trim()).filter(Boolean) }),
  });
  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (query.trim().length >= 3) search.mutate();
  };
  const result: SearchResponse | undefined = search.data;
  return (
    <div className="space-y-4">
      <Card title="Retrieval test" description="Runs the same authorized hybrid retrieval the Evidence Retrieval Agent uses (vector + BM25 with reciprocal-rank fusion and lexical reranking).">
        <form onSubmit={submit} className="grid gap-3 md:grid-cols-6">
          <Field label="Query" htmlFor="q" className="md:col-span-3"><input id="q" className={inputClass} value={query} minLength={3} maxLength={500} onChange={(e) => setQuery(e.target.value)} /></Field>
          <Field label="Mode" htmlFor="q-mode"><select id="q-mode" className={inputClass} value={mode} onChange={(e) => setMode(e.target.value)}><option value="hybrid">Hybrid</option><option value="semantic">Semantic</option><option value="keyword">Keyword (BM25)</option></select></Field>
          <Field label="Top K" htmlFor="q-k"><input id="q-k" type="number" min={1} max={20} className={inputClass} value={topK} onChange={(e) => setTopK(Math.min(20, Math.max(1, Number(e.target.value) || 5)))} /></Field>
          <Field label="Tags (comma separated)" htmlFor="q-tags"><input id="q-tags" className={inputClass} value={tags} onChange={(e) => setTags(e.target.value)} placeholder="e.g. kafka" /></Field>
          <fieldset className="md:col-span-4">
            <legend className="text-xs font-medium text-slate-700">Classification filter (empty = all you are cleared for)</legend>
            <div className="mt-1 flex flex-wrap gap-3">
              {CLASSIFICATIONS.map((c) => (
                <label key={c} className="flex items-center gap-1.5 text-sm"><input type="checkbox" className="size-4" checked={classes.includes(c)} onChange={(e) => setClasses((cur) => e.target.checked ? [...cur, c] : cur.filter((x) => x !== c))} />{humanize(c)}</label>
              ))}
            </div>
          </fieldset>
          <div className="flex items-end md:col-span-2 md:justify-end">
            <Button type="submit" icon={<Search className="size-4" aria-hidden />} loading={search.isPending} disabledReason={query.trim().length < 3 ? "Enter at least 3 characters." : null}>Search</Button>
          </div>
        </form>
      </Card>
      {search.isError && <ErrorState error={search.error} title="Retrieval failed" />}
      {result && (
        <Card title={`${result.results.length} result(s)`} description={`${result.mode} · ${result.latency_ms} ms · ${result.candidate_count} candidates · index ${result.index_version}`}>
          <div className="mb-3 space-y-2">
            <Notice tone={result.sufficient ? "success" : "warning"} title={result.sufficient ? "Sufficient evidence" : "Insufficient evidence"}>{result.reason}</Notice>
            <p className="text-xs text-slate-600"><strong>{result.excluded_unauthorized}</strong> chunk(s) excluded by tenant / classification / role filters before ranking · top score {result.top_score?.toFixed(3) ?? "—"}</p>
          </div>
          {result.results.length === 0 ? <EmptyState title="No authorized results" /> : (
            <ol className="space-y-3">
              {result.results.map((r, index) => (
                <li key={r.chunk_id} className="rounded-md border border-slate-200 p-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <Badge tone="navy">#{index + 1}</Badge>
                    <span className="text-sm font-semibold text-slate-900">{r.title}</span>
                    <ClassificationBadge value={r.classification} />
                    {r.trust === "unverified" && <Badge tone="warning">unverified source (down-ranked)</Badge>}
                    {r.injection_detected && <Badge tone="purple">injection neutralized: {r.injection_patterns.join(", ")}</Badge>}
                  </div>
                  <p className="mt-1 font-mono text-[11px] text-slate-500">{r.citation}</p>
                  <p className="mt-1 text-xs text-slate-500">rerank {r.rerank_score.toFixed(3)} · fused {r.fused_score.toFixed(4)} · semantic {r.semantic_score.toFixed(3)} · keyword {r.keyword_score.toFixed(3)}</p>
                  <p className="mt-2 whitespace-pre-wrap text-xs leading-relaxed text-slate-700">{r.content}</p>
                </li>
              ))}
            </ol>
          )}
        </Card>
      )}
    </div>
  );
}

function IngestTab() {
  const { can, user } = useAuth();
  const toast = useToast();
  const queryClient = useQueryClient();
  const fileRef = useRef<HTMLInputElement>(null);
  const [form, setForm] = useState({ title: "", doc_key: "", version: "1.0", classification: "internal", tags: "" });
  const [roles, setRoles] = useState<string[]>(["demo_admin", "operations_manager", "operations_analyst", "auditor"]);
  const [error, setError] = useState<string | null>(null);
  const ingest = useMutation({
    mutationFn: () => {
      const file = fileRef.current?.files?.[0];
      if (!file) throw new Error("Choose a .md, .txt or .pdf file.");
      const data = new FormData();
      data.set("file", file);
      for (const [key, value] of Object.entries(form)) data.set(key, value);
      data.set("allowed_roles", roles.join(","));
      return endpoints.ingest(data);
    },
    onSuccess: (doc) => {
      toast(`Indexed ${doc.doc_key}: ${doc.chunk_count} chunk(s)${doc.injection_flag_count ? `, ${doc.injection_flag_count} injection flag(s) neutralized` : ""}.`, "success");
      setError(null);
      void queryClient.invalidateQueries({ queryKey: ["knowledge"] });
    },
    onError: (err) => setError(err instanceof ApiError && err.code === "duplicate_document" ? "An identical document is already indexed (duplicate content hash)." : errorMessage(err)),
  });
  if (!can("knowledge:ingest")) {
    return <Notice tone="info" title="Ingestion requires knowledge:ingest">Your role ({humanize(user?.role)}) can search and read documents but cannot ingest new ones. Operations managers and the demo administrator can.</Notice>;
  }
  const clearance = CLEARANCE[user?.role ?? "read_only"] ?? 1;
  return (
    <Card title="Ingest a synthetic knowledge document" description="Approved formats: Markdown, text, PDF (size-limited, content-sniffed). Duplicates are detected by content hash; instruction-like text is neutralized at ingestion.">
      <form className="grid gap-3 md:grid-cols-2" onSubmit={(e) => { e.preventDefault(); ingest.mutate(); }}>
        <Field label="File" htmlFor="ing-file" className="md:col-span-2"><input id="ing-file" ref={fileRef} type="file" accept=".md,.markdown,.txt,.pdf,text/markdown,text/plain,application/pdf" className={inputClass} /></Field>
        <Field label="Title" htmlFor="ing-title"><input id="ing-title" className={inputClass} required minLength={3} maxLength={200} value={form.title} onChange={(e) => setForm({ ...form, title: e.target.value })} /></Field>
        <Field label="Document key" htmlFor="ing-key" hint="e.g. RB-TEST-020 (letters, digits and dashes)"><input id="ing-key" className={inputClass} required minLength={3} maxLength={64} value={form.doc_key} onChange={(e) => setForm({ ...form, doc_key: e.target.value })} /></Field>
        <Field label="Version" htmlFor="ing-version"><input id="ing-version" className={inputClass} maxLength={16} value={form.version} onChange={(e) => setForm({ ...form, version: e.target.value })} /></Field>
        <Field label="Classification" htmlFor="ing-class" hint="You cannot upload above your own clearance.">
          <select id="ing-class" className={inputClass} value={form.classification} onChange={(e) => setForm({ ...form, classification: e.target.value })}>
            {CLASSIFICATIONS.filter((c) => RANK[c] <= clearance).map((c) => <option key={c} value={c}>{humanize(c)}</option>)}
          </select>
        </Field>
        <fieldset className="md:col-span-2">
          <legend className="text-xs font-medium text-slate-700">Allowed roles</legend>
          <div className="mt-1 flex flex-wrap gap-3">{ROLES.map((r) => (
            <label key={r} className="flex items-center gap-1.5 text-sm"><input type="checkbox" className="size-4" checked={roles.includes(r)} onChange={(e) => setRoles((cur) => e.target.checked ? [...cur, r] : cur.filter((x) => x !== r))} />{humanize(r)}</label>
          ))}</div>
        </fieldset>
        <Field label="Tags (comma separated)" htmlFor="ing-tags" className="md:col-span-2"><input id="ing-tags" className={inputClass} maxLength={300} value={form.tags} onChange={(e) => setForm({ ...form, tags: e.target.value })} /></Field>
        {error && <p role="alert" className="text-sm text-red-700 md:col-span-2">{error}</p>}
        <div className="md:col-span-2">
          <Button type="submit" icon={<Upload className="size-4" aria-hidden />} loading={ingest.isPending}
            disabledReason={!form.title.trim() || form.doc_key.trim().length < 3 ? "Enter a title and a document key." : roles.length === 0 ? "Select at least one allowed role." : null}>
            Upload and index
          </Button>
        </div>
      </form>
    </Card>
  );
}

function IndexTab() {
  const { can } = useAuth();
  const toast = useToast();
  const queryClient = useQueryClient();
  const stats = useQuery({ queryKey: ["knowledge", "stats"], queryFn: endpoints.knowledgeStats });
  const stale = useMutation({
    mutationFn: endpoints.reindexStale,
    onSuccess: (res) => { toast(`Re-indexed ${res.reindexed} stale document(s).`, "success"); void queryClient.invalidateQueries({ queryKey: ["knowledge"] }); },
    onError: (error) => toast(errorMessage(error), "error"),
  });
  if (stats.isPending) return <Loading />;
  if (stats.isError) return <ErrorState error={stats.error} />;
  const s = stats.data;
  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <Stat label="Documents" value={s.documents} hint={`${s.chunks} chunks indexed`} />
        <Stat label="Stale documents" value={s.stale_documents} tone={s.stale_documents ? "warning" : undefined} hint={`index ${s.index_version}`} />
        <Stat label="Injection-flagged docs" value={s.injection_flagged_documents} hint="neutralized at ingestion" />
        <Stat label="Failed documents" value={s.failed_documents} tone={s.failed_documents ? "danger" : undefined} />
      </div>
      <div className="grid gap-4 lg:grid-cols-2">
        <Card title="Index configuration">
          <KeyValue items={[
            ["Vector backend", s.vector_backend],
            ["Embeddings", `${s.embedding.provider} / ${s.embedding.model} (${s.embedding.dim}d)`],
            ["Chunking", `${s.chunking.chunk_size} chars, ${s.chunking.chunk_overlap} overlap (structure-aware)`],
            ["Retrieval", `${s.retrieval.mode}, top ${s.retrieval.top_k}, min score ${s.retrieval.min_score}`],
            ["Fusion / rerank", `${s.retrieval.fusion} / ${s.retrieval.reranker}`],
            ["Index version", s.index_version],
          ]} />
          <div className="mt-4">
            <Button variant="secondary" icon={<RefreshCw className="size-4" aria-hidden />} loading={stale.isPending} onClick={() => stale.mutate()}
              disabledReason={!can("knowledge:manage") ? "Requires knowledge:manage." : s.stale_documents === 0 ? "No stale documents — index is current." : null}>
              Re-index stale documents
            </Button>
          </div>
        </Card>
        <Card title="Retrieval metrics" description={`MEASURED — ${s.retrieval_metrics.source}`}>
          <KeyValue items={[
            ["Queries", s.retrieval_metrics.queries],
            ["Latency p50 / p95", `${s.retrieval_metrics.latency_ms_p50 ?? "—"} ms / ${s.retrieval_metrics.latency_ms_p95 ?? "—"} ms`],
            ["Sufficiency rate", pct(s.retrieval_metrics.sufficiency_rate)],
            ["Errors", s.retrieval_metrics.errors],
            ["Avg. chunks excluded by authorization", s.retrieval_metrics.avg_excluded_unauthorized ?? "—"],
          ]} />
          <p className="mt-3 text-xs text-slate-500">Labeled retrieval quality (Recall@K, MRR, precision) is measured by the <Link to="/evaluations" className="text-navy-700 underline">evaluation harness</Link>.</p>
        </Card>
      </div>
      <Card title="Prompt-injection pattern catalog" description="Deterministic detectors applied to documents, logs, tool results and analyst notes">
        <ul className="grid gap-1 text-sm md:grid-cols-2">{Object.entries(s.injection_patterns).map(([id, description]) => <li key={id}><Badge tone="purple">{id}</Badge> <span className="text-slate-700">{description}</span></li>)}</ul>
      </Card>
    </div>
  );
}

export function KnowledgePage() {
  const [tab, setTab] = useState("documents");
  return (
    <div className="space-y-4">
      <PageHeader title="Knowledge Center" description="Governed RAG over fictional runbooks. All retrieved text is treated as untrusted data: authorization is enforced in the query, and instruction-like content is neutralized." />
      <Tabs label="Knowledge sections" active={tab} onChange={setTab} tabs={[
        { id: "documents", label: "Documents" }, { id: "search", label: "Retrieval test" }, { id: "ingest", label: "Ingest" }, { id: "index", label: "Index status" },
      ]} />
      <TabPanel id={tab}>
        {tab === "documents" && <DocumentsTab />}
        {tab === "search" && <SearchTab />}
        {tab === "ingest" && <IngestTab />}
        {tab === "index" && <IndexTab />}
      </TabPanel>
    </div>
  );
}

export function DocumentPage() {
  const { docId = "" } = useParams();
  const doc = useQuery({ queryKey: ["knowledge", "document", docId], queryFn: () => endpoints.document(docId) });
  if (doc.isPending) return <Loading label="Loading document…" />;
  if (doc.isError) return <ErrorState error={doc.error} title="Document unavailable" />;
  const d = doc.data;
  return (
    <div className="space-y-4">
      <PageHeader title={d.title} description={<span><code>{d.doc_key}</code> v{d.version} · {d.source}</span>} actions={<Link to="/knowledge" className="text-sm font-medium text-navy-700 hover:underline">← Knowledge Center</Link>}>
        <div className="mt-2 flex flex-wrap gap-2"><ClassificationBadge value={d.classification} /><SyntheticBadge /><Badge>{humanize(d.status)}</Badge>{d.tags.map((t) => <Badge key={t} tone="navy">{t}</Badge>)}</div>
      </PageHeader>
      <Card title="Metadata">
        <KeyValue columns={3} items={[
          ["Allowed roles", d.allowed_roles.map(humanize).join(", ")],
          ["Source type", d.source_type],
          ["Content hash (SHA-256)", <code key="h" className="break-all text-xs">{d.content_hash}</code>],
          ["Index version", `${d.index_version ?? "—"}${d.index_current ? " (current)" : " (stale)"}`],
          ["Created", formatDateTime(d.created_at)],
          ["Updated", formatDateTime(d.updated_at)],
          ["Injection flags", d.injection_flag_count],
          ["Retention until", formatDateTime(d.retention_until)],
          ["Size", `${formatNumber(d.byte_size)} bytes`],
        ]} />
      </Card>
      <Card title={`${d.chunks.length} chunk(s)`} description="Structure-aware chunks with section paths; these are the units cited by agents" actions={<FileSearch className="size-4 text-slate-400" aria-hidden />}>
        {d.chunks.length === 0 ? <EmptyState title="No chunks (deleted or not indexed)" /> : (
          <ol className="space-y-3">
            {d.chunks.map((c) => (
              <li key={c.id} className="rounded-md border border-slate-200 p-3">
                <div className="flex flex-wrap items-center gap-2 text-xs text-slate-500">
                  <code className="font-mono text-slate-700">{c.chunk_ref}</code><span>{c.section}</span><span>{c.char_count} chars · ~{c.token_estimate} tokens · {c.embedding_model}</span>
                  {c.injection_detected && <Badge tone="purple">injection neutralized: {c.injection_patterns.join(", ")}</Badge>}
                </div>
                <p className="mt-2 whitespace-pre-wrap text-xs leading-relaxed text-slate-800">{c.content}</p>
              </li>
            ))}
          </ol>
        )}
      </Card>
    </div>
  );
}
