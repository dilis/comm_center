import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import { server } from "@/test/server";
import { emptyBackend, page, renderApp, signIn, type Role } from "@/test/utils";

const user = (id: number, username: string, over: Record<string, unknown> = {}) => ({
  id, username, contact_id: 100 + id, name: `${username} Name`, first_name: username, middle_name: null, last_name: "Name", email: `${username}@example.com`, phones: [],
  is_active: true, owner_id: 1, groups: [{ id: 3, name: "agent" }], locked: false, created_at: "2026-11-01T08:00:00", ...over,
});
const me = user(1, "tester", { groups: [{ id: 1, name: "admin" }] }); // meFor() is user id 1
const bea = user(2, "bea");
const cy = user(3, "cy", { is_active: false, groups: [] });

const groups = [
  { id: 1, name: "admin", is_system: true, permissions: ["users:delete", "users:read_all", "contacts:read_all"] },
  { id: 2, name: "contacts_viewer", is_system: true, permissions: ["contacts:read_all"] },
  { id: 3, name: "agent", is_system: true, permissions: ["contacts:read_all", "messages:read_own"] },
];

let requests: URL[];
function backend(users: unknown[] = [me, bea, cy]) {
  requests = [];
  server.use(
    http.get("*/api/users", ({ request }) => {
      requests.push(new URL(request.url));
      return HttpResponse.json(page(users));
    }),
    http.get("*/api/groups", () => HttpResponse.json(page(groups))),
  );
}
const lastQuery = () => Object.fromEntries(requests.at(-1)!.searchParams);

async function open(role: Role | string[] = "admin", url = "/users") {
  signIn(role);
  renderApp(url);
  await screen.findByRole("heading", { name: "Users" });
}

beforeEach(() => emptyBackend());

describe("list", () => {
  test("shows username, name, groups and status", async () => {
    backend();
    await open();
    const row = (await screen.findByText("bea")).closest("tr")!;
    expect(within(row).getByText("bea Name")).toBeInTheDocument();
    expect(within(row).getByText("agent")).toBeInTheDocument();
    expect(within(row).getByText("Active")).toBeInTheDocument();
    expect(screen.getByText("cy").closest("tr")).toHaveTextContent("Inactive");
  });

  test("defaults to newest first; search and status are server-side", async () => {
    backend();
    await open();
    await screen.findByText("bea");
    expect(lastQuery()).toMatchObject({ sort: "created_at", order: "desc", page: "1" });
    await userEvent.type(screen.getByRole("searchbox", { name: "Search users" }), "be");
    await waitFor(() => expect(lastQuery()).toMatchObject({ q: "be" }));
    await userEvent.selectOptions(screen.getByLabelText("Status"), "inactive");
    await waitFor(() => expect(lastQuery()).toMatchObject({ is_active: "false" }));
    await userEvent.selectOptions(screen.getByLabelText("Status"), "active");
    await waitFor(() => expect(lastQuery()).toMatchObject({ is_active: "true" }));
  });

  test.each<[Role, boolean, boolean, boolean]>([
    ["admin", true, true, true],
    ["operator", false, false, false],
    ["auditor", false, false, false],
  ])("%s: create=%s edit=%s delete=%s", async (role, create, edit, remove) => {
    backend([bea]);
    await open(role);
    await screen.findByText("bea");
    expect(!!screen.queryByRole("button", { name: "New user" })).toBe(create);
    expect(!!screen.queryByRole("button", { name: "Edit bea" })).toBe(edit);
    expect(!!screen.queryByRole("button", { name: "Delete bea" })).toBe(remove);
  });

  test("you cannot delete yourself from the list", async () => {
    backend();
    await open();
    await screen.findByText("bea");
    expect(screen.getByRole("button", { name: "Edit tester" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete tester" })).not.toBeInTheDocument();
  });
});

describe("create", () => {
  async function openCreate(role: Role | string[] = "admin") {
    backend([bea]);
    await open(role);
    await userEvent.click(await screen.findByRole("button", { name: "New user" }));
    return screen.findByRole("dialog", { name: "New user" });
  }

  test("creates a user with a new contact and chosen groups", async () => {
    let body: unknown;
    server.use(http.post("*/api/users", async ({ request }) => ((body = await request.json()), HttpResponse.json(bea, { status: 201 }))));
    const dialog = await openCreate();
    await userEvent.type(within(dialog).getByLabelText("Username"), "newbie");
    await userEvent.type(within(dialog).getByLabelText("Password"), "a long enough pass");
    await userEvent.type(within(dialog).getByLabelText("First name"), "New");
    await userEvent.type(within(dialog).getByLabelText("Last name"), "Bie");
    await userEvent.type(within(dialog).getByLabelText("Email"), "n@example.com");
    await userEvent.click(await within(dialog).findByRole("checkbox", { name: /agent/ }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Create user" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(body).toEqual({
      username: "newbie", password: "a long enough pass", is_active: true, group_ids: [3],
      contact: { first_name: "New", middle_name: null, last_name: "Bie", email: "n@example.com", type: "person", phones: [] },
    });
  });

  test("can link an existing contact instead", async () => {
    let body: unknown;
    server.use(
      http.post("*/api/users", async ({ request }) => ((body = await request.json()), HttpResponse.json(bea, { status: 201 }))),
      http.get("*/api/contacts", () => HttpResponse.json(page([{ id: 77, name: "Dora Existing", email: null, phones: [] }]))),
    );
    const dialog = await openCreate();
    await userEvent.type(within(dialog).getByLabelText("Username"), "dora");
    await userEvent.type(within(dialog).getByLabelText("Password"), "a long enough pass");
    await userEvent.click(within(dialog).getByLabelText("Existing contact"));
    await userEvent.type(within(dialog).getByRole("searchbox", { name: "Find a contact" }), "dora");
    await userEvent.click(await within(dialog).findByRole("radio", { name: /Dora Existing/ }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Create user" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(body).toMatchObject({ username: "dora", contact_id: 77 });
    expect(body).not.toHaveProperty("contact");
  });

  test("validates before sending", async () => {
    let posted = false;
    server.use(http.post("*/api/users", () => ((posted = true), HttpResponse.json(bea, { status: 201 }))));
    const dialog = await openCreate();
    await userEvent.click(within(dialog).getByRole("button", { name: "Create user" }));
    expect(await within(dialog).findByText("Enter a username")).toBeInTheDocument();
    expect(within(dialog).getByText("Enter a first name")).toBeInTheDocument();
    await userEvent.type(within(dialog).getByLabelText("Password"), "short");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create user" }));
    expect(await within(dialog).findByText("At least 10 characters")).toBeInTheDocument();
    expect(posted).toBe(false);
  });

  test("groups the caller could not assign are shown but disabled (the API enforces the same rule)", async () => {
    const dialog = await openCreate([
      "users:read_all", "users:create", "groups:read_all", "contacts:create", "contacts:read_all",
    ]);
    expect(await within(dialog).findByRole("checkbox", { name: /contacts_viewer/ })).toBeEnabled();
    expect(within(dialog).getByRole("checkbox", { name: /^admin/ })).toBeDisabled();
    expect(within(dialog).getByRole("checkbox", { name: /agent/ })).toBeDisabled(); // needs messages:read_own
  });

  test("without contacts:create only linking an existing contact is offered", async () => {
    const dialog = await openCreate(["users:read_all", "users:create", "contacts:read_all"]);
    expect(within(dialog).queryByLabelText("New contact")).not.toBeInTheDocument();
    expect(within(dialog).getByRole("searchbox", { name: "Find a contact" })).toBeInTheDocument();
  });

  test("without groups:read_all there is no group picker", async () => {
    const dialog = await openCreate(["users:read_all", "users:create", "contacts:create"]);
    expect(within(dialog).queryByText("Groups")).not.toBeInTheDocument();
  });

  test("shows the server's reason, e.g. a taken username, and stays open", async () => {
    server.use(http.post("*/api/users", () => HttpResponse.json({ detail: "username already in use" }, { status: 409 })));
    const dialog = await openCreate();
    await userEvent.type(within(dialog).getByLabelText("Username"), "bea");
    await userEvent.type(within(dialog).getByLabelText("Password"), "a long enough pass");
    await userEvent.type(within(dialog).getByLabelText("First name"), "Bea");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create user" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("username already in use");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});

describe("edit", () => {
  async function openEdit(name: string, role: Role | string[] = "admin") {
    backend();
    await open(role);
    await userEvent.click(await screen.findByRole("button", { name: `Edit ${name}` }));
    return screen.findByRole("dialog", { name: "Edit user" });
  }

  test("pre-fills and sends only what changed", async () => {
    let body: unknown;
    server.use(http.put("*/api/users/2", async ({ request }) => ((body = await request.json()), HttpResponse.json(bea))));
    const dialog = await openEdit("bea");
    expect(within(dialog).getByLabelText("Username")).toHaveValue("bea");
    expect(within(dialog).getByLabelText("First name")).toHaveValue("bea");
    expect(within(dialog).getByLabelText("Last name")).toHaveValue("Name");
    expect(await within(dialog).findByRole("checkbox", { name: /agent/ })).toBeChecked();
    await userEvent.clear(within(dialog).getByLabelText("Username"));
    await userEvent.type(within(dialog).getByLabelText("Username"), "bea2");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(body).toEqual({ username: "bea2" });
  });

  test("changing groups, status, name and a cleared email are all sent", async () => {
    let body: unknown;
    server.use(http.put("*/api/users/2", async ({ request }) => ((body = await request.json()), HttpResponse.json(bea))));
    const dialog = await openEdit("bea");
    await userEvent.click(await within(dialog).findByRole("checkbox", { name: /agent/ }));
    await userEvent.click(within(dialog).getByRole("checkbox", { name: /contacts_viewer/ }));
    await userEvent.click(within(dialog).getByLabelText("Active"));
    await userEvent.clear(within(dialog).getByLabelText("First name"));
    await userEvent.type(within(dialog).getByLabelText("First name"), "Beatriz");
    await userEvent.clear(within(dialog).getByLabelText("Email"));
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(body).toEqual({ is_active: false, group_ids: [2], first_name: "Beatriz", email: null });
  });

  test("you cannot deactivate yourself", async () => {
    const dialog = await openEdit("tester");
    expect(within(dialog).getByLabelText("Active")).toBeDisabled();
  });

  test("name and email are editable only with contacts:update", async () => {
    const dialog = await openEdit("bea", ["users:read_all", "users:update", "groups:read_all"]);
    expect(within(dialog).queryByLabelText("First name")).not.toBeInTheDocument();
    expect(within(dialog).queryByLabelText("Email")).not.toBeInTheDocument();
    expect(within(dialog).getByLabelText("Username")).toBeInTheDocument();
  });

  test("an escalation refusal from the API is shown", async () => {
    server.use(
      http.put("*/api/users/2", () => HttpResponse.json({ detail: "cannot assign a group with permissions you lack" }, { status: 403 })),
    );
    const dialog = await openEdit("bea");
    await userEvent.click(await within(dialog).findByRole("checkbox", { name: /contacts_viewer/ }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("cannot assign a group with permissions you lack");
  });
});

describe("delete", () => {
  test("asks first, deletes, and shows refusals", async () => {
    backend([bea]);
    let deleted = false;
    server.use(http.delete("*/api/users/2", () => ((deleted = true), new HttpResponse(null, { status: 204 }))));
    await open();
    await userEvent.click(await screen.findByRole("button", { name: "Delete bea" }));
    const dialog = await screen.findByRole("dialog", { name: "Delete user" });
    expect(deleted).toBe(false);
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(deleted).toBe(true));
  });

  test("a server refusal is shown in the dialog", async () => {
    backend([bea]);
    server.use(http.delete("*/api/users/2", () => HttpResponse.json({ detail: "user not found" }, { status: 404 })));
    await open();
    await userEvent.click(await screen.findByRole("button", { name: "Delete bea" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("user not found");
  });
});

describe("unlock", () => {
  const dee = user(4, "dee", { locked: true });

  test("a locked-out user is marked and can be unlocked, after which the list refreshes", async () => {
    let locked = true;
    let unlocked = 0;
    server.use(
      http.get("*/api/users", () => HttpResponse.json(page([me, user(4, "dee", { locked })]))),
      http.post("*/api/users/4/unlock", () => ((unlocked += 1), (locked = false), new HttpResponse(null, { status: 204 }))),
      http.get("*/api/groups", () => HttpResponse.json(page(groups))),
    );
    await open();
    const row = (await screen.findByText("dee")).closest("tr")!;
    expect(within(row).getByText("Locked")).toBeInTheDocument();
    await userEvent.click(within(row).getByRole("button", { name: "Unlock dee" }));
    await waitFor(() => expect(unlocked).toBe(1));
    await waitFor(() => expect(screen.queryByText("Locked")).not.toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Unlock dee" })).not.toBeInTheDocument();
  });

  test("users who are not locked have no Unlock button", async () => {
    backend();
    await open();
    await screen.findByText("bea");
    expect(screen.queryByRole("button", { name: /Unlock/ })).not.toBeInTheDocument();
  });

  test("without users:update there is no Unlock button", async () => {
    backend([me, dee]);
    await open(["users:read_all"]);
    await screen.findByText("dee");
    expect(screen.queryByRole("button", { name: "Unlock dee" })).not.toBeInTheDocument();
  });

  test("a server refusal is shown", async () => {
    backend([me, dee]);
    server.use(http.post("*/api/users/4/unlock", () => HttpResponse.json({ detail: "user not found" }, { status: 404 })));
    await open();
    await userEvent.click(await screen.findByRole("button", { name: "Unlock dee" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("user not found");
  });
});
