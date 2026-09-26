/**
 * Pure helpers for the unidad (cabaña/balsa) dialogs — RQ 6 / RQ 14.
 *
 * Keeping these as pure functions (no React) makes them trivially testable and
 * keeps the dialog components focused on wiring + rendering.
 *
 * - `buildNuevaUnidadPayload` converts the "Nueva unidad" form into an
 *   `ImportPayload` so the backend creates Parcela + socios + membresías
 *   transactionally (RQ 6 / RQ 12). First socio row is the Titular; the rest
 *   are Integrantes.
 * - `itemsPorConcepto` composes ONE payment line per ticked concept (área,
 *   cuota social, servicio, recargo). It replaced the single-item resolvers
 *   `itemsParaMembresias`/`itemsParaMembresiasConParcelas`, which could only
 *   ever bill one arancel for the whole charge (PR 7).
 *
 * Every amount this module produces is a client ESTIMATE: the server re-resolves
 * each line against the catalog and is the only authority over the total.
 */

import type {
  Arancel,
  Area,
  CategoriaParcela,
  ConceptoCobro,
  ConceptoMembresia,
  EstadoSocio,
  ImportMembresia,
  ImportPayload,
  ImportSocio,
  Membresia,
  PagoItemInput,
  ParcelaConMembresias,
  Predio,
  Rol,
  UnidadFiltro,
  UnidadGroup,
} from "./types";
import { ORDEN_ESTADOS } from "./utils";

/** Fila de socio del diálogo "Nueva unidad" (primera = Titular). */
export interface NuevaUnidadSocio {
  nombre: string;
  dni: string;
  telefono?: string;
  email?: string;
}

/**
 * Predio correcto para un tipo de unidad (regla del dominio).
 * Embalse aloja solo balsas; Almafuerte aloja cabañas (y guardería).
 */
export function predioDeTipo(tipo: "cabaña" | "balsa"): Predio {
  return tipo === "balsa" ? "Embalse" : "Almafuerte";
}

/**
 * Indica si una membresía se puede cobrar individualmente en /pagos.
 * Regla del dominio: las unidades (cabañas/balsas) se cobran por el TITULAR,
 * no por integrante — una membresía de unidad solo es cobrable si `rol` es
 * "Titular". Guardería y Windsurf (sin unidad) siempre son cobrables.
 */
export function esMembresiaCobrable(m: Membresia): boolean {
  const esUnidad = m.area === "Cabañeros" || m.area === "Balseros";
  if (esUnidad) return m.rol === "Titular";
  return true;
}

/** Estado del formulario "Nueva unidad" antes de convertirlo a payload. */
export interface NuevaUnidadForm {
  nombre: string;
  tipo: "cabaña" | "balsa";
  categoria?: CategoriaParcela;
  vencimiento: string;
  /** Arancel asignado explícitamente a las membresías de la unidad (opcional). */
  arancelId?: string;
  /** Primera fila → Titular; resto → Integrantes. */
  socios: NuevaUnidadSocio[];
}

/**
 * Convierte el formulario "Nueva unidad" en un `ImportPayload` de una sola
 * unidad. La primera fila de socios recibe rol Titular y las demás Integrante.
 * Devuelve `null` cuando la fila es inválida o no hay socios.
 */
export function buildNuevaUnidadPayload(form: NuevaUnidadForm): ImportPayload | null {
  if (!form.nombre.trim()) return null;
  if (form.socios.length === 0) return null;
  if (!form.socios[0]!.nombre.trim()) return null;

  const vencimiento = form.vencimiento || undefined;
  const miembros: ImportMembresia[] = form.socios.map((s, i) => {
    const rol: Rol = i === 0 ? "Titular" : "Integrante";
    const socio: ImportSocio = {
      nombre: s.nombre.trim(),
      dni: s.dni.trim(),
    };
    const tel = s.telefono?.trim();
    if (tel) socio.telefono = tel;
    const em = s.email?.trim();
    if (em) socio.email = em;
    const m: ImportMembresia = { socio, rol };
    if (vencimiento) m.vencimiento = vencimiento;
    return m;
  });

  const unidad: ImportPayload["unidades"][number] = {
    nombre: form.nombre.trim(),
    tipo: form.tipo,
    predio: predioDeTipo(form.tipo),
    miembros,
  };
  if (form.categoria) unidad.categoria = form.categoria;
  if (form.arancelId) unidad.arancelId = form.arancelId;

  return { unidades: [unidad] };
}

/**
 * Anclas de las líneas de cobro. `PagoItem.membresiaId` es NOT NULL, así que
 * cada concepto necesita una membresía a la que imputarse (CBM-03).
 *
 * Son PISTAS de contabilidad, nunca instrucciones: el servidor vuelve a elegir
 * su propio ancla (`_anchor_cuota` / `_anchor_area` / `_anchor_nea`) y una
 * línea de recargo o servicio no renueva nada aunque lleve un id (REN-01).
 */
export interface AnclasCobro {
  /** Ancla de área; también la de servicio y recargo cuando hay unidad. */
  area?: string | undefined;
  /** Membresía de cuota social del socio; ancla la línea de cuota social. */
  cuota?: string | undefined;
}

/** Una línea de cobro compuesta en el cliente (PAG-01: estimación, NO autoridad). */
export interface LineaCobro {
  concepto: ConceptoCobro;
  arancelId: string;
  arancelNombre: string;
  membresiaId: string;
  /** Estimación del cliente para mostrar mientras se arma el cobro. */
  monto: number;
  /** Multiplicador estimado: 1, o la cantidad de miembros (cuota social). */
  factor: number;
  /** Sólo recargo/servicio: importe a cobrar en ESTE cobro. */
  montoAplicado?: number;
}

export interface OpcionesItemsPorConcepto {
  anclas: AnclasCobro;
  /** Miembros de la unidad gestionada → multiplicador de la cuota social. */
  miembros: number;
  /** Catálogo completo, tal como lo sirve `GET /api/aranceles`. */
  aranceles: Arancel[];
  /** Área+predio+categoría que priced la línea de área; sin unidad no hay línea de área. */
  lugar?: { area: Area; predio: Predio; categoria: CategoriaParcela | null };
  /** Importe tipeado por el operador para el recargo (CBM-03). */
  recargo?: number;
  /** Ajuste del importe de servicio para ESTE cobro (PAG-03). */
  servicio?: number;
}

/**
 * Concepto de un arancel. Una fila sin `concepto` es una fila de área: ese es
 * el default de la columna en la base (`ConceptoCobro.AREA`) y todas las filas
 * anteriores a la migración por concepto lo eran.
 */
function conceptoDeArancel(a: Arancel): ConceptoCobro {
  return a.concepto ?? "area";
}

/**
 * Devuelve la fila de catálogo que priced un concepto, replicando la
 * resolución del servidor (`resolucion.py`):
 *
 * - `area` → arancel de la categoría exacta de la unidad y, si no hay, el
 *   catch-all (`categoria` null) del mismo área+predio.
 * - cualquier otro concepto → la fila etiquetada con ese concepto, ignorando
 *   área y predio (esas filas guardan valores placeholder porque las columnas
 *   son NOT NULL). Ante varias, gana la de menor id, igual que en el servidor.
 *
 * Nunca devuelve nada por coincidencia de texto: el concepto es la clave.
 */
export function arancelPorConcepto(
  aranceles: Arancel[],
  concepto: ConceptoCobro,
  lugar?: { area: Area; predio: Predio; categoria: CategoriaParcela | null },
): Arancel | undefined {
  if (concepto !== "area") {
    return primeraPorId((a) => conceptoDeArancel(a) === concepto && a.categoria == null, aranceles);
  }
  if (!lugar) return undefined;
  if (lugar.categoria) {
    const exacta = aranceles.find(
      (a) =>
        conceptoDeArancel(a) === "area" &&
        a.area === lugar.area &&
        a.predio === lugar.predio &&
        a.categoria === lugar.categoria,
    );
    if (exacta) return exacta;
  }
  return primeraPorId(
    (a) =>
      conceptoDeArancel(a) === "area" &&
      a.area === lugar.area &&
      a.predio === lugar.predio &&
      a.categoria == null,
    aranceles,
  );
}

/** Primera fila que cumple el predicado, por id ascendente (determinismo). */
function primeraPorId(match: (a: Arancel) => boolean, aranceles: Arancel[]): Arancel | undefined {
  return [...aranceles].filter(match).sort((x, y) => (x.id < y.id ? -1 : 1))[0];
}

/**
 * Compone UN ítem por cada concepto marcado por el operador (CBM-02).
 *
 * El cliente propone el desglose y el `montoAplicado` viaja como PISTA: el
 * servidor re-resuelve cada línea contra el catálogo y es la única autoridad
 * del total (PAG-01). Lo que se replica acá es la FORMA de la línea, para que
 * el total que ve el operador sea el mismo que va a cobrar el servidor:
 *
 * - `area` → monto de catálogo, factor 1 (una balsa no se multiplica por
 *   integrantes). Sin arancel de área la línea se cae, igual que el servidor.
 * - `cuota social` → precio de UN miembro × cantidad de miembros de la unidad.
 * - `servicio` → precio de catálogo (o el ajuste del operador para este cobro),
 *   factor 1: los servicios se cobran por unidad, no por integrante.
 * - `recargo` → el importe tipeado. Sin importe mayor a 0 la línea se cae, en
 *   lugar de dejar que el servidor la rechace con un 422.
 *
 * Una línea sin ancla o sin fila de catálogo no se emite; devolver un array
 * vacío es justamente lo que deja el botón de confirmar deshabilitado.
 */
export function itemsPorConcepto(
  conceptos: readonly ConceptoCobro[],
  o: OpcionesItemsPorConcepto,
): LineaCobro[] {
  const lineas: LineaCobro[] = [];
  for (const concepto of conceptos) {
    const membresiaId = concepto === "cuota social" ? o.anclas.cuota : o.anclas.area;
    if (!membresiaId) continue;
    const arancel = arancelPorConcepto(o.aranceles, concepto, o.lugar);
    if (!arancel) continue;

    if (concepto === "recargo") {
      const monto = o.recargo ?? 0;
      if (monto <= 0) continue;
      lineas.push({
        concepto,
        arancelId: arancel.id,
        arancelNombre: arancel.nombre,
        membresiaId,
        monto,
        factor: 1,
        montoAplicado: monto,
      });
      continue;
    }

    if (concepto === "servicio") {
      const monto = o.servicio ?? arancel.monto;
      if (monto <= 0) continue;
      lineas.push({
        concepto,
        arancelId: arancel.id,
        arancelNombre: arancel.nombre,
        membresiaId,
        monto,
        factor: 1,
        // El importe de catálogo no necesita viajar: el servidor ya lo usa
        // cuando el ítem no trae montoAplicado. Sólo se manda si se ajustó.
        ...(monto !== arancel.monto ? { montoAplicado: monto } : {}),
      });
      continue;
    }

    const factor = concepto === "cuota social" ? Math.max(1, o.miembros) : 1;
    lineas.push({
      concepto,
      arancelId: arancel.id,
      arancelNombre: arancel.nombre,
      membresiaId,
      monto: arancel.monto * factor,
      factor,
    });
  }
  return lineas;
}

/** Total estimado de las líneas compuestas; el servidor recalcula el suyo. */
export function totalEstimado(lineas: LineaCobro[]): number {
  return lineas.reduce((s, l) => s + l.monto, 0);
}

/**
 * Convierte una línea compuesta en el ítem que viaja al backend (PAG-01 / 5a).
 *
 * `montoAplicado` solo se envía cuando el operador fijó un importe para ESTE
 * cobro: el recargo (siempre) y el servicio (solo si se ajustó el catálogo).
 * Para área y cuota social el servidor ignora el valor y usa el catálogo; para
 * un servicio sin ajuste prefiere su propio catálogo vigente, así que omitirlo
 * evita congelar un precio de catálogo ya desactualizado (decision #646).
 */
export function lineaAPagoItem(l: LineaCobro): PagoItemInput {
  return {
    arancelId: l.arancelId,
    membresiaId: l.membresiaId,
    ...(l.montoAplicado != null ? { montoAplicado: l.montoAplicado } : {}),
    arancelNombre: l.arancelNombre,
    concepto: l.concepto,
  };
}

/**
 * Conceptos que se pueden ofrecer para un socio (PAG-01 / CS-05).
 *
 * - `cuota social` solo si el socio tiene la membresía: sin ella el servidor
 *   rechaza el cobro con un 422, así que no se ofrece.
 * - `area` solo si hay una membresía de área que no sea Windsurf.
 * - `servicio` y `recargo` solo si el catálogo tiene la fila que los priced,
 *   para no ofrecer un tick que no puede cobrarse.
 * - Un socio de Windsurf (sin otra área) cobra CUOTA SOCIAL y nada más.
 */
export function conceptosDisponibles(
  membresias: Membresia[],
  aranceles: Arancel[],
): ConceptoCobro[] {
  const hayCuota = membresias.some((m) => conceptoDeMembresia(m) === "cuota social");
  const hayArea = membresias.some(
    (m) => conceptoDeMembresia(m) === "area" && m.area !== "Windsurf",
  );
  // El área identifica a Windsurf, no el concepto: una membresía de Windsurf ES
  // una cuota social (CS-05), así que buscar sólo por concepto no la distingue
  // de un socio que sólo tiene cuota social (CS-06).
  const soloWindsurf = !hayArea && membresias.some((m) => m.area === "Windsurf");

  const disponibles: ConceptoCobro[] = [];
  if (hayCuota) disponibles.push("cuota social");
  if (hayArea) disponibles.push("area");
  if (soloWindsurf) return disponibles;
  if (arancelPorConcepto(aranceles, "servicio")) disponibles.push("servicio");
  if (arancelPorConcepto(aranceles, "recargo")) disponibles.push("recargo");
  return disponibles;
}

/** Concepto de una membresía; sin `concepto` servido, un área es un área. */
export function conceptoDeMembresia(m: Membresia): ConceptoMembresia {
  return m.concepto ?? "area";
}

// ---------------------------------------------------------------------------
// Estado crítico de una unidad + filtros (EST-01)
// ---------------------------------------------------------------------------

/**
 * Estado más urgente de una lista de estados SERVIDOS por el backend (EST-01).
 *
 * No deriva nada: recibe los `EstadoSocio` que ya calculó el servidor y devuelve
 * el más severo según `ORDEN_ESTADOS`. Un grupo sin miembros (o sin estados
 * cargados) cae a "Socio activo", el estado menos alarmante.
 */
export function estadoCriticoDe(estados: readonly EstadoSocio[]): EstadoSocio {
  for (const e of ORDEN_ESTADOS) {
    if (estados.includes(e)) return e;
  }
  return "Socio activo";
}

/**
 * Estado de cada unidad (`parcelaId → EstadoSocio`) tal como lo sirve el panel
 * (D5): el peor `estadoSocio` entre los miembros de la unidad. El servidor ya
 * scopó cada `estadoSocio` a la unidad (`areas_por_unidad`), así que acá solo se
 * agrega lo servido — nunca se re-deriva la regla de vencimiento (EST-04).
 */
export function estadoSocioPorParcela(
  parcelas: readonly ParcelaConMembresias[],
): Map<string, EstadoSocio> {
  const map = new Map<string, EstadoSocio>();
  for (const p of parcelas) {
    map.set(p.parcela.id, estadoCriticoDe(p.membresias.map((m) => m.estadoSocio)));
  }
  return map;
}

/**
 * Filtra una lista de unidades según el estado crítico de cada una (servido, no
 * recalculado). `estadoDe` extrae el estado crítico de un grupo — el llamador lo
 * construye a partir de los estados que sirvió el backend.
 *
 * - `todas`: no filtra.
 * - `vencidas`: estado 🔴 "Inactivo — revisar".
 * - `alertas`: estado 🔴 "Inactivo — revisar" o ⚠️ "Socio activo — revisar".
 */
export function filtrarUnidades(
  grupos: UnidadGroup[],
  filtro: UnidadFiltro,
  estadoDe: (g: UnidadGroup) => EstadoSocio,
): UnidadGroup[] {
  return grupos.filter((g) => {
    const e = estadoDe(g);
    if (filtro === "vencidas") return e === "Inactivo — revisar";
    if (filtro === "alertas") return e === "Inactivo — revisar" || e === "Socio activo — revisar";
    return true;
  });
}
