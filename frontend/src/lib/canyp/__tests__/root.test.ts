/**
 * Compile-time + runtime test for PR 3 cleanup, STEP 3:
 * `__root.tsx` must NOT wrap the app in <CanypProvider> anymore.
 *
 * RED:   Fails while __root.tsx still imports/uses CanypProvider (source contains
 *        the identifier). `pnpm tsc --noEmit` also fails because the type-only
 *        import of `Route` from the (still-broken) module won't resolve once the
 *        provider import is removed incorrectly.
 * GREEN: After removing the CanypProvider import + wrapper (keeping
 *        QueryClientProvider), the source no longer references CanypProvider and
 *        the module still exports a valid `Route`.
 *
 * Type-only import keeps this file out of the app runtime graph (avoids pulling
 * CSS `?url` imports through tsx), while the fs check gives genuine runtime RED.
 */

import type { Route } from "../../../routes/__root";
import { existsSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

// Compile-time: the module still exports a Route object after the edit.
type HasRoute = typeof Route extends { options: unknown } ? true : false;
const _routeCheck: HasRoute = true;
void _routeCheck;

function assert(cond: boolean, msg: string) {
  if (!cond) throw new Error(`root.test failed: ${msg}`);
}

const here = dirname(fileURLToPath(import.meta.url));
const rootPath = join(here, "../../../routes/__root.tsx");
const rootSrc = readFileSync(rootPath, "utf8");

assert(!rootSrc.includes("CanypProvider"), "__root.tsx must not reference CanypProvider");
assert(
  rootSrc.includes("QueryClientProvider"),
  "__root.tsx must keep QueryClientProvider for TanStack Query",
);

console.log("root.test: OK — __root.tsx renders without CanypProvider");
