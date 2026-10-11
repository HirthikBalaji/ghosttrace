import { defineConfig } from "@playwright/test";

// Default: starts `vite preview` (proxying /api to the API on :8000, GT_DEMO_TOKEN=dev-demo-token).
// E2E_BASE_URL=http://localhost:8080 runs the same flow against the Docker Compose stack instead.
const external = process.env.E2E_BASE_URL;
export default defineConfig({
  testDir: "e2e",
  timeout: 90_000,
  use: { baseURL: external ?? "http://localhost:4173", viewport: { width: 1440, height: 1000 } },
  webServer: external ? undefined : { command: "npx vite preview --port 4173 --strictPort", port: 4173, reuseExistingServer: true },
  reporter: [["list"]],
});
