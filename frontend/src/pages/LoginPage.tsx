import { useQuery } from "@tanstack/react-query";
import { KeyRound, Landmark } from "lucide-react";
import { useRef, useState, type FormEvent } from "react";
import { Navigate, useLocation, useNavigate } from "react-router";
import { ApiError, errorMessage } from "../api/client";
import { endpoints } from "../api/endpoints";
import { useAuth } from "../auth/AuthContext";
import { SyntheticBanner } from "../components/Layout";
import { Button, Field, Notice, inputClass } from "../components/ui";
import { humanize } from "../lib/format";

export function LoginPage() {
  const { login, user, sessionExpired } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();
  const from = (location.state as { from?: string } | null)?.from ?? "/";
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const passwordRef = useRef<HTMLInputElement>(null);
  const accounts = useQuery({ queryKey: ["demo-accounts"], queryFn: endpoints.demoAccounts, staleTime: Infinity, retry: false });

  if (user) return <Navigate to={from} replace />;

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username.trim(), password);
      navigate(from, { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) setError("Invalid username or password.");
      else if (err instanceof ApiError && err.status === 429) setError("Too many sign-in attempts. Wait a minute and try again.");
      else setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen flex-col bg-navy-950">
      <SyntheticBanner />
      <div className="flex flex-1 items-center justify-center px-4 py-10">
        <div className="grid w-full max-w-4xl gap-6 md:grid-cols-2">
          <div className="text-navy-100">
            <Landmark className="size-9 text-navy-300" aria-hidden />
            <h1 className="mt-4 text-2xl font-semibold text-white">BankOps AI Command Center</h1>
            <p className="mt-2 text-sm leading-relaxed text-navy-200">
              Governed AI investigation of synthetic banking operations incidents: authorized retrieval with citations,
              bounded multi-agent analysis, a deterministic policy engine, human approval, simulated remediation,
              verification and a tamper-evident audit trail.
            </p>
            <ul className="mt-4 space-y-1 text-xs text-navy-300">
              <li>• The language model is never the authorization boundary.</li>
              <li>• Every action is simulated against seeded demo state.</li>
              <li>• Runs offline in deterministic MOCK MODE without API keys.</li>
            </ul>
          </div>
          <div className="rounded-lg bg-white p-6 shadow-xl">
            <h2 className="text-lg font-semibold text-slate-900">Sign in</h2>
            {sessionExpired && (
              <div className="mt-3"><Notice tone="warning">Your session ended (expired or revoked). Please sign in again.</Notice></div>
            )}
            <form className="mt-4 space-y-4" onSubmit={submit} noValidate>
              <Field label="Username" htmlFor="username">
                <input id="username" className={inputClass} autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required maxLength={80} />
              </Field>
              <Field label="Password" htmlFor="password">
                <input id="password" ref={passwordRef} type="password" className={inputClass} autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required maxLength={200} />
              </Field>
              {error && <p role="alert" className="text-sm font-medium text-red-700">{error}</p>}
              <Button type="submit" loading={busy} className="w-full" icon={<KeyRound className="size-4" aria-hidden />}
                disabledReason={!username.trim() || !password ? "Enter a username and password." : null}>
                Sign in
              </Button>
            </form>
            {(accounts.data?.length ?? 0) > 0 && (
              <div className="mt-6 border-t border-slate-200 pt-4">
                <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Local demo accounts</h3>
                <p className="mt-1 text-xs text-slate-500">
                  All demo accounts share the local-only <code className="rounded bg-slate-100 px-1">DEMO_PASSWORD</code> from your <code className="rounded bg-slate-100 px-1">.env</code> (see README). Demo accounts are refused outside local/demo mode.
                </p>
                <ul className="mt-2 grid grid-cols-1 gap-1 sm:grid-cols-2">
                  {accounts.data?.map((account) => (
                    <li key={account.username}>
                      <button
                        type="button"
                        onClick={() => {
                          setUsername(account.username);
                          passwordRef.current?.focus();
                        }}
                        className="w-full rounded-md border border-slate-200 px-2 py-1.5 text-left text-xs hover:border-navy-300 hover:bg-navy-50"
                      >
                        <span className="block font-mono font-medium text-slate-900">{account.username}</span>
                        <span className="text-slate-500">{humanize(account.role)} · {account.tenant_id}</span>
                      </button>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
