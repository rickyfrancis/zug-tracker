import { defineConfig } from "vitest/config";

// Unit tests cover the framework-free modules in src/lib. They need no DOM:
// the map itself is WebGL and is checked in a browser, not here.
export default defineConfig({
  resolve: { tsconfigPaths: true },
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
  },
});
