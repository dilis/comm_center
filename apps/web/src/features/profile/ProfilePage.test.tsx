import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import { server } from "@/test/server";
import { emptyBackend, page, renderApp, signIn } from "@/test/utils";

const profile = { first_name: "Test", middle_name: null, last_name: "User", email: "t@example.com" };

async function open() {
  signIn("agent", profile);
  renderApp("/messages");
  await userEvent.click(await screen.findByRole("link", { name: "My profile" }));
  await screen.findByRole("heading", { name: "My profile" });
}

beforeEach(() => emptyBackend());

test("the name in the header opens the profile with the current values", async () => {
  await open();
  expect(screen.getByLabelText("First name")).toHaveValue("Test");
  expect(screen.getByLabelText("Email")).toHaveValue("t@example.com");
});

test("saving the profile sends the edited parts", async () => {
  let body: unknown;
  server.use(
    http.patch("*/api/auth/me/profile", async ({ request }) => {
      body = await request.json();
      return HttpResponse.json({ id: 1, username: "tester", name: "Tess User", ...profile, first_name: "Tess", phones: [], groups: [], permissions: [] });
    }),
  );
  await open();
  const first = screen.getByLabelText("First name");
  await userEvent.clear(first);
  await userEvent.type(first, "Tess");
  await userEvent.click(screen.getByRole("button", { name: "Save profile" }));
  expect(await screen.findByRole("status")).toHaveTextContent("Saved.");
  expect(body).toEqual({ first_name: "Tess", middle_name: null, last_name: "User", email: "t@example.com" });
});

test("the new password must be confirmed", async () => {
  await open();
  await userEvent.type(screen.getByLabelText("Current password"), "old password 1");
  await userEvent.type(screen.getByLabelText("New password"), "a new long password");
  await userEvent.type(screen.getByLabelText("Confirm new password"), "something else!!");
  await userEvent.click(screen.getByRole("button", { name: "Change password" }));
  expect(await screen.findByText("The passwords do not match")).toBeInTheDocument();
});

test("a wrong current password shows the server's message and stays signed in", async () => {
  server.use(http.put("*/api/auth/me/password", () => HttpResponse.json({ detail: "current password is incorrect" }, { status: 403 })));
  await open();
  await userEvent.type(screen.getByLabelText("Current password"), "wrong password");
  await userEvent.type(screen.getByLabelText("New password"), "a new long password");
  await userEvent.type(screen.getByLabelText("Confirm new password"), "a new long password");
  await userEvent.click(screen.getByRole("button", { name: "Change password" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("current password is incorrect");
});

test("changing the password signs the person out", async () => {
  server.use(
    http.put("*/api/auth/me/password", () => new HttpResponse(null, { status: 204 })),
    http.post("*/api/auth/logout", () => new HttpResponse(null, { status: 204 })),
  );
  await open();
  await userEvent.type(screen.getByLabelText("Current password"), "old password 1");
  await userEvent.type(screen.getByLabelText("New password"), "a new long password");
  await userEvent.type(screen.getByLabelText("Confirm new password"), "a new long password");
  await userEvent.click(screen.getByRole("button", { name: "Change password" }));
  await waitFor(() => expect(screen.getByRole("button", { name: /sign in/i })).toBeInTheDocument());
});

test("lists where you are signed in and marks this device", async () => {
  const session = { ip: "10.0.0.7", signed_in_at: "2026-11-01T08:00:00", last_active_at: "2026-11-09T08:00:00" };
  server.use(
    http.get("*/api/auth/me/sessions", () =>
      HttpResponse.json(
        page([
          { ...session, id: "a", current: true, user_agent: "Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0" },
          { ...session, id: "b", current: false, user_agent: null, ip: null },
        ]),
      ),
    ),
  );
  await open();
  const table = await screen.findByRole("table", { name: "Sessions" });
  const here = (await within(table).findByText("Firefox on Linux")).closest("tr")!;
  expect(within(here).getByText("This device")).toBeInTheDocument();
  expect(within(here).getByText("10.0.0.7")).toBeInTheDocument();
  const other = within(table).getByText("Unknown device").closest("tr")!;
  expect(within(other).queryByText("This device")).not.toBeInTheDocument();
});
