import { http, HttpResponse } from "msw";

import { server } from "@/test/server";

import { clearSession, getAccessToken, getRefreshToken, refreshSession, setSession } from "./tokens";

const pair = (n: number) => ({
  access_token: `access-${n}`,
  refresh_token: `refresh-${n}`,
  token_type: "bearer",
  expires_in: 900,
});

beforeEach(() => clearSession());

function refreshEndpoint(handler: (token: string) => Response | Promise<Response>) {
  const seen: string[] = [];
  server.use(
    http.post("*/api/auth/refresh", async ({ request }) => {
      const { refresh_token } = (await request.json()) as { refresh_token: string };
      seen.push(refresh_token);
      return handler(refresh_token);
    }),
  );
  return seen;
}

test("the access token stays in memory and the refresh token goes to localStorage", () => {
  setSession(pair(1));
  expect(getAccessToken()).toBe("access-1");
  expect(getRefreshToken()).toBe("refresh-1");
  expect(localStorage.getItem("cc.refresh")).toBe("refresh-1");
  expect(JSON.stringify({ ...localStorage })).not.toContain("access-1");
});

test("a refresh rotates both tokens and stores the new refresh token at once", async () => {
  setSession(pair(1));
  refreshEndpoint(() => HttpResponse.json(pair(2)));
  expect(await refreshSession()).toBe("ok");
  expect(getAccessToken()).toBe("access-2");
  expect(localStorage.getItem("cc.refresh")).toBe("refresh-2");
});

test("concurrent refreshes share one request (a spent token would revoke every session)", async () => {
  setSession(pair(1));
  const seen = refreshEndpoint(() => HttpResponse.json(pair(2)));
  const results = await Promise.all([refreshSession(), refreshSession(), refreshSession()]);
  expect(results).toEqual(["ok", "ok", "ok"]);
  expect(seen).toEqual(["refresh-1"]);
});

test("a later refresh sends the rotated token, not the first one", async () => {
  setSession(pair(1));
  let n = 1;
  const seen = refreshEndpoint(() => HttpResponse.json(pair(++n)));
  await refreshSession();
  await refreshSession();
  expect(seen).toEqual(["refresh-1", "refresh-2"]);
});

test("it uses the refresh token another tab stored, not a stale in-memory copy", async () => {
  setSession(pair(1));
  localStorage.setItem("cc.refresh", "refresh-from-other-tab");
  const seen = refreshEndpoint(() => HttpResponse.json(pair(9)));
  await refreshSession();
  expect(seen).toEqual(["refresh-from-other-tab"]);
});

test("a rejected refresh token ends the session", async () => {
  setSession(pair(1));
  refreshEndpoint(() => new HttpResponse(null, { status: 401 }));
  expect(await refreshSession()).toBe("denied");
  expect(getAccessToken()).toBeNull();
  expect(localStorage.getItem("cc.refresh")).toBeNull();
});

test("a network failure keeps the refresh token so a retry can work", async () => {
  setSession(pair(1));
  refreshEndpoint(() => HttpResponse.error());
  expect(await refreshSession()).toBe("error");
  expect(localStorage.getItem("cc.refresh")).toBe("refresh-1");
});

test("a server error is not treated as a rejected token", async () => {
  setSession(pair(1));
  refreshEndpoint(() => new HttpResponse(null, { status: 503 }));
  expect(await refreshSession()).toBe("error");
  expect(localStorage.getItem("cc.refresh")).toBe("refresh-1");
});

test("without a refresh token there is nothing to refresh", async () => {
  expect(await refreshSession()).toBe("denied");
});
