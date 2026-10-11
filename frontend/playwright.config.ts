import { defineConfig } from "@playwright/test";

// Expects the API on :8000 (GT_DEMO_TOKEN=dev-demo-token) and FalkorDB running; starts `vite preview` itself.
export default defineConfig({
  testDir: "e2e",
  timeout: 90_000,
  use: { baseURL: "http://localhost:4173", viewport: { width: 1440, height: 1000 } },
  webServer: { command: "npx vite preview --port 4173 --strictPort", port: 4173, reuseExistingServer: true },
  reporter: [["list"]],
});
