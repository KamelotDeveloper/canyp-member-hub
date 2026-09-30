import { QueryClient, QueryClientProvider, useQueryClient } from "@tanstack/react-query";
import {
  Outlet,
  Link,
  createRootRouteWithContext,
  useRouter,
  HeadContent,
  Scripts,
} from "@tanstack/react-router";
import { useEffect, useState, type ReactNode } from "react";

import appCss from "../styles.css?url";
import { reportLovableError } from "../lib/lovable-error-reporting";
import { TOKEN_KEY, clearToken, logout } from "../lib/canyp/api";
import { CLIENT_BUILD } from "../lib/canyp/build-flags";
import { useActivacion } from "../lib/canyp/queries";
import { AppShell } from "../components/canyp/AppShell";
import { DataModeWizard } from "../components/canyp/DataModeWizard";
import { LicenseGate } from "../components/canyp/LicenseGate";
import { LoginGate } from "../components/canyp/LoginGate";
import { Toaster } from "../components/ui/sonner";

function NotFoundComponent() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="max-w-md text-center">
        <h1 className="text-7xl font-bold text-foreground">404</h1>
        <h2 className="mt-4 text-xl font-semibold text-foreground">Page not found</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          The page you're looking for doesn't exist or has been moved.
        </p>
        <div className="mt-6">
          <Link
            to="/"
            className="inline-flex items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            Go home
          </Link>
        </div>
      </div>
    </div>
  );
}

function ErrorComponent({ error, reset }: { error: Error; reset: () => void }) {
  console.error(error);
  const router = useRouter();
  useEffect(() => {
    reportLovableError(error, { boundary: "tanstack_root_error_component" });
  }, [error]);

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="max-w-md text-center">
        <h1 className="text-xl font-semibold tracking-tight text-foreground">
          This page didn't load
        </h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Something went wrong on our end. You can try refreshing or head back home.
        </p>
        <div className="mt-6 flex flex-wrap justify-center gap-2">
          <button
            onClick={() => {
              router.invalidate();
              reset();
            }}
            className="inline-flex items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            Try again
          </button>
          <a
            href="/"
            className="inline-flex items-center justify-center rounded-md border border-input bg-background px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-accent"
          >
            Go home
          </a>
        </div>
      </div>
    </div>
  );
}

export const Route = createRootRouteWithContext<{ queryClient: QueryClient }>()({
  head: () => ({
    meta: [
      { charSet: "utf-8" },
      { name: "viewport", content: "width=device-width, initial-scale=1" },
      { title: "CANYP — Sistema de gestión del club" },
      {
        name: "description",
        content:
          "Sistema administrativo del Club Náutico CANYP: socios, membresías, aranceles, pagos y notificaciones.",
      },
      { name: "author", content: "CANYP" },
      { property: "og:title", content: "CANYP — Sistema de gestión del club" },
      {
        property: "og:description",
        content: "Gestión de socios, membresías y pagos de los predios Embalse y Almafuerte.",
      },
      { property: "og:type", content: "website" },
      { name: "twitter:card", content: "summary_large_image" },
      { name: "twitter:site", content: "@Lovable" },
    ],
    links: [
      {
        rel: "stylesheet",
        href: appCss,
      },
      { rel: "icon", href: "/favicon.ico", type: "image/x-icon" },
      {
        rel: "stylesheet",
        href: "https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@400;500;600;700&display=swap",
      },
    ],
  }),
  shellComponent: RootShell,
  component: RootComponent,
  notFoundComponent: NotFoundComponent,
  errorComponent: ErrorComponent,
});

function RootShell({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <head>
        <HeadContent />
      </head>
      <body>
        {children}
        <Scripts />
      </body>
    </html>
  );
}

function RootComponent() {
  const { queryClient } = Route.useRouteContext();

  // After a new deploy, previously loaded pages point at chunk filenames that no
  // longer exist, so lazy route imports fail with a blank screen. Reload once to
  // pick up the fresh asset manifest.
  useEffect(() => {
    // Build de cliente (instalador): no hay hot deploys — un chunk que falte
    // no se cura recargando; el handler solo produciría un loop de reload.
    // En web (dev/host) sí recargar una vez tras un deploy es correcto.
    if (CLIENT_BUILD) return;
    const onPreloadError = (event: Event) => {
      event.preventDefault();
      // Guard con timestamp: permite recargar una vez tras un deploy (el primer
      // intento ya carga el manifest fresco), pero si el fallo persiste NO entra
      // en un loop de reload infinito: espera al menos 10 s entre reintentos.
      const key = "canyp:chunk-reload";
      const lastAttempt = Number(sessionStorage.getItem(key) ?? 0);
      if (Date.now() - lastAttempt < 10_000) return;
      sessionStorage.setItem(key, String(Date.now()));
      window.location.reload();
    };
    window.addEventListener("vite:preloadError", onPreloadError);
    return () => window.removeEventListener("vite:preloadError", onPreloadError);
  }, []);

  return (
    <QueryClientProvider client={queryClient}>
      {/* Bloqueo de seguridad: un build de cliente JAMÁS corre en modo local. */}
      <ClientBuildGuard>
        {/* Wizard de primer uso: aparece solo mientras no haya modo configurado. */}
        <DataModeWizard />
        {/* Licencia (Fase 1): bloquea mientras no haya suscripción/trial activo. */}
        <LicenseGate>
          <AuthGate />
        </LicenseGate>
        {/* Toaster global: LicenseGate/LoginGate disparan toasts pre-login. */}
        <Toaster position="top-right" richColors />
      </ClientBuildGuard>
    </QueryClientProvider>
  );
}

/**
 * Guard de build de cliente: refleja el veredicto del SERVIDOR
 * (GET /api/activacion). Fuera de builds de cliente (dev / web) no hace nada.
 *
 * Antes este guard derivaba el bloqueo de `settings` y sólo tapaba un caso
 * (`configured === true && dataMode === "local"`). El estado `configured:false`
 * —es decir, una instalación nueva, o un `settings.json` escrito a mano— pasaba
 * de largo y la app abría completa sobre una base local vacía. Ahora la
 * pregunta no es "¿qué dice el archivo de ajustes?" sino "¿dice el servidor que
 * esta instalación puede operar?": en un build de cliente, sin base remota
 * provisionada, la respuesta es no.
 *
 * Sigue siendo un ESPEJO. Si esta pantalla mintiera, el backend igual devolvería
 * 503 en cada ruta de dominio (backend/activation.py).
 */
function ClientBuildGuard({ children }: { children: ReactNode }) {
  const { data, isLoading, isError, refetch } = useActivacion();

  if (!CLIENT_BUILD) return <>{children}</>;

  // Todavía no se pudo consultar al servidor: se espera su respuesta. No es
  // una pantalla de bloqueo, es la espera de la primera respuesta.
  if (isLoading) return <>{children}</>;

  // FALLA CERRADO. Sólo un "sí" explícito del servidor libera la app: si la
  // consulta falló o nunca volvió, `data` es undefined y la instalación NO se
  // abre. La versión anterior era `!isError && (...)`, o sea que un error de
  // red soltaba la app entera — el comentario de arriba incluso decía "se
  // espera" mientras el código hacía lo contrario. Aunque el backend igual
  // negaría cada ruta con 503, un espejo que se abre solo es exactamente la
  // clase de bug que esta frontera vino a cerrar.
  const bloqueado = data?.operacionPermitida !== true;

  if (bloqueado) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background px-4">
        <div className="max-w-md text-center">
          <h1 className="text-xl font-semibold tracking-tight text-foreground">
            Esperando activación
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            {isError
              ? "No se pudo contactar al servicio local. Reintente; si el problema continúa, comuníquese con el administrador."
              : (data?.mensaje ??
                "Este equipo todavía no tiene una base de datos provisionada por el administrador. Comuníquese con el administrador.")}
          </p>
          <button
            onClick={() => void refetch()}
            className="mt-6 inline-flex items-center justify-center rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            Reintentar
          </button>
        </div>
      </div>
    );
  }

  return <>{children}</>;
}

/**
 * Login gate (D12): guard inline, sin redirect por ruta. El token vive en
 * localStorage y se lee client-only en un useEffect (SSR-safe: el primer
 * render, en el servidor, es `token === null` → LoginGate).
 */
function AuthGate() {
  const queryClient = useQueryClient();
  const router = useRouter();
  const [token, setToken] = useState<string | null>(null);

  useEffect(() => {
    setToken(window.localStorage.getItem(TOKEN_KEY));
  }, []);

  if (token) {
    return (
      <>
        <AppShell
          onLogout={() => {
            // Cerrar sesión: avisa al backend, limpia el token y vuelve al login.
            void logout();
            clearToken();
            setToken(null);
            queryClient.clear();
          }}
        >
          {/* Required: nested routes render here. Removing <Outlet /> breaks all child routes. */}
          <Outlet />
        </AppShell>
      </>
    );
  }

  return (
    <LoginGate
      onAuthenticated={(newToken) => {
        setToken(newToken);
        // Las rutas montadas esperan datos autenticados; forzar refetch con token.
        queryClient.invalidateQueries();
        router.invalidate();
      }}
    />
  );
}
