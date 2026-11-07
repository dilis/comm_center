import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import { server } from "@/test/server";
import { emptyBackend, meFor, renderApp, signIn, tokenPair, type Role } from "@/test/utils";

beforeEach(() => emptyBackend());

describe("route guard", () => {
  test("an anonymous visitor is sent to the login form", async () => {
    renderApp("/messages");
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  test("a stored session is restored on load without showing the login form", async () => {
    signIn("admin");
    renderApp("/contacts");
    expect(await screen.findByRole("heading", { name: "Contacts" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Sign in" })).not.toBeInTheDocument();
  });

  test("a rejected refresh token falls back to the login form", async () => {
    localStorage.setItem("cc.refresh", "stale");
    server.use(http.post("*/api/auth/refresh", () => new HttpResponse(null, { status: 401 })));
    renderApp("/contacts");
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });

  test("an unreachable server shows an error with a retry, not the login form", async () => {
    localStorage.setItem("cc.refresh", "refresh-0");
    server.use(http.post("*/api/auth/refresh", () => HttpResponse.error()));
    renderApp("/contacts");
    expect(await screen.findByText(/cannot reach the server/i)).toBeInTheDocument();
    signIn("admin");
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(await screen.findByRole("heading", { name: "Contacts" })).toBeInTheDocument();
  });
});

describe("login", () => {
  test("valid credentials open the app", async () => {
    server.use(
      http.post("*/api/auth/login", async ({ request }) => {
        expect(await request.json()).toEqual({ username: "tester", password: "correct horse battery" });
        return HttpResponse.json(tokenPair(1));
      }),
      http.get("*/api/auth/me", () => HttpResponse.json(meFor("admin"))),
    );
    renderApp("/login");
    await userEvent.type(await screen.findByLabelText("Username"), "tester");
    await userEvent.type(screen.getByLabelText("Password"), "correct horse battery");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "Messages" })).toBeInTheDocument();
    expect(localStorage.getItem("cc.refresh")).toBe("refresh-1");
  });

  test("a wrong password shows the server's message and stays on the form", async () => {
    server.use(
      http.post("*/api/auth/login", () => HttpResponse.json({ detail: "invalid credentials" }, { status: 401 })),
    );
    renderApp("/login");
    await userEvent.type(await screen.findByLabelText("Username"), "tester");
    await userEvent.type(screen.getByLabelText("Password"), "nope");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("invalid credentials");
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(localStorage.getItem("cc.refresh")).toBeNull();
  });

  test("empty fields are rejected before any request", async () => {
    renderApp("/login");
    await userEvent.click(await screen.findByRole("button", { name: "Sign in" }));
    expect(await screen.findByText("Enter your username")).toBeInTheDocument();
    expect(screen.getByText("Enter your password")).toBeInTheDocument();
  });

  test("returns to the page you were trying to open", async () => {
    server.use(
      http.post("*/api/auth/login", () => HttpResponse.json(tokenPair(1))),
      http.get("*/api/auth/me", () => HttpResponse.json(meFor("admin"))),
    );
    renderApp("/contacts");
    await userEvent.type(await screen.findByLabelText("Username"), "tester");
    await userEvent.type(screen.getByLabelText("Password"), "pw");
    await userEvent.click(screen.getByRole("button", { name: "Sign in" }));
    expect(await screen.findByRole("heading", { name: "Contacts" })).toBeInTheDocument();
  });
});

describe("sign out", () => {
  test("revokes the refresh token, clears it locally and returns to login", async () => {
    signIn("admin");
    let revoked: unknown;
    server.use(
      http.post("*/api/auth/logout", async ({ request }) => {
        revoked = await request.json();
        return new HttpResponse(null, { status: 204 });
      }),
    );
    renderApp("/messages");
    await userEvent.click(await screen.findByRole("button", { name: "Sign out" }));
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(revoked).toEqual({ refresh_token: "refresh-1" });
    expect(localStorage.getItem("cc.refresh")).toBeNull();
  });

  test("a session the server ends mid-use sends you back to login", async () => {
    signIn("admin");
    renderApp("/messages");
    await screen.findByRole("heading", { name: "Messages" });
    server.use(
      http.get("*/api/contacts", () => new HttpResponse(null, { status: 401 })),
      http.post("*/api/auth/refresh", () => new HttpResponse(null, { status: 401 })),
    );
    await userEvent.click(screen.getByRole("link", { name: "Contacts" }));
    expect(await screen.findByRole("heading", { name: "Sign in" })).toBeInTheDocument();
  });
});

describe("permission-aware navigation", () => {
  const nav = async () =>
    (await screen.findAllByRole("link")).map((a) => a.textContent).filter((t) => ["Messages", "Contacts", "Users"].includes(t ?? ""));

  test.each<[Role, string[]]>([
    ["admin", ["Messages", "Contacts", "Users"]],
    ["operator", ["Messages", "Contacts", "Users"]],
    ["auditor", ["Messages", "Contacts", "Users"]],
    ["agent", ["Messages", "Contacts"]],
  ])("%s sees %j", async (role, expected) => {
    signIn(role);
    renderApp("/messages");
    expect(await nav()).toEqual(expected);
  });

  test("a user who may read nothing sees a clear message", async () => {
    signIn(["groups:read_all"]);
    renderApp("/");
    expect(await screen.findByText(/you don't have access to any pages/i)).toBeInTheDocument();
  });

  test("opening a page you may not read shows an access-denied view", async () => {
    signIn("agent");
    renderApp("/users");
    expect(await screen.findByText(/you don't have access to this page/i)).toBeInTheDocument();
  });

  test("the root path lands on the first page you can read", async () => {
    signIn(["contacts:read_all"]);
    renderApp("/");
    expect(await screen.findByRole("heading", { name: "Contacts" })).toBeInTheDocument();
  });

  test("shows who is signed in", async () => {
    signIn("admin", { name: "Admin One" });
    renderApp("/messages");
    expect(await screen.findByText("Admin One")).toBeInTheDocument();
    await waitFor(() => expect(screen.getByRole("button", { name: "Sign out" })).toBeEnabled());
  });
});
