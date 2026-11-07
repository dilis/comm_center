import { useQueryClient } from "@tanstack/react-query";
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react";

import { api, setSessionExpiredHandler, unwrap } from "@/api/client";
import type { components } from "@/api/schema";

import { canActOnRow, canAny, canDeleteMessage, hasPermission, type PermissionSet } from "./permissions";
import { clearSession, getRefreshToken, refreshSession, setSession } from "./tokens";

export type Me = components["schemas"]["MeOut"];
type Status = "loading" | "anonymous" | "authenticated" | "error";

type AuthValue = {
  status: Status;
  me: Me | null;
  permissions: PermissionSet;
  can: (permission: string) => boolean;
  canAny: (permissions: string[]) => boolean;
  canDeleteMessage: (message: { owner_id: number; direction: "inbound" | "outbound" }) => boolean;
  canActOn: (resource: "messages" | "contacts" | "users", action: "update" | "delete", ownerId: number) => boolean;
  login: (username: string, password: string) => Promise<void>;
  logout: () => Promise<void>;
  retry: () => void;
};

const AuthContext = createContext<AuthValue | null>(null);
const NO_PERMISSIONS: PermissionSet = new Set();

export function AuthProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient();
  const [status, setStatus] = useState<Status>("loading");
  const [me, setMe] = useState<Me | null>(null);
  const [attempt, setAttempt] = useState(0);

  const endSession = useCallback(() => {
    clearSession();
    queryClient.clear(); // nothing from this session may linger for the next one
    setMe(null);
    setStatus("anonymous");
  }, [queryClient]);

  useEffect(() => setSessionExpiredHandler(endSession), [endSession]);

  // Restore a session on load. Refreshing is single-flight, so React StrictMode's double effect
  // cannot spend the same rotating refresh token twice.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!getRefreshToken()) return setStatus("anonymous");
      setStatus("loading");
      const result = await refreshSession();
      if (cancelled) return;
      if (result === "denied") return setStatus("anonymous");
      if (result === "error") return setStatus("error");
      try {
        const profile = await unwrap(api.GET("/auth/me"));
        if (cancelled) return;
        setMe(profile);
        setStatus("authenticated");
      } catch {
        if (!cancelled) setStatus("error");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [attempt]);

  const login = useCallback(async (username: string, password: string) => {
    const tokens = await unwrap(api.POST("/auth/login", { body: { username, password } }));
    setSession(tokens);
    setMe(await unwrap(api.GET("/auth/me")));
    setStatus("authenticated");
  }, []);

  const logout = useCallback(async () => {
    const refreshToken = getRefreshToken();
    if (refreshToken) {
      // Best effort: the local session ends either way.
      await api.POST("/auth/logout", { body: { refresh_token: refreshToken } }).catch(() => {});
    }
    endSession();
  }, [endSession]);

  const value = useMemo<AuthValue>(() => {
    const permissions: PermissionSet = me ? new Set(me.permissions) : NO_PERMISSIONS;
    return {
      status,
      me,
      permissions,
      can: (p) => hasPermission(permissions, p),
      canAny: (ps) => canAny(permissions, ps),
      canDeleteMessage: (message) => me !== null && canDeleteMessage(permissions, message, me.id),
      canActOn: (resource, action, ownerId) =>
        me !== null && canActOnRow(permissions, resource, action, ownerId, me.id),
      login,
      logout,
      retry: () => setAttempt((n) => n + 1),
    };
  }, [status, me, login, logout]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthValue {
  const value = useContext(AuthContext);
  if (!value) throw new Error("useAuth must be used inside AuthProvider");
  return value;
}
