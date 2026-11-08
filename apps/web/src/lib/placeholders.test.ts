import { insertAt, placeholderError, renderPreview } from "./placeholders";

describe("renderPreview mirrors what the server will send", () => {
  test.each([
    ["Hello {{name}}!", "Hello Ana Cruz!"],
    ["Hello {{ name }}!", "Hello Ana Cruz!"],
    ["{{name}}, {{name}}", "Ana Cruz, Ana Cruz"],
    ["No placeholders", "No placeholders"],
    ["Single {name} braces", "Single {name} braces"],
    ["Unclosed {{name", "Unclosed {{name"],
  ])("%s", (text, expected) => {
    expect(renderPreview(text, "Ana Cruz")).toBe(expected);
  });

  test("the name is inserted literally", () => {
    expect(renderPreview("Hi {{name}}.", "A$&B $1")).toBe("Hi A$&B $1.");
    expect(renderPreview("Hi {{name}}.", "{{name}}")).toBe("Hi {{name}}.");
  });
});

describe("placeholderError", () => {
  test("valid text has no error", () => {
    expect(placeholderError("Hi {{name}} and {{ name }}")).toBeNull();
    expect(placeholderError("plain")).toBeNull();
    expect(placeholderError("{name}")).toBeNull();
  });

  test.each([
    ["Hi {{nam}}", "Unknown placeholder {{nam}}; supported: {{name}}"],
    ["Hi {{Name}}", "Unknown placeholder {{Name}}; supported: {{name}}"],
    ["{{a}} {{b}} {{a}}", "Unknown placeholders {{a}}, {{b}}; supported: {{name}}"],
    ["{{}}", "Unknown placeholder {{}}; supported: {{name}}"],
  ])("%s", (text, message) => {
    expect(placeholderError(text)).toBe(message);
  });
});

describe("insertAt", () => {
  test("inserts at the cursor and says where the cursor goes", () => {
    expect(insertAt("Hello !", 6, 6, "{{name}}")).toEqual({ text: "Hello {{name}}!", cursor: 14 });
  });
  test("replaces a selection", () => {
    expect(insertAt("Hello XXX!", 6, 9, "{{name}}")).toEqual({ text: "Hello {{name}}!", cursor: 14 });
  });
  test("works on empty text", () => {
    expect(insertAt("", 0, 0, "{{name}}")).toEqual({ text: "{{name}}", cursor: 8 });
  });
});
