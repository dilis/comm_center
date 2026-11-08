import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";

import { server } from "@/test/server";

import { POLL } from "./polling";
import { emptyBackend, page, renderApp, signIn, type Role } from "@/test/utils";

const base = {
  channel: "gsm", contact_id: 10, contact_name: "Ana Cruz", phone_number: "+639171234567", owner_id: 1, owner_name: "Rhea Admin",
  gsm_device_id: null, reply_to_id: null, created_at: "2026-11-05T08:00:00", sent_at: null, received_at: null, error_message: null,
};
const out = { ...base, id: 1, direction: "outbound", content: "hello Ana", status: "sent", sent_at: "2026-11-05T08:00:05" };
const incoming = { ...base, id: 2, direction: "inbound", owner_id: 3, owner_name: "gsm-modem1", content: "hi from Ana", status: "received", received_at: "2026-11-05T09:00:00" };
const failed = { ...base, id: 3, direction: "outbound", content: "never arrives", status: "failed", error_message: "no signal" };
const queued = { ...base, id: 4, direction: "outbound", content: "waiting", status: "queued" };

let requests: URL[];
function backend(items: unknown[] = [out, incoming, failed], counts = { all: 3, sent: 2, received: 1 }) {
  requests = [];
  server.use(
    http.get("*/api/messages/counts", () => HttpResponse.json(counts)),
    http.get("*/api/messages", ({ request }) => {
      requests.push(new URL(request.url));
      return HttpResponse.json(page(items));
    }),
  );
}
const lastQuery = () => Object.fromEntries(requests.at(-1)!.searchParams);
// userEvent.type reads "{{" as an escape for one "{", so text with placeholders is set directly.
const setText = (box: HTMLElement, value: string) => fireEvent.change(box, { target: { value } });

async function open(role: Role | string[] = "admin", url = "/messages") {
  signIn(role);
  renderApp(url);
  await screen.findByRole("heading", { name: "Messages" });
}

beforeEach(() => emptyBackend());

describe("list", () => {
  test("shows direction, contact, content and status", async () => {
    backend();
    await open();
    const row = (await screen.findByText("hello Ana")).closest("tr")!;
    expect(within(row).getByText("Sent")).toBeInTheDocument();
    expect(within(row).getByText("Ana Cruz")).toBeInTheDocument();
    expect(within(row).getByText("+639171234567")).toBeInTheDocument();
    expect(screen.getByText("hi from Ana").closest("tr")).toHaveTextContent("Received");
    const failedRow = screen.getByText("never arrives").closest("tr")!;
    expect(failedRow).toHaveTextContent("failed");
    expect(failedRow).toHaveTextContent("no signal");
  });

  test("shows who owns each message (the sender, for sent ones)", async () => {
    backend();
    await open();
    const row = (await screen.findByText("hello Ana")).closest("tr")!;
    expect(within(row).getByText("Rhea Admin")).toBeInTheDocument();
    expect(screen.getByText("hi from Ana").closest("tr")).toHaveTextContent("gsm-modem1");
  });

  test("the owner column is called Owner on the All tab", async () => {
    backend();
    await open();
    expect(await screen.findByRole("columnheader", { name: "Owner" })).toBeInTheDocument();
  });

  test("the owner column is called Sender on the Sent tab", async () => {
    backend();
    await open("admin", "/messages?direction=sent");
    expect(await screen.findByRole("columnheader", { name: "Sender" })).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Owner" })).not.toBeInTheDocument();
  });

  test("asks for the newest first, on the All tab", async () => {
    backend();
    await open();
    await screen.findByText("hello Ana");
    expect(lastQuery()).toMatchObject({ direction: "all", order: "desc", page: "1", page_size: "20" });
  });

  test("tabs show scoped counts and switch the direction", async () => {
    backend();
    await open();
    expect(await screen.findByRole("tab", { name: "All 3" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tab", { name: "Sent 2" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Received 1" }));
    await waitFor(() => expect(lastQuery()).toMatchObject({ direction: "received", page: "1" }));
    expect(screen.getByRole("tab", { name: "Received 1" })).toHaveAttribute("aria-selected", "true");
  });

  test("the tab is restored from the URL", async () => {
    backend();
    await open("admin", "/messages?direction=sent");
    await screen.findByText("hello Ana");
    expect(lastQuery()).toMatchObject({ direction: "sent" });
    expect(screen.getByRole("tab", { name: /Sent/ })).toHaveAttribute("aria-selected", "true");
  });

  test("status and search are sent to the API", async () => {
    backend();
    await open();
    await userEvent.selectOptions(screen.getByLabelText("Status"), "failed");
    await waitFor(() => expect(lastQuery()).toMatchObject({ status: "failed" }));
    await userEvent.type(screen.getByRole("searchbox", { name: "Search messages" }), "ana");
    await waitFor(() => expect(lastQuery()).toMatchObject({ q: "ana", status: "failed", page: "1" }));
  });

  test("the date column flips the sort order", async () => {
    backend();
    await open();
    await screen.findByText("hello Ana");
    await userEvent.click(within(screen.getByRole("columnheader", { name: /Date/ })).getByRole("button"));
    await waitFor(() => expect(lastQuery()).toMatchObject({ order: "asc" }));
  });

  test("message content is untrusted: shown as text, with line breaks kept", async () => {
    backend([{ ...incoming, content: "<script>alert(1)</script>\n<b>bold?</b>" }]);
    await open();
    const cell = await screen.findByText(/<script>alert\(1\)<\/script>/);
    expect(cell).toHaveTextContent("<b>bold?</b>");
    expect(cell.className).toMatch(/whitespace-pre-wrap/);
    expect(document.querySelector("script, b")).toBeNull();
  });

  test("empty state", async () => {
    backend([], { all: 0, sent: 0, received: 0 });
    await open();
    expect(await screen.findByText("No messages found.")).toBeInTheDocument();
  });
});

describe("live updates", () => {
  const defaults = { ...POLL };
  beforeEach(() => Object.assign(POLL, { pendingMs: 40, idleMs: 40 }));
  afterEach(() => Object.assign(POLL, defaults));

  test("received messages appear on their own, with the tab counts, without a reload", async () => {
    let arrived = false;
    server.use(
      http.get("*/api/messages/counts", () =>
        HttpResponse.json(arrived ? { all: 2, sent: 1, received: 1 } : { all: 1, sent: 1, received: 0 }),
      ),
      http.get("*/api/messages", () => HttpResponse.json(page(arrived ? [incoming, out] : [out]))),
    );
    await open();
    expect(await screen.findByText("hello Ana")).toBeInTheDocument();
    expect(screen.queryByText("hi from Ana")).not.toBeInTheDocument();
    expect(await screen.findByRole("tab", { name: "Received 0" })).toBeInTheDocument();
    arrived = true;
    expect(await screen.findByText("hi from Ana")).toBeInTheDocument();
    expect(await screen.findByRole("tab", { name: "Received 1" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "All 2" })).toBeInTheDocument();
  });

  test("the page, filters and tab you chose are kept across refreshes", async () => {
    backend();
    await open("admin", "/messages?direction=received&status=received&q=ana&page=2");
    await screen.findByText("hello Ana");
    const seen = requests.length;
    await waitFor(() => expect(requests.length).toBeGreaterThan(seen + 2)); // several refreshes later
    for (const url of requests) {
      expect(Object.fromEntries(url.searchParams)).toMatchObject({ direction: "received", status: "received", q: "ana", page: "2" });
    }
    expect(screen.getByRole("searchbox", { name: "Search messages" })).toHaveValue("ana");
  });

  test("a queued message is refreshed until the worker has sent it", async () => {
    let calls = 0;
    server.use(
      http.get("*/api/messages/counts", () => HttpResponse.json({ all: 1, sent: 1, received: 0 })),
      http.get("*/api/messages", () => HttpResponse.json(page([++calls < 3 ? queued : { ...queued, status: "sent" }]))),
    );
    await open();
    const table = () => within(screen.getByRole("table", { name: "Messages" }));
    expect(await screen.findByText("queued")).toBeInTheDocument();
    await waitFor(() => expect(table().getByText("sent")).toBeInTheDocument());
  });

  test("a failed background refresh keeps the rows on screen and the next one recovers", async () => {
    let failing = false;
    server.use(
      http.get("*/api/messages/counts", () => HttpResponse.json({ all: 1, sent: 1, received: 0 })),
      http.get("*/api/messages", () =>
        failing ? HttpResponse.json({ detail: "temporarily down" }, { status: 500 }) : HttpResponse.json(page([out])),
      ),
    );
    await open();
    expect(await screen.findByText("hello Ana")).toBeInTheDocument();
    failing = true;
    await new Promise((r) => setTimeout(r, 300)); // several failed refreshes
    expect(screen.getByText("hello Ana")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    failing = false;
    expect(screen.getByText("hello Ana")).toBeInTheDocument();
  });

  test("a failing first load still reports the error", async () => {
    server.use(
      http.get("*/api/messages/counts", () => HttpResponse.json({ all: 0, sent: 0, received: 0 })),
      http.get("*/api/messages", () => HttpResponse.json({ detail: "temporarily down" }, { status: 500 })),
    );
    await open();
    expect(await screen.findByRole("alert")).toHaveTextContent("temporarily down");
  });
});

describe("what each role is offered", () => {
  test.each<[Role, boolean, boolean]>([
    ["admin", true, true],
    ["operator", true, false],
    ["agent", true, false],
    ["auditor", false, false],
  ])("%s: send=%s delete=%s", async (role, send, remove) => {
    backend([out]);
    await open(role);
    await screen.findByText("hello Ana");
    expect(!!screen.queryByRole("button", { name: "New message" })).toBe(send);
    expect(!!screen.queryByRole("button", { name: "Delete message 1" })).toBe(remove);
  });

  test("with read_own only the caller's own messages can be deleted", async () => {
    backend([out, { ...out, id: 9, owner_id: 99, content: "someone else's" }]);
    await open(["messages:read_own", "messages:delete"]);
    await screen.findByText("hello Ana");
    expect(screen.getByRole("button", { name: "Delete message 1" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete message 9" })).not.toBeInTheDocument();
  });
});

describe("send", () => {
  const ana = { id: 10, name: "Ana Cruz", email: null, user_id: null, phones: [
    { phone: "+639171111111", label: "home", is_primary: false },
    { phone: "+639172222222", label: "work", is_primary: true },
  ] };
  const ben = { id: 11, name: "Ben Lim", email: null, user_id: null, phones: [{ phone: "+639173333333", label: null, is_primary: true }] };
  const noPhone = { id: 12, name: "No Phone", email: null, user_id: null, phones: [] };
  let contactQueries: URL[];

  async function openSend(role: Role | string[] = "admin") {
    backend([]);
    contactQueries = [];
    server.use(
      http.get("*/api/contacts", ({ request }) => {
        const url = new URL(request.url);
        contactQueries.push(url);
        const q = (url.searchParams.get("q") ?? "").toLowerCase();
        return HttpResponse.json(page([ana, ben, noPhone].filter((c) => c.name.toLowerCase().includes(q))));
      }),
    );
    await open(role);
    await userEvent.click(await screen.findByRole("button", { name: "New message" }));
    return screen.findByRole("dialog", { name: "New message" });
  }
  const choose = async (dialog: HTMLElement, name: RegExp) =>
    userEvent.click(await within(dialog).findByRole("checkbox", { name }));
  const sendButton = (dialog: HTMLElement) => within(dialog).getByRole("button", { name: /^Send/ });

  test("sends to one contact's primary number and refreshes the list", async () => {
    let body: unknown;
    server.use(http.post("*/api/messages/send", async ({ request }) => ((body = await request.json()), HttpResponse.json({ ...queued, id: 50 }, { status: 201 }))));
    const dialog = await openSend();
    const before = requests.length;
    await choose(dialog, /Ana Cruz/);
    expect(within(dialog).getByLabelText("Phone number")).toHaveValue("+639172222222");
    await userEvent.type(within(dialog).getByLabelText("Message"), "hello there");
    await userEvent.click(sendButton(dialog));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(body).toEqual({ contact_id: 10, phone: "+639172222222", content: "hello there" });
    await waitFor(() => expect(requests.length).toBeGreaterThan(before));
  });

  test("with one contact another of its numbers can be chosen", async () => {
    let body: { phone?: string } = {};
    server.use(http.post("*/api/messages/send", async ({ request }) => ((body = (await request.json()) as typeof body), HttpResponse.json({ ...queued, id: 51 }, { status: 201 }))));
    const dialog = await openSend();
    await choose(dialog, /Ana Cruz/);
    await userEvent.selectOptions(within(dialog).getByLabelText("Phone number"), "+639171111111");
    await userEvent.type(within(dialog).getByLabelText("Message"), "x");
    await userEvent.click(sendButton(dialog));
    await waitFor(() => expect(body.phone).toBe("+639171111111"));
  });

  test("contacts without a phone number are not offered", async () => {
    const dialog = await openSend();
    await within(dialog).findByRole("checkbox", { name: /Ana Cruz/ });
    expect(within(dialog).queryByRole("checkbox", { name: /No Phone/ })).not.toBeInTheDocument();
  });

  test("several contacts are sent in one request, each to its own primary number", async () => {
    let body: unknown;
    let bulk = 0;
    server.use(
      http.post("*/api/messages/send-bulk", async ({ request }) => {
        bulk += 1;
        body = await request.json();
        return HttpResponse.json({ queued: [queued, { ...queued, id: 5 }], skipped: [] }, { status: 201 });
      }),
      http.post("*/api/messages/send", () => HttpResponse.json({}, { status: 500 })),
    );
    const dialog = await openSend();
    const before = requests.length;
    await choose(dialog, /Ana Cruz/);
    await choose(dialog, /Ben Lim/);
    expect(within(dialog).getByText("2 selected")).toBeInTheDocument();
    expect(within(dialog).queryByLabelText("Phone number")).not.toBeInTheDocument(); // each uses its primary
    expect(sendButton(dialog)).toHaveTextContent("Send to 2 contacts");
    await userEvent.type(within(dialog).getByLabelText("Message"), "Hello everyone");
    await userEvent.click(sendButton(dialog));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(body).toEqual({ contact_ids: [10, 11], content: "Hello everyone" });
    expect(bulk).toBe(1);
    await waitFor(() => expect(requests.length).toBeGreaterThan(before));
  });

  test("when some contacts were skipped the dialog says who and why, and stays until closed", async () => {
    server.use(
      http.post("*/api/messages/send-bulk", () =>
        HttpResponse.json(
          { queued: [{ ...queued, id: 60 }], skipped: [{ contact_id: 11, reason: "no phone number" }] },
          { status: 201 },
        ),
      ),
    );
    const dialog = await openSend();
    const before = requests.length;
    await choose(dialog, /Ana Cruz/);
    await choose(dialog, /Ben Lim/);
    await userEvent.type(within(dialog).getByLabelText("Message"), "hi all");
    await userEvent.click(sendButton(dialog));
    const summary = await within(dialog).findByRole("status");
    expect(summary).toHaveTextContent("Queued 1 message");
    expect(summary).toHaveTextContent("Ben Lim");
    expect(summary).toHaveTextContent("no phone number");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    await waitFor(() => expect(requests.length).toBeGreaterThan(before)); // the list already refreshed
    await userEvent.click(within(dialog).getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  test("select all shown, clear selection, and removing one contact", async () => {
    const dialog = await openSend();
    await within(dialog).findByRole("checkbox", { name: /Ana Cruz/ });
    await userEvent.click(within(dialog).getByRole("button", { name: "Select all shown" }));
    expect(within(dialog).getByText("2 selected")).toBeInTheDocument(); // Ana and Ben; No Phone is not offered
    await userEvent.click(within(dialog).getByRole("button", { name: "Remove Ana Cruz" }));
    expect(within(dialog).getByText("1 selected")).toBeInTheDocument();
    expect(within(dialog).getByLabelText("Phone number")).toBeInTheDocument(); // back to one contact
    await userEvent.click(within(dialog).getByRole("button", { name: "Clear selection" }));
    expect(within(dialog).queryByText(/selected$/)).not.toBeInTheDocument();
  });

  test("the selection survives searching for other contacts", async () => {
    const dialog = await openSend();
    await userEvent.type(within(dialog).getByRole("searchbox", { name: "Find contacts" }), "ben");
    await choose(dialog, /Ben Lim/);
    await waitFor(() => expect(within(dialog).queryByRole("checkbox", { name: /Ana Cruz/ })).not.toBeInTheDocument());
    await userEvent.clear(within(dialog).getByRole("searchbox", { name: "Find contacts" }));
    await choose(dialog, /Ana Cruz/);
    expect(within(dialog).getByText("2 selected")).toBeInTheDocument();
    expect(within(dialog).getByRole("checkbox", { name: /Ben Lim/ })).toBeChecked();
  });

  test("asks for up to 100 contacts at a time, by name", async () => {
    const dialog = await openSend();
    await within(dialog).findByRole("checkbox", { name: /Ana Cruz/ });
    expect(Object.fromEntries(contactQueries.at(-1)!.searchParams)).toMatchObject({ page_size: "100", sort: "name", order: "asc" });
  });

  test("a contact and a message are required, and the length is limited, before any request", async () => {
    let posted = 0;
    server.use(
      http.post("*/api/messages/send", () => (posted++, HttpResponse.json(queued, { status: 201 }))),
      http.post("*/api/messages/send-bulk", () => (posted++, HttpResponse.json({ queued: [], skipped: [] }, { status: 201 }))),
    );
    const dialog = await openSend();
    await userEvent.click(sendButton(dialog));
    expect(await within(dialog).findByText("Choose at least one contact")).toBeInTheDocument();
    expect(within(dialog).getByText("Enter a message")).toBeInTheDocument();
    await choose(dialog, /Ana Cruz/);
    fireEvent.change(within(dialog).getByLabelText("Message"), { target: { value: "x".repeat(1601) } });
    await userEvent.click(sendButton(dialog));
    expect(await within(dialog).findByText("At most 1600 characters")).toBeInTheDocument();
    expect(posted).toBe(0);
  });

  test("shows a character counter", async () => {
    const dialog = await openSend();
    await userEvent.type(within(dialog).getByLabelText("Message"), "12345");
    expect(within(dialog).getByText("5 / 1600")).toBeInTheDocument();
  });

  test("shows the server's reason and keeps the form open", async () => {
    server.use(http.post("*/api/messages/send-bulk", () => HttpResponse.json({ detail: "permission denied" }, { status: 403 })));
    const dialog = await openSend();
    await choose(dialog, /Ana Cruz/);
    await choose(dialog, /Ben Lim/);
    await userEvent.type(within(dialog).getByLabelText("Message"), "hi");
    await userEvent.click(sendButton(dialog));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("permission denied");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });
});

describe("placeholders in the send dialog", () => {
  const ana = { id: 10, name: "Ana Cruz", email: null, user_id: null, phones: [{ phone: "+639172222222", label: null, is_primary: true }] };
  const ben = { id: 11, name: "Ben Lim", email: null, user_id: null, phones: [{ phone: "+639173333333", label: null, is_primary: true }] };

  async function openSend() {
    backend([]);
    server.use(http.get("*/api/contacts", () => HttpResponse.json(page([ana, ben]))));
    await open();
    await userEvent.click(await screen.findByRole("button", { name: "New message" }));
    return screen.findByRole("dialog", { name: "New message" });
  }

  test("Insert name puts {{name}} at the cursor", async () => {
    const dialog = await openSend();
    const box = within(dialog).getByLabelText("Message") as HTMLTextAreaElement;
    await userEvent.type(box, "Hello !");
    box.setSelectionRange(6, 6);
    await userEvent.click(within(dialog).getByRole("button", { name: "Insert name" }));
    expect(box.value).toBe("Hello {{name}}!");
    expect(within(dialog).getByText("15 / 1600")).toBeInTheDocument();
  });

  test("a preview shows how the first selected contact will read it", async () => {
    const dialog = await openSend();
    expect(within(dialog).queryByText(/Preview for/)).not.toBeInTheDocument();
    await userEvent.click(await within(dialog).findByRole("checkbox", { name: /Ana Cruz/ }));
    setText(within(dialog).getByLabelText("Message"), "Dear {{name}}, see you");
    const preview = within(dialog).getByTestId("preview");
    expect(preview).toHaveTextContent("Preview for Ana Cruz");
    expect(preview).toHaveTextContent("Dear Ana Cruz, see you");
  });

  test("no preview when the text has no placeholder", async () => {
    const dialog = await openSend();
    await userEvent.click(await within(dialog).findByRole("checkbox", { name: /Ana Cruz/ }));
    await userEvent.type(within(dialog).getByLabelText("Message"), "Just text");
    expect(within(dialog).queryByTestId("preview")).not.toBeInTheDocument();
  });

  test("the server gets the template as typed and fills in each name itself", async () => {
    let body: unknown;
    server.use(http.post("*/api/messages/send-bulk", async ({ request }) => ((body = await request.json()), HttpResponse.json({ queued: [], skipped: [] }, { status: 201 }))));
    const dialog = await openSend();
    await userEvent.click(await within(dialog).findByRole("checkbox", { name: /Ana Cruz/ }));
    await userEvent.click(within(dialog).getByRole("checkbox", { name: /Ben Lim/ }));
    setText(within(dialog).getByLabelText("Message"), "Hi {{name}}!");
    await userEvent.click(within(dialog).getByRole("button", { name: /^Send/ }));
    await waitFor(() => expect(body).toEqual({ contact_ids: [10, 11], content: "Hi {{name}}!" }));
  });

  test("an unknown placeholder is caught before anything is sent", async () => {
    let posted = 0;
    server.use(
      http.post("*/api/messages/send", () => (posted++, HttpResponse.json(queued, { status: 201 }))),
      http.post("*/api/messages/send-bulk", () => (posted++, HttpResponse.json({ queued: [], skipped: [] }, { status: 201 }))),
    );
    const dialog = await openSend();
    await userEvent.click(await within(dialog).findByRole("checkbox", { name: /Ana Cruz/ }));
    setText(within(dialog).getByLabelText("Message"), "Hi {{nam}}");
    await userEvent.click(within(dialog).getByRole("button", { name: /^Send/ }));
    expect(await within(dialog).findByText("Unknown placeholder {{nam}}; supported: {{name}}")).toBeInTheDocument();
    expect(posted).toBe(0);
  });

  test("warns when a long name pushes the message over the limit", async () => {
    server.use(http.get("*/api/contacts", () => HttpResponse.json(page([{ ...ana, name: "N".repeat(60) }]))));
    backend([]);
    await open();
    await userEvent.click(await screen.findByRole("button", { name: "New message" }));
    const dialog = await screen.findByRole("dialog", { name: "New message" });
    await userEvent.click(await within(dialog).findByRole("checkbox"));
    fireEvent.change(within(dialog).getByLabelText("Message"), { target: { value: "{{name}}".repeat(100) } });
    expect(within(dialog).getByTestId("preview")).toHaveTextContent("Over 1600 characters once the name is inserted");
  });
});

describe("reply", () => {
  const original = { ...incoming, id: 2, content: "Are you coming <b>Sunday</b>?", contact_name: "Ana Cruz" };
  const answer = { ...out, id: 8, content: "Yes!", reply_to_id: 2, status: "queued" };

  test.each<[Role, boolean]>([
    ["admin", true],
    ["operator", true],
    ["agent", true],
    ["auditor", false],
  ])("%s: reply offered on a received message = %s", async (role, offered) => {
    backend([original, out]);
    await open(role);
    await screen.findByText("hello Ana");
    expect(!!screen.queryByRole("button", { name: "Reply to message 2" })).toBe(offered);
    expect(screen.queryByRole("button", { name: "Reply to message 1" })).not.toBeInTheDocument(); // sent: nothing to reply to
  });

  test("the dialog shows who you are answering and what they wrote, as text", async () => {
    backend([original]);
    await open();
    await userEvent.click(await screen.findByRole("button", { name: "Reply to message 2" }));
    const dialog = await screen.findByRole("dialog", { name: "Reply" });
    expect(dialog).toHaveTextContent("To Ana Cruz, at +639171234567");
    expect(within(dialog).getByText(/Ana Cruz wrote on/)).toBeInTheDocument();
    expect(within(dialog).getByText("Are you coming <b>Sunday</b>?")).toBeInTheDocument();
    expect(dialog.querySelector("b")).toBeNull();
  });

  test("sends the reply to the original message, with names filled in by the server, and refreshes", async () => {
    backend([original]);
    let body: unknown;
    server.use(http.post("*/api/messages/2/reply", async ({ request }) => ((body = await request.json()), HttpResponse.json(answer, { status: 201 }))));
    await open();
    const before = requests.length;
    await userEvent.click(await screen.findByRole("button", { name: "Reply to message 2" }));
    const dialog = await screen.findByRole("dialog", { name: "Reply" });
    await userEvent.type(within(dialog).getByLabelText("Message"), "Yes ");
    await userEvent.click(within(dialog).getByRole("button", { name: "Insert name" }));
    expect(within(dialog).getByTestId("preview")).toHaveTextContent("Yes Ana Cruz");
    await userEvent.click(within(dialog).getByRole("button", { name: "Send reply" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(body).toEqual({ content: "Yes {{name}}" });
    await waitFor(() => expect(requests.length).toBeGreaterThan(before));
  });

  test("a message is required and placeholders are checked before any request", async () => {
    backend([original]);
    let posted = false;
    server.use(http.post("*/api/messages/2/reply", () => ((posted = true), HttpResponse.json(answer, { status: 201 }))));
    await open();
    await userEvent.click(await screen.findByRole("button", { name: "Reply to message 2" }));
    const dialog = await screen.findByRole("dialog", { name: "Reply" });
    await userEvent.click(within(dialog).getByRole("button", { name: "Send reply" }));
    expect(await within(dialog).findByText("Enter a message")).toBeInTheDocument();
    setText(within(dialog).getByLabelText("Message"), "Hi {{who}}");
    await userEvent.click(within(dialog).getByRole("button", { name: "Send reply" }));
    expect(await within(dialog).findByText(/Unknown placeholder \{\{who\}\}/)).toBeInTheDocument();
    expect(posted).toBe(false);
  });

  test("the server's reason is shown and the dialog stays open", async () => {
    backend([original]);
    server.use(http.post("*/api/messages/2/reply", () => HttpResponse.json({ detail: "message not found" }, { status: 404 })));
    await open();
    await userEvent.click(await screen.findByRole("button", { name: "Reply to message 2" }));
    const dialog = await screen.findByRole("dialog", { name: "Reply" });
    await userEvent.type(within(dialog).getByLabelText("Message"), "hi");
    await userEvent.click(within(dialog).getByRole("button", { name: "Send reply" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("message not found");
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  test("a reply is marked in the list", async () => {
    backend([answer, original]);
    await open();
    const row = (await screen.findByText("Yes!")).closest("tr")!;
    expect(row).toHaveTextContent("Reply to #2");
    expect(screen.getByText("Are you coming <b>Sunday</b>?").closest("tr")).not.toHaveTextContent("Reply to");
  });

  test("a reply's details show the message it answers", async () => {
    backend([answer]);
    server.use(http.get("*/api/messages/2", () => HttpResponse.json(original)));
    await open();
    await userEvent.click(await screen.findByRole("button", { name: "View message 8" }));
    const dialog = await screen.findByRole("dialog", { name: "Message" });
    expect(await within(dialog).findByText("Are you coming <b>Sunday</b>?")).toBeInTheDocument();
    expect(within(dialog).getByText(/In reply to/)).toBeInTheDocument();
  });

  test("if the original is no longer available the details say so", async () => {
    backend([answer]);
    server.use(http.get("*/api/messages/2", () => HttpResponse.json({ detail: "message not found" }, { status: 404 })));
    await open();
    await userEvent.click(await screen.findByRole("button", { name: "View message 8" }));
    const dialog = await screen.findByRole("dialog", { name: "Message" });
    expect(await within(dialog).findByText("The original message is no longer available.")).toBeInTheDocument();
  });

  test("a received message's details list the replies sent to it", async () => {
    backend([original]);
    server.use(http.get("*/api/messages", ({ request }) => {
      const url = new URL(request.url);
      return HttpResponse.json(page((url.searchParams.get("reply_to_id") === "2" ? [answer] : [original]) as unknown[]));
    }));
    await open();
    await userEvent.click(await screen.findByRole("button", { name: "View message 2" }));
    const dialog = await screen.findByRole("dialog", { name: "Message" });
    expect(await within(dialog).findByText("Yes!")).toBeInTheDocument();
    expect(within(dialog).getByText(/Replies/)).toBeInTheDocument();
  });

  test("a received message without replies shows no replies section", async () => {
    backend([original]);
    server.use(http.get("*/api/messages", ({ request }) => {
      const url = new URL(request.url);
      requests.push(url);
      return HttpResponse.json(page(url.searchParams.get("reply_to_id") ? [] : [original]));
    }));
    await open();
    await userEvent.click(await screen.findByRole("button", { name: "View message 2" }));
    const dialog = await screen.findByRole("dialog", { name: "Message" });
    await waitFor(() => expect(requests.some((u) => u.searchParams.get("reply_to_id") === "2")).toBe(true));
    expect(within(dialog).queryByText(/Replies/)).not.toBeInTheDocument();
  });

  test("a received message's details offer Reply", async () => {
    backend([original]);
    await open();
    await userEvent.click(await screen.findByRole("button", { name: "View message 2" }));
    const details = await screen.findByRole("dialog", { name: "Message" });
    await userEvent.click(within(details).getByRole("button", { name: "Reply" }));
    expect(await screen.findByRole("dialog", { name: "Reply" })).toBeInTheDocument();
  });

  test("details of a sent message have no Reply button", async () => {
    backend([out]);
    await open();
    await userEvent.click(await screen.findByRole("button", { name: "View message 1" }));
    const details = await screen.findByRole("dialog", { name: "Message" });
    expect(within(details).queryByRole("button", { name: "Reply" })).not.toBeInTheDocument();
  });
});

describe("view and delete", () => {
  test("a message can be opened to read all of it", async () => {
    backend([failed]);
    await open();
    await userEvent.click(await screen.findByRole("button", { name: "View message 3" }));
    const dialog = await screen.findByRole("dialog", { name: "Message" });
    expect(within(dialog).getByText("never arrives")).toBeInTheDocument();
    expect(within(dialog).getByText("no signal")).toBeInTheDocument();
    expect(within(dialog).getByText("+639171234567")).toBeInTheDocument();
  });

  test("delete asks first, then removes and refreshes", async () => {
    backend([out]);
    let deleted = false;
    server.use(http.delete("*/api/messages/1", () => ((deleted = true), new HttpResponse(null, { status: 204 }))));
    await open();
    await userEvent.click(await screen.findByRole("button", { name: "Delete message 1" }));
    const dialog = await screen.findByRole("dialog", { name: "Delete message" });
    expect(deleted).toBe(false);
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(deleted).toBe(true));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  test("a refusal is shown in the dialog", async () => {
    backend([out]);
    server.use(http.delete("*/api/messages/1", () => HttpResponse.json({ detail: "message not found" }, { status: 404 })));
    await open();
    await userEvent.click(await screen.findByRole("button", { name: "Delete message 1" }));
    const dialog = await screen.findByRole("dialog");
    await userEvent.click(within(dialog).getByRole("button", { name: "Delete" }));
    expect(await within(dialog).findByRole("alert")).toHaveTextContent("message not found");
  });
});


describe("modem health", () => {
  const device = { id: 1, name: "m1", phone_number: "+639170000000", status: "online", last_error: null, last_error_at: null };
  const devices = (items: unknown[]) => server.use(http.get("*/api/devices", () => HttpResponse.json(items)));

  test("a modem in error is called out with its last error", async () => {
    backend();
    devices([{ ...device, status: "error", last_error: "serial port gone", last_error_at: "2026-11-09T08:00:00" }]);
    await open();
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("m1");
    expect(alert).toHaveTextContent("serial port gone");
  });

  test("an offline modem warns that queued messages will wait", async () => {
    backend();
    devices([{ ...device, status: "offline" }]);
    await open();
    expect(await screen.findByRole("alert")).toHaveTextContent(/offline/i);
  });

  test("healthy modems show nothing, even with an old error on record", async () => {
    backend();
    devices([{ ...device, last_error: "old problem", last_error_at: "2026-11-01T08:00:00" }]);
    await open();
    await screen.findByText("hello Ana");
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  test("people who cannot read every message are not shown (or asked for) modem health", async () => {
    backend();
    let asked = false;
    server.use(http.get("*/api/devices", () => { asked = true; return HttpResponse.json([]); }));
    await open("agent");
    await screen.findByRole("heading", { name: "Messages" });
    expect(asked).toBe(false);
  });
});
