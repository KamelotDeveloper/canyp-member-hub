// Desktop (Tauri) build config — SPA-only, no SSR, no nitro.
// Standalone TanStack Start config: no SSR entry, no nitro — plain static build.
import { defineConfig, type Plugin } from "vite";
import { tanstackStart } from "@tanstack/react-start/plugin/vite";
import tailwindcss from "@tailwindcss/vite";
import tsConfigPaths from "vite-tsconfig-paths";
import react from "@vitejs/plugin-react";

export default defineConfig({
  // Packaged client builds (Tauri) never run in local data mode: the flag is
  // baked in here because this config is ONLY used by `pnpm build:desktop`.
  // Dev builds (vite.config.ts) leave it undefined -> CLIENT_BUILD === false.
  define: {
    __CLIENT_BUILD__: JSON.stringify(true),
    __DATABASE_URL__: JSON.stringify(process.env.CANYP_DATABASE_URL ?? ""),
  },
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
      // SPA mode: no server entry, no SSR — emit a plain client build.
      server: {},
      spa: { enabled: true },
    }),
    react(),
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
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
