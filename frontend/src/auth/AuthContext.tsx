import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { ApiError, onUnauthorized, readSession, writeSession } from "../api/client";
import { endpoints } from "../api/endpoints";
import type { User } from "../api/types";

type AuthStatus = "checking" | "authenticated" | "anonymous";

interface AuthContextValue {
  user: User | null;
  status: AuthStatus;
  sessionExpired: boolean;
  login: (username: string, password: string) => Promise<User>;
  logout: () => Promise<void>;
  /** UI convenience only - every permission is enforced again by the API. */
  can: (permission: string) => boolean;
}

const AuthContext = createContext<AuthContextValue | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [user, setUser] = useState<User | null>(() => readSession()?.user ?? null);
  const [status, setStatus] = useState<AuthStatus>(() => (readSession() ? "checking" : "anonymous"));
  const [sessionExpired, setSessionExpired] = useState(false);

  const clear = useCallback((expired: boolean) => {
    writeSession(null);
    setUser(null);
    setStatus("anonymous");
    setSessionExpired(expired);
    queryClient.clear();
  }, [queryClient]);

  useEffect(() => {
    onUnauthorized(() => clear(true));
    return () => onUnauthorized(null);
  }, [clear]);

  // Re-validate a stored session with the server (token may be revoked, expired or for a deactivated user).
  useEffect(() => {
    if (status !== "checking") return;
    let cancelled = false;
    endpoints.me()
      .then((me) => {
        if (cancelled) return;
        const session = readSession();
        if (session) writeSession({ ...session, user: me });
        setUser(me);
        setStatus("authenticated");
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        if (error instanceof ApiError && error.status === 401) clear(true);
        else setStatus(readSession() ? "authenticated" : "anonymous"); // backend unreachable: pages show their own errors
      });
    return () => {
      cancelled = true;
    };
  }, [status, clear]);

  // Proactively end the session when the short-lived token expires.
  useEffect(() => {
    const session = readSession();
    if (!user || !session) return;
    const remaining = Date.parse(session.expiresAt) - Date.now();
    const timer = window.setTimeout(() => clear(true), Math.max(0, Math.min(remaining, 2 ** 31 - 1)));
    return () => window.clearTimeout(timer);
  }, [user, clear]);

  const login = useCallback(async (username: string, password: string) => {
    const response = await endpoints.login(username, password);
    writeSession({ token: response.access_token, expiresAt: response.expires_at, user: response.user });
    queryClient.clear();
    setUser(response.user);
    setStatus("authenticated");
    setSessionExpired(false);
    return response.user;
  }, [queryClient]);

  const logout = useCallback(async () => {
    try {
      await endpoints.logout();
    } catch {
      // The token may already be expired or revoked; the local session is cleared either way.
    }
    clear(false);
  }, [clear]);

  const can = useCallback((permission: string) => Boolean(user?.permissions.includes(permission)), [user]);

  const value = useMemo(
    () => ({ user, status, sessionExpired, login, logout, can }),
    [user, status, sessionExpired, login, logout, can],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used inside <AuthProvider>");
  return context;
}
