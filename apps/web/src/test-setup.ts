import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";

import { server } from "./test/server";

beforeAll(() => server.listen({ onUnhandledFrame: "error" }));
afterEach(() => {
  cleanup();
  server.resetHandlers();
  localStorage.clear();
});
afterAll(() => server.close());
