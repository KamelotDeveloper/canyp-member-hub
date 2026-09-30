/**
 * CANYP API client — typed fetch wrapper for backend endpoints.
 *
 * All backend routers live under /api/. In dev the Vite server proxies
 * /api to the locally running backend (default dev port); in the packaged
 * desktop shell the sidecar listens on a dynamic port chosen at startup
 * (CANYP_PORT, fetched via the get_backend_port command).
 */

import type {
  AppSettings,
  Arancel,
  Area,
  CategoriaParcela,
  ConceptoCobro,
  ConceptoMembresia,
  DashboardAlerta,
  DashboardStats,
  EstadoActivacion,
  EstadoMembresia,
  ExecuteResult,
  ImportPayload,
  ImportResponse,
  Membresia,
  Notificacion,
  Parcela,
  ParcelaConMembresias,
  Pago,
  PagoItemInput,
  Predio,
  PreviewResult,
  RowData,
  Socio,
  Usuario,
} from "./types";

// ---------------------------------------------------------------------------
// Base client
// ---------------------------------------------------------------------------

let baseUrlPromise: Promise<string> | null = null;

/** Base URL resuelta una sola vez por sesión (caché). */
async function getBaseUrl(): Promise<string> {
  if (!baseUrlPromise) baseUrlPromise = resolveBaseUrl();
  return baseUrlPromise;
}

/**
 * Resolve the API base for the current runtime.
 * - Browser dev (Vite proxy): `/api`
 * - Tauri desktop shell: the sidecar FastAPI listens on a dynamic port chosen
 *   at startup. Tauri v2 exposes window.__TAURI_INTERNALS__; call the
 *   `get_backend_port` command so the same bundle works in dev and packaged.
 */
async function resolveBaseUrl(): Promise<string> {
  const inTauri = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;
  if (!inTauri) return "/api";
  try {
    const internals = (
      window as unknown as { __TAURI_INTERNALS__: { invoke: (cmd: string) => Promise<number> } }
    ).__TAURI_INTERNALS__;
    const port = await internals.invoke("get_backend_port");
    return `http://127.0.0.1:${port}/api`;
  } catch {
    // Comando no disponible (dev sin sidecar): fallback coherente con uvicorn manual.
    return "http://127.0.0.1:8000/api";
  }
}

/**
 * localStorage key where the JWT is persisted after login / first-user.
 * Read/write are client-guarded so the SSR pass (no `window`) never throws.
 */
export const TOKEN_KEY = "canyp.token";

function getToken(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.setItem(TOKEN_KEY, token);
  } catch {
    // Storage may be unavailable (private mode); auth still works in-memory.
  }
}

export function clearToken(): void {
  if (typeof window === "undefined") return;
  try {
    window.localStorage.removeItem(TOKEN_KEY);
  } catch {
    // ignore
  }
}

/**
 * Cerrar sesión: avisa al backend (open, sin guard) y descarta el token local.
 * El endpoint no revoca el JWT en v1 (D4) — el "logout" real es eliminar el
 * token del cliente. Se ignora cualquier error para que el cierre nunca falle.
 */
export async function logout(): Promise<void> {
  try {
    await fetch(`${await getBaseUrl()}/auth/logout`, { method: "POST" });
  } catch {
    // network failure — still clear the local token below
  }
  clearToken();
}

/**
 * Auth endpoints (login/first-user/status/logout) are open by design, so a 401
 * there is a legitimate credential error — never trigger the token-clear
 * reload. Settings is conditionally guarded (open pre-config, guarded after),
 * so it is also excluded to avoid a reload loop while the login gate boots.
 */
function isAuthPath(path: string): boolean {
  return path.startsWith("/auth/") || path === "/settings";
}

function attachAuthHeaders(init?: RequestInit): RequestInit {
  const token = getToken();
  if (!token) return init ?? {};
  return {
    ...init,
    headers: { Authorization: `Bearer ${token}`, ...init?.headers },
  };
}

/** On an expired/invalid token, drop it and reload so the login gate renders. */
function handleUnauthorized(path: string): void {
  if (isAuthPath(path)) return;
  clearToken();
  if (typeof window !== "undefined") window.location.reload();
}

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
  const url = `${await getBaseUrl()}${path}`;
  const res = await fetch(
    url,
    attachAuthHeaders({
      headers: { "Content-Type": "application/json", ...init?.headers },
      ...init,
    }),
  );
  if (!res.ok) {
    if (res.status === 401) handleUnauthorized(path);
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
  const url = `${await getBaseUrl()}${path}`;
  const res = await fetch(url, attachAuthHeaders(init));
  if (!res.ok) {
    if (res.status === 401) handleUnauthorized(path);
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

/**
 * POST /api/socios/{id}/foto — multipart field `foto` (image/*, max 5 MB).
 * 200 `{tieneFoto: true}`; 415 non-image; 413 too big; 404 missing socio.
 */
export function subirFoto(id: string, foto: File): Promise<{ tieneFoto: boolean }> {
  const formData = new FormData();
  formData.append("foto", foto);
  return apiFetchMultipart<{ tieneFoto: boolean }>(`/socios/${id}/foto`, formData);
}

/**
 * GET /api/socios/{id}/foto — raw JPEG bytes (`Content-Type: image/jpeg`).
 * Throws ApiError 404 if the socio is missing or has no photo. Used by the
 * carnet print flow (blob -> object URL), never JSON.
 */
export function getSocioFoto(id: string): Promise<Blob> {
  return apiFetchRaw(`/socios/${id}/foto`).then((res) => res.blob());
}

/**
 * DELETE /api/socios/{id}/foto — removes the carnet photo.
 * 204 on success (photo cleared); 404 if the socio is missing.
 */
export function quitarFoto(id: string): Promise<void> {
  return apiFetch<void>(`/socios/${id}/foto`, { method: "DELETE" });
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

/**
 * GET /api/membresias/parcelas — unidades (cabañas/balsas) con sus miembros y
 * el estado de socio SCOPED a la unidad (`estadoSocio`, D5). El servidor ya
 * marca ⚠️ a TODO el grupo cuando cualquier área de la unidad está vencida, así
 * que el panel solo agrega lo servido por unidad.
 */
export function getMembresiasParcelas(): Promise<ParcelaConMembresias[]> {
  return apiFetch<ParcelaConMembresias[]>("/membresias/parcelas");
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

/**
 * Cambia el vencimiento de TODAS las membresías de una parcela (batch, CBM-06).
 *
 * `concepto` es el valor del enum (`"area"` | `"cuota social"`); la UI lo envía
 * SIEMPRE: omitirlo mezcla área + cuota social en el mismo lote. La fecha se
 * guarda VERBATIM (sin proyección a día 10): esa regla es del cobro, no del
 * editor manual.
 */
export function setBatchVencimiento(
  parcelaId: string,
  vencimiento: string,
  concepto?: ConceptoMembresia,
): Promise<unknown> {
  const qs = concepto ? `?concepto=${encodeURIComponent(concepto)}` : "";
  return apiFetch(`/parcelas/${parcelaId}/vencimiento${qs}`, {
    method: "PUT",
    body: JSON.stringify({ vencimiento }),
  });
}

/**
 * Edita el `vencimiento` ABSOLUTO de UNA membresía (área o cuota social, CBM-06).
 *
 * El id decide cuál; no hay endpoint separado de cuota. La fecha se guarda
 * VERBATIM y se acepta una fecha pasada (las filas legacy a corregir están
 * justamente vencidas). No crea ni toca ningún `Pago`.
 */
export function updateMembresiaVencimiento(id: string, vencimiento: string): Promise<Membresia> {
  return apiFetch<Membresia>(`/membresias/${id}/vencimiento`, {
    method: "PUT",
    body: JSON.stringify({ vencimiento }),
  });
}

/**
 * Arma el payload de cobro por unidad (RQ 14): un Pago a nombre del Titular con
 * `items` = un ítem por cada concepto marcado por el operador, y `membresiaIds`
 * con TODOS los miembros para que el backend renueve a titulares e integrantes.
 *
 * `items` ya viene compuesto por `itemsPorArancel` (7.2): el cliente propone
 * el desglose y el `montoAplicado` es una PISTA — el servidor re-resuelve cada
 * línea contra el catálogo y es la única autoridad del total (PAG-01).
 *
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
  /** Fecha del cobro; por defecto hoy (PAG-02). */
  fecha?: string;
  /** Un ítem por arancel marcado, ya compuesto por `itemsPorArancel`. */
  items: PagoItemInput[];
}): CreatePagoInput | null {
  const { titular, integrantes, medio, nota, fecha, items } = params;
  if (!titular.socioId) return null;
  if (items.length === 0) return null;
  return {
    socioId: titular.socioId,
    medio,
    ...(fecha ? { fecha } : {}),
    ...(nota ? { nota } : {}),
    items,
    membresiaIds: [titular.membresiaId, ...integrantes.map((i) => i.membresiaId)],
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
  /**
   * Concepto que precio la fila (ReQ-005). Opcional porque el backend lo
   * defaulta a `area` igual que la columna; el catálogo lo manda siempre.
   */
  concepto?: ConceptoCobro;
  /** Categoría de parcela; null/ausente = catch-all del área+predio. */
  categoria?: CategoriaParcela | null;
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

export interface UpdateArancelInput {
  nombre?: string;
  area?: Area;
  predio?: Predio;
  monto?: number;
  categoria?: CategoriaParcela | null;
  vigenteDesde?: string;
  /**
   * Re-tag del catálogo (ReQ-005/006). El backend exige un valor no nulo: un
   * `null` explícito responde 422, no "borrá el concepto".
   */
  concepto?: ConceptoCobro;
}

export function updateArancel(id: string, data: UpdateArancelInput): Promise<Arancel> {
  return apiFetch<Arancel>(`/aranceles/${id}`, {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

export function deleteArancel(id: string): Promise<Arancel> {
  return apiFetch<Arancel>(`/aranceles/${id}`, { method: "DELETE" });
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
  /** Fecha del cobro; el operador la elige y por defecto es hoy (PAG-02). */
  fecha?: string;
  /** Nota opcional que se muestra en el comprobante. */
  nota?: string;
  items: PagoItemInput[];
  /**
   * Opcional a propósito (PAG-01): el servidor es la única autoridad del
   * total. El cliente manda su estimación como pista en `montoAplicado`, pero
   * el campo `total` viaja solo si el llamador lo define explícitamente.
   */
  total?: number;
  /** Membresías a renovar (puede diferir de los ítems: cobro por unidad). */
  membresiaIds?: string[];
}

export function createPago(data: CreatePagoInput): Promise<Pago> {
  const hoy = new Date().toISOString().slice(0, 10);
  return apiFetch<Pago>("/pagos", {
    method: "POST",
    body: JSON.stringify({
      // El id lo genera el backend (uuid4, seguro para modo remoto/Postgres).
      socioId: data.socioId,
      fecha: data.fecha ?? hoy,
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
    // Los ids los genera el backend (uuid4, seguro para modo remoto/Postgres).
    body: JSON.stringify(items),
  });
}

// ---------------------------------------------------------------------------
// Activación (frontera de confianza — espejo del veredicto del servidor)
// ---------------------------------------------------------------------------

/**
 * GET /api/activacion → veredicto de activación de esta instalación.
 *
 * Endpoint abierto y pre-login a propósito: la instalación puede estar sin
 * activar y la UI tiene que poder preguntar igual. Devuelve 200 siempre — que
 * no esté activada es un estado, no un error; el 503 vive en las rutas de
 * dominio.
 */
export function getActivacion(): Promise<EstadoActivacion> {
  return apiFetch<EstadoActivacion>("/activacion");
}

// ---------------------------------------------------------------------------
// Settings (data mode: local SQLite / remoto PostgreSQL)
// ---------------------------------------------------------------------------

export function getSettings(): Promise<AppSettings> {
  return apiFetch<AppSettings>("/settings");
}

export interface UpdateSettingsInput {
  dataMode: AppSettings["dataMode"];
  /** Obligatoria para "remoto"; por defecto la app borra la URL al volver a local. */
  databaseUrl?: string;
}

export function updateSettings(data: UpdateSettingsInput): Promise<AppSettings> {
  return apiFetch<AppSettings>("/settings", {
    method: "PUT",
    body: JSON.stringify(data),
  });
}

// ---------------------------------------------------------------------------
// Auth + Usuarios
// ---------------------------------------------------------------------------

/** Open endpoint (no auth): whether any user exists yet. */
export function getAuthStatus(): Promise<{ users_exist: boolean }> {
  return apiFetch<{ users_exist: boolean }>("/auth/status");
}

/** POST /api/auth/login → 200 {token} | 401 "Credenciales inválidas". */
export function login(username: string, password: string): Promise<{ token: string }> {
  return apiFetch<{ token: string }>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

/** POST /api/auth/first-user → 201 {token, user} | 409 | 422. */
export function createFirstUser(
  username: string,
  password: string,
): Promise<{ token: string; user: Usuario }> {
  return apiFetch<{ token: string; user: Usuario }>("/auth/first-user", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

/** GET /api/usuarios (guarded). */
export function getUsuarios(): Promise<Usuario[]> {
  return apiFetch<Usuario[]>("/usuarios");
}

/** POST /api/usuarios (guarded). */
export function createUsuario(username: string, password: string): Promise<Usuario> {
  return apiFetch<Usuario>("/usuarios", {
    method: "POST",
    body: JSON.stringify({ username, password }),
  });
}

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------

export function getDashboardStats(): Promise<DashboardStats> {
  return apiFetch<DashboardStats>("/dashboard/stats");
}

export function getDashboardAlertas(): Promise<DashboardAlerta[]> {
  return apiFetch<DashboardAlerta[]>("/dashboard/alertas");
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

// ---------------------------------------------------------------------------
// Export (generic resource-based data export; CSV + XLSX)
// ---------------------------------------------------------------------------

export type ExportFormat = "csv" | "xlsx";

/**
 * Download the complete export of a resource (all rows — never paginated).
 * Returns the raw bytes so the caller can trigger a browser download.
 * `resource` is the slash-less plural resource name, e.g. "socios".
 */
export function exportResource(resource: string, format: ExportFormat = "csv"): Promise<Blob> {
  return apiFetchRaw(`/export/${resource}?format=${format}`).then((res) => res.blob());
}
