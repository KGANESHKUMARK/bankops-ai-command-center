import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  BookOpen,
  CirclePlay,
  ClipboardCheck,
  FlaskConical,
  Landmark,
  LayoutDashboard,
  Lock,
  LogOut,
  Menu,
  Settings,
  Siren,
  TriangleAlert,
  Workflow,
  Wrench,
  X,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router";
import { endpoints } from "../api/endpoints";
import { useAuth } from "../auth/AuthContext";
import { humanize } from "../lib/format";
import { ModeBadge } from "./badges";
import { Badge, cx } from "./ui";

interface NavItem {
  to: string;
  label: string;
  icon: LucideIcon;
  permission: string;
  end?: boolean;
}

export const NAV_ITEMS: NavItem[] = [
  { to: "/", label: "Overview", icon: LayoutDashboard, permission: "dashboard:read", end: true },
  { to: "/incidents", label: "Incident Explorer", icon: Siren, permission: "incidents:read" },
  { to: "/investigations", label: "AI Investigations", icon: Workflow, permission: "investigations:read" },
  { to: "/approvals", label: "Approval Center", icon: ClipboardCheck, permission: "approvals:read" },
  { to: "/actions", label: "Remediation Center", icon: Wrench, permission: "actions:read" },
  { to: "/knowledge", label: "Knowledge Center", icon: BookOpen, permission: "knowledge:read" },
  { to: "/governance", label: "Governance Center", icon: Landmark, permission: "governance:read" },
  { to: "/evaluations", label: "Evaluation & Releases", icon: FlaskConical, permission: "evaluations:read" },
  { to: "/observability", label: "Observability", icon: Activity, permission: "observability:read" },
  { to: "/settings", label: "Settings", icon: Settings, permission: "settings:read" },
  { to: "/demo", label: "Guided Demo", icon: CirclePlay, permission: "incidents:read" },
];

export function SyntheticBanner() {
  return (
    <div role="note" className="bg-amber-100 px-4 py-1.5 text-center text-xs font-medium text-amber-950">
      SYNTHETIC DEMO DATA — fictional banks, customers, systems and incidents. All remediation is simulated against seeded
      demo state; no real banking system is connected.
    </div>
  );
}

function Sidebar({ onNavigate }: { onNavigate?: () => void }) {
  const { can, user } = useAuth();
  const pending = useQuery({
    queryKey: ["approvals", "pending-count"],
    queryFn: () => endpoints.approvals({ status: "pending", page_size: 1 }),
    enabled: can("approvals:read"),
    refetchInterval: 15000,
  });
  return (
    <nav aria-label="Primary" className="flex flex-col gap-0.5 px-3 py-4">
      {NAV_ITEMS.map((item) => {
        const Icon = item.icon;
        if (!can(item.permission)) {
          return (
            <span
              key={item.to}
              aria-disabled="true"
              title={`Requires ${item.permission} (your role: ${humanize(user?.role)})`}
              className="flex cursor-not-allowed items-center gap-2.5 rounded-md px-3 py-2 text-sm text-navy-300/60"
            >
              <Icon className="size-4" aria-hidden />
              <span className="flex-1">{item.label}</span>
              <Lock className="size-3" aria-hidden />
              <span className="sr-only">(not available for your role)</span>
            </span>
          );
        }
        return (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.end}
            onClick={onNavigate}
            className={({ isActive }) =>
              cx(
                "flex items-center gap-2.5 rounded-md px-3 py-2 text-sm font-medium transition-colors",
                isActive ? "bg-navy-700 text-white" : "text-navy-100 hover:bg-navy-800 hover:text-white",
              )
            }
          >
            <Icon className="size-4" aria-hidden />
            <span className="flex-1">{item.label}</span>
            {item.to === "/approvals" && (pending.data?.total ?? 0) > 0 && (
              <span className="rounded-full bg-amber-400 px-1.5 text-xs font-semibold text-navy-950" aria-label={`${pending.data?.total} pending approvals`}>
                {pending.data?.total}
              </span>
            )}
          </NavLink>
        );
      })}
    </nav>
  );
}

function SystemStatus() {
  const { can } = useAuth();
  const ready = useQuery({ queryKey: ["ready"], queryFn: endpoints.ready, refetchInterval: 30000, retry: false });
  const faults = useQuery({ queryKey: ["faults"], queryFn: endpoints.faults, enabled: can("observability:read"), refetchInterval: 30000 });
  const activeFaults = Object.entries(faults.data?.faults ?? {}).filter(([, on]) => on).map(([name]) => name);
  const status = ready.isError ? "unreachable" : ready.data?.status ?? "checking";
  const tone = status === "ready" && !activeFaults.length ? "success" : status === "checking" ? "neutral" : status === "degraded" || activeFaults.length ? "warning" : "danger";
  const label = status === "ready" && activeFaults.length ? "Degraded (fault injection)" : humanize(status);
  const mode = (ready.data?.checks?.model_gateway as { mode?: string } | undefined)?.mode;
  return (
    <div className="flex flex-wrap items-center gap-2">
      <ModeBadge mode={mode} />
      <Badge tone={tone} title={activeFaults.length ? `Active faults: ${activeFaults.join(", ")}` : "API readiness (/ready)"}>
        System: {label}
      </Badge>
    </div>
  );
}

function DegradedBanner() {
  const { can } = useAuth();
  const ready = useQuery({ queryKey: ["ready"], queryFn: endpoints.ready, refetchInterval: 30000, retry: false });
  const faults = useQuery({ queryKey: ["faults"], queryFn: endpoints.faults, enabled: can("observability:read"), refetchInterval: 30000 });
  const activeFaults = Object.entries(faults.data?.faults ?? {}).filter(([, on]) => on).map(([name]) => name);
  const failing = Object.entries(ready.data?.checks ?? {}).filter(([, check]) => !check.ok).map(([name]) => name);
  if (ready.isError) {
    return (
      <div role="alert" className="flex items-center gap-2 bg-red-700 px-4 py-2 text-sm text-white">
        <TriangleAlert className="size-4" aria-hidden /> The BankOps API is unreachable. Data shown may be stale.
      </div>
    );
  }
  if (!activeFaults.length && !failing.length) return null;
  return (
    <div role="status" className="flex flex-wrap items-center gap-2 bg-amber-50 px-4 py-2 text-sm text-amber-950 ring-1 ring-amber-200">
      <TriangleAlert className="size-4" aria-hidden />
      <strong>Degraded mode.</strong>
      {failing.length > 0 && <span>Failing readiness checks: {failing.map(humanize).join(", ")}.</span>}
      {activeFaults.length > 0 && <span>Injected faults active: {activeFaults.map(humanize).join(", ")} (Settings → Failure injection).</span>}
      <span>Incident access, deterministic diagnostics and audit remain available.</span>
    </div>
  );
}

export function Layout() {
  const { user, logout } = useAuth();
  const [mobileOpen, setMobileOpen] = useState(false);
  const location = useLocation();

  useEffect(() => {
    setMobileOpen(false);
  }, [location.pathname]);

  return (
    <div className="min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-white focus:px-3 focus:py-2">
        Skip to main content
      </a>
      <SyntheticBanner />
      <div className="flex">
        <aside className="sticky top-0 hidden h-screen w-64 shrink-0 overflow-y-auto bg-navy-950 lg:block">
          <div className="border-b border-navy-800 px-5 py-4">
            <p className="text-sm font-semibold text-white">BankOps AI</p>
            <p className="text-xs text-navy-300">Command Center</p>
          </div>
          <Sidebar />
        </aside>
        {mobileOpen && (
          <div className="fixed inset-0 z-40 lg:hidden">
            <div className="absolute inset-0 bg-slate-950/50" onClick={() => setMobileOpen(false)} aria-hidden />
            <aside className="relative h-full w-72 overflow-y-auto bg-navy-950">
              <div className="flex items-center justify-between border-b border-navy-800 px-5 py-4">
                <p className="text-sm font-semibold text-white">BankOps AI Command Center</p>
                <button type="button" aria-label="Close navigation" onClick={() => setMobileOpen(false)} className="text-navy-200">
                  <X className="size-5" aria-hidden />
                </button>
              </div>
              <Sidebar onNavigate={() => setMobileOpen(false)} />
            </aside>
          </div>
        )}
        <div className="flex min-w-0 flex-1 flex-col">
          <header className="sticky top-0 z-30 flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 bg-white/95 px-4 py-2.5 backdrop-blur sm:px-6">
            <div className="flex items-center gap-3">
              <button type="button" aria-label="Open navigation" onClick={() => setMobileOpen(true)} className="rounded p-1 text-slate-600 hover:bg-slate-100 lg:hidden">
                <Menu className="size-5" aria-hidden />
              </button>
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-slate-900">{user?.tenant_name}</p>
                <p className="text-xs text-slate-500">Banking operations AI · synthetic tenant</p>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-3">
              <SystemStatus />
              <div className="text-right">
                <p className="text-sm font-medium text-slate-900">{user?.display_name}</p>
                <p className="text-xs text-slate-500">{humanize(user?.role)}</p>
              </div>
              <button
                type="button"
                onClick={() => void logout()}
                className="inline-flex items-center gap-1.5 rounded-md border border-slate-300 px-2.5 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
              >
                <LogOut className="size-3.5" aria-hidden /> Sign out
              </button>
            </div>
          </header>
          <DegradedBanner />
          <main id="main" tabIndex={-1} className="mx-auto w-full max-w-[1500px] flex-1 px-4 py-6 sm:px-6">
            <Outlet />
          </main>
          <footer className="border-t border-slate-200 px-6 py-3 text-xs text-slate-500">
            BankOps AI Command Center · portfolio demonstration · synthetic data only · simulated remediation only
          </footer>
        </div>
      </div>
    </div>
  );
}
