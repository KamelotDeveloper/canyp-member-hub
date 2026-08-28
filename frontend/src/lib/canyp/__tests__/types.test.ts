/**
 * Type-level tests for CANYP frontend types.
 *
 * These are compile-time checks — if `tsc --noEmit` passes, the types are correct.
 * No runtime assertions needed; TypeScript IS the test runner here.
 */

import type {
  CategoriaParcela,
  ImportMembresia,
  ImportParcela,
  ImportPayload,
  ImportResponse,
  Membresia,
  PagoItem,
  PagoItemInput,
  Parcela,
  Predio,
  Rol,
  Socio,
  UnidadFiltro,
  UnidadGroup,
} from "../types";

// --- Socio must have `activo: boolean` ---
type SocioHasActivo = Socio["activo"] extends boolean ? true : false;
const _socioActivoCheck: SocioHasActivo = true;

// --- Membresia must have `parcelaId?: string` (NOT `parcela`) ---
type MembresiaHasParcelaId = "parcelaId" extends keyof Membresia ? true : false;
const _membresiaParcelaIdCheck: MembresiaHasParcelaId = true;

// --- Membresia must NOT have a `parcela` field ---
// If this errors, someone added back the old field name
type MembresiaHasParcela = "parcela" extends keyof Membresia ? true : false;
type MembresiaNoParcela = MembresiaHasParcela extends true ? never : true;
const _membresiaNoParcelaCheck: MembresiaNoParcela = true;

// --- Parcela type must exist with expected shape ---
type ParcelaHasId = "id" extends keyof Parcela ? true : false;
type ParcelaHasNombre = "nombre" extends keyof Parcela ? true : false;
type ParcelaHasTipo = "tipo" extends keyof Parcela ? true : false;
type ParcelaHasPredio = "predio" extends keyof Parcela ? true : false;
const _parcelaShapeCheck: ParcelaHasId & ParcelaHasNombre & ParcelaHasTipo & ParcelaHasPredio =
  true;

// --- Predio type must include Embalse and Almafuerte ---
type HasEmbalse = Extract<Predio, "Embalse"> extends never ? false : true;
type HasAlmafuerte = Extract<Predio, "Almafuerte"> extends never ? false : true;
const _predioCheck: HasEmbalse & HasAlmafuerte = true;

// --- Rol must be the unit membership role union ---
const _rolValues: Rol[] = ["Titular", "Integrante"];

// --- CategoriaParcela must include the four cabaña categories ---
const _categorias: CategoriaParcela[] = ["Chica", "Mediana", "Especial", "Grande"];

// --- Membresia must expose the optional rol field ---
type MembresiaHasRol = "rol" extends keyof Membresia ? true : false;
const _membresiaRolCheck: MembresiaHasRol = true;

// --- Parcela must expose the optional categoria field ---
type ParcelaHasCategoria = "categoria" extends keyof Parcela ? true : false;
const _parcelaCategoriaCheck: ParcelaHasCategoria = true;

// --- PagoItem must expose the optional membresiaId field (RQ 14) ---
type PagoItemHasMembresiaId = "membresiaId" extends keyof PagoItem ? true : false;
const _pagoItemMembresiaIdCheck: PagoItemHasMembresiaId = true;

// --- PagoItemInput must carry the per-item membresiaId (backend contract) ---
const _pagoItemInput: PagoItemInput = {
  arancelId: "ar1",
  membresiaId: "m1",
  montoAplicado: 100,
  arancelNombre: "Mensualidad",
};

// --- UnidadFiltro must match the panel filters ---
const _unidadFiltros: UnidadFiltro[] = ["todas", "por_vencer", "vencidas", "alertas"];

// --- UnidadGroup shape ---
const _unidadGroup: UnidadGroup = {
  parcelaId: null,
  nombre: "Sin asignar",
  predio: "Almafuerte",
  categoria: null,
  members: [],
};

// --- Import payload types shape (RQ 8) ---
const _importMiembro: ImportMembresia = { socio: { nombre: "A", dni: "1" }, rol: "Titular" };
const _importParcela: ImportParcela = {
  nombre: "Cabaña E",
  tipo: "cabaña",
  categoria: "Mediana",
  predio: "Almafuerte",
  miembros: [_importMiembro],
};
const _importPayload: ImportPayload = { unidades: [_importParcela] };
const _importResponse: ImportResponse = { parcelas: [], socios: [], membresias: [] };
