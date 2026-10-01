import { Loader2 } from "lucide-react";
import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ApiError } from "@/lib/canyp/api";
import { CLIENT_BUILD } from "@/lib/canyp/build-flags";
import { useLicencia, useSettings } from "@/lib/canyp/queries";
import {
  activarTrial,
  crearPreferencia,
  esperarConfirmacionPreferencia,
  getClientId,
  obtenerPlanes,
  type PlanInfo,
} from "@/lib/canyp/suscripcion";
import { guardarPagoPendiente, leerPagoPendiente, limpiarPagoPendiente } from "./pago-pendiente";

/**
 * Gate de licencia (Fase 1): bloquea la app hasta que la instalación tenga una
 * suscripción activa (MercadoPago) o un trial local de 7 días.
 *
 * Reglas:
 * - Sistema sin configurar (`configured: false`): passthrough — el
 *   DataModeWizard de primer uso manda.
 * - Configurado: verifica la licencia vía /api/suscripcion/verificar.
 *   - Activa → passthrough (deja entrar a AuthGate/login).
 *   - Sin licencia → pantalla de planes (comprar o trial).
 *   - Servidor no responde → pantalla amigable con reintentar (el sidecar
 *     local puede tardar en arrancar).
 *
 * En un BUILD DE CLIENTE el passthrough de "sin configurar" ya no aplica: sin
 * settings no hay base remota provisionada, y sin base remota la instalación
 * no puede operar (lo decide backend/activation.py, no este componente). La
 * diferencia es deliberada: en dev el asistente de primer uso tiene que poder
 * correr, y en un build distribuido ese mismo estado es justamente el bypass
 * —un `settings.json` con `configured:false` abría la app completa sin licencia.
 * El ClientBuildGuard de __root.tsx cubre ese estado con el mensaje del
 * servidor; acá sólo evitamos que, aun con la pantalla de planes, se cuelgue el
 * children por debajo.
 */
export function LicenseGate({ children }: { children: ReactNode }) {
  const { data: settings, error: settingsError, isLoading: settingsLoading } = useSettings();
  const settingsUnauthorized = settingsError instanceof ApiError && settingsError.status === 401;
  const configured = settings?.configured === true || settingsUnauthorized;

  const clientId = useRef(getClientId()).current;
  const licencia = useLicencia(clientId);
  // La query cacheada evita el loop de "Verificando licencia…": antes, cada
  // remount cancelaba la promesa previa (cleanup `cancelled`) y el estado
  // quedaba clavado en "checking". Ahora el veredicto se sirve de cache.
  const state: LicenciaState = licencia.isLoading
    ? "checking"
    : licencia.isError
      ? "unavailable"
      : licencia.data?.ok || licencia.data?.activo
        ? "ok"
        : "blocked";

  useResolverPagoPendiente(clientId);

  // Sólo el build de cliente pierde el atajo de "sin configurar". El trial
  // tampoco existe ahí (lo rechaza el backend), así que la pantalla de planes
  // de abajo es la de desarrollo: en un cliente sin activar se muestra
  // primero el "Esperando activación" del ClientBuildGuard.
  if (CLIENT_BUILD) {
    return (
      <>{state === "ok" ? children : <LicenseUI onLicensed={() => void licencia.refetch()} />}</>
    );
  }

  if (!configured || settingsLoading) return <>{children}</>;

  if (state === "ok") return <>{children}</>;

  if (state === "checking") {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center gap-3 bg-background">
        <Loader2 className="size-6 animate-spin text-muted-foreground" />
        <p className="text-sm text-muted-foreground">Verificando licencia…</p>
      </div>
    );
  }

  if (state === "unavailable") {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background px-4">
        <Card className="w-full max-w-sm">
          <CardHeader className="text-center">
            <img
              src="/CANYP_Almafuerte_logo.svg?v=3"
              alt="CANYP logo"
              className="mx-auto mb-3 size-16 object-contain"
            />
            <CardTitle>No se pudo conectar</CardTitle>
            <CardDescription>
              El servidor local no respondió. Verificá que CANYP esté corriendo e intentá de nuevo.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button className="w-full" onClick={() => void licencia.refetch()}>
              Reintentar
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return <LicenseUI onLicensed={() => void licencia.refetch()} />;
}

type LicenciaState = "checking" | "ok" | "blocked" | "unavailable";

/**
 * Retoma un pago que quedó a medio camino.
 *
 * El usuario paga en el navegador externo y vuelve a la app a mano. Cuando
 * vuelve, esta hook intenta cerrar el pago con el `preference_id` que quedó
 * guardado y, si se activa, revalida la licencia para dejar entrar.
 *
 * Se dispara en dos momentos a propósito:
 * - al montar, para el caso de que la app se haya reiniciado o el usuario
 *   vuelve por el ícono del Dock;
 * - al volver a la ventana (`focus`), que es el caso real: el usuario deja la app
 *   abierta, paga afuera y vuelve.
 *
 * Un 404/502 que agote los reintentos NO es motivo para toast de error: el
 * webhook puede activar igual más tarde, y el usuario ya está en la pantalla de
 * planes con su botón de reintentar. Un rechazo real (400/403) sí se avisa.
 */
function useResolverPagoPendiente(clientId: string): void {
  const resolver = useRef(false);

  useEffect(() => {
    if (typeof window === "undefined") return;

    const intentar = () => {
      if (resolver.current) return;
      const pendiente = leerPagoPendiente();
      if (!pendiente) return;

      resolver.current = true;
      void esperarConfirmacionPreferencia(pendiente.preference_id, clientId)
        .then((estado) => {
          if (estado.activo) {
            limpiarPagoPendiente();
            toast.success("¡Pago confirmado! Tu licencia ya está activa.");
            // La query de licencia está cacheada en "blocked": sin esto, seguiría
            // mostrando la pantalla de planes con la licencia ya comprada.
            window.location.reload();
          }
        })
        .catch((err: unknown) => {
          if (esRechazo(err)) {
            limpiarPagoPendiente();
            toast.error(
              "No pudimos confirmar ese pago. Si ya te cobró, escribinos y lo activamos.",
            );
          }
          // Si es "todavía no" (404) o "no se pudo verificar" (502/503), se deja
          // el pago pendiente para reintentar en el próximo focus o arranque: el
          // webhook puede activarlo sin que la app haga nada.
        })
        .finally(() => {
          resolver.current = false;
        });
    };

    intentar();
    window.addEventListener("focus", intentar);
    return () => window.removeEventListener("focus", intentar);
  }, [clientId]);
}

/**
 * Un rechazo del backend no mejora reintentando.
 *
 * Se mira el status y no el texto: 400 (petición inválida) y 403 (el pago es de
 * otro cliente) son definitivos, y avisarle al usuario tiene sentido porque no
 * se va a resolver solo. Los 404/502/503 son "todavía no" y los deja para el
 * webhook.
 */
function esRechazo(e: unknown): boolean {
  return e instanceof ApiError && (e.status === 400 || e.status === 403);
}

function LicenseUI({ onLicensed }: { onLicensed: () => void }) {
  const [planes, setPlanes] = useState<PlanInfo[]>([]);
  const [planesLoading, setPlanesLoading] = useState(true);
  const [planesError, setPlanesError] = useState(false);
  const [trialPending, setTrialPending] = useState(false);
  const clientId = getClientId();

  const cargarPlanes = useCallback(() => {
    setPlanesLoading(true);
    setPlanesError(false);
    obtenerPlanes()
      .then((res) => {
        if (res.ok && res.planes.length > 0) setPlanes(res.planes);
        else setPlanesError(true);
      })
      .catch(() => setPlanesError(true))
      .finally(() => setPlanesLoading(false));
  }, []);

  useEffect(() => {
    cargarPlanes();
  }, [cargarPlanes]);

  async function comprar(plan: PlanInfo) {
    try {
      const res = await crearPreferencia(clientId, plan.id);
      const url = res.init_point;
      if (!url) {
        toast.error(res.message ?? "No se pudo crear el pago");
        return;
      }
      // Se guarda ANTES de abrir el navegador: si el usuario paga y vuelve, el
      // `preference_id` es lo único que permite retomar. Guardarlo después
      // perdería la carrera con el cierre de la app.
      if (res.preference_id) {
        guardarPagoPendiente(res.preference_id, plan.id);
      } else {
        toast.error(
          "No pudimos identificar este pago. Si completás la compra, avisanos para activarla.",
        );
      }
      await abrirPago(url);
      toast.success(
        `Pago iniciado para ${plan.nombre}. Completá el pago en el navegador y volvé a CANYP.`,
      );
    } catch (err) {
      toast.error(err instanceof Error && err.message ? err.message : "Error creando el pago");
    }
  }

  async function activarPrueba() {
    setTrialPending(true);
    try {
      const res = await activarTrial(clientId);
      if (res.ok || res.activo) {
        toast.success("Prueba gratuita activada");
        onLicensed();
      } else {
        toast.error(res.mensaje ?? res.error ?? "No se pudo activar la prueba");
      }
    } catch {
      toast.error("Error de conexión con el servidor local");
    } finally {
      setTrialPending(false);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4 py-10">
      <div className="w-full max-w-2xl">
        <div className="mb-8 text-center">
          <img
            src="/CANYP_Almafuerte_logo.svg?v=3"
            alt="CANYP logo"
            className="mx-auto mb-3 size-16 object-contain"
          />
          <h1 className="text-2xl font-bold text-foreground">CANYP</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Elegí un plan para activar tu licencia. También podés probar gratis 7 días.
          </p>
        </div>

        {planesLoading && (
          <div className="flex items-center justify-center gap-2 text-muted-foreground">
            <Loader2 className="size-5 animate-spin" />
            <span className="text-sm">Cargando planes…</span>
          </div>
        )}

        {planesError && !planesLoading && (
          <div className="flex flex-col items-center gap-3 rounded-lg border border-destructive/40 p-6 text-center">
            <p className="text-sm text-destructive">No se pudieron cargar los planes.</p>
            <Button variant="outline" onClick={cargarPlanes}>
              Reintentar
            </Button>
          </div>
        )}

        {!planesLoading && !planesError && planes.length > 0 && (
          <div className="grid gap-4 sm:grid-cols-3">
            {planes.map((plan) => (
              <Card key={plan.id} className="flex flex-col">
                <CardHeader className="pb-3">
                  <CardTitle className="text-base">{plan.nombre}</CardTitle>
                  <CardDescription>{plan.descripcion}</CardDescription>
                </CardHeader>
                <CardContent className="flex flex-1 flex-col justify-between gap-4">
                  <div>
                    <p className="text-3xl font-bold text-foreground">
                      ${formaPrecio(plan.precio)}
                    </p>
                    <p className="mt-1 text-xs text-muted-foreground">{periodo(plan.dias)}</p>
                  </div>
                  <Button disabled={trialPending} onClick={() => void comprar(plan)}>
                    Comprar
                  </Button>
                </CardContent>
              </Card>
            ))}
          </div>
        )}

        <div className="mt-6 text-center">
          <Button variant="ghost" disabled={trialPending} onClick={() => void activarPrueba()}>
            {trialPending && <Loader2 className="size-4 animate-spin" />}
            Activar prueba gratis de 7 días
          </Button>
        </div>
      </div>
    </div>
  );
}

function formaPrecio(precio: number): string {
  return precio.toLocaleString("es-AR");
}

function periodo(dias: number): string {
  if (dias >= 360) return "por año";
  if (dias >= 150) return "por 6 meses";
  if (dias >= 25) return "por mes";
  return `por ${dias} días`;
}

/** Abre la URL de pago: Tauri usa el plugin shell; en navegador, window.open. */
async function abrirPago(url: string): Promise<void> {
  const inTauri = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
  if (inTauri) {
    const { open } = await import("@tauri-apps/plugin-shell");
    await open(url);
    return;
  }
  window.open(url, "_blank", "noopener,noreferrer");
}
