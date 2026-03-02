import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vitest/config";

const cspPolicy =
  "default-src 'self'; " +
  "script-src 'self' 'unsafe-inline'; " +
  "style-src 'self' 'unsafe-inline'; " +
  "img-src 'self' data: blob:; " +
  "font-src 'self' data:; " +
  "connect-src 'self' http://localhost:8000 ws: wss:; " +
  "frame-ancestors 'none'; base-uri 'self'; form-action 'self'";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    headers: {
      "Content-Security-Policy": cspPolicy,
      "X-Content-Type-Options": "nosniff",
      "X-Frame-Options": "DENY"
    }
  },
  preview: {
    headers: {
      "Content-Security-Policy": cspPolicy,
      "X-Content-Type-Options": "nosniff",
      "X-Frame-Options": "DENY"
    }
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts"
  }
});
