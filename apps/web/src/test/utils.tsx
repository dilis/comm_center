import { render } from "@testing-library/react";
import { http, HttpResponse } from "msw";
import { MemoryRouter } from "react-router";

import App from "@/App";
import { clearSession } from "@/auth/tokens";

import { server } from "./server";

/** Permissions of the four seed roles, written out by hand from SPECS.md 4.6. */
export const ROLE_PERMISSIONS = {
  admin: [
    "users:create", "users:read_all", "users:update", "users:delete", "groups:read_all",
    "contacts:create", "contacts:read_all", "contacts:update", "contacts:delete",
    "messages:create", "messages:read_all", "messages:delete",
  ],
  operator: [
    "contacts:create", "contacts:read_all", "contacts:update",
    "messages:create", "messages:read_all", "users:read_all",
  ],
  agent: ["contacts:read_all", "messages:create", "messages:read_own", "messages:read_received"],
  auditor: ["contacts:read_all", "messages:read_all", "users:read_all"],
} as const;

export type Role = keyof typeof ROLE_PERMISSIONS;

export const tokenPair = (n = 1) => ({
  access_token: `access-${n}`,
  refresh_token: `refresh-${n}`,
  token_type: "bearer",
  expires_in: 900,
});

export function meFor(role: Role | string[], overrides: Record<string, unknown> = {}) {
  const permissions = Array.isArray(role) ? role : [...ROLE_PERMISSIONS[role]];
  return {
    id: 1,
    username: "tester",
    name: "Test User",
    email: null,
    phones: [],
    groups: Array.isArray(role) ? [] : [role],
    permissions,
    ...overrides,
  };
}

export const page = <T,>(items: T[], extra: Partial<{ total: number; page: number; page_size: number }> = {}) => ({
  items,
  total: items.length,
  page: 1,
  page_size: 20,
  ...extra,
});

/** Pretend a session exists: a stored refresh token the API accepts, and /auth/me. */
export function signIn(role: Role | string[] = "admin", overrides: Record<string, unknown> = {}) {
  localStorage.setItem("cc.refresh", "refresh-0");
  server.use(
    http.post("*/api/auth/refresh", () => HttpResponse.json(tokenPair(1))),
    http.get("*/api/auth/me", () => HttpResponse.json(meFor(role, overrides))),
  );
}

/** Empty list endpoints so a page can mount without every test stubbing all of them. */
export function emptyBackend() {
  server.use(
    http.get("*/api/messages/counts", () => HttpResponse.json({ all: 0, sent: 0, received: 0 })),
    http.get("*/api/messages", () => HttpResponse.json(page([]))),
    http.get("*/api/contacts", () => HttpResponse.json(page([]))),
    http.get("*/api/users", () => HttpResponse.json(page([]))),
    http.get("*/api/groups", () => HttpResponse.json(page([]))),
  );
}

export function renderApp(route = "/") {
  // Drop any access token a previous test left in memory, but keep the stored refresh token that
  // signIn() just planted.
  const stored = localStorage.getItem("cc.refresh");
  clearSession();
  if (stored) localStorage.setItem("cc.refresh", stored);
  return render(
    <MemoryRouter initialEntries={[route]}>
      <App />
    </MemoryRouter>,
  );
}
