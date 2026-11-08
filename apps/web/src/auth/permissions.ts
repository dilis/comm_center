/** Permissions arrive from ``GET /auth/me`` as ``"resource:action"`` strings. UI gating is
 *  cosmetic: the API enforces every one of these again. */

export type PermissionSet = ReadonlySet<string>;

export const hasPermission = (held: PermissionSet, permission: string) => held.has(permission);

export const canAny = (held: PermissionSet, permissions: string[]) =>
  permissions.some((p) => held.has(p));

export function canReadResource(held: PermissionSet, resource: "messages" | "contacts" | "users" | "logs") {
  const actions = ["read_all", "read_own", ...(resource === "messages" ? ["read_received"] : [])];
  return actions.some((a) => held.has(`${resource}:${a}`));
}

/** True if ``held`` covers every wanted permission. ``read_all`` on a resource also covers its
 *  ``read_own`` and ``read_received`` (the same refinement the API applies when assigning groups). */
export function isSubset(wanted: string[], held: PermissionSet): boolean {
  return wanted.every((permission) => {
    if (held.has(permission)) return true;
    const [resource, action] = permission.split(":");
    return (action === "read_own" || action === "read_received") && held.has(`${resource}:read_all`);
  });
}

/** Whether to offer ``action`` (update/delete) on a row: the caller must hold it and be able to
 *  read that row (``read_all``, or ``read_own`` for rows they own). */
export function canActOnRow(
  held: PermissionSet,
  resource: "messages" | "contacts" | "users",
  action: "update" | "delete",
  ownerId: number,
  myId: number,
): boolean {
  if (!held.has(`${resource}:${action}`)) return false;
  return held.has(`${resource}:read_all`) || (held.has(`${resource}:read_own`) && ownerId === myId);
}

/** Whether to offer Delete on a message: ``messages:delete`` applies to the messages the caller can
 *  read (``read_all``; ``read_own`` and owned; or ``read_received`` and inbound). */
export function canDeleteMessage(
  held: PermissionSet,
  message: { owner_id: number; direction: "inbound" | "outbound" },
  myId: number,
): boolean {
  if (!held.has("messages:delete")) return false;
  return (
    held.has("messages:read_all") ||
    (held.has("messages:read_own") && message.owner_id === myId) ||
    (held.has("messages:read_received") && message.direction === "inbound")
  );
}
