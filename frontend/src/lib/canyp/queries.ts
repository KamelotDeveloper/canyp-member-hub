/**
 * CANYP TanStack Query hooks — wraps api.ts with cache management.
 *
 * Each query hook maps to a GET endpoint.
 * Each mutation hook wraps a POST/PUT/DELETE and invalidates relevant caches on success.
 */

import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import * as api from "./api";
import type {
  EstadoMembresia,
  ExecuteResult,
  ImportPayload,
  Membresia,
  Notificacion,
  Parcela,
  PreviewResult,
  RowData,
  Socio,
} from "./types";

// ---------------------------------------------------------------------------
// QUERIES
// ---------------------------------------------------------------------------

/** List all socios, optionally filtered by search term */
export function useSocios(params?: { search?: string }) {
  return useQuery({
    queryKey: ["socios", params],
    queryFn: () => api.getSocios(params),
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

/** List aranceles, optionally filtered by predio */
export function useAranceles(params?: { predio?: string; area?: string }) {
  return useQuery({
    queryKey: ["aranceles", params],
    queryFn: () => api.getAranceles(params),
  });
}

/** List pagos, optionally filtered by socio */
export function usePagos(socioId?: string) {
  return useQuery({
    queryKey: ["pagos", socioId],
    queryFn: () => api.getPagos(socioId ? { socioId } : undefined),
  });
}

/** List notificaciones, optionally filtered by socio */
export function useNotificaciones(socioId?: string) {
  return useQuery({
    queryKey: ["notificaciones", socioId],
    queryFn: () => api.getNotificaciones(socioId ? { socioId } : undefined),
  });
}

/** Dashboard stats from the backend */
export function useDashboardStats() {
  return useQuery({
    queryKey: ["dashboard", "stats"],
    queryFn: api.getDashboardStats,
  });
}

/** Dashboard alerts — membresias vencidas / por vencer */
export function useDashboardAlertas() {
  return useQuery({
    queryKey: ["dashboard", "alertas"],
    queryFn: api.getDashboardAlertas,
  });
}

/** List parcelas, optionally filtered by predio */
export function useParcelas(predio?: string) {
  return useQuery({
    queryKey: ["parcelas", predio],
    queryFn: () => api.getParcelas(predio ? { predio } : undefined),
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
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["socios"] });
    },
  });
}

/** Update an existing socio */
export function useUpdateSocio() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<Socio> }) => api.updateSocio(id, data),
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
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["socios"] });
      qc.invalidateQueries({ queryKey: ["membresias"] });
    },
  });
}

// ---------------------------------------------------------------------------
// MUTATIONS — Membresias
// ---------------------------------------------------------------------------

/** Create a new membresia */
export function useCreateMembresia() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: Omit<Membresia, "id">) => api.createMembresia(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["membresias"] });
    },
  });
}

/** Update an existing membresia (estado, vencimiento, etc.) */
export function useUpdateMembresia() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<Membresia> }) =>
      api.updateMembresia(id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["membresias"] });
    },
  });
}

/** Delete a membresia */
export function useDeleteMembresia() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => api.deleteMembresia(id),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["membresias"] });
    },
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
      qc.invalidateQueries({ queryKey: ["membresias"] });
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
      qc.invalidateQueries({ queryKey: ["membresias"] });
      qc.invalidateQueries({ queryKey: ["socios"] });
    },
  });
}

/** Cambia el estado de todas las membresías de una parcela (batch). */
export function useSetBatchEstado() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ parcelaId, estado }: { parcelaId: string; estado: EstadoMembresia }) =>
      api.setBatchEstado(parcelaId, estado),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["membresias"] });
    },
  });
}

/** Cambia el vencimiento de todas las membresías de una parcela (batch). */
export function useSetBatchVencimiento() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ parcelaId, vencimiento }: { parcelaId: string; vencimiento: string }) =>
      api.setBatchVencimiento(parcelaId, vencimiento),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["membresias"] });
    },
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
      qc.invalidateQueries({ queryKey: ["membresias"] });
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
      // Importing membresias links rows to existing socios by DNI, so both the
      // padron (a membership makes a socio "activo") and the memberships list
      // change after an execute — refresh both caches.
      qc.invalidateQueries({ queryKey: ["socios"] });
      qc.invalidateQueries({ queryKey: ["membresias"] });
    },
  });
}
