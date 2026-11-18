import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import { server } from "@/test/server";
import { fakeSubscription, installPush, uninstallPush } from "@/test/push";
import { emptyBackend, renderApp, signIn } from "@/test/utils";

// bytes 1, 2, 3, 250, 251 as a VAPID key would be sent
const PUBLIC_KEY = "AQID-vs";

function serverPush(enabled = true) {
  server.use(
    http.get("*/api/auth/me/push", () =>
      HttpResponse.json({ enabled, public_key: enabled ? PUBLIC_KEY : null }),
    ),
  );
}

async function open(role: Parameters<typeof signIn>[0] = "agent") {
  signIn(role);
  renderApp("/profile");
  await screen.findByRole("heading", { name: "Notifications" });
}

beforeEach(() => emptyBackend());
afterEach(() => uninstallPush());

test("someone who cannot see received messages is not offered notifications", async () => {
  installPush();
  serverPush();
  signIn(["messages:read_own", "messages:create"]);
  renderApp("/profile");
  await screen.findByRole("heading", { name: "My profile" });
  expect(screen.queryByRole("heading", { name: "Notifications" })).not.toBeInTheDocument();
});

test("a server without push keys says so and offers no switch", async () => {
  installPush();
  serverPush(false);
  await open();
  expect(await screen.findByText(/not set up on this server/i)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /turn on notifications/i })).not.toBeInTheDocument();
});

test("a browser without push support explains, with the iPhone hint", async () => {
  serverPush(); // nothing installed: no service worker, PushManager or Notification
  await open();
  expect(await screen.findByText(/cannot show notifications/i)).toHaveTextContent(/home screen/i);
  expect(screen.queryByRole("button", { name: /turn on notifications/i })).not.toBeInTheDocument();
});

test("blocked notifications are explained, not retried", async () => {
  installPush({ permission: "denied" });
  serverPush();
  await open();
  expect(await screen.findByText(/blocked/i)).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: /turn on notifications/i })).not.toBeInTheDocument();
});

test("turning on asks permission, subscribes with the server's key and tells the server", async () => {
  const push = installPush();
  serverPush();
  let body: unknown;
  server.use(
    http.put("*/api/auth/me/push", async ({ request }) => {
      body = await request.json();
      return new HttpResponse(null, { status: 204 });
    }),
  );
  await open();
  await userEvent.click(await screen.findByRole("button", { name: "Turn on notifications" }));
  expect(await screen.findByRole("button", { name: "Turn off notifications" })).toBeInTheDocument();
  expect(push.requestPermission).toHaveBeenCalled();
  const options = push.pushManager.subscribe.mock.calls[0][0];
  expect(options.userVisibleOnly).toBe(true);
  expect(Array.from(options.applicationServerKey)).toEqual([1, 2, 3, 250, 251]);
  expect(body).toEqual({ endpoint: "https://push.example.com/send/1", keys: { p256dh: "key1", auth: "auth1" } });
});

test("declining the permission prompt leaves everything off and says why", async () => {
  const push = installPush({ prompt: "denied" });
  serverPush();
  await open();
  await userEvent.click(await screen.findByRole("button", { name: "Turn on notifications" }));
  expect(await screen.findByRole("alert")).toHaveTextContent(/not allowed/i);
  expect(push.pushManager.subscribe).not.toHaveBeenCalled();
});

test("if the server refuses, the browser subscription is undone and the error shown", async () => {
  const push = installPush();
  serverPush();
  server.use(http.put("*/api/auth/me/push", () => HttpResponse.json({ detail: "push notifications are not set up" }, { status: 409 })));
  await open();
  await userEvent.click(await screen.findByRole("button", { name: "Turn on notifications" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("push notifications are not set up");
  expect(push.current()).toBeNull(); // the browser subscription was undone
  expect(screen.getByRole("button", { name: "Turn on notifications" })).toBeInTheDocument();
});

test("a browser that is already subscribed shows as on", async () => {
  installPush({ permission: "granted", subscription: fakeSubscription(5) });
  serverPush();
  await open();
  expect(await screen.findByRole("button", { name: "Turn off notifications" })).toBeInTheDocument();
});

test("turning off tells the server and drops the browser subscription", async () => {
  const sub = fakeSubscription(5);
  installPush({ permission: "granted", subscription: sub });
  serverPush();
  let body: unknown;
  server.use(
    http.delete("*/api/auth/me/push", async ({ request }) => {
      body = await request.json();
      return new HttpResponse(null, { status: 204 });
    }),
  );
  await open();
  await userEvent.click(await screen.findByRole("button", { name: "Turn off notifications" }));
  expect(await screen.findByRole("button", { name: "Turn on notifications" })).toBeInTheDocument();
  expect(body).toEqual({ endpoint: "https://push.example.com/send/5" });
  expect(sub.unsubscribe).toHaveBeenCalled();
});

test("signing out turns notifications off for that browser, so the next person starts clean", async () => {
  const sub = fakeSubscription(5);
  installPush({ permission: "granted", subscription: sub });
  let removed: unknown;
  server.use(
    http.delete("*/api/auth/me/push", async ({ request }) => {
      removed = await request.json();
      return new HttpResponse(null, { status: 204 });
    }),
    http.post("*/api/auth/logout", () => new HttpResponse(null, { status: 204 })),
  );
  signIn("agent");
  renderApp("/messages");
  await userEvent.click(await screen.findByRole("button", { name: "Sign out" }));
  await waitFor(() => expect(screen.getByRole("button", { name: /sign in/i })).toBeInTheDocument());
  expect(removed).toEqual({ endpoint: "https://push.example.com/send/5" });
  expect(sub.unsubscribe).toHaveBeenCalled();
});

test("signing out still works when the server cannot be told", async () => {
  installPush({ permission: "granted", subscription: fakeSubscription(5) });
  server.use(
    http.delete("*/api/auth/me/push", () => HttpResponse.error()),
    http.post("*/api/auth/logout", () => new HttpResponse(null, { status: 204 })),
  );
  signIn("agent");
  renderApp("/messages");
  await userEvent.click(await screen.findByRole("button", { name: "Sign out" }));
  await waitFor(() => expect(screen.getByRole("button", { name: /sign in/i })).toBeInTheDocument());
});
