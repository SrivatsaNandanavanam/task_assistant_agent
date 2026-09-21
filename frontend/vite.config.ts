import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  test: {
    environment: "jsdom",
    globals: false,
    // Tests assert relative /api/... URLs, so pin the base URL: a VITE_API_BASE_URL exported in the shell,
    // set in a .env file or in CI must not change them. Vitest-only: `vite build` ignores this block, so
    // production builds still read the real VITE_API_BASE_URL.
    env: { VITE_API_BASE_URL: "" },
  },
  server: {
    port: 5173,
    proxy: { "/api": "http://localhost:8000" },
  },
});
