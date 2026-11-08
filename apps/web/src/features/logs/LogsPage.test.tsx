import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import { server } from "@/test/server";
import { emptyBackend, page, renderApp, signIn } from "@/test/utils";

const entry = {
  id: 3, user_id: 7, username: "ana", name: "Ana Cruz", action: "create", resource: "contact",
  resource_id: 12, summary: "Created contact Ben", ip: "10.0.0.5", created_at: "2026-11-09T08:00:00",
};
const signin = { id: 9, event: "login_failed", username: "ghost", user_id: null, ip: "10.0.0.9", created_at: "2026-11-09T08:05:00" };

let activity: URL[];
let logins: URL[];
function stub() {
  activity = [];
  logins = [];
  server.use(
    http.get("*/api/logs/activity", ({ request }) => {
      activity.push(new URL(request.url));
      return HttpResponse.json(page([entry]));
    }),
    http.get("*/api/logs/logins", ({ request }) => {
      logins.push(new URL(request.url));
      return HttpResponse.json(page([signin]));
    }),
  );
}

beforeEach(() => emptyBackend());

async function open(url = "/logs") {
  signIn("admin");
  renderApp(url);
  await screen.findByRole("heading", { name: "Logs" });
}

test("shows what people did, with who, what and where from", async () => {
  stub();
  await open();
  const row = (await screen.findByText("Created contact Ben")).closest("tr")!;
  expect(within(row).getByText("Ana Cruz")).toBeInTheDocument();
  expect(within(row).getByText("create")).toBeInTheDocument();
  expect(within(row).getByText("contact")).toBeInTheDocument();
  expect(within(row).getByText("10.0.0.5")).toBeInTheDocument();
  expect(logins).toHaveLength(0); // the other tab is not loaded until opened
});

test("the sign-ins tab is a separate log", async () => {
  stub();
  await open();
  await userEvent.click(screen.getByRole("tab", { name: "Sign-ins" }));
  const row = (await screen.findByText("ghost")).closest("tr")!;
  expect(within(row).getByText("login_failed")).toBeInTheDocument();
  expect(within(row).getByText("10.0.0.9")).toBeInTheDocument();
  expect(screen.queryByText("Created contact Ben")).not.toBeInTheDocument();
});

test("a link opens straight on the sign-ins tab", async () => {
  stub();
  await open("/logs?tab=logins");
  expect(await screen.findByText("ghost")).toBeInTheDocument();
  expect(activity).toHaveLength(0);
});

test("searching and filtering by action reach the server", async () => {
  stub();
  await open();
  await screen.findByText("Created contact Ben");
  await userEvent.type(screen.getByRole("searchbox", { name: "Search logs" }), "ben");
  await waitFor(() => expect(Object.fromEntries(activity.at(-1)!.searchParams)).toMatchObject({ q: "ben", page: "1" }));
  await userEvent.selectOptions(screen.getByLabelText("Action"), "delete");
  await waitFor(() => expect(activity.at(-1)!.searchParams.get("action")).toBe("delete"));
});

test("a failed request is reported", async () => {
  server.use(http.get("*/api/logs/activity", () => HttpResponse.json({ detail: "boom" }, { status: 500 })));
  await open();
  expect(await screen.findByText("boom")).toBeInTheDocument();
});
