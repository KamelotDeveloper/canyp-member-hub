export type Predio = "Embalse" | "Almafuerte";
export type Area = "Balseros" | "Cabañeros" | "Guardería" | "Windsurf";
export type EstadoMembresia = "activa" | "suspendida" | "vencida" | "baja";

/** Rol de un miembro dentro de una unidad compartida (cabaña/balsa). */
export type Rol = "Titular" | "Integrante";

/** Categoría de una parcela (cabañas: Chica/Mediana/Especial/Grande; balsas: null). */
export type CategoriaParcela = "Chica" | "Mediana" | "Especial" | "Grande";

export interface Socio {
  id: string;
  nombre: string;
  dni: string;
  telefono: string;
  email: string;
  direccion: string;
  fechaAlta: string;
  activo: boolean;
}

export interface Membresia {
  id: string;
  socioId: string;
  area: Area;
  predio: Predio;
  estado: EstadoMembresia;
  vencimiento: string;
  detalle?: string;
  /** Rol dentro de una unidad compartida (Titular/Integrante), null fuera de unidades. */
  rol?: Rol;
  /** Parcela / cabaña compartida (área Cabañeros) */
  parcelaId?: string;
}

export interface Arancel {
  id: string;
  nombre: string;
  area: Area;
  predio: Predio;
  monto: number;
  /** Categoría a la que aplica; null = catch-all para el área+predio. */
  categoria?: CategoriaParcela;
  vigenteDesde: string;
  historico: { monto: number; vigenteDesde: string }[];
}

export interface PagoItem {
  arancelId: string;
  nombre: string;
  monto: number;
  /** Membresía que renueva este ítem (presente en pagos de unidades compartidas). */
  membresiaId?: string;
}

/** Ítem de pago tal como lo espera el backend al crear un Pago (RQ 14 multi-membresía). */
export interface PagoItemInput {
  arancelId: string;
  membresiaId: string;
  montoAplicado: number;
  arancelNombre: string;
}

export interface Pago {
  id: string;
  numero: string;
  socioId: string;
  fecha: string;
  medio: string;
  nota?: string;
  items: PagoItem[];
  total: number;
  membresiaIds: string[];
}

export interface Notificacion {
  id: string;
  socioId: string;
  canal: "email" | "whatsapp";
  fecha: string;
  motivo: string;
  mensaje: string;
}

export interface Parcela {
  id: string;
  nombre: string;
  tipo: "cabaña" | "balsa" | "guardería";
  tamano?: string;
  predio: Predio;
  /** Categoría (cabañas y guardería); null para balsas. */
  categoria?: CategoriaParcela;
}

// ---------------------------------------------------------------------------
// Unidades compartidas (cabañas/balsas) — grouping + filters
// ---------------------------------------------------------------------------

/** Filtros disponibles para el UnidadesPanel. */
export type UnidadFiltro = "todas" | "por_vencer" | "vencidas" | "alertas";

/** Unidad agrupada (una cabaña/balsa o el grupo "Sin asignar"). */
export interface UnidadGroup {
  /** parcelaId de la unidad; null → grupo "Sin asignar". */
  parcelaId: string | null;
  /** Nombre legible de la unidad (del registro Parcela, "Sin asignar" si no hay). */
  nombre: string;
  predio: Predio;
  /** Categoría de la unidad; null para balsas. */
  categoria: CategoriaParcela | null;
  /** Membresías que componen la unidad. */
  members: Membresia[];
}

// ---------------------------------------------------------------------------
// Import de unidades (POST /api/parcelas/import)
// ---------------------------------------------------------------------------

export interface ImportSocio {
  nombre: string;
  dni: string;
  telefono?: string;
  email?: string;
}

export interface ImportMembresia {
  socio: ImportSocio;
  rol: Rol;
  vencimiento?: string;
}

export interface ImportParcela {
  nombre: string;
  tipo: "cabaña" | "balsa" | "guardería";
  categoria?: CategoriaParcela;
  predio: Predio;
  miembros: ImportMembresia[];
}

export interface ImportPayload {
  unidades: ImportParcela[];
}

export interface ImportResponse {
  parcelas: string[];
  socios: string[];
  membresias: string[];
}
