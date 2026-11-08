import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export const cn = (...inputs: ClassValue[]) => twMerge(clsx(inputs));

// The API sends naive UTC timestamps; mark them as UTC before converting to local time.
const toDate = (value: string) => new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(value) ? value : `${value}Z`);

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "";
  return toDate(value).toLocaleString();
}

const plural = (n: number, unit: string) => `${n} ${unit}${n === 1 ? "" : "s"} ago`;

/** "5 minutes ago", "yesterday", then a plain date after a week. For lists, where scanning matters
 *  more than precision; show ``formatDateTime`` (or put it in a tooltip) where the exact time does.
 *  A time a little ahead of ``now`` (clock skew between server and browser) reads "just now". */
export function formatRelative(value: string | null | undefined, now: number = Date.now()): string {
  if (!value) return "";
  const then = toDate(value).getTime();
  const elapsed = now - then;
  if (elapsed < -5 * 60_000) return formatDateTime(value); // genuinely in the future
  const minutes = Math.floor(elapsed / 60_000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return plural(minutes, "minute");
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return plural(hours, "hour");
  const days = Math.floor(hours / 24);
  if (days === 1) return "yesterday";
  if (days < 7) return plural(days, "day");
  return new Date(then).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" });
}
