import { screen, waitFor } from "@testing-library/react";
import { http, HttpResponse } from "msw";

import { fakeSubscription, installPush, uninstallPush } from "@/test/push";
import { server } from "@/test/server";
import { emptyBackend, renderApp, signIn } from "@/test/utils";

beforeEach(() => emptyBackend());
afterEach(() => uninstallPush());

const refused = () => HttpResponse.json({ detail: "not authenticated" }, { status: 401 });

test("a browser signed out from elsewhere drops its notification subscription when it opens", async () => {
  const subscription = fakeSubscription();
  const push = installPush({ permission: "granted", subscription });
  signIn("agent");
  server.use(http.post("*/api/auth/refresh", refused));
  renderApp("/messages");
  expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
  await waitFor(() => expect(push.current()).toBeNull());
});

test("and when it finds out while open", async () => {
  const push = installPush({ permission: "granted", subscription: fakeSubscription() });
  signIn("agent");
  let refreshes = 0;
  server.use(
    http.post("*/api/auth/refresh", () =>
      ++refreshes === 1
        ? HttpResponse.json({ access_token: "a", refresh_token: "r", token_type: "bearer", expires_in: 900 })
        : refused(),
    ),
    http.get("*/api/messages", refused),
  );
  renderApp("/messages");
  expect(await screen.findByRole("button", { name: "Sign in" })).toBeInTheDocument();
  await waitFor(() => expect(push.current()).toBeNull());
});
