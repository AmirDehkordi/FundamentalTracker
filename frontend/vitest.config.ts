import { fileURLToPath, URL } from "node:url";

import { defineConfig } from "vitest/config";

// Standalone from vite.config.ts on purpose: pure-function unit tests need no react plugin, which keeps
// vitest's bundled Vite types from clashing with the app's Vite. Backend carries coverage; this is a thin
// formatter safety net (see the P7 test cap).
export default defineConfig({
  resolve: {
    alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) },
  },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
