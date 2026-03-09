import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { defineConfig } from "vitest/config";

const apiBaseUrl = process.env.VITE_API_BASE_URL ?? "http://localhost:8000";
const apiOrigin = (() => {
  try {
    return new URL(apiBaseUrl).origin;
  } catch {
    return "http://localhost:8000";
  }
})();

const cspPolicy =
  "default-src 'self'; " +
  "script-src 'self' 'unsafe-inline'; " +
  "style-src 'self' 'unsafe-inline'; " +
  "img-src 'self' data: blob:; " +
  "font-src 'self' data:; " +
  `connect-src 'self' ${apiOrigin} https://*.run.app ws: wss:; ` +
  "frame-ancestors 'none'; base-uri 'self'; form-action 'self'";

const allowedHosts = ["localhost", "127.0.0.1", ".run.app", "centracortex.com", ".centracortex.com"];

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    allowedHosts,
    headers: {
      "Cache-Control": "no-store",
      "Content-Security-Policy": cspPolicy,
      "X-Content-Type-Options": "nosniff",
      "X-Frame-Options": "DENY"
    }
  },
  preview: {
    allowedHosts,
    headers: {
      "Cache-Control": "no-store",
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
