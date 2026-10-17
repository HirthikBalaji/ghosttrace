import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: { port: 5174, proxy: { "/api": "http://localhost:8000", "/ready": "http://localhost:8000", "/health": "http://localhost:8000" } },
  preview: { port: 4173, proxy: { "/api": "http://localhost:8000", "/ready": "http://localhost:8000", "/health": "http://localhost:8000" } },
});
