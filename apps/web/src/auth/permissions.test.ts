import { canActOnRow, canAny, canDeleteMessage, canReadResource, hasPermission, isSubset } from "./permissions";

const perms = (...p: string[]) => new Set(p);

test("hasPermission checks one resource:action pair", () => {
  expect(hasPermission(perms("contacts:create"), "contacts:create")).toBe(true);
  expect(hasPermission(perms("contacts:create"), "contacts:delete")).toBe(false);
});

test("canAny is true when any listed permission is held", () => {
  expect(canAny(perms("users:read_all"), ["contacts:read_all", "users:read_all"])).toBe(true);
  expect(canAny(perms(), ["contacts:read_all"])).toBe(false);
});

test("a resource is readable with read_all or read_own; messages also with read_received", () => {
  expect(canReadResource(perms("contacts:read_all"), "contacts")).toBe(true);
  expect(canReadResource(perms("users:read_own"), "users")).toBe(true);
  expect(canReadResource(perms("users:update"), "users")).toBe(false);
  expect(canReadResource(perms("messages:read_received"), "messages")).toBe(true);
  expect(canReadResource(perms("contacts:read_received"), "contacts")).toBe(false);
});

describe("isSubset mirrors the API's escalation rule", () => {
  test("every wanted permission must be held", () => {
    expect(isSubset(["contacts:read_all"], perms("contacts:read_all", "users:read_all"))).toBe(true);
    expect(isSubset(["users:delete"], perms("users:read_all"))).toBe(false);
  });

  test("read_all covers the narrower reads of the same resource only", () => {
    expect(isSubset(["messages:read_own", "messages:read_received"], perms("messages:read_all"))).toBe(true);
    expect(isSubset(["contacts:read_own"], perms("messages:read_all"))).toBe(false);
  });

  test("an empty group is always assignable", () => {
    expect(isSubset([], perms())).toBe(true);
  });
});

describe("canActOnRow follows the API's scope: update and delete apply to rows the caller can read", () => {
  test("with read_all, any row", () => {
    expect(canActOnRow(perms("contacts:read_all", "contacts:update"), "contacts", "update", 9, 1)).toBe(true);
  });
  test("with only read_own, just rows the caller owns", () => {
    const held = perms("contacts:read_own", "contacts:update");
    expect(canActOnRow(held, "contacts", "update", 1, 1)).toBe(true);
    expect(canActOnRow(held, "contacts", "update", 9, 1)).toBe(false);
  });
  test("without the action itself, never", () => {
    expect(canActOnRow(perms("contacts:read_all"), "contacts", "delete", 1, 1)).toBe(false);
  });
});

describe("canDeleteMessage follows message visibility", () => {
  const sent = { owner_id: 1, direction: "outbound" as const };
  const received = { owner_id: 50, direction: "inbound" as const };
  test("needs the delete permission", () => {
    expect(canDeleteMessage(perms("messages:read_all"), sent, 1)).toBe(false);
  });
  test("read_all covers every message", () => {
    const held = perms("messages:read_all", "messages:delete");
    expect(canDeleteMessage(held, sent, 7)).toBe(true);
    expect(canDeleteMessage(held, received, 7)).toBe(true);
  });
  test("read_own covers only messages the caller owns", () => {
    const held = perms("messages:read_own", "messages:delete");
    expect(canDeleteMessage(held, sent, 1)).toBe(true);
    expect(canDeleteMessage(held, sent, 7)).toBe(false);
    expect(canDeleteMessage(held, received, 7)).toBe(false);
  });
  test("read_received covers inbound messages", () => {
    const held = perms("messages:read_received", "messages:delete");
    expect(canDeleteMessage(held, received, 7)).toBe(true);
    expect(canDeleteMessage(held, sent, 1)).toBe(false);
  });
});
