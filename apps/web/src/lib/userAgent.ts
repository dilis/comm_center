// The first match wins, so a browser comes before the ones it also claims to be (Edge says it is
// Chrome, and Chrome says it is Safari). The same goes for Android, which says it is Linux.
const BROWSERS: [RegExp, string][] = [
  [/Edg(e|A|iOS)?\//, "Edge"],
  [/OPR\//, "Opera"],
  [/SamsungBrowser\//, "Samsung Internet"],
  [/(Firefox|FxiOS)\//, "Firefox"],
  [/(Chrome|CriOS)\//, "Chrome"],
  [/Safari\//, "Safari"],
];
const SYSTEMS: [RegExp, string][] = [
  [/iPhone/, "iPhone"],
  [/iPad/, "iPad"],
  [/Android/, "Android"],
  [/Windows/, "Windows"],
  [/Macintosh/, "Mac"],
  [/CrOS/, "ChromeOS"],
  [/Linux/, "Linux"],
];

/** A short name for the browser behind a user agent, such as "Chrome on Android". What the browser
 *  says about itself is only a hint. One that is not recognized is shown as it is. */
export function describeDevice(userAgent: string | null): string {
  if (!userAgent) return "Unknown device";
  const find = (table: [RegExp, string][]) => table.find(([pattern]) => pattern.test(userAgent))?.[1];
  const browser = find(BROWSERS);
  const system = find(SYSTEMS);
  return browser && system ? `${browser} on ${system}` : userAgent;
}
