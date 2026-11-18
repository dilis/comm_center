import { vi } from "vitest";

/** A stand-in for the browser's push stack (service worker, PushManager, Notification). */
export type FakeSubscription = {
  endpoint: string;
  toJSON: () => { endpoint: string; keys: { p256dh: string; auth: string } };
  unsubscribe: ReturnType<typeof vi.fn>;
};

export function fakeSubscription(n = 1): FakeSubscription {
  const endpoint = `https://push.example.com/send/${n}`;
  return {
    endpoint,
    toJSON: () => ({ endpoint, keys: { p256dh: `key${n}`, auth: `auth${n}` } }),
    unsubscribe: vi.fn(async () => true),
  };
}

type Options = {
  permission?: NotificationPermission;
  /** What the permission prompt answers. */
  prompt?: NotificationPermission;
  subscription?: FakeSubscription | null;
};

const globals = ["PushManager", "Notification"] as const;

export function installPush({ permission = "default", prompt = "granted", subscription = null }: Options = {}) {
  let current: FakeSubscription | null = null;
  // Unsubscribing really removes it, as a browser does.
  const hold = (sub: FakeSubscription) => {
    sub.unsubscribe = vi.fn(async () => {
      current = null;
      return true;
    });
    return (current = sub);
  };
  if (subscription) hold(subscription);
  const pushManager = {
    getSubscription: vi.fn(async () => current),
    subscribe: vi.fn(async (_options: { userVisibleOnly: boolean; applicationServerKey: Uint8Array }) => hold(fakeSubscription())),
  };
  const requestPermission = vi.fn(async () => prompt);
  Object.defineProperty(navigator, "serviceWorker", {
    configurable: true,
    value: { ready: Promise.resolve({ pushManager }), register: vi.fn(async () => ({})) },
  });
  Object.defineProperty(window, "PushManager", { configurable: true, value: class {} });
  Object.defineProperty(window, "Notification", {
    configurable: true,
    value: Object.assign(function Notification() {}, { permission, requestPermission }),
  });
  return { pushManager, requestPermission, current: () => current };
}

export function uninstallPush() {
  // @ts-expect-error: removing what installPush added
  delete navigator.serviceWorker;
  for (const name of globals) delete (window as unknown as Record<string, unknown>)[name];
}
