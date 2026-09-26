/**
 * CANYP subscription service — MercadoPago checkout + license verification.
 *
 * Espeja el contrato de negocio de Ordo-ERP adaptado al stack CANYP:
 * - APP_ID fijo "canyp" (el webhook remoto valida contra este app_id).
 * - client_id local persistido en localStorage (una instalación = un id).
 * - Endpoints del backend local (open/pre-login) bajo /api/suscripcion.
 */

import { apiFetch } from "./api";

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
