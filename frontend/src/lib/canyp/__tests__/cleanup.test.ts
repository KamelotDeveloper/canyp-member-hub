/**
 * Compile-time + runtime test for PR 3 cleanup, STEP 4:
 * `store.tsx` and `data.ts` must be deleted and no file may import from them.
 * Also covers STEP 2 (all route/component imports repointed to `@/lib/canyp/utils`).
 *
 * RED:   Fails while store.tsx / data.ts still exist, or while any source file
 *        still imports from `canyp/store` or `canyp/data`.
 * GREEN: After deleting both files and repointing imports, this passes.
 *
 * Uses fs to scan the source tree so it works at runtime under tsx (no app
 * module graph loaded). The `@/` alias imports are checked as plain strings.
 */

import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

function assert(cond: boolean, msg: string) {
  if (!cond) throw new Error(`cleanup.test failed: ${msg}`);
}

const here = dirname(fileURLToPath(import.meta.url));
const libCanyp = join(here, "..");
const storePath = join(libCanyp, "store.tsx");
const dataPath = join(libCanyp, "data.ts");

assert(!existsSync(storePath), "store.tsx must be deleted");
assert(!existsSync(dataPath), "data.ts must be deleted");

// Walk src/ and collect every file that still imports from canyp/store or canyp/data.
const srcRoot = join(libCanyp, "..", ".."); // src/
const badImports: string[] = [];
const importRe = /from\s+["']([^"']*(?:canyp\/store|canyp\/data))["']/;

function walk(dir: string) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    const st = statSync(full);
    if (st.isDirectory()) {
      if (entry === "node_modules" || entry.startsWith(".git")) continue;
      walk(full);
    } else if (full.endsWith(".ts") || full.endsWith(".tsx")) {
      const src = readFileSync(full, "utf8");
      if (importRe.test(src)) badImports.push(full);
    }
  }
}
walk(srcRoot);

assert(
  badImports.length === 0,
  `no imports from canyp/store or canyp/data allowed, found in: ${badImports.join(", ")}`,
);

console.log("cleanup.test: OK — store/data deleted, no stale imports remain");
