/** Placeholders in message text, the browser side of the server's ``app/templating.py``: the
 *  server does the real substitution when it creates each message; this only validates what you
 *  type and previews the result. Keep the two in step (``name`` is the only one for now). */

export const PLACEHOLDERS = ["name"] as const;

const PATTERN = /\{\{\s*([^{}]*?)\s*\}\}/g;
const listed = (names: readonly string[]) => names.map((n) => `{{${n}}}`).join(", ");

export function placeholderError(text: string): string | null {
  const unknown = [...new Set([...text.matchAll(PATTERN)].map((m) => m[1]))].filter(
    (n) => !(PLACEHOLDERS as readonly string[]).includes(n),
  );
  if (unknown.length === 0) return null;
  return `Unknown placeholder${unknown.length > 1 ? "s" : ""} ${listed(unknown)}; supported: ${listed(PLACEHOLDERS)}`;
}

/** The text one recipient will get. The name is inserted literally, never re-expanded. */
export function renderPreview(text: string, name: string): string {
  return text.replace(PATTERN, (whole, key: string) => (key === "name" ? name : whole));
}

/** ``text`` with ``insert`` at the cursor (or replacing the selection), plus the new cursor. */
export function insertAt(text: string, start: number, end: number, insert: string) {
  return { text: text.slice(0, start) + insert + text.slice(end), cursor: start + insert.length };
}
