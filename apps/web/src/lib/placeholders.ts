/** Placeholders in message text, the browser side of the server's ``app/templating.py``: the
 *  server does the real substitution when it creates each message; this only validates what you
 *  type and previews the result. Keep the two in step (``name`` is the full name; ``first_name`` and ``last_name`` its parts). */

export const PLACEHOLDERS = ["name", "first_name", "last_name"] as const;

/** What a recipient's placeholders become (``last_name`` is null when they have none). */
export type Recipient = { name: string; first_name: string; last_name?: string | null };

const PATTERN = /\{\{\s*([^{}]*?)\s*\}\}/g;
const listed = (names: readonly string[]) => names.map((n) => `{{${n}}}`).join(", ");

export function placeholderError(text: string): string | null {
  const unknown = [...new Set([...text.matchAll(PATTERN)].map((m) => m[1]))].filter(
    (n) => !(PLACEHOLDERS as readonly string[]).includes(n),
  );
  if (unknown.length === 0) return null;
  return `Unknown placeholder${unknown.length > 1 ? "s" : ""} ${listed(unknown)}; supported: ${listed(PLACEHOLDERS)}`;
}

/** The text one recipient will get. Names are inserted literally, never re-expanded. */
export function renderPreview(text: string, who: Recipient): string {
  const values: Record<string, string> = { name: who.name, first_name: who.first_name, last_name: who.last_name ?? "" };
  return text.replace(PATTERN, (whole, key: string) => (Object.hasOwn(values, key) ? values[key] : whole));
}

/** ``text`` with ``insert`` at the cursor (or replacing the selection), plus the new cursor. */
export function insertAt(text: string, start: number, end: number, insert: string) {
  return { text: text.slice(0, start) + insert + text.slice(end), cursor: start + insert.length };
}
