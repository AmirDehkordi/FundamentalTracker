import { fileURLToPath, URL } from "node:url";

import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The backend CORS allowlist is exactly http://localhost:5173 and the prod build is served same-origin
// by FastAPI, so the app only ever calls relative /api. strictPort keeps us on 5173 (a silent fall to
// 5174 would be a cross-origin the backend rejects); the dev proxy forwards /api to the API server.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": { target: "http://localhost:8000", changeOrigin: true },
    },
  },
  build: {
    target: "es2020",
  },
});
