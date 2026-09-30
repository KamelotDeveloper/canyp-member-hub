/**
 * CANYP TanStack Query hooks — wraps api.ts with cache management.
 *
 * Each query hook maps to a GET endpoint.
 * Each mutation hook wraps a POST/PUT/DELETE and invalidates relevant caches on success.
 */

import { useQuery, useMutation, useQueryClient, type QueryClient } from "@tanstack/react-query";
import * as api from "./api";
import { clearFotosCache } from "./fotos";
import { verificarSuscripcion } from "./suscripcion";
import type {
  ConceptoMembresia,
  EstadoMembresia,
  ExecuteResult,
  ImportPayload,
  Membresia,
  Notificacion,
  Parcela,
  PreviewResult,
  RowData,
  Socio,
  Usuario,
} from "./types";

// ---------------------------------------------------------------------------
// QUERIES
// ---------------------------------------------------------------------------

/**
 * Auto-refresh cadence for list/dashboard queries (ms).
 * En modo remoto dos PCs comparten la base: refrescar cada ~15s mantiene la
 * UI al día sin realtime. El cache de TanStack Query ya cubre el resto.
 */
const REFRESH_INTERVAL_MS = 15_000;

/** List all socios, optionally filtered by search term */
export function useSocios(params?: { search?: string }) {
  return useQuery({
    queryKey: ["socios", params],
    queryFn: () => api.getSocios(params),
    refetchInterval: REFRESH_INTERVAL_MS,
  });
}

/** Get a single socio by ID */
export function useSocio(id: string) {
  return useQuery({
    queryKey: ["socios", id],
    queryFn: () => api.getSocio(id),
    enabled: !!id,
  });
}

/** List membresias with optional filters */
export function useMembresias(filters?: { predio?: string; estado?: string; socioId?: string }) {
  return useQuery({
    queryKey: ["membresias", filters],
    queryFn: () => api.getMembresias(filters),
    refetchInterval: REFRESH_INTERVAL_MS,
  });
}

/** Get a single membresia by ID */
export function useMembresia(id: string) {
  return useQuery({
    queryKey: ["membresias", id],
    queryFn: () => api.getMembresia(id),
    enabled: !!id,
  });
}

/** List unidades (cabañas/balsas) con sus miembros y `estadoSocio` unit-scoped. */
export function useMembresiasParcelas() {
  return useQuery({
    queryKey: ["membresias", "parcelas"],
    queryFn: api.getMembresiasParcelas,
    refetchInterval: REFRESH_INTERVAL_MS,
  });
}

/** List aranceles, optionally filtered by predio */
export function useAranceles(params?: { predio?: string; area?: string }) {
  return useQuery({
    queryKey: ["aranceles", params],
    queryFn: () => api.getAranceles(params),
    refetchInterval: REFRESH_INTERVAL_MS,
  });
}

/** List pagos, optionally filtered by socio */
export function usePagos(socioId?: string) {
  return useQuery({
    queryKey: ["pagos", socioId],
    queryFn: () => api.getPagos(socioId ? { socioId } : undefined),
    refetchInterval: REFRESH_INTERVAL_MS,
  });
}

/** List notificaciones, optionally filtered by socio */
export function useNotificaciones(socioId?: string) {
  return useQuery({
    queryKey: ["notificaciones", socioId],
    queryFn: () => api.getNotificaciones(socioId ? { socioId } : undefined),
    refetchInterval: REFRESH_INTERVAL_MS,
  });
}

/** Dashboard stats from the backend */
export function useDashboardStats() {
  return useQuery({
    queryKey: ["dashboard", "stats"],
    queryFn: api.getDashboardStats,
    refetchInterval: REFRESH_INTERVAL_MS,
  });
}

/** Dashboard alerts — membresias vencidas / por vencer */
export function useDashboardAlertas() {
  return useQuery({
    queryKey: ["dashboard", "alertas"],
    queryFn: api.getDashboardAlertas,
    refetchInterval: REFRESH_INTERVAL_MS,
  });
}

/** List parcelas, optionally filtered by predio */
export function useParcelas(predio?: string) {
  return useQuery({
    queryKey: ["parcelas", predio],
    queryFn: () => api.getParcelas(predio ? { predio } : undefined),
    refetchInterval: REFRESH_INTERVAL_MS,
  });
}

/**
 * Reintentar SOLO errores de red (fetch TypeError: ERR_CONNECTION_REFUSED…),
 * y hacerlo SIN límite: el sidecar empaquetado es local y SIEMPRE termina
 * arrancando. En frío (PyInstaller onefile, ~55 MB) puede tardar entre 20 y 60+ s
 * según disco/antivirus; si abandonáramos los reintentos el LoginGate caería en
 * el placeholder "Configurando CANYP…" (pantalla en blanco) aunque el backend
 * levante un segundo después. Un 401 real (settings configurado, D9) NO
 * reintenta: el LoginGate deriva `configured=true` al instante de ese status.
 */
const NETWORK_RETRY_DELAY_MS = 3_000;

function retryOnNetwork(_failureCount: number, error: Error): boolean {
  return error instanceof TypeError;
}

/**
 * Veredicto de activación del servidor (GET /api/activacion).
 *
 * Es el ÚNICO origen de la decisión "abre o no" en la UI. Los guards
 * (ClientBuildGuard, LicenseGate) lo consultan; ninguno de los dos calcula el
 * veredicto por su cuenta. Aun así sigue siendo un espejo: si el frontend
 * mintiera, el backend igual negaría la petición.
 *
 * `refetchOnWindowFocus` para que una instalación que el administrador acaba
 * de activar se destrabe sola al volver a la ventana, sin reiniciar a mano.
 */
export function useActivacion() {
  return useQuery({
    queryKey: ["activacion"],
    queryFn: api.getActivacion,
    staleTime: 10_000,
    retry: retryOnNetwork,
    retryDelay: NETWORK_RETRY_DELAY_MS,
    refetchOnWindowFocus: true,
  });
}

/** Current data-mode settings (badge + wizard + Ajustes). */
export function useSettings() {
  return useQuery({
    queryKey: ["settings"],
    queryFn: api.getSettings,
    staleTime: 30_000,
    retry: retryOnNetwork,
    retryDelay: NETWORK_RETRY_DELAY_MS,
  });
}

/**
 * License state for a client_id (POST /suscripcion/verificar).
 *
 * Cached per client_id so a remount of LicenseGate NEVER resets the gate to
 * "checking": the verdict is served from cache instantly and the endpoint is
 * not re-pinged at 1Hz. Refetch only on explicit invalidation (reintentar,
 * trial activado) or after staleTime.
 */
export function useLicencia(clientId: string) {
  return useQuery({
    queryKey: ["licencia", clientId],
    queryFn: () => verificarSuscripcion(clientId),
    staleTime: 60_000,
    retry: retryOnNetwork,
    retryDelay: NETWORK_RETRY_DELAY_MS,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
  });
}

/** Save data-mode settings; refreshes the cached value immediately. */
export function useUpdateSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: api.UpdateSettingsInput) => api.updateSettings(data),
    onSuccess: (updated) => {
      qc.setQueryData(["settings"], updated);
      qc.invalidateQueries({ queryKey: ["settings"] });
    },
  });
}

// ---------------------------------------------------------------------------
// Auth + Usuarios
// ---------------------------------------------------------------------------

/**
 * Open auth status (whether any user exists). Cached hard: it only changes
 * after the first-user bootstrap, which reloads the app anyway.
 */
export function useAuthStatus() {
  return useQuery({
    queryKey: ["auth", "status"],
    queryFn: api.getAuthStatus,
    staleTime: Infinity,
    retry: retryOnNetwork,
    retryDelay: NETWORK_RETRY_DELAY_MS,
  });
}

/** List usuarios (guarded). */
export function useUsuarios() {
  return useQuery({
    queryKey: ["usuarios"],
    queryFn: api.getUsuarios,
    refetchInterval: REFRESH_INTERVAL_MS,
  });
}

/** Create a new usuario; invalidates the usuarios cache. */
export function useCreateUsuario() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ username, password }: { username: string; password: string }) =>
      api.createUsuario(username, password),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["usuarios"] });
    },
  });
}

// ---------------------------------------------------------------------------
// MUTATIONS — Socios
// ---------------------------------------------------------------------------

/** Create a new socio */
export function useCreateSocio() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Omit<Socio, "id" | "fechaAlta">) => api.createSocio(data),
    // The server also provisions the new socio's cuota social row in the same
    // transaction (`routers/socios.py` -> `crear_cuota_social`), so this write
    // touches a membership too, and the new socio immediately lands in the
    // "Solo cuota social" bucket the dashboard counts.
    onSuccess: () => invalidateMembershipWrites(qc),
  });
}

/** Update an existing socio */
export function useUpdateSocio() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<Socio> }) => api.updateSocio(id, data),
    // Socio columns only: the server derives the 4 states from MEMBERSHIP data,
    // so an edit here cannot move a bucket and the dashboard cards stay valid.
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["socios"] });
    },
  });
}

/** Delete a socio */
export function useDeleteSocio() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteSocio(id),
    // The server deletes the socio's memberships with them (promoting a
    // successor Titular first), which changes both the membersía list and the
    // bucket every unit member is counted into. A socio with pagos is refused
    // with a 409, so the receipts list cannot have changed.
    onSuccess: () => invalidateMembershipWrites(qc),
  });
}

/**
 * Upload a socio photo (carnet). On success `tieneFoto` flips in the payloads,
 * so the `socios` cache is invalidated; the object-URL cache is also cleared
 * so the next print refetches the photo.
 */
export function useSubirFoto() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, foto }: { id: string; foto: File }) => api.subirFoto(id, foto),
    onSuccess: () => {
      clearFotosCache();
      qc.invalidateQueries({ queryKey: ["socios"] });
    },
  });
}

/**
 * Remove a socio photo (carnet). Same cache handling as `useSubirFoto`:
 * `tieneFoto` flips back to false, object URLs are revoked.
 */
export function useQuitarFoto() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.quitarFoto(id),
    onSuccess: () => {
      clearFotosCache();
      qc.invalidateQueries({ queryKey: ["socios"] });
    },
  });
}

// ---------------------------------------------------------------------------
// MUTATIONS — Membresias
// ---------------------------------------------------------------------------

/**
 * Invalidates every cache a membership write can move.
 *
 * The 4 socio states are NOT stored: the server derives them from the stored
 * `vencimiento`/`estado` of the cuota social and área memberships on every read
 * (EST-01/EST-02). So any write that changes `estado`, changes `vencimiento`,
 * or removes a membership row can move a socio into a different bucket — the
 * padrón (`Socio.estado`) and the dashboard cards (`estados`) are projections of
 * that derivation, so they have to be refetched together with the membership.
 *
 * Invalidating only `["membresias"]` leaves the operator reading a state the
 * server has already moved: the lista de membresías shows the new `estado` next
 * to a stale badge, and the dashboard card keeps counting the old bucket until
 * its own 15s poll happens to land.
 */
function invalidateMembershipWrites(qc: QueryClient) {
  qc.invalidateQueries({ queryKey: ["membresias"] });
  qc.invalidateQueries({ queryKey: ["socios"] });
  qc.invalidateQueries({ queryKey: ["dashboard"] });
}

/**
 * Invalidates the caches that COUNT socios, for a write that changes how many
 * socios there are or which bucket each one falls in — without editing any
 * membership row itself.
 *
 * `dashboard/stats` derives its four cards by walking EVERY socio
 * (`routers/dashboard.py:63`), and `dashboard/alertas` + the "N a revisar"
 * counter of each area card are projections of the same derivation. So a write
 * that adds or removes a socio moves those numbers even when no membership
 * changed. `Socio activo` / `Solo cuota social` are counts, not filters, and a
 * stale count is exactly the bug the owner reported: the card said one thing and
 * the list another.
 */
function invalidatePadronCounts(qc: QueryClient) {
  qc.invalidateQueries({ queryKey: ["socios"] });
  qc.invalidateQueries({ queryKey: ["dashboard"] });
}

/** Create a new membresia */
export function useCreateMembresia() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Omit<Membresia, "id">) => api.createMembresia(data),
    onSuccess: () => invalidateMembershipWrites(qc),
  });
}

/** Update an existing membresia (estado, vencimiento, etc.) */
export function useUpdateMembresia() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<Membresia> }) =>
      api.updateMembresia(id, data),
    // This is the mutation behind the `estado` selector of the socio ficha and
    // of the membresías table, so it is the one that can flip a socio's bucket.
    onSuccess: () => invalidateMembershipWrites(qc),
  });
}

/** Delete a membresia */
export function useDeleteMembresia() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteMembresia(id),
    onSuccess: () => invalidateMembershipWrites(qc),
  });
}

// ---------------------------------------------------------------------------
// MUTATIONS — Parcelas
// ---------------------------------------------------------------------------

/** Create a new parcela */
export function useCreateParcela() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Omit<Parcela, "id"> & { id: string }) => api.createParcela(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["parcelas"] });
    },
  });
}

/** Update an existing parcela */
export function useUpdateParcela() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<Parcela> }) =>
      api.updateParcela(id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["parcelas"] });
    },
  });
}

/** Delete a parcela */
export function useDeleteParcela() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteParcela(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["parcelas"] });
      // Removing a unit removes its área memberships, so every member of the
      // unit can land in a different socio state.
      invalidateMembershipWrites(qc);
    },
  });
}

// ---------------------------------------------------------------------------
// MUTATIONS — Unidades compartidas (import + batch)
// ---------------------------------------------------------------------------

/** Importa unidades (parcelas + socios + membresías) de forma idempotente. */
export function useImportParcelas() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (payload: ImportPayload) => api.importParcelas(payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["parcelas"] });
      // The import writes socios AND memberships, so it moves socio states too.
      invalidateMembershipWrites(qc);
    },
  });
}

/** Cambia el estado de todas las membresías de una parcela (batch). */
export function useSetBatchEstado() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ parcelaId, estado }: { parcelaId: string; estado: EstadoMembresia }) =>
      api.setBatchEstado(parcelaId, estado),
    onSuccess: () => invalidateMembershipWrites(qc),
  });
}

/** Cambia el vencimiento de todas las membresías de una parcela (batch). */
export function useSetBatchVencimiento() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      parcelaId,
      vencimiento,
      concepto,
    }: {
      parcelaId: string;
      vencimiento: string;
      concepto?: ConceptoMembresia;
    }) => api.setBatchVencimiento(parcelaId, vencimiento, concepto),
    onSuccess: () => invalidateMembershipWrites(qc),
  });
}

/** Edita el vencimiento absoluto de UNA membresía (área | cuota social). */
export function useUpdateMembresiaVencimiento() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, vencimiento }: { id: string; vencimiento: string }) =>
      api.updateMembresiaVencimiento(id, vencimiento),
    onSuccess: () => invalidateMembershipWrites(qc),
  });
}

// ---------------------------------------------------------------------------
// MUTATIONS — Notificaciones
// ---------------------------------------------------------------------------

/** Create notificaciones (batch — one per socio) */
export function useCreateNotificacion() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      socioIds,
      canal,
      motivo,
    }: {
      socioIds: string[];
      canal: "email" | "whatsapp";
      motivo: string;
    }) => {
      const hoy = new Date().toISOString().slice(0, 10);
      const items = socioIds.map((socioId) => ({
        socioId,
        canal,
        fecha: hoy,
        motivo,
        mensaje:
          canal === "email"
            ? "Recordatorio de vencimiento enviado por email."
            : "Mensaje de WhatsApp generado y listo para enviar.",
      }));
      return api.createNotificaciones(items);
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["notificaciones"] });
    },
  });
}

// ---------------------------------------------------------------------------
// MUTATIONS — Aranceles
// ---------------------------------------------------------------------------

/** Create a new arancel */
export function useCreateArancel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: api.CreateArancelInput) => api.createArancel(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["aranceles"] });
    },
  });
}

/** Update an arancel monto (old value is frozen in historico by the backend) */
export function useUpdateArancelMonto() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, monto }: { id: string; monto: number }) => api.updateArancelMonto(id, monto),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["aranceles"] });
    },
  });
}

/** Fully update an arancel (nombre, area, predio, monto, categoria, vigenteDesde) */
export function useUpdateArancel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: api.UpdateArancelInput }) =>
      api.updateArancel(id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["aranceles"] });
    },
  });
}

/** Delete an arancel */
export function useDeleteArancel() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteArancel(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["aranceles"] });
    },
  });
}

// ---------------------------------------------------------------------------
// MUTATIONS — Pagos
// ---------------------------------------------------------------------------

/** Create a pago (payment + membership renewal handled by backend) */
export function useCreatePago() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: api.CreatePagoInput) => api.createPago(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["pagos"] });
      // A charge RENOVES: `services/renovacion.renovar_membresias` rewrites
      // `vencimiento` to max(vencimiento, dia10(hoy)) and forces
      // `estado = 'activa'` on every membership it settles. Those are exactly
      // the two fields `services/estado_socio` derives the 4 socio states from,
      // so charging somebody moves them out of 🔴/⚠️ — the padrón badge and the
      // dashboard cards are stale until their own 15s poll lands, and the
      // operator just watched money go in while the club still looked in debt.
      invalidateMembershipWrites(qc);
      // La renovación puede modificar aranceles aplicables; refrescar en paralelo.
      qc.invalidateQueries({ queryKey: ["aranceles"] });
    },
  });
}

// ---------------------------------------------------------------------------
// MUTATIONS — Import masivo (generic resource-based bulk import)
// ---------------------------------------------------------------------------

/** Upload a file for server-side parse + validation (step 1 -> 2). */
export function usePreviewImport() {
  return useMutation({
    mutationFn: ({ resource, file }: { resource: string; file: File }): Promise<PreviewResult> =>
      api.previewImport(resource, file),
  });
}

/** Execute an import batch from validated rows; refreshes the target cache. */
export function useExecuteImport() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      resource,
      rows,
    }: {
      resource: string;
      rows: RowData[];
    }): Promise<ExecuteResult> => api.executeImport(resource, rows),
    onSuccess: () => {
      // Importing socios links rows to existing socios by DNI and imports
      // memberships, so the padron (a membership makes a socio "activo") and the
      // memberships list change after an execute — and the dashboard cards count
      // both, so they change with them. Refreshing socios+membresias and leaving
      // the cards alone is what made an import look like it had done nothing.
      invalidateMembershipWrites(qc);
    },
  });
}
