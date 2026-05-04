import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";

// Bind workspace package names to their source roots so tests never
// silently bind to a stale `dist/` build (which is gitignored and
// rebuilt out-of-band by `pnpm build`).
const fromHere = (rel: string) =>
  fileURLToPath(new URL(rel, import.meta.url));

export default defineConfig({
  resolve: {
    alias: {
      "@ariaflow/core": fromHere("./packages/core/src/index.ts"),
      "@ariaflow/api": fromHere("./packages/api/src/index.ts"),
    },
  },
  test: {
    include: ["packages/*/src/**/*.test.ts"],
    environment: "node",
  },
});
