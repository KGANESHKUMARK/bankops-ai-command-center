const dateTime = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });
const relative = new Intl.RelativeTimeFormat(undefined, { numeric: "auto" });
const number = new Intl.NumberFormat(undefined);

function toDate(value?: string | null): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function formatDateTime(value?: string | null): string {
  const date = toDate(value);
  return date ? dateTime.format(date) : "—";
}

export function relativeTime(value?: string | null, now: number = Date.now()): string {
  const date = toDate(value);
  if (!date) return "—";
  const seconds = Math.round((date.getTime() - now) / 1000);
  const abs = Math.abs(seconds);
  if (abs < 45) return relative.format(seconds, "second");
  if (abs < 2700) return relative.format(Math.round(seconds / 60), "minute");
  if (abs < 64800) return relative.format(Math.round(seconds / 3600), "hour");
  if (abs < 2592000) return relative.format(Math.round(seconds / 86400), "day");
  return dateTime.format(date);
}

export function formatDuration(ms?: number | null): string {
  if (ms === null || ms === undefined || Number.isNaN(ms)) return "—";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const seconds = ms / 1000;
  if (seconds < 60) return `${seconds.toFixed(1)} s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${Math.round(seconds % 60)}s`;
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
}

export function formatSeconds(seconds?: number | null): string {
  return seconds === null || seconds === undefined ? "—" : formatDuration(seconds * 1000);
}

export function pct(value?: number | null, digits = 0): string {
  return value === null || value === undefined || Number.isNaN(value) ? "—" : `${(value * 100).toFixed(digits)}%`;
}

export function formatNumber(value?: number | null): string {
  return value === null || value === undefined ? "—" : number.format(value);
}

export function formatUsd(value?: number | null): string {
  if (value === null || value === undefined) return "—";
  return `$${value.toFixed(value > 0 && value < 0.01 ? 6 : 2)}`;
}

export function humanize(value?: string | null): string {
  if (!value) return "—";
  const text = value.replace(/[_:]+/g, " ").trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
}

export function shortId(id?: string | null): string {
  return id ? id.slice(0, 8) : "—";
}

export function formatMetric(value: unknown): string {
  if (typeof value === "number") return Number.isInteger(value) ? String(value) : value.toFixed(3);
  if (typeof value === "boolean") return value ? "true" : "false";
  if (value === null || value === undefined) return "—";
  return Array.isArray(value) ? (value.length ? value.join(", ") : "none") : String(value);
}
