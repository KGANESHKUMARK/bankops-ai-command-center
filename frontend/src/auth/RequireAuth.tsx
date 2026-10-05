import { Lock } from "lucide-react";
import type { ReactNode } from "react";
import { Link, Navigate, useLocation } from "react-router";
import { Loading } from "../components/ui";
import { humanize } from "../lib/format";
import { useAuth } from "./AuthContext";

export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, status } = useAuth();
  const location = useLocation();
  if (status === "checking") return <Loading label="Restoring your session…" />;
  if (!user) return <Navigate to="/login" replace state={{ from: `${location.pathname}${location.search}` }} />;
  return <>{children}</>;
}

/** Client-side gate for a page. The API enforces the same permission server-side (403) regardless. */
export function RequirePermission({ permission, children }: { permission: string; children: ReactNode }) {
  const { can, user } = useAuth();
  if (can(permission)) return <>{children}</>;
  return (
    <div role="alert" className="mx-auto mt-10 max-w-lg rounded-lg border border-slate-200 bg-white p-6 text-center shadow-sm">
      <Lock className="mx-auto size-6 text-slate-400" aria-hidden />
      <h1 className="mt-3 text-lg font-semibold text-slate-900">Access restricted</h1>
      <p className="mt-1 text-sm text-slate-600">
        Your role <strong>{humanize(user?.role)}</strong> does not have the <code className="rounded bg-slate-100 px-1">{permission}</code>{" "}
        permission. Access is enforced by the server&apos;s RBAC policy, not by this page.
      </p>
      <Link to="/" className="mt-4 inline-block text-sm font-medium text-navy-700 underline">Back to overview</Link>
    </div>
  );
}
