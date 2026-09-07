// Desktop (Tauri) build config — SPA-only, no SSR, no nitro.
// The Lovable wrapper still provides TanStack Start + React + aliases;
// we turn off SSR/nitro so it emits plain static assets in dist/.
import { defineConfig } from "@lovable.dev/vite-tanstack-config";

export default defineConfig({
  tanstackStart: {
    // SPA mode: no server entry, no SSR — emit a plain client build.
    server: {},
    spa: { enabled: true },
  },
  nitro: false,
  vite: {
    build: {
      outDir: "dist",
      emptyOutDir: true,
    },
  },
});