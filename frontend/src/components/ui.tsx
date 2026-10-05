import { CircleAlert, Inbox, LoaderCircle } from "lucide-react";
import { useId, useRef, type ButtonHTMLAttributes, type KeyboardEvent, type ReactNode } from "react";
import { ApiError, errorMessage } from "../api/client";
import { formatDateTime, relativeTime } from "../lib/format";

export function cx(...parts: (string | false | null | undefined)[]): string {
  return parts.filter(Boolean).join(" ");
}

type Variant = "primary" | "secondary" | "danger" | "success" | "ghost";
const VARIANTS: Record<Variant, string> = {
  primary: "bg-navy-700 text-white hover:bg-navy-800 disabled:bg-navy-300",
  secondary: "border border-slate-300 bg-white text-navy-800 hover:bg-slate-50 disabled:text-slate-400 disabled:hover:bg-white",
  danger: "bg-red-700 text-white hover:bg-red-800 disabled:bg-red-300",
  success: "bg-emerald-700 text-white hover:bg-emerald-800 disabled:bg-emerald-300",
  ghost: "text-navy-700 hover:bg-navy-50 disabled:text-slate-400 disabled:hover:bg-transparent",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant;
  size?: "sm" | "md";
  loading?: boolean;
  icon?: ReactNode;
  /** When set the button is disabled and the reason is shown next to it (and linked via aria-describedby). */
  disabledReason?: string | null;
}

export function Button({ variant = "primary", size = "md", loading, icon, disabledReason, disabled, className, children, ...rest }: ButtonProps) {
  const reasonId = useId();
  const isDisabled = Boolean(disabled || loading || disabledReason);
  const button = (
    <button
      type="button"
      {...rest}
      disabled={isDisabled}
      aria-busy={loading || undefined}
      aria-describedby={disabledReason ? reasonId : rest["aria-describedby"]}
      className={cx(
        "inline-flex items-center justify-center gap-1.5 rounded-md font-medium shadow-sm transition-colors disabled:cursor-not-allowed",
        size === "sm" ? "px-2.5 py-1.5 text-xs" : "px-3.5 py-2 text-sm",
        VARIANTS[variant],
        className,
      )}
    >
      {loading ? <LoaderCircle className="size-4 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  );
  if (!disabledReason) return button;
  return (
    <span className="inline-flex max-w-sm flex-col items-start gap-1">
      {button}
      <span id={reasonId} className="text-xs leading-snug text-slate-500">{disabledReason}</span>
    </span>
  );
}

export function Card({ title, description, actions, children, className, bodyClassName }: {
  title?: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}) {
  const headingId = useId();
  return (
    <section aria-labelledby={title ? headingId : undefined} className={cx("min-w-0 rounded-lg border border-slate-200 bg-white shadow-sm", className)}>
      {(title || actions) && (
        <header className="flex flex-wrap items-start justify-between gap-3 border-b border-slate-100 px-5 py-3.5">
          <div className="min-w-0">
            {title && <h2 id={headingId} className="text-sm font-semibold text-slate-900">{title}</h2>}
            {description && <p className="mt-0.5 text-xs text-slate-500">{description}</p>}
          </div>
          {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
        </header>
      )}
      <div className={cx("px-5 py-4", bodyClassName)}>{children}</div>
    </section>
  );
}

export function PageHeader({ title, description, actions, children }: { title: ReactNode; description?: ReactNode; actions?: ReactNode; children?: ReactNode }) {
  return (
    <div className="mb-5 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        <h1 className="text-xl font-semibold tracking-tight text-slate-900">{title}</h1>
        {description && <p className="mt-1 max-w-3xl text-sm text-slate-600">{description}</p>}
        {children}
      </div>
      {actions && <div className="flex flex-wrap items-center gap-2">{actions}</div>}
    </div>
  );
}

export type Tone = "neutral" | "info" | "success" | "warning" | "danger" | "navy" | "purple";
const TONES: Record<Tone, string> = {
  neutral: "bg-slate-100 text-slate-700 ring-slate-200",
  info: "bg-sky-50 text-sky-800 ring-sky-200",
  success: "bg-emerald-50 text-emerald-800 ring-emerald-200",
  warning: "bg-amber-50 text-amber-900 ring-amber-300",
  danger: "bg-red-50 text-red-800 ring-red-200",
  navy: "bg-navy-50 text-navy-800 ring-navy-200",
  purple: "bg-violet-50 text-violet-800 ring-violet-200",
};

export function Badge({ tone = "neutral", children, title, className }: { tone?: Tone; children: ReactNode; title?: string; className?: string }) {
  return (
    <span title={title} className={cx("inline-flex items-center gap-1 whitespace-nowrap rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset", TONES[tone], className)}>
      {children}
    </span>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div role="status" className="flex items-center justify-center gap-2 py-10 text-sm text-slate-500">
      <LoaderCircle className="size-4 animate-spin" aria-hidden />
      {label}
    </div>
  );
}

export function ErrorState({ error, title = "Could not load data", onRetry }: { error: unknown; title?: string; onRetry?: () => void }) {
  const requestId = error instanceof ApiError ? error.requestId : null;
  return (
    <div role="alert" className="flex flex-wrap items-start justify-between gap-3 rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-900">
      <div className="flex items-start gap-2">
        <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
        <div>
          <p className="font-semibold">{title}</p>
          <p className="mt-0.5">{errorMessage(error)}</p>
          {requestId && <p className="mt-1 font-mono text-xs text-red-700">Request ID: {requestId}</p>}
        </div>
      </div>
      {onRetry && <Button variant="secondary" size="sm" onClick={onRetry}>Retry</Button>}
    </div>
  );
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center justify-center gap-1 rounded-md border border-dashed border-slate-300 px-4 py-8 text-center">
      <Inbox className="size-5 text-slate-400" aria-hidden />
      <p className="text-sm font-medium text-slate-700">{title}</p>
      {children && <div className="text-xs text-slate-500">{children}</div>}
    </div>
  );
}

export function Notice({ tone = "info", title, children, icon }: { tone?: "info" | "warning" | "danger" | "success" | "purple"; title?: ReactNode; children?: ReactNode; icon?: ReactNode }) {
  const styles = {
    info: "border-sky-200 bg-sky-50 text-sky-900",
    warning: "border-amber-300 bg-amber-50 text-amber-950",
    danger: "border-red-200 bg-red-50 text-red-900",
    success: "border-emerald-200 bg-emerald-50 text-emerald-900",
    purple: "border-violet-200 bg-violet-50 text-violet-900",
  }[tone];
  return (
    <div role="note" className={cx("flex items-start gap-2 rounded-md border px-3.5 py-2.5 text-sm", styles)}>
      {icon && <span className="mt-0.5 shrink-0" aria-hidden>{icon}</span>}
      <div className="min-w-0">
        {title && <p className="font-semibold">{title}</p>}
        {children && <div className={title ? "mt-0.5" : undefined}>{children}</div>}
      </div>
    </div>
  );
}

export function Stat({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: ReactNode; tone?: "danger" | "warning" | "success" }) {
  const color = tone === "danger" ? "text-red-700" : tone === "warning" ? "text-amber-700" : tone === "success" ? "text-emerald-700" : "text-slate-900";
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
      <p className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</p>
      <p className={cx("mt-1 text-2xl font-semibold tabular-nums", color)}>{value}</p>
      {hint && <p className="mt-1 text-xs text-slate-500">{hint}</p>}
    </div>
  );
}

export function KeyValue({ items, columns = 2 }: { items: [string, ReactNode][]; columns?: 1 | 2 | 3 }) {
  const grid = columns === 1 ? "" : columns === 2 ? "sm:grid-cols-2" : "sm:grid-cols-3";
  return (
    <dl className={cx("grid grid-cols-1 gap-x-6 gap-y-3", grid)}>
      {items.map(([key, value]) => (
        <div key={key} className="min-w-0">
          <dt className="text-xs font-medium text-slate-500">{key}</dt>
          <dd className="mt-0.5 break-words text-sm text-slate-900">{value ?? "—"}</dd>
        </div>
      ))}
    </dl>
  );
}

export function JsonBlock({ value, label }: { value: unknown; label?: string }) {
  return (
    <pre aria-label={label} className="max-h-72 overflow-auto rounded-md bg-slate-950 p-3 font-mono text-xs leading-relaxed text-slate-100">
      {JSON.stringify(value, null, 2)}
    </pre>
  );
}

export function Time({ value }: { value?: string | null }) {
  if (!value) return <span>—</span>;
  return <time dateTime={value} title={formatDateTime(value)}>{relativeTime(value)}</time>;
}

export const inputClass =
  "w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm text-slate-900 shadow-sm placeholder:text-slate-400 " +
  "focus:border-navy-500 focus:outline-none focus:ring-2 focus:ring-navy-200 disabled:bg-slate-100";

export function Field({ label, htmlFor, hint, children, className }: { label: string; htmlFor: string; hint?: ReactNode; children: ReactNode; className?: string }) {
  return (
    <div className={cx("flex min-w-0 flex-col gap-1", className)}>
      <label htmlFor={htmlFor} className="text-xs font-medium text-slate-700">{label}</label>
      {children}
      {hint && <p className="text-xs text-slate-500">{hint}</p>}
    </div>
  );
}

export function Tabs({ tabs, active, onChange, label }: { tabs: { id: string; label: string }[]; active: string; onChange: (id: string) => void; label: string }) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const onKeyDown = (event: KeyboardEvent<HTMLButtonElement>, index: number) => {
    if (event.key !== "ArrowRight" && event.key !== "ArrowLeft") return;
    event.preventDefault();
    const next = (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
    onChange(tabs[next].id);
    refs.current[next]?.focus();
  };
  return (
    <div role="tablist" aria-label={label} className="flex flex-wrap gap-1 border-b border-slate-200">
      {tabs.map((tab, index) => (
        <button
          key={tab.id}
          ref={(node) => {
            refs.current[index] = node;
          }}
          type="button"
          role="tab"
          id={`tab-${tab.id}`}
          aria-selected={active === tab.id}
          aria-controls={`panel-${tab.id}`}
          tabIndex={active === tab.id ? 0 : -1}
          onKeyDown={(event) => onKeyDown(event, index)}
          onClick={() => onChange(tab.id)}
          className={cx(
            "-mb-px border-b-2 px-3 py-2 text-sm font-medium transition-colors",
            active === tab.id ? "border-navy-700 text-navy-800" : "border-transparent text-slate-500 hover:text-slate-800",
          )}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );
}

export function TabPanel({ id, children }: { id: string; children: ReactNode }) {
  return (
    <div role="tabpanel" id={`panel-${id}`} aria-labelledby={`tab-${id}`} className="pt-4">
      {children}
    </div>
  );
}

export function Pagination({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (page: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <nav aria-label="Pagination" className="flex flex-wrap items-center justify-between gap-3 pt-3 text-sm text-slate-600">
      <span>{total === 0 ? "No results" : `${(page - 1) * pageSize + 1}–${Math.min(page * pageSize, total)} of ${total}`}</span>
      <div className="flex items-center gap-2">
        <Button variant="secondary" size="sm" disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous</Button>
        <span className="tabular-nums">Page {page} of {pages}</span>
        <Button variant="secondary" size="sm" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next</Button>
      </div>
    </nav>
  );
}

export const th = "px-3 py-2 text-left text-xs font-semibold uppercase tracking-wide text-slate-500";
export const td = "px-3 py-2.5 align-top text-sm text-slate-700";

export function Table({ children, label }: { children: ReactNode; label: string }) {
  return (
    <div className="overflow-x-auto">
      <table aria-label={label} className="min-w-full divide-y divide-slate-200">{children}</table>
    </div>
  );
}

export function ProgressBar({ value, max, label }: { value: number; max: number; label: string }) {
  const ratio = max > 0 ? Math.min(1, value / max) : 0;
  const color = ratio >= 0.9 ? "bg-red-600" : ratio >= 0.7 ? "bg-amber-500" : "bg-navy-600";
  return (
    <div>
      <div className="flex justify-between text-xs text-slate-600">
        <span>{label}</span>
        <span className="tabular-nums">{value} / {max}</span>
      </div>
      <div role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={max} aria-valuenow={value} className="mt-1 h-1.5 rounded-full bg-slate-200">
        <div className={cx("h-1.5 rounded-full", color)} style={{ width: `${ratio * 100}%` }} />
      </div>
    </div>
  );
}
