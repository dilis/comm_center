import createClient from "openapi-fetch";

import { getAccessToken, refreshSession } from "@/auth/tokens";

import { API_BASE } from "./base";
import type { paths } from "./schema";

let onSessionExpired: () => void = () => {};
/** Called when the refresh token is rejected; the auth provider uses it to go back to Login. */
export function setSessionExpiredHandler(handler: () => void) {
  onSessionExpired = handler;
}

const AUTH_ENDPOINTS = ["/auth/login", "/auth/refresh", "/auth/logout"];

/** Adds the bearer token; on a 401 refreshes once (single-flight) and replays the request. */
async function authedFetch(request: Request): Promise<Response> {
  const isAuthEndpoint = AUTH_ENDPOINTS.some((p) => new URL(request.url).pathname.endsWith(p));
  const replay = request.clone();
  const withToken = (req: Request) => {
    const token = getAccessToken();
    if (token && !isAuthEndpoint) req.headers.set("Authorization", `Bearer ${token}`);
    return req;
  };
  const response = await fetch(withToken(request));
  if (response.status !== 401 || isAuthEndpoint) return response;
  const refreshed = await refreshSession();
  if (refreshed === "ok") return fetch(withToken(replay));
  if (refreshed === "denied") onSessionExpired();
  return response;
}

export const api = createClient<paths>({ baseUrl: API_BASE, fetch: authedFetch });

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly detail: unknown,
  ) {
    super(typeof detail === "string" ? detail : `request failed (${status})`);
  }
}

/** Resolve to the response body, or throw an ``ApiError`` carrying the server's ``detail``. */
export async function unwrap<T>(
  call: Promise<{ data?: T; error?: unknown; response: Response }>,
): Promise<T> {
  const { data, error, response } = await call;
  if (!response.ok) {
    throw new ApiError(response.status, (error as { detail?: unknown } | undefined)?.detail);
  }
  return data as T;
}

type FieldIssue = { loc?: (string | number)[]; msg?: string };

/** A message safe to show a person. Never includes anything but the server's own text. */
export function errorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    if (typeof err.detail === "string") return err.detail;
    if (Array.isArray(err.detail)) {
      return (err.detail as FieldIssue[])
        .map((i) => {
          const field = (i.loc ?? []).filter((p) => p !== "body").join(".");
          return field ? `${field}: ${i.msg}` : String(i.msg);
        })
        .join("; ");
    }
    return `Server error (${err.status})`;
  }
  if (err instanceof Error) return err.message;
  return "Something went wrong";
}
