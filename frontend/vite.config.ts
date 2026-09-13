import { defineConfig } from "vite";
import { tanstackStart } from "@tanstack/react-start/plugin/vite";
import tailwindcss from "@tailwindcss/vite";
import tsConfigPaths from "vite-tsconfig-paths";
import react from "@vitejs/plugin-react";
import { nitro } from "nitro/vite";

// Standalone TanStack Start config (no @lovable.dev wrapper).
// Replaces what the Lovable wrapper provided for this project:
//   - TanStack Start with SSR server entry (src/server.ts)
//   - Tailwind CSS v4 plugin
//   - tsconfig paths + "@/*" alias
//   - React plugin, dedupe/optimizeDeps defaults
//   - Dev server on port 8080 with /api proxy to the backend
//   - Nitro build (default preset cloudflare-module, same as before)

export default defineConfig(({ command }) => ({
  plugins: [
    tailwindcss(),
    tsConfigPaths({ projects: ["./tsconfig.json"] }),
    tanstackStart({
      importProtection: {
        behavior: "error",
        client: {
          files: ["**/server/**"],
          specifiers: ["server-only"],
        },
      },
      server: { entry: "server" },
    }),
    react(),
    // SSR bundling via Nitro (cloudflare-module default preset), build-only.
    // nitro() returns Plugin[]; spread the whole array into the plugins list.
    ...(command === "build" ? nitro({ defaultPreset: "cloudflare-module" }) : []),
  ],
  resolve: {
    alias: { "@": `${process.cwd()}/src` },
    dedupe: [
      "react",
      "react-dom",
      "react/jsx-runtime",
      "react/jsx-dev-runtime",
      "@tanstack/react-query",
      "@tanstack/query-core",
    ],
  },
  optimizeDeps: {
    include: [
      "react",
      "react-dom",
      "react-dom/client",
      "react/jsx-runtime",
      "react/jsx-dev-runtime",
    ],
    ignoreOutdatedRequests: true,
  },
  server: {
    host: "::",
    port: 8080,
    proxy: {
      "/api": "http://localhost:8000",
    },
    watch: {
      awaitWriteFinish: { stabilityThreshold: 1000, pollInterval: 100 },
    },
  },
}));