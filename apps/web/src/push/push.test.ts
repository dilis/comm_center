import { urlBase64ToBytes } from "./push";

test("a URL-safe base64 key becomes the bytes the browser wants", () => {
  // 0xfb 0xff is "-_8" in URL-safe base64 without padding ("+/8=" in the standard alphabet)
  expect(Array.from(urlBase64ToBytes("-_8"))).toEqual([0xfb, 0xff]);
  expect(Array.from(urlBase64ToBytes("AQID"))).toEqual([1, 2, 3]);
});
