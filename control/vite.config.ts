import { defineConfig } from "vitest/config";
export default defineConfig({
  root: ".",
  build: { outDir: "dist/web" },
  server: { proxy: { "/api": "http://127.0.0.1:3770" } },
  test: { include: ["tests/**/*.test.ts"], maxWorkers: 1 },
});
