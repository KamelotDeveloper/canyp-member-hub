/**
 * CANYP subscription service — MercadoPago checkout + license verification.
 *
 * Espeja el contrato de negocio de Ordo-ERP adaptado al stack CANYP:
 * - APP_ID fijo "canyp" (el webhook remoto valida contra este app_id).
 * - client_id local persistido en localStorage (una instalación = un id).
 * - Endpoints del backend local (open/pre-login) bajo /api/suscripcion.
 */

import { ApiError, apiFetch } from "./api";

export const APP_ID = "canyp";
export const CLIENT_ID_KEY = "canyp_client_id";

export interface PlanInfo {
  id: string;
  nombre: string;
  descripcion: string;
  precio: number;
  dias: number;
}

export interface PruebaGratis {
  id: string;
  nombre: string;
  descripcion: string;
  precio: number;
  dias: number;
}

export interface PlanesResponse {
  ok: boolean;
  planes: PlanInfo[];
  prueba_gratis: PruebaGratis;
}

export interface VerificarResponse {
  ok: boolean;
  activo?: boolean;
  tipo?: "licencia" | "trial" | "ninguno";
  estado?: string | null;
  plan?: string | null;
  fecha_expiracion?: string;
  fecha_fin?: string;
  dias_restantes?: number;
  error?: string;
  mensaje?: string;
}

export interface CrearPreferenciaResponse {
  success: boolean;
  init_point?: string;
  payment_url?: string;
  preference_id?: string;
  payment_id?: string;
  modo?: "real" | "mock" | "gratis";
  message?: string;
  error?: string;
}

/**
 * Lee (o genera y persiste) el client_id de esta instalación.
 * Se guarda en localStorage, no en Tauri fs: simple y suficiente.
 * El id tiene prefijo `canyp_` y NO lleva ':' (contrato del webhook).
 */
export function getClientId(): string {
  if (typeof window === "undefined") return "";
  try {
    const existing = window.localStorage.getItem(CLIENT_ID_KEY);
    if (existing) return existing;
    const id = `canyp_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;
    window.localStorage.setItem(CLIENT_ID_KEY, id);
    return id;
  } catch {
    return `canyp_${Date.now()}`;
  }
}

/** GET /api/suscripcion/planes?app_id=canyp → catálogo (Supabase o fallback local). */
export function obtenerPlanes(): Promise<PlanesResponse> {
  return apiFetch<PlanesResponse>(`/suscripcion/planes?app_id=${APP_ID}`);
}

/**
 * POST /api/suscripcion/crear-preferencia → init_point de MercadoPago.
 * Normaliza el campo: el backend local devuelve payment_url en modo mock.
 */
export async function crearPreferencia(
  clientId: string,
  plan: string,
): Promise<CrearPreferenciaResponse> {
  const data = await apiFetch<CrearPreferenciaResponse>("/suscripcion/crear-preferencia", {
    method: "POST",
    body: JSON.stringify({ client_id: clientId, app_id: APP_ID, plan }),
  });
  const url = data.init_point || data.payment_url || undefined;
  return { ...data, ...(url ? { init_point: url } : {}) };
}

/** POST /api/suscripcion/verificar → estado de licencia (Supabase + trial local). */
export function verificarSuscripcion(clientId: string): Promise<VerificarResponse> {
  return apiFetch<VerificarResponse>("/suscripcion/verificar", {
    method: "POST",
    body: JSON.stringify({ client_id: clientId, app_id: APP_ID }),
  });
}

/** POST /api/suscripcion/trial → activa el trial local de 7 días (una vez por instalación). */
export function activarTrial(clientId: string): Promise<VerificarResponse> {
  return apiFetch<VerificarResponse>("/suscripcion/trial", {
    method: "POST",
    body: JSON.stringify({ client_id: clientId, app_id: APP_ID }),
  });
}

export interface ConfirmarPagoResponse {
  success: boolean;
  verificado: boolean;
  idempotente: boolean;
  estado: string;
  error?: string;
}

export interface EstadoPagoResponse {
  ok: boolean;
  activo: boolean;
  estado: string | null;
  plan: string | null;
  fecha_expiracion: string | null;
  dias_restantes: number;
}

/**
 * POST /api/suscripcion/confirmar-pago → activa la licencia tras verificar el pago.
 *
 * Respaldo del webhook: si el pago llegó pero la fila sigue `pendiente`, esto la
 * activa. El backend NO confía en este `payment_id`: lo consulta en MercadoPago y
 * exige `status == approved`. Por eso un error acá no significa "pago rechazado",
 * sino "no se pudo verificar todavía" — hay que reintentar.
 *
 * `clientId` se manda solo para que el backend pueda rechazar de entrada un pago
 * ajeno; no alcanza para activar nada por sí mismo.
 */
export function confirmarPago(paymentId: string, clientId: string): Promise<ConfirmarPagoResponse> {
  const params = new URLSearchParams({ payment_id: paymentId, app_id: APP_ID });
  if (clientId) params.set("client_id", clientId);
  return apiFetch<ConfirmarPagoResponse>(`/suscripcion/confirmar-pago?${params}`, {
    method: "POST",
  });
}

/**
 * GET /api/suscripcion/estado-pago → ¿ya está activa la licencia de este pago?
 *
 * Solo lee. Es el companion de `confirmarPago` para el caso "todavía no": el
 * pago se acredita después de que Checkout Pro redirigió, así que hay que
 * reintentar.
 */
export function consultarEstadoPago(paymentId: string): Promise<EstadoPagoResponse> {
  return apiFetch<EstadoPagoResponse>(
    `/suscripcion/estado-pago?payment_id=${encodeURIComponent(paymentId)}`,
  );
}

/**
 * POST /api/suscripcion/confirmar-preferencia → resuelve el pago por preferencia.
 *
 * Este es el que usa la app de verdad. En Tauri el Checkout Pro abre en el
 * navegador EXTERNO, así que la app nunca recibe el `payment_id` de la URL de
 * retorno: lo único que guardó fue el `preference_id` de `crearPreferencia`.
 *
 * `clientId` no es opcional a propósito: el backend lo exige para no activar por
 * accidente la licencia de otro si alguien adivina un `preference_id`.
 */
export function confirmarPreferencia(
  preferenceId: string,
  clientId: string,
): Promise<ConfirmarPagoResponse> {
  const params = new URLSearchParams({
    preference_id: preferenceId,
    app_id: APP_ID,
    client_id: clientId,
  });
  return apiFetch<ConfirmarPagoResponse>(`/suscripcion/confirmar-preferencia?${params}`, {
    method: "POST",
  });
}

/**
 * Espera a que el pago se aclare, confirmando y reintentando con backoff.
 *
 * El flujo real es: Checkout Pro abre en el navegador EXTERNO y el usuario
 * vuelve a la app a mano. Cuando vuelve, el pago puede llevar segundos acreditado
 * o ninguno. Por eso esto reintenta en vez de preguntar una sola vez y rendirse.
 *
 * Corta apenas la licencia queda activa, y también si el backend responde que el
 * pago NO es activable (404 = todavía no hay pago acreditado), para no esperar
 * inútilmente.
 */
export async function esperarConfirmacionPreferencia(
  preferenceId: string,
  clientId: string,
  opciones: { intentos?: number; delayMs?: number } = {},
): Promise<EstadoPagoResponse> {
  const intentos = opciones.intentos ?? 10;
  const delayMs = opciones.delayMs ?? 3000;
  let ultimoError: string | undefined;

  for (let intento = 0; intento < intentos; intento++) {
    if (intento > 0) await dormir(delayMs);
    try {
      await confirmarPreferencia(preferenceId, clientId);
      const estado = await consultarEstadoPagoPreferencia(preferenceId);
      if (estado.activo) return estado;
      ultimoError = undefined;
    } catch (e) {
      // 404 = la preferencia todavía no tiene pago acreditado, que es el estado
      // normal al volver del navegador. 502/503 = no se pudo verificar todavía.
      // Un 400/403 no mejora con reintentar, así que se propaga.
      ultimoError = e instanceof Error ? e.message : String(e);
      if (!esReintentable(e)) throw e;
    }
  }

  throw new Error(
    ultimoError ??
      "El pago todavía no se confirmó. Revisá en un minuto; si ya figuras con el pago hecho, escribinos.",
  );
}

/** GET /api/suscripcion/estado-pago?preference_id=… → estado por preferencia. */
export function consultarEstadoPagoPreferencia(preferenceId: string): Promise<EstadoPagoResponse> {
  return apiFetch<EstadoPagoResponse>(
    `/suscripcion/estado-pago?preference_id=${encodeURIComponent(preferenceId)}`,
  );
}

/**
 * ¿Este error vale la pena reintentar?
 *
 * Se decide por el STATUS, no por el texto: los mensajes los escribe el backend y
 * cambiarlos no debería cambiar el comportamiento del cliente. Además, un
 * rechazo (400/403) no mejora por insistir, así que propagarlo es lo correcto.
 *
 * - 404: la preferencia todavía no tiene pago acreditado. Es el estado NORMAL al
 *   volver del navegador, no un fallo.
 * - 502/503: no se pudo verificar contra MercadoPago (o falta el token).
 * - sin status (red caída, Tauri sin sidecar): reintentable, va a volver solo.
 */
function esReintentable(e: unknown): boolean {
  if (e instanceof ApiError) {
    return e.status === 404 || e.status === 502 || e.status === 503;
  }
  return true;
}

function dormir(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
