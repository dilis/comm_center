/** Web Push in the browser: registering the service worker and (un)subscribing this device. */
import { api, unwrap } from "@/api/client";

export function urlBase64ToBytes(value: string): Uint8Array<ArrayBuffer> {
  const padded = (value + "=".repeat((4 - (value.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(padded);
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

export function pushSupported(): boolean {
  return "serviceWorker" in navigator && "PushManager" in window && "Notification" in window;
}

export const permission = (): NotificationPermission => Notification.permission;

/** Start the service worker. Without it nothing can be pushed; failures only mean no push. */
export function registerServiceWorker(): void {
  if (!("serviceWorker" in navigator)) return;
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}

async function pushManager(): Promise<PushManager> {
  return (await navigator.serviceWorker.ready).pushManager;
}

/** This browser's subscription, if it has one. */
export async function browserSubscription(): Promise<PushSubscription | null> {
  if (!pushSupported()) return null;
  return (await pushManager()).getSubscription();
}

export class PermissionRefused extends Error {
  constructor() {
    super("Notifications were not allowed. You can allow them in your browser's settings.");
  }
}

function keysOf(subscription: PushSubscription) {
  const { endpoint, keys } = subscription.toJSON();
  return { endpoint: endpoint as string, keys: { p256dh: keys?.p256dh ?? "", auth: keys?.auth ?? "" } };
}

/** Ask permission, subscribe this browser and tell the server. If the server refuses, the browser
 * subscription is undone, so the two never disagree. */
export async function turnOn(publicKey: string): Promise<void> {
  if ((await Notification.requestPermission()) !== "granted") throw new PermissionRefused();
  const manager = await pushManager();
  const subscription =
    (await manager.getSubscription()) ??
    (await manager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToBytes(publicKey) }));
  try {
    await unwrap(api.PUT("/auth/me/push", { body: keysOf(subscription) }));
  } catch (error) {
    await subscription.unsubscribe().catch(() => {});
    throw error;
  }
}

/** Tell the server to stop, then drop the browser subscription. */
export async function turnOff(): Promise<void> {
  const subscription = await browserSubscription();
  if (!subscription) return;
  await unwrap(api.DELETE("/auth/me/push", { body: { endpoint: subscription.endpoint } }));
  await subscription.unsubscribe();
}

/** On sign-out: this browser stops notifying the person who just left, whatever goes wrong. The
 * next person on a shared device starts with notifications off. */
export async function dropForSignOut(): Promise<void> {
  try {
    const subscription = await browserSubscription();
    if (!subscription) return;
    await api.DELETE("/auth/me/push", { body: { endpoint: subscription.endpoint } }).catch(() => {});
    await subscription.unsubscribe();
  } catch {
    // signing out must never wait on, or fail because of, push
  }
}

/** The session was ended from outside (signed out elsewhere, or refused): only the browser's side
 * is left to undo, since there is no access token and the server has dropped its own side. */
export async function forgetSubscription(): Promise<void> {
  try {
    await (await browserSubscription())?.unsubscribe();
  } catch {
    // nothing to do: the next sign-in shows the switch as the browser has it
  }
}
