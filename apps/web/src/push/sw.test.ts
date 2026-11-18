import source from "../../public/sw.js?raw";

type Listener = (event: unknown) => void;

function loadWorker(windows: { url: string; focus: () => Promise<unknown>; navigate?: (u: string) => Promise<unknown> }[] = []) {
  const listeners: Record<string, Listener> = {};
  const self = {
    addEventListener: (type: string, fn: Listener) => (listeners[type] = fn),
    registration: { showNotification: vi.fn(async () => {}) },
    clients: { matchAll: vi.fn(async () => windows), openWindow: vi.fn(async () => ({})), claim: vi.fn(async () => {}) },
    location: { origin: "https://app.example.com" },
    skipWaiting: vi.fn(),
  };
  new Function("self", source)(self);
  return { self, listeners };
}

/** Run a handler and wait for whatever it passed to waitUntil. */
async function fire(listener: Listener, event: Record<string, unknown>) {
  let pending: Promise<unknown> = Promise.resolve();
  await listener({ ...event, waitUntil: (p: Promise<unknown>) => (pending = p) });
  await pending;
}

const pushOf = (data: unknown) => ({ data: { json: () => data } });

test("a push shows a notification with the title, body and tag it carries", async () => {
  const { self, listeners } = loadWorker();
  await fire(listeners.push, pushOf({ title: "New message", body: "From Maria", url: "/messages?direction=received", tag: "message-7" }));
  expect(self.registration.showNotification).toHaveBeenCalledWith(
    "New message",
    expect.objectContaining({ body: "From Maria", tag: "message-7", data: { url: "/messages?direction=received" } }),
  );
});

test("a push that is not JSON still shows something, never nothing", async () => {
  // A browser that receives a push and shows nothing may revoke the permission.
  const { self, listeners } = loadWorker();
  await fire(listeners.push, { data: { json: () => { throw new SyntaxError("bad"); } } });
  await fire(listeners.push, { data: null });
  expect(self.registration.showNotification).toHaveBeenCalledTimes(2);
  expect(self.registration.showNotification).toHaveBeenLastCalledWith("New message", expect.objectContaining({ data: { url: "/" } }));
});

test("a link to another site is replaced by the app's own home", async () => {
  const { self, listeners } = loadWorker();
  await fire(listeners.push, pushOf({ title: "t", url: "https://evil.example.org/x" }));
  expect(self.registration.showNotification).toHaveBeenCalledWith("t", expect.objectContaining({ data: { url: "/" } }));
});

test("clicking closes the notification and opens the app when no window is open", async () => {
  const { self, listeners } = loadWorker([]);
  const close = vi.fn();
  await fire(listeners.notificationclick, { notification: { close, data: { url: "/messages?direction=received" } } });
  expect(close).toHaveBeenCalled();
  expect(self.clients.openWindow).toHaveBeenCalledWith("/messages?direction=received");
});

test("clicking focuses a window that is already open and takes it to the messages", async () => {
  const focus = vi.fn(async () => {});
  const navigate = vi.fn(async () => {});
  const { self, listeners } = loadWorker([{ url: "https://app.example.com/contacts", focus, navigate }]);
  await fire(listeners.notificationclick, { notification: { close: vi.fn(), data: { url: "/messages?direction=received" } } });
  expect(focus).toHaveBeenCalled();
  expect(navigate).toHaveBeenCalledWith("/messages?direction=received");
  expect(self.clients.openWindow).not.toHaveBeenCalled();
});

test("clicking ignores windows of other origins", async () => {
  const other = { url: "https://elsewhere.example.org/", focus: vi.fn(async () => {}), navigate: vi.fn(async () => {}) };
  const { self, listeners } = loadWorker([other]);
  await fire(listeners.notificationclick, { notification: { close: vi.fn(), data: { url: "/" } } });
  expect(other.focus).not.toHaveBeenCalled();
  expect(self.clients.openWindow).toHaveBeenCalledWith("/");
});

test("a new version takes over at once", async () => {
  const { self, listeners } = loadWorker();
  await fire(listeners.install, {});
  expect(self.skipWaiting).toHaveBeenCalled();
  await fire(listeners.activate, {});
  expect(self.clients.claim).toHaveBeenCalled();
});
