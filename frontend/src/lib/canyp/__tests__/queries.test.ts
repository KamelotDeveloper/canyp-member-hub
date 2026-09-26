/**
 * Compile-time tests for CANYP TanStack Query hooks.
 *
 * RED PHASE: This test FAILS until queries.ts is implemented with all exports.
 * If `tsc --noEmit` passes after implementation, all hooks exist with correct signatures.
 */

import { it, expect } from "vitest";
import {
  useSocios,
  useSocio,
  useMembresias,
  useMembresia,
  useAranceles,
  usePagos,
  useNotificaciones,
  useDashboardStats,
  useDashboardAlertas,
  useParcelas,
  useCreateSocio,
  useUpdateSocio,
  useDeleteSocio,
  useCreateMembresia,
  useUpdateMembresia,
  useDeleteMembresia,
  useCreateParcela,
  useUpdateParcela,
  useDeleteParcela,
  useCreateNotificacion,
  useCreatePago,
  useImportParcelas,
  useSetBatchEstado,
  useSetBatchVencimiento,
  useSubirFoto,
} from "../queries";

import type {
  Socio,
  Membresia,
  Arancel,
  Pago,
  Notificacion,
  Parcela,
  ImportPayload,
  ImportResponse,
  EstadoMembresia,
  ConceptoMembresia,
} from "../types";
import type { UseQueryResult, UseMutationResult } from "@tanstack/react-query";

// --- Query hooks must return UseQueryResult ---

type UseSociosReturns = ReturnType<typeof useSocios>;
type IsSociosQuery = UseSociosReturns extends UseQueryResult<Socio[]> ? true : false;
const _useSociosCheck: IsSociosQuery = true;

type UseSocioReturns = ReturnType<typeof useSocio>;
type IsSocioQuery = UseSocioReturns extends UseQueryResult<Socio> ? true : false;
const _useSocioCheck: IsSocioQuery = true;

type UseMembresiasReturns = ReturnType<typeof useMembresias>;
type IsMembresiasQuery = UseMembresiasReturns extends UseQueryResult<Membresia[]> ? true : false;
const _useMembresiasCheck: IsMembresiasQuery = true;

type UseArancelesReturns = ReturnType<typeof useAranceles>;
type IsArancelesQuery = UseArancelesReturns extends UseQueryResult<Arancel[]> ? true : false;
const _useArancelesCheck: IsArancelesQuery = true;

type UsePagosReturns = ReturnType<typeof usePagos>;
type IsPagosQuery = UsePagosReturns extends UseQueryResult<Pago[]> ? true : false;
const _usePagosCheck: IsPagosQuery = true;

type UseNotificacionesReturns = ReturnType<typeof useNotificaciones>;
type IsNotificacionesQuery =
  UseNotificacionesReturns extends UseQueryResult<Notificacion[]> ? true : false;
const _useNotificacionesCheck: IsNotificacionesQuery = true;

type UseParcelasReturns = ReturnType<typeof useParcelas>;
type IsParcelasQuery = UseParcelasReturns extends UseQueryResult<Parcela[]> ? true : false;
const _useParcelasCheck: IsParcelasQuery = true;

// --- Mutation hooks must return UseMutationResult ---

type UseCreateSocioReturns = ReturnType<typeof useCreateSocio>;
type IsCreateSocioMutation =
  UseCreateSocioReturns extends UseMutationResult<Socio, unknown, Omit<Socio, "id" | "fechaAlta">>
    ? true
    : false;
const _useCreateSocioCheck: IsCreateSocioMutation = true;

type UseUpdateSocioReturns = ReturnType<typeof useUpdateSocio>;
type IsUpdateSocioMutation =
  UseUpdateSocioReturns extends UseMutationResult<
    Socio,
    unknown,
    { id: string; data: Partial<Socio> }
  >
    ? true
    : false;
const _useUpdateSocioCheck: IsUpdateSocioMutation = true;

type UseDeleteSocioReturns = ReturnType<typeof useDeleteSocio>;
type IsDeleteSocioMutation =
  UseDeleteSocioReturns extends UseMutationResult<void, unknown, string> ? true : false;
const _useDeleteSocioCheck: IsDeleteSocioMutation = true;

type UseCreateMembresiaReturns = ReturnType<typeof useCreateMembresia>;
type IsCreateMembresiaMutation =
  UseCreateMembresiaReturns extends UseMutationResult<Membresia, unknown, Omit<Membresia, "id">>
    ? true
    : false;
const _useCreateMembresiaCheck: IsCreateMembresiaMutation = true;

type UseUpdateMembresiaReturns = ReturnType<typeof useUpdateMembresia>;
type IsUpdateMembresiaMutation =
  UseUpdateMembresiaReturns extends UseMutationResult<
    Membresia,
    unknown,
    { id: string; data: Partial<Membresia> }
  >
    ? true
    : false;
const _useUpdateMembresiaCheck: IsUpdateMembresiaMutation = true;

type UseDeleteMembresiaReturns = ReturnType<typeof useDeleteMembresia>;
type IsDeleteMembresiaMutation =
  UseDeleteMembresiaReturns extends UseMutationResult<void, unknown, string> ? true : false;
const _useDeleteMembresiaCheck: IsDeleteMembresiaMutation = true;

type UseCreateParcelaReturns = ReturnType<typeof useCreateParcela>;
type IsCreateParcelaMutation =
  UseCreateParcelaReturns extends UseMutationResult<
    Parcela,
    unknown,
    Omit<Parcela, "id"> & { id: string }
  >
    ? true
    : false;
const _useCreateParcelaCheck: IsCreateParcelaMutation = true;

type UseUpdateParcelaReturns = ReturnType<typeof useUpdateParcela>;
type IsUpdateParcelaMutation =
  UseUpdateParcelaReturns extends UseMutationResult<
    Parcela,
    unknown,
    { id: string; data: Partial<Parcela> }
  >
    ? true
    : false;
const _useUpdateParcelaCheck: IsUpdateParcelaMutation = true;

type UseDeleteParcelaReturns = ReturnType<typeof useDeleteParcela>;
type IsDeleteParcelaMutation =
  UseDeleteParcelaReturns extends UseMutationResult<void, unknown, string> ? true : false;
const _useDeleteParcelaCheck: IsDeleteParcelaMutation = true;

type UseCreateNotificacionReturns = ReturnType<typeof useCreateNotificacion>;
type IsCreateNotificacionMutation =
  UseCreateNotificacionReturns extends UseMutationResult<
    Notificacion[],
    unknown,
    { socioIds: string[]; canal: "email" | "whatsapp"; motivo: string }
  >
    ? true
    : false;
const _useCreateNotificacionCheck: IsCreateNotificacionMutation = true;

import type { CreatePagoInput } from "../api";

type UseCreatePagoReturns = ReturnType<typeof useCreatePago>;
type IsCreatePagoMutation =
  UseCreatePagoReturns extends UseMutationResult<Pago, unknown, CreatePagoInput> ? true : false;
const _useCreatePagoCheck: IsCreatePagoMutation = true;

// --- Unidades compartidas mutations (PR 3) ---

type UseImportParcelasReturns = ReturnType<typeof useImportParcelas>;
type IsImportParcelasMutation =
  UseImportParcelasReturns extends UseMutationResult<ImportResponse, unknown, ImportPayload>
    ? true
    : false;
const _useImportParcelasCheck: IsImportParcelasMutation = true;

type UseSetBatchEstadoReturns = ReturnType<typeof useSetBatchEstado>;
type IsSetBatchEstadoMutation =
  UseSetBatchEstadoReturns extends UseMutationResult<
    unknown,
    unknown,
    { parcelaId: string; estado: EstadoMembresia }
  >
    ? true
    : false;
const _useSetBatchEstadoCheck: IsSetBatchEstadoMutation = true;

type UseSetBatchVencimientoReturns = ReturnType<typeof useSetBatchVencimiento>;
type IsSetBatchVencimientoMutation =
  UseSetBatchVencimientoReturns extends UseMutationResult<
    unknown,
    unknown,
    { parcelaId: string; vencimiento: string; concepto?: ConceptoMembresia }
  >
    ? true
    : false;
const _useSetBatchVencimientoCheck: IsSetBatchVencimientoMutation = true;

// --- Carnet foto mutation (subirFoto) ---

type UseSubirFotoReturns = ReturnType<typeof useSubirFoto>;
type IsSubirFotoMutation =
  UseSubirFotoReturns extends UseMutationResult<
    { tieneFoto: boolean },
    unknown,
    { id: string; foto: File }
  >
    ? true
    : false;
const _useSubirFotoCheck: IsSubirFotoMutation = true;

it("hook type-level checks compile (runtime smoke)", () => {
  expect(typeof useSetBatchEstado).toBe("function");
  expect(typeof useCreatePago).toBe("function");
  expect(typeof useSubirFoto).toBe("function");
});
