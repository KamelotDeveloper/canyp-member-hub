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
import { it } from "vitest";

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

it("__root.tsx must not reference CanypProvider", () => {
  assert(!rootSrc.includes("CanypProvider"), "__root.tsx must not reference CanypProvider");
});

it("__root.tsx keeps QueryClientProvider for TanStack Query", () => {
  assert(
    rootSrc.includes("QueryClientProvider"),
    "__root.tsx must keep QueryClientProvider for TanStack Query",
  );
});

// ---------------------------------------------------------------------------
// BYPASS 2: el guard de build de cliente NO puede decidir por su cuenta.
//
// Éste se verifica por fuente y no renderizando el componente, porque
// `__root.tsx` importa `styles.css?url` y eso no resuelve fuera del pipeline de
// Vite (mismo motivo por el que este archivo no importa `Route` en runtime).
// Lo que importa acá es una invariante de código: el guard tiene que LEER el
// veredicto del servidor, no derivarlo de `settings`.
// ---------------------------------------------------------------------------

it("ClientBuildGuard lee el veredicto del servidor, no los settings", () => {
  assert(
    rootSrc.includes("useActivacion"),
    "ClientBuildGuard debe consultar GET /api/activacion (useActivacion)",
  );
  assert(
    !rootSrc.includes("data?.configured === true"),
    "ClientBuildGuard no puede derivar el bloqueo de `configured`: ese era el bypass 2",
  );
  assert(
    rootSrc.includes("operacionPermitida"),
    "ClientBuildGuard debe bloquear cuando el servidor dice operacionPermitida === false",
  );
});

it("ClientBuildGuard muestra el mensaje del servidor al bloquear", () => {
  assert(
    rootSrc.includes("Esperando activación"),
    "El estado bloqueado es 'esperando activación', no una app vacía",
  );
  assert(
    rootSrc.includes("data?.mensaje"),
    "El mensaje explicativo lo aporta el servidor (GET /api/activacion)",
  );
});

it("ClientBuildGuard falla CERRADO: sólo un sí explícito abre la app", () => {
  // Un error de red o una respuesta perdida NO pueden soltar la app. La
  // versión anterior escribía `!isError && (...)`, que fail-OPEN: con el
  // sidecar caído, el guard renderizaba los children y el usuario veía la app
  // completa (con cada ruta fallando por 503) en vez de un mensaje de estado.
  assert(
    rootSrc.includes("data?.operacionPermitida !== true"),
    "El bloqueo debe derivarse de la ausencia de un veredicto positivo, no de la presencia de un error",
  );
  assert(
    !/const\s+bloqueado\s*=\s*!isError/.test(rootSrc),
    "Un error de red no puede liberar la app: es un fail-open del espejo",
  );
});

it("el mensaje de error de red no afirma que falte la base del administrador", () => {
  // Con el guard fail-closed, un sidecar caído caería en el mensaje por defecto
  // ("no tiene una base provisionada"), que sería una falsehood: manda a
  // soporte a buscar un problema de licencia que no existe.
  assert(
    /isError[\s\S]{0,400}No se pudo contactar/.test(rootSrc),
    "Un fallo de conexión debe decir que no se pudo contactar al servicio local",
  );
});

it("__root.tsx monta el DataModeWizard y el LicenseGate dentro del guard", () => {
  // El orden importa: si el wizard o el gate colgaran del guard, la pantalla
  // de activación quedaría detrás de ellos.
  const iGuard = rootSrc.indexOf("<ClientBuildGuard>");
  const iWizard = rootSrc.indexOf("<DataModeWizard />");
  const iLicense = rootSrc.indexOf("<LicenseGate>");
  assert(iGuard !== -1 && iWizard !== -1 && iLicense !== -1, "faltan los guards en __root.tsx");
  assert(iGuard < iWizard, "ClientBuildGuard debe envolver al DataModeWizard");
  assert(iWizard < iLicense, "DataModeWizard debe montar antes que LicenseGate");
});
