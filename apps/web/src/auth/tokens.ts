/**
 * Session tokens. The short-lived access token lives only in memory; the refresh token is in
 * localStorage so a reload keeps you signed in. Both are script-readable, which is why all
 * untrusted text (SMS content) is rendered as text and the production CSP is strict.
 *
 * The API rotates refresh tokens and treats a spent one coming back as theft (it ends every
 * session), so refreshing is single-flight: concurrent callers share one request.
 */
import { API_BASE } from "@/api/base";

const KEY = "cc.refresh";

export type TokenPair = { access_token: string; refresh_token: string };
export type RefreshResult = "ok" | "denied" | "error";

let accessToken: string | null = null;
let inFlight: Promise<RefreshResult> | null = null;

export const getAccessToken = () => accessToken;
export const getRefreshToken = () => localStorage.getItem(KEY);

export function setSession(pair: TokenPair): void {
  accessToken = pair.access_token;
  localStorage.setItem(KEY, pair.refresh_token);
}

export function clearSession(): void {
  accessToken = null;
  inFlight = null;
  localStorage.removeItem(KEY);
}

async function doRefresh(): Promise<RefreshResult> {
  // Read the latest token at call time: another tab may have rotated it since we loaded.
  const token = getRefreshToken();
  if (!token) return "denied";
  let response: Response;
  try {
    response = await fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: token }),
    });
  } catch {
    return "error"; // offline: keep the token
  }
  if (response.status === 401) {
    clearSession();
    return "denied";
  }
  if (!response.ok) return "error";
  setSession((await response.json()) as TokenPair);
  return "ok";
}

export function refreshSession(): Promise<RefreshResult> {
  inFlight ??= doRefresh().finally(() => {
    inFlight = null;
  });
  return inFlight;
}
