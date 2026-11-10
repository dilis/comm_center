import { insertAt, placeholderError, renderPreview } from "./placeholders";

const ANA = { name: "Ana Maria Cruz", first_name: "Ana", last_name: "Cruz" };

describe("renderPreview mirrors what the server will send", () => {
  test.each([
    ["Hello {{name}}!", "Hello Ana Maria Cruz!"],
    ["Hello {{ name }}!", "Hello Ana Maria Cruz!"],
    ["Dear {{first_name}} {{last_name}}", "Dear Ana Cruz"],
    ["{{name}}, {{name}}", "Ana Maria Cruz, Ana Maria Cruz"],
    ["No placeholders", "No placeholders"],
    ["Single {name} braces", "Single {name} braces"],
    ["Unclosed {{name", "Unclosed {{name"],
  ])("%s", (text, expected) => {
    expect(renderPreview(text, ANA)).toBe(expected);
  });

  test("the name is inserted literally", () => {
    expect(renderPreview("Hi {{name}}.", { name: "A$&B $1", first_name: "A$&B" })).toBe("Hi A$&B $1.");
    expect(renderPreview("Hi {{name}}.", { name: "{{name}}", first_name: "{{name}}" })).toBe("Hi {{name}}.");
  });
});

describe("placeholderError", () => {
  test("valid text has no error", () => {
    expect(placeholderError("Hi {{name}} and {{ name }}")).toBeNull();
    expect(placeholderError("plain")).toBeNull();
    expect(placeholderError("{name}")).toBeNull();
  });

  test.each([
    ["Hi {{nam}}", "Unknown placeholder {{nam}}; supported: {{name}}, {{first_name}}, {{last_name}}"],
    ["Hi {{Name}}", "Unknown placeholder {{Name}}; supported: {{name}}, {{first_name}}, {{last_name}}"],
    ["{{a}} {{b}} {{a}}", "Unknown placeholders {{a}}, {{b}}; supported: {{name}}, {{first_name}}, {{last_name}}"],
    ["{{}}", "Unknown placeholder {{}}; supported: {{name}}, {{first_name}}, {{last_name}}"],
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
