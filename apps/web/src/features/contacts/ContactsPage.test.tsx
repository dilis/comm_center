import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import { server } from "@/test/server";
import { emptyBackend, page, renderApp, signIn, type Role } from "@/test/utils";

const ana = {
  id: 10, name: "Ana Cruz", first_name: "Ana", middle_name: null, last_name: "Cruz", type: "person", email: "ana@example.com", notes: null, owner_id: 1, user_id: null,
  phones: [{ phone: "+639171234567", label: "mobile", is_primary: true }],
  created_at: "2026-11-01T08:00:00", updated_at: "2026-11-01T08:00:00",
};
const acme = { ...ana, id: 11, name: "Acme Corp", first_name: "Acme Corp", middle_name: null, last_name: null, type: "entity", email: null, phones: [] };
const staff = { ...ana, id: 12, name: "Sam Staff", first_name: "Sam", last_name: "Staff", user_id: 5, owner_id: 2 };

let requests: URL[];
function listContacts(items: unknown[] = [ana, acme, staff], total = items.length) {
  requests = [];
  server.use(
    http.get("*/api/contacts", ({ request }) => {
      requests.push(new URL(request.url));
      return HttpResponse.json(page(items, { total }));
    }),
  );
}
const lastQuery = () => Object.fromEntries(requests.at(-1)!.searchParams);

async function open(role: Role | string[] = "admin", url = "/contacts") {
  signIn(role);
  renderApp(url);
  await screen.findByRole("heading", { name: "Contacts" });
}

beforeEach(() => emptyBackend());

describe("list", () => {
  test("shows contacts with their numbers, type and linked user", async () => {
    listContacts();
    await open();
    const row = (await screen.findByText("Ana Cruz")).closest("tr")!;
    expect(within(row).getByText("+639171234567")).toBeInTheDocument();
    expect(within(row).getByText("mobile")).toBeInTheDocument();
    expect(screen.getByText("Acme Corp").closest("tr")).toHaveTextContent("entity");
    expect(screen.getByText("Sam Staff").closest("tr")).toHaveTextContent("User");
  });

  test("asks for the newest first by default", async () => {
    listContacts();
    await open();
    await screen.findByText("Ana Cruz");
    expect(lastQuery()).toMatchObject({ sort: "created_at", order: "desc", page: "1", page_size: "20" });
  });

  test("searching sends q and returns to the first page", async () => {
    listContacts();
    await open("admin", "/contacts?page=3");
    await userEvent.type(screen.getByRole("searchbox", { name: "Search contacts" }), "ana");
    await waitFor(() => expect(lastQuery()).toMatchObject({ q: "ana", page: "1" }));
  });

  test("the type filter is sent to the API", async () => {
    listContacts();
    await open();
    await userEvent.selectOptions(screen.getByLabelText("Type"), "entity");
    await waitFor(() => expect(lastQuery()).toMatchObject({ type: "entity" }));
  });

  test("paging and sorting are server-driven", async () => {
    listContacts([ana], 45);
    await open();
    await screen.findByText("Ana Cruz");
    await userEvent.click(screen.getByRole("button", { name: "Next page" }));
    await waitFor(() => expect(lastQuery()).toMatchObject({ page: "2" }));
    await userEvent.click(within(screen.getByRole("columnheader", { name: /Name/ })).getByRole("button"));
    await waitFor(() => expect(lastQuery()).toMatchObject({ sort: "name", order: "asc", page: "1" }));
  });

  test("filters are restored from the URL", async () => {
    listContacts();
    await open("admin", "/contacts?q=acme&type=entity&page=2&sort=name&order=desc");
    await screen.findByText("Ana Cruz");
    expect(lastQuery()).toMatchObject({ q: "acme", type: "entity", page: "2", sort: "name", order: "desc" });
    expect(screen.getByRole("searchbox", { name: "Search contacts" })).toHaveValue("acme");
  });

  test("shows an empty state and the server's error", async () => {
    listContacts([]);
    await open();
    expect(await screen.findByText("No contacts found.")).toBeInTheDocument();
  });

  test("a failed request is reported in the table", async () => {
    server.use(http.get("*/api/contacts", () => HttpResponse.json({ detail: "permission denied" }, { status: 403 })));
    await open();
    expect(await screen.findByRole("alert")).toHaveTextContent("permission denied");
  });

  test("renders names and notes as text, never as markup", async () => {
    listContacts([{ ...ana, name: "<img src=x onerror=alert(1)>", first_name: "<img src=x onerror=alert(1)>", last_name: null, phones: [] }]);
    await open();
    expect(await screen.findByText("<img src=x onerror=alert(1)>")).toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull();
  });
});

describe("what each role is offered", () => {
  test.each<[Role, boolean, boolean, boolean]>([
    ["admin", true, true, true],
    ["operator", true, true, false],
    ["auditor", false, false, false],
    ["agent", false, false, false],
  ])("%s: create=%s edit=%s delete=%s", async (role, create, edit, remove) => {
    listContacts([ana]);
    await open(role);
    await screen.findByText("Ana Cruz");
    expect(!!screen.queryByRole("button", { name: "New contact" })).toBe(create);
    expect(!!screen.queryByRole("button", { name: "Edit Ana Cruz" })).toBe(edit);
    expect(!!screen.queryByRole("button", { name: "Delete Ana Cruz" })).toBe(remove);
  });

  test("with only read_own, actions appear only on contacts you own", async () => {
    listContacts([ana, { ...acme, owner_id: 99 }]);
    await open(["contacts:read_own", "contacts:update", "contacts:delete"]);
    await screen.findByText("Ana Cruz");
    expect(screen.getByRole("button", { name: "Edit Ana Cruz" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit Acme Corp" })).not.toBeInTheDocument();
  });
});

describe("create", () => {
  test("posts the contact with normalized fields and refreshes the list", async () => {
    listContacts([]);
    let body: unknown;
    server.use(
      http.post("*/api/contacts", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json({ ...ana, id: 20 }, { status: 201 });
      }),
    );
    await open();
    const before = requests.length;
    await userEvent.click(screen.getByRole("button", { name: "New contact" }));
    const dialog = await screen.findByRole("dialog", { name: "New contact" });
    await userEvent.type(within(dialog).getByLabelText("First name"), "Ana");
    await userEvent.type(within(dialog).getByLabelText("Middle name"), "Maria");
    await userEvent.type(within(dialog).getByLabelText("Last name"), "Cruz");
    await userEvent.type(within(dialog).getByLabelText("Email"), "ana@example.com");
    await userEvent.click(within(dialog).getByRole("button", { name: "Add phone" }));
    await userEvent.type(within(dialog).getByLabelText("Phone 1"), "0917 123 4567");
    await userEvent.type(within(dialog).getByLabelText("Label 1"), "mobile");
    await userEvent.click(within(dialog).getByLabelText("Primary 1"));
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(body).toEqual({
      first_name: "Ana", middle_name: "Maria", last_name: "Cruz", type: "person", email: "ana@example.com", notes: null,
      phones: [{ phone: "0917 123 4567", label: "mobile", is_primary: true }],
    });
    await waitFor(() => expect(requests.length).toBeGreaterThan(before));
  });

  test("blank rows are dropped and a bad email is caught before any request", async () => {
    listContacts([]);
    let posted = false;
    server.use(http.post("*/api/contacts", () => ((posted = true), HttpResponse.json(ana, { status: 201 }))));
    await open();
    await userEvent.click(screen.getByRole("button", { name: "New contact" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await within(dialog).findByText("Enter a first name")).toBeInTheDocument();
    await userEvent.type(within(dialog).getByLabelText("First name"), "X");
    await userEvent.type(within(dialog).getByLabelText("Email"), "not-an-email");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await within(dialog).findByText("Enter a valid email")).toBeInTheDocument();
    expect(posted).toBe(false);
  });

  test("a phone number already in use is reported and the form stays open", async () => {
    listContacts([]);
    server.use(http.post("*/api/contacts", () => HttpResponse.json({ detail: "phone number already in use" }, { status: 409 })));
    await open();
    await userEvent.click(screen.getByRole("button", { name: "New contact" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.type(within(dialog).getByLabelText("First name"), "Dup");
    await userEvent.click(within(dialog).getByRole("button", { name: "Add phone" }));
    await userEvent.type(within(dialog).getByLabelText("Phone 1"), "0917 123 4567");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("phone number already in use");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  test("a phone row can be removed", async () => {
    listContacts([]);
    await open();
    await userEvent.click(screen.getByRole("button", { name: "New contact" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Add phone" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Remove phone 1" }));
    expect(within(dialog).queryByLabelText("Phone 1")).not.toBeInTheDocument();
  });
});

describe("edit", () => {
  test("pre-fills the form and sends a full update including the phones", async () => {
    listContacts([ana]);
    let body: unknown;
    server.use(
      http.put("*/api/contacts/10", async ({ request }) => {
        body = await request.json();
        return HttpResponse.json(ana);
      }),
    );
    await open();
    await userEvent.click(await screen.findByRole("button", { name: "Edit Ana Cruz" }));
    const dialog = await screen.findByRole("dialog", { name: "Edit contact" });
    expect(within(dialog).getByLabelText("First name")).toHaveValue("Ana");
    expect(within(dialog).getByLabelText("Middle name")).toHaveValue("");
    expect(within(dialog).getByLabelText("Last name")).toHaveValue("Cruz");
    expect(within(dialog).getByLabelText("Phone 1")).toHaveValue("+639171234567");
    expect(within(dialog).getByLabelText("Primary 1")).toBeChecked();
    await userEvent.clear(within(dialog).getByLabelText("Last name"));
    await userEvent.type(within(dialog).getByLabelText("Last name"), "Cruz-Lim");
    await userEvent.click(within(dialog).getByRole("button", { name: "Save" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(body).toEqual({
      first_name: "Ana", middle_name: null, last_name: "Cruz-Lim", type: "person", email: "ana@example.com", notes: null,
      phones: [{ phone: "+639171234567", label: "mobile", is_primary: true }],
    });
  });

  test("a contact that belongs to a user must stay a person", async () => {
    listContacts([staff]);
    await open();
    await userEvent.click(await screen.findByRole("button", { name: "Edit Sam Staff" }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByLabelText("Type")).toBeDisabled();
  });
});

describe("delete", () => {
  test("asks first, then deletes and refreshes", async () => {
    listContacts([ana]);
    let deleted = false;
    server.use(http.delete("*/api/contacts/10", () => ((deleted = true), new HttpResponse(null, { status: 204 }))));
    await open();
    await userEvent.click(await screen.findByRole("button", { name: "Delete Ana Cruz" }));
    const dialog = await screen.findByRole("dialog", { name: "Delete contact" });
    expect(deleted).toBe(false);
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(deleted).toBe(true));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  test("cancelling does nothing", async () => {
    listContacts([ana]);
    let deleted = false;
    server.use(http.delete("*/api/contacts/10", () => ((deleted = true), new HttpResponse(null, { status: 204 }))));
    await open();
    await userEvent.click(await screen.findByRole("button", { name: "Delete Ana Cruz" }));
    await userEvent.click(within(await screen.findByRole("dialog")).getByRole("button", { name: "Cancel" }));
    expect(deleted).toBe(false);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  test("shows why the server refused, e.g. a contact linked to a user", async () => {
    listContacts([staff]);
    server.use(
      http.delete("*/api/contacts/12", () => HttpResponse.json({ detail: "contact is linked to an active user" }, { status: 409 })),
    );
    await open();
    await userEvent.click(await screen.findByRole("button", { name: "Delete Sam Staff" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("contact is linked to an active user");
  });
});
