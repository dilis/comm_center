/** True when the browser can open the system share sheet (needs HTTPS; Android and iOS browsers, some desktops). */
export const canShare = () => typeof navigator !== "undefined" && typeof navigator.share === "function";

/** Open the share sheet with `text`. Must be called from a click. Returns false if the user dismissed it or it failed. */
export async function shareText(text: string): Promise<boolean> {
  if (!canShare()) return false;
  try {
    await navigator.share({ text });
    return true;
  } catch {
    return false; // AbortError when the sheet is closed, or the share failed
  }
}
