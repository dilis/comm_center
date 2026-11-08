import { formatDateTime, formatRelative } from "./utils";

const NOW = new Date("2026-11-09T12:00:00Z").getTime();
const ago = (ms: number) => new Date(NOW - ms).toISOString().replace("Z", ""); // the API sends naive UTC
const S = 1000, M = 60 * S, H = 60 * M, D = 24 * H;

describe("formatRelative", () => {
  test.each([
    [5 * S, "just now"],
    [59 * S, "just now"],
    [60 * S, "1 minute ago"],
    [5 * M, "5 minutes ago"],
    [59 * M, "59 minutes ago"],
    [60 * M, "1 hour ago"],
    [3 * H, "3 hours ago"],
    [23 * H, "23 hours ago"],
    [24 * H, "yesterday"],
    [47 * H, "yesterday"],
    [2 * D, "2 days ago"],
    [6 * D, "6 days ago"],
  ])("%i ms ago reads %s", (elapsed, expected) => {
    expect(formatRelative(ago(elapsed), NOW)).toBe(expected);
  });

  test("a week or more ago falls back to the date", () => {
    const text = formatRelative(ago(8 * D), NOW);
    expect(text).toBe(new Date(NOW - 8 * D).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }));
  });

  test("a time slightly in the future (clock skew) is just now; further ahead is the full time", () => {
    expect(formatRelative(new Date(NOW + 20 * S).toISOString(), NOW)).toBe("just now");
    expect(formatRelative(new Date(NOW + 3 * H).toISOString(), NOW)).toBe(formatDateTime(new Date(NOW + 3 * H).toISOString()));
  });

  test("nothing in, nothing out", () => {
    expect(formatRelative(null, NOW)).toBe("");
    expect(formatRelative(undefined, NOW)).toBe("");
  });
});
