/**
 * CANYP API client — typed fetch wrapper for backend endpoints.
 *
 * All backend routers live under /api/. The Vite dev server proxies
 * /api → http://localhost:8000 so this works in dev without CORS issues.
 */

import type {
  Arancel,
  Area,
  EstadoMembresia,
  ExecuteResult,
  ImportPayload,
  ImportResponse,
  Membresia,
  Notificacion,
  Parcela,
  Pago,
  PagoItemInput,
  Predio,
  PreviewResult,
  RowData,
  Socio,
} from "./types";

// ---------------------------------------------------------------------------
// Base client
// ---------------------------------------------------------------------------

const BASE_URL = "/api";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${BASE_URL}${path}`;
  const res = await fetch(url, {
    headers: { "Content-Type": "application/json", ...init?.headers },
    ...init,
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, body.detail ?? res.statusText);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

/**
 * Fetch variant for requests that must NOT set `Content-Type: application/json`.
 *
 * Used for multipart/form-data (the browser computes the boundary) and for
 * responses like Blob downloads. Error handling mirrors `apiFetch` (ApiError
 * with the backend `detail`), but it does not auto-parse JSON.
 */
export async function apiFetchRaw(path: string, init?: RequestInit): Promise<Response> {
  const url = `${BASE_URL}${path}`;
  const res = await fetch(url, init);
  if (!res.ok) {
    const body = await res.json().catch(() => ({ detail: res.statusText }));
    throw new ApiError(res.status, body.detail ?? res.statusText);
  }
  return res;
}

/**
 * Multipart variant: sends FormData without forcing a JSON Content-Type so the
 * browser can set the boundary. Resolves to the parsed JSON response.
 */
export async function apiFetchMultipart<T>(path: string, formData: FormData): Promise<T> {
  const res = await apiFetchRaw(path, { method: "POST", body: formData });
  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Socios
// ---------------------------------------------------------------------------

export function getSocios(params?: { search?: string }): Promise<Socio[]> {
  const qs = params?.search ? `?search=${encodeURIComponent(params.search)}` : "";
  return apiFetch<Socio[]>(`/socios${qs}`);
}

export function getSocio(id: string): Promise<Socio> {
  return apiFetch<Socio>(`/socios/${id}`);
}

export function createSocio(data: Omit<Socio, "id" | "fechaAlta">): Promise<Socio> {
  return apiFetch<Socio>("/socios", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function updateSocio(id: string, data: Partial<Socio>): Promise<Socio> {
  return apiFetch<Socio>(`/socios/${id}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export function deleteSocio(id: string): Promise<void> {
  return apiFetch<void>(`/socios/${id}`, { method: "DELETE" });
}

// ---------------------------------------------------------------------------
// Membresias
// ---------------------------------------------------------------------------

export function getMembresias(params?: {
  predio?: string;
  estado?: string;
  socioId?: string;
}): Promise<Membresia[]> {
  const entries = Object.entries(params ?? {}).filter(([, v]) => v != null);
  const qs = entries.length
    ? `?${new URLSearchParams(entries as [string, string][]).toString()}`
    : "";
  return apiFetch<Membresia[]>(`/membresias${qs}`);
}

export function getMembresia(id: string): Promise<Membresia> {
  return apiFetch<Membresia>(`/membresias/${id}`);
}

export function createMembresia(data: Omit<Membresia, "id">): Promise<Membresia> {
  return apiFetch<Membresia>("/membresias", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function updateMembresia(id: string, data: Partial<Membresia>): Promise<Membresia> {
  return apiFetch<Membresia>(`/membresias/${id}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export function deleteMembresia(id: string): Promise<void> {
  return apiFetch<void>(`/membresias/${id}`, { method: "DELETE" });
}

// ---------------------------------------------------------------------------
// Parcelas
// ---------------------------------------------------------------------------

export function getParcelas(params?: { predio?: string }): Promise<Parcela[]> {
  const qs = params?.predio ? `?predio=${encodeURIComponent(params.predio)}` : "";
  return apiFetch<Parcela[]>(`/parcelas${qs}`);
}

export function getParcela(id: string): Promise<Parcela> {
  return apiFetch<Parcela>(`/parcelas/${id}`);
}

export function createParcela(data: Omit<Parcela, "id"> & { id: string }): Promise<Parcela> {
  return apiFetch<Parcela>("/parcelas", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function updateParcela(id: string, data: Partial<Parcela>): Promise<Parcela> {
  return apiFetch<Parcela>(`/parcelas/${id}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export function deleteParcela(id: string): Promise<void> {
  return apiFetch<void>(`/parcelas/${id}`, { method: "DELETE" });
}

// ---------------------------------------------------------------------------
// Parcelas — unidades compartidas (cabañas/balsas)
// ---------------------------------------------------------------------------

/**
 * Importa unidades (parcelas + socios + membresías) transaccionalmente.
 * Idempotente: el backend saltea parcelas existentes por (nombre, predio, tipo)
 * y socios por dni. Devuelve solo los ids recién creados (vacío en re-call).
 */
export function importParcelas(payload: ImportPayload): Promise<ImportResponse> {
  return apiFetch<ImportResponse>("/parcelas/import", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

/** Cambia el estado de TODAS las membresías de una parcela (batch, RQ 5). */
export function setBatchEstado(parcelaId: string, estado: EstadoMembresia): Promise<unknown> {
  return apiFetch(`/parcelas/${parcelaId}/estado`, {
    method: "POST",
    body: JSON.stringify({ estado }),
  });
}

/** Cambia el vencimiento de TODAS las membresías de una parcela (batch, RQ 5). */
export function setBatchVencimiento(parcelaId: string, vencimiento: string): Promise<unknown> {
  return apiFetch(`/parcelas/${parcelaId}/vencimiento`, {
    method: "PUT",
    body: JSON.stringify({ vencimiento }),
  });
}

/**
 * Arma el payload de cobro por unidad (RQ 14): un Pago a nombre del Titular,
 * con UN único ítem (el arancel de la categoría de la unidad) y `membresiaIds`
 * con TODOS los miembros para que el backend renueve a titulares e integrantes.
 * Retorna `null` si no hay titular o no hay ítems por cobrar.
 */
export function buildUnitPago(params: {
  /** El miembro titular de la unidad (su socioId + membresiaId). */
  titular: { socioId: string; membresiaId: string };
  /** Resto de miembros a renovar junto al titular. */
  integrantes: { membresiaId: string }[];
  medio: string;
  /** Nota opcional que se muestra en el comprobante. */
  nota?: string;
  /** Ítem único del cobro (el arancel de la unidad). */
  items: { arancelId: string; arancelNombre: string; montoAplicado: number; membresiaId: string }[];
}): CreatePagoInput | null {
  const items: PagoItemInput[] = params.items.map((it) => ({
    arancelId: it.arancelId,
    membresiaId: it.membresiaId,
    montoAplicado: it.montoAplicado,
    arancelNombre: it.arancelNombre,
  }));
  if (!params.titular.socioId) return null;
  if (items.length === 0) return null;
  return {
    socioId: params.titular.socioId,
    medio: params.medio,
    ...(params.nota ? { nota: params.nota } : {}),
    items,
    membresiaIds: [params.titular.membresiaId, ...params.integrantes.map((i) => i.membresiaId)],
    total: items.reduce((s, i) => s + i.montoAplicado, 0),
  };
}

// ---------------------------------------------------------------------------
// Aranceles
// ---------------------------------------------------------------------------

export function getAranceles(params?: { predio?: string; area?: string }): Promise<Arancel[]> {
  const entries = Object.entries(params ?? {}).filter(([, v]) => v != null);
  const qs = entries.length
    ? `?${new URLSearchParams(entries as [string, string][]).toString()}`
    : "";
  return apiFetch<Arancel[]>(`/aranceles${qs}`);
}

export interface CreateArancelInput {
  nombre: string;
  area: Area;
  predio: Predio;
  monto: number;
  vigenteDesde: string;
}

export function createArancel(data: CreateArancelInput): Promise<Arancel> {
  return apiFetch<Arancel>("/aranceles", {
    method: "POST",
    body: JSON.stringify({ ...data, historico: [] }),
  });
}

export function updateArancelMonto(id: string, monto: number): Promise<Arancel> {
  return apiFetch<Arancel>(`/aranceles/${id}/monto`, {
    method: "PUT",
    body: JSON.stringify({ monto }),
  });
}

// ---------------------------------------------------------------------------
// Pagos
// ---------------------------------------------------------------------------

export function getPagos(params?: { socioId?: string }): Promise<Pago[]> {
  const qs = params?.socioId ? `?socioId=${encodeURIComponent(params.socioId)}` : "";
  return apiFetch<Pago[]>(`/pagos${qs}`);
}

export interface CreatePagoInput {
  socioId: string;
  medio: string;
  /** Nota opcional que se muestra en el comprobante. */
  nota?: string;
  items: PagoItemInput[];
  total: number;
  /** Membresías a renovar (puede diferir de los ítems: cobro por unidad). */
  membresiaIds?: string[];
}

export function createPago(data: CreatePagoInput): Promise<Pago> {
  const hoy = new Date().toISOString().slice(0, 10);
  return apiFetch<Pago>("/pagos", {
    method: "POST",
    body: JSON.stringify({
      id: `p${Date.now()}`,
      socioId: data.socioId,
      fecha: hoy,
      medio: data.medio,
      total: data.total,
      nota: data.nota,
      items: data.items,
      membresiaIds: data.membresiaIds ?? data.items.map((i) => i.membresiaId),
    }),
  });
}

// ---------------------------------------------------------------------------
// Notificaciones
// ---------------------------------------------------------------------------

export function getNotificaciones(params?: { socioId?: string }): Promise<Notificacion[]> {
  const qs = params?.socioId ? `?socioId=${encodeURIComponent(params.socioId)}` : "";
  return apiFetch<Notificacion[]>(`/notificaciones${qs}`);
}

export interface CreateNotificacionInput {
  socioId: string;
  canal: "email" | "whatsapp";
  fecha: string;
  motivo: string;
  mensaje: string;
}

export function createNotificaciones(items: CreateNotificacionInput[]): Promise<Notificacion[]> {
  return apiFetch<Notificacion[]>("/notificaciones", {
    method: "POST",
    body: JSON.stringify(
      items.map((item) => ({
        id: `n${Date.now()}-${Math.random().toString(36).slice(2, 6)}`,
        ...item,
      })),
    ),
  });
}

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------

export function getDashboard(): Promise<Record<string, unknown>> {
  return apiFetch<Record<string, unknown>>("/dashboard");
}

// ---------------------------------------------------------------------------
// Import masivo (generic resource-based bulk import; `socios` wired in backend)
// ---------------------------------------------------------------------------

/**
 * Download the import template XLSX for a resource.
 * Returns the raw bytes so the caller can trigger a browser download.
 */
export function getImportTemplate(resource: string): Promise<Blob> {
  return apiFetchRaw(`/${resource}/import/template`).then((res) => res.blob());
}

/**
 * Upload a file for server-side parse + validation.
 * `resource` is the slash-less plural resource name, e.g. "socios".
 */
export function previewImport(resource: string, file: File): Promise<PreviewResult> {
  const formData = new FormData();
  formData.append("file", file);
  return apiFetchMultipart<PreviewResult>(`/${resource}/import/preview`, formData);
}

/**
 * Execute an import batch from the validated rows the client edited/skipped.
 * Server re-validates each row and persists via savepoints.
 */
export function executeImport(resource: string, rows: RowData[]): Promise<ExecuteResult> {
  return apiFetch<ExecuteResult>(`/${resource}/import/execute`, {
    method: "POST",
    body: JSON.stringify({ rows }),
  });
}
