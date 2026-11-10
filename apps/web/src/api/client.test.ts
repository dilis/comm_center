import { http, HttpResponse } from "msw";

import { clearSession, getAccessToken, setSession } from "@/auth/tokens";
import { server } from "@/test/server";

import { api, ApiError, errorMessage, setSessionExpiredHandler, unwrap } from "./client";

const pair = (n: number) => ({
  access_token: `access-${n}`,
  refresh_token: `refresh-${n}`,
  token_type: "bearer",
  expires_in: 900,
});

beforeEach(() => {
  clearSession();
  setSessionExpiredHandler(() => {});
});

test("requests carry the access token", async () => {
  setSession(pair(1));
  let auth: string | null = null;
  server.use(
    http.get("*/api/groups", ({ request }) => {
      auth = request.headers.get("Authorization");
      return HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 });
    }),
  );
  await api.GET("/groups");
  expect(auth).toBe("Bearer access-1");
});

test("a 401 refreshes once and replays the request with the new token, body intact", async () => {
  setSession(pair(1));
  const bodies: unknown[] = [];
  server.use(
    http.post("*/api/contacts", async ({ request }) => {
      bodies.push(await request.clone().json());
      if (request.headers.get("Authorization") === "Bearer access-1") {
        return new HttpResponse(null, { status: 401 });
      }
      return HttpResponse.json({ id: 7 }, { status: 201 });
    }),
    http.post("*/api/auth/refresh", () => HttpResponse.json(pair(2))),
  );
  const { response } = await api.POST("/contacts", { body: { first_name: "Ana" } });
  expect(response.status).toBe(201);
  expect(bodies).toEqual([{ first_name: "Ana" }, { first_name: "Ana" }]);
  expect(getAccessToken()).toBe("access-2");
});

test("parallel 401s trigger a single refresh", async () => {
  setSession(pair(1));
  let refreshes = 0;
  server.use(
    http.get("*/api/groups", ({ request }) =>
      request.headers.get("Authorization") === "Bearer access-2"
        ? HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 })
        : new HttpResponse(null, { status: 401 }),
    ),
    http.post("*/api/auth/refresh", () => {
      refreshes += 1;
      return HttpResponse.json(pair(2));
    }),
  );
  const results = await Promise.all([api.GET("/groups"), api.GET("/groups"), api.GET("/groups")]);
  expect(results.map((r) => r.response.status)).toEqual([200, 200, 200]);
  expect(refreshes).toBe(1);
});

test("when the refresh is rejected the session-expired handler runs and the 401 is returned", async () => {
  setSession(pair(1));
  const expired = vi.fn();
  setSessionExpiredHandler(expired);
  server.use(
    http.get("*/api/groups", () => new HttpResponse(null, { status: 401 })),
    http.post("*/api/auth/refresh", () => new HttpResponse(null, { status: 401 })),
  );
  const { response } = await api.GET("/groups");
  expect(response.status).toBe(401);
  expect(expired).toHaveBeenCalledOnce();
});

test("an unreachable refresh endpoint does not end the session", async () => {
  setSession(pair(1));
  const expired = vi.fn();
  setSessionExpiredHandler(expired);
  server.use(
    http.get("*/api/groups", () => new HttpResponse(null, { status: 401 })),
    http.post("*/api/auth/refresh", () => HttpResponse.error()),
  );
  await api.GET("/groups");
  expect(expired).not.toHaveBeenCalled();
  expect(localStorage.getItem("cc.refresh")).toBe("refresh-1");
});

test("a wrong password on login is a plain 401, not a refresh loop", async () => {
  let refreshes = 0;
  server.use(
    http.post("*/api/auth/login", () => new HttpResponse(JSON.stringify({ detail: "invalid credentials" }), { status: 401 })),
    http.post("*/api/auth/refresh", () => {
      refreshes += 1;
      return HttpResponse.json(pair(2));
    }),
  );
  const { response } = await api.POST("/auth/login", { body: { username: "a", password: "b" } });
  expect(response.status).toBe(401);
  expect(refreshes).toBe(0);
});

describe("errors", () => {
  test("unwrap returns data and throws ApiError with the server's detail", async () => {
    server.use(
      http.get("*/api/groups", () => HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 })),
      http.get("*/api/contacts/5", () => HttpResponse.json({ detail: "contact not found" }, { status: 404 })),
    );
    expect((await unwrap(api.GET("/groups"))).total).toBe(0);
    const failure = await unwrap(api.GET("/contacts/{contact_id}", { params: { path: { contact_id: 5 } } })).catch((e) => e);
    expect(failure).toBeInstanceOf(ApiError);
    expect(failure.status).toBe(404);
    expect(errorMessage(failure)).toBe("contact not found");
  });

  test("validation errors list the offending fields", () => {
    const err = new ApiError(422, [
      { loc: ["body", "phones", 0, "phone"], msg: "Value error, invalid phone number: '1'" },
      { loc: ["body", "name"], msg: "String should have at least 1 character" },
    ]);
    expect(errorMessage(err)).toBe(
      "phones.0.phone: Value error, invalid phone number: '1'; name: String should have at least 1 character",
    );
  });

  test("other errors fall back to a generic message", () => {
    expect(errorMessage(new Error("boom"))).toBe("boom");
    expect(errorMessage("weird")).toBe("Something went wrong");
    expect(errorMessage(new ApiError(500, undefined))).toBe("Server error (500)");
  });
});
