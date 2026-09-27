export type Predio = "Embalse" | "Almafuerte";
export type Area = "Balseros" | "Cabañeros" | "Guardería" | "Windsurf";
export type EstadoMembresia = "activa" | "suspendida" | "vencida" | "baja";

/**
 * Los 4 estados de socio servidos por el backend (EST-01).
 *
 * El string ES la nominación exacta de UI (UI-04), em dash incluido: el
 * frontend nunca la arma ni la parafrasea, la muestra tal cual viene.
 */
export type EstadoSocio =
  "Socio activo" | "Socio activo — revisar" | "Inactivo — revisar" | "Solo cuota social";

/**
 * Vocabulario de conceptos de cobro servido por el backend (CBM-04).
 *
 * `area` y `cuota social` renuevan membresías; `recargo` y `servicio` son
 * líneas de importe y NO renuevan nada (REN-01). El cliente no lo deriva:
 * lo lee del `concepto` que el servidor agrega a cada respuesta.
 */
export type ConceptoCobro = "area" | "cuota social" | "recargo" | "servicio";

/** Concepto de una membresía (MEM-01): área o cuota social. */
export type ConceptoMembresia = "area" | "cuota social";

/** Modo de datos de la app: "local" (SQLite) o "remoto" (PostgreSQL/Supabase). */
export type DataMode = "local" | "remoto";

export interface AppSettings {
  dataMode: DataMode;
  databaseUrl: string;
  /** Falso hasta que el wizard de primer uso (o Ajustes) guardó una elección. */
  configured: boolean;
}

/** Usuario del sistema (autenticación). Nunca expone password_hash. */
export interface Usuario {
  id: string;
  username: string;
  created_at: string;
}

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
  /** Categoría libre ("activo" | "vitalicio"); null cuando no se definió. */
  categoria?: string | null;
  /** Número de socio secuencial (carnet); null hasta que el backend lo asigna. */
  numeroSocio: string | null;
  /** Indica si el socio tiene foto cargada (bytes NUNCA viajan en los listados). */
  tieneFoto: boolean;
  /** Usuario que creó el registro; null en importes masivos (sin operador). */
  createdBy?: string | null;
  updatedBy?: string | null;
  /**
   * Estado de socio servido por el backend (EST-01). Opcional a propósito: no
   * viaja en el alta ni en la edición (lo computa el servidor y solo se sirve
   * en las lecturas). `nominacion` es el mismo string exacto de UI (em dash
   * incluido, UI-04); el frontend nunca lo arma ni lo parafrasea.
   */
  estado?: EstadoSocio;
  nominacion?: string;
}

export interface Membresia {
  id: string;
  socioId: string;
  /**
   * `area`/`predio` son null en una membresía de cuota social: no es un lugar
   * físico (CS-01). El frontend lo lee del servidor y no lo re-deriva.
   */
  area: Area | null;
  predio: Predio | null;
  estado: EstadoMembresia;
  vencimiento: string;
  detalle?: string;
  /** Rol dentro de una unidad compartida (Titular/Integrante), null fuera de unidades. */
  rol?: Rol;
  /** Parcela / cabaña compartida (área Cabañeros) */
  parcelaId?: string;
  /** Arancel asignado explícitamente (null = resolver por heurística area+predio+categoria). */
  arancelId?: string;
  /**
   * Concepto servido por el backend (MEM-01). Opcional: las respuestas
   * previas a la migración no lo traen y el área sigue siendo la fuente
   * de verdad para las superficies que no son de cobro.
   */
  concepto?: ConceptoMembresia | undefined;
  createdBy?: string | null;
  updatedBy?: string | null;
}

export interface Arancel {
  id: string;
  nombre: string;
  area: Area;
  predio: Predio;
  monto: number;
  /** Categoría a la que aplica; null = catch-all para el área+predio. */
  categoria?: CategoriaParcela;
  /** Concepto de catálogo (CBM-01); define a qué ítem puede resolver este arancel. */
  concepto?: ConceptoCobro | undefined;
  vigenteDesde: string;
  historico: { monto: number; vigenteDesde: string }[];
  createdBy?: string | null;
  updatedBy?: string | null;
}

export interface PagoItem {
  arancelId: string;
  nombre: string;
  monto: number;
  /** Membresía que renueva este ítem (presente en pagos de unidades compartidas). */
  membresiaId?: string;
  /** Concepto resuelto por el servidor; el enviado por el cliente es solo una pista. */
  concepto?: ConceptoCobro | null;
  /** Multiplicador resuelto por el servidor (balsa = 1, cuota social = miembros). */
  factor?: number | null;
}

/** Ítem de pago tal como lo espera el backend al crear un Pago (RQ 14 multi-membresía). */
export interface PagoItemInput {
  arancelId: string;
  membresiaId: string;
  /**
   * Importe que el operador fijó para ESTE cobro. Solo viaja para el recargo
   * (siempre) y para el servicio (solo si se ajustó). Para área y cuota social
   * el servidor ignora el valor y usa el catálogo; para un servicio sin ajuste
   * prefiere su propio catálogo vigente. Omitirlo evita congelar un precio de
   * catálogo ya desactualizado (decision #646, debt 5a).
   */
  montoAplicado?: number;
  arancelNombre: string;
  /** Pista de concepto; el servidor lo re-resuelve contra el catálogo. */
  concepto?: ConceptoCobro;
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
  createdBy?: string | null;
  updatedBy?: string | null;
  /**
   * Avisos de resolución del POST /api/pagos (D8, ReQ-011): lista los
   * `arancelId` enviados que el servidor tuvo que reemplazar por el precio del
   * lugar de la unidad. El cobro se registra igual — el aviso no bloquea nada.
   * Opcional a propósito: viaja SOLO en la respuesta del POST, un GET no lo trae.
   */
  avisos?: string[];
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

/** Filtros disponibles para el UnidadesPanel (el 30-day `por_vencer` ya no existe, EST-04). */
export type UnidadFiltro = "todas" | "vencidas" | "alertas";

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

/** Miembro de una unidad tal como lo sirve GET /api/membresias/parcelas. */
export interface ParcelaMiembro {
  id: string;
  socioId: string;
  area: Area | null;
  predio: Predio | null;
  estado: EstadoMembresia;
  vencimiento: string;
  rol?: Rol | null;
  detalle?: string | null;
  /**
   * Estado del socio SCOPED a la unidad (D5): el servidor ya marca ⚠️ a TODOS
   * los miembros cuando cualquier área de la unidad está vencida. El panel solo
   * lo agrega (peor `estadoSocio` por unidad), nunca deriva la regla de fechas.
   */
  estadoSocio: EstadoSocio;
  nominacion?: string;
}

/** Una parcela + sus miembros, tal como lo sirve GET /api/membresias/parcelas. */
export interface ParcelaConMembresias {
  parcela: Parcela;
  membresias: ParcelaMiembro[];
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
  arancelId?: string;
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

// ---------------------------------------------------------------------------
// Import masivo (generic 3-step data import engine, backend-authoritative)
// Shapes mirror backend/schemas/import_bulk.py (OrmConfig camelCase in JSON).
// ---------------------------------------------------------------------------

/** Mapped headers: source header text -> canonical field (mirrors dict[str,str]). */
export type HeadersMapping = Record<string, string>;

/** A single per-row, per-field validation error. */
export interface FieldError {
  fila: number;
  campo: string;
  error: string;
}

/** A single row sent for execution; client edits canonical fields and may skip. */
export interface RowData {
  skip?: boolean;
  /** Canonical camelCase fields of the resource's row schema. */
  data: Record<string, unknown>;
}

/** Aggregate statistics for a preview. */
export interface ImportStats {
  total: number;
  validas: number;
  conErrores: number;
  aSaltar: number;
}

/** Canonical preview response: mapped columns, rows, warnings, stats, errors. */
export interface PreviewResult {
  resource: string;
  /** Detected header -> canonical field. */
  columns: HeadersMapping;
  ignoredColumns: string[];
  /** Canonical normalized rows (flat field dicts; client wraps into RowData to execute). */
  rows: Record<string, unknown>[];
  stats: ImportStats;
  errors: FieldError[];
}

/** Per-row execute outcome. */
export interface ExecuteRow {
  fila: number;
  outcome: "importado" | "fallido" | "omitido";
  id?: string;
  errores: FieldError[];
}

/** Canonical execute response. */
export interface ExecuteResult {
  importados: number;
  fallidos: number;
  omitidos: number;
  rows: ExecuteRow[];
}

// ---------------------------------------------------------------------------
// Dashboard — estados + alertas servidos (EST-01 / GET /api/dashboard/*)
// ---------------------------------------------------------------------------

/** Conteos del dashboard servidos por GET /api/dashboard/stats. */
export interface DashboardStats {
  totalMembresias: number;
  countsByArea: Record<string, number>;
  /** Los 4 estados de socio, cada uno con su conteo (siempre las 4 claves). */
  estados: Record<EstadoSocio, number>;
}

/**
 * Fila de alerta del dashboard: una membresía vencida/suspendida + el estado de
 * SU socio (`estadoSocio`), tal como lo sirve GET /api/dashboard/alertas.
 */
export interface DashboardAlerta {
  id: string;
  socioId: string;
  area: Area | null;
  predio: Predio | null;
  estado: EstadoMembresia;
  vencimiento: string;
  estadoSocio: EstadoSocio;
  nominacion: string;
}
