import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export const cn = (...inputs: ClassValue[]) => twMerge(clsx(inputs));

export function formatDateTime(value: string | null | undefined): string {
  if (!value) return "";
  // The API sends naive UTC timestamps; mark them as UTC before converting to local time.
  const iso = /[zZ]|[+-]\d\d:?\d\d$/.test(value) ? value : `${value}Z`;
  return new Date(iso).toLocaleString();
}
