/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The browser only ever talks to its own origin under /api; this proxy (and nginx in the web
// image) forwards it to the API, so there is no CORS and the CSP can say connect-src 'self'.
const proxy = {
  "/api": {
    target: process.env.API_PROXY_TARGET ?? "http://127.0.0.1:8000",
    rewrite: (path: string) => path.replace(/^\/api/, ""),
  },
};

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { "@": "/src" } },
  server: { proxy },
  preview: { proxy },
  test: {
    environment: "happy-dom",
    globals: true,
    setupFiles: ["./src/test-setup.ts"],
    css: false,
  },
});
