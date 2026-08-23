import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
/// <reference types="vitest" />
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  // The desk keeps one `.env` at the repository root, shared by the backend and
  // this app. Vite otherwise looks only in its own root (`frontend/`), finds
  // nothing, and silently serves an empty `import.meta.env` - so every
  // `VITE_*` value reads as undefined and features like push report themselves
  // unconfigured with no error to explain why.
  envDir: "..",
  server: {
    port: 5173,
    // The dashboard calls the API on a relative path, so the backend origin
    // lives in one place instead of being baked into every fetch.
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/test/setup.ts"],
    // The dev server is not running under test; every fetch is stubbed.
    css: false,
  },
});
