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
 * - `itemsPorArancel` composes ONE payment line per ticked `arancelId` (ReQ-001
 *   / ReQ-012). Keying by the catalog row instead of the concept is what lets
 *   two apartes of the same place be two independent lines.
 * - `arancelesDisponibles` lists the catalog rows a charge may tick for a set of
 *   places, and `membresiaDeLugar` finds the membership that anchors a place so
 *   every line imputes to its own unit, never the titular's (ReQ-004).
 * - `formatearAvisosCobro` turns the server's resolution warnings (D8, ReQ-011)
 *   into the one line the cobro dialogs show the operator.
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
 * Lugar físico de una membresía: la pareja área+predio y, para `area`, la
 * categoría de la parcela.
 *
 * `area` y `servicio` se resuelven por LUGAR (ReQ-002): dos lugares del club
 * llevan precios distintos. `cuota social` y `recargo` ignoran el lugar y se
 * resuelven por concepto (ReQ-101).
 */
export interface LugarCobro {
  area: Area;
  predio: Predio;
  categoria: CategoriaParcela | null;
}

/**
 * Un lugar cobrable junto con la membresía que lo ancla (ReQ-004): cada línea de
 * área/servicio se imputa al lugar de SU membresía, nunca al del titular.
 */
export interface LugarCobrable extends LugarCobro {
  membresiaId: string;
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

/**
 * Una línea de cobro compuesta en el cliente (PAG-01: estimación, NO autoridad).
 *
 * La identidad de la línea es `arancelId`, no `concepto` (ReQ-012): dos filas
 * del mismo concepto son dos líneas distintas. `concepto` viaja sólo como pista.
 */
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

/**
 * Concepto de un arancel. Una fila sin `concepto` es una fila de área: ese es
 * el default de la columna en la base (`ConceptoCobro.AREA`) y todas las filas
 * anteriores a la migración por concepto lo eran.
 */
function conceptoDeArancel(a: Arancel): ConceptoCobro {
  return a.concepto ?? "area";
}

/**
 * Devuelve la fila de catálogo que priced un concepto, replicando la resolución
 * del servidor (`resolucion.py`) con la **regla dual** (ReQ-008):
 *
 * - `area` y `servicio` se resuelven por LUGAR (área+predio; la categoría sólo
 *   aplica a `area`, y el resto cae al catch-all `categoria` null). Dos lugares
 *   del club llevan precios distintos, así que una fila global cobraría de más o
 *   de menos (ReQ-002).
 * - `cuota social` y `recargo` se resuelven por CONCEPTO, ignorando área y
 *   predio (guardan un placeholder porque esas columnas son NOT NULL). Ante
 *   varias, gana la de menor id, igual que el servidor.
 *
 * Un `servicio` sin `lugar` NO resuelve nada: PR6 borró el fallback global
 * histórico al recablear al último consumidor. Mantenerlo vivo reintroducía el
 * bug reportado — un único precio de servicio para todos los lugares (D2).
 */
export function arancelPorConcepto(
  aranceles: Arancel[],
  concepto: ConceptoCobro,
  lugar?: LugarCobro,
): Arancel | undefined {
  if (concepto === "area") return arancelDeArea(aranceles, lugar);
  if (concepto === "servicio") {
    return lugar ? arancelDeLugar(aranceles, concepto, lugar, false) : undefined;
  }
  return primeraPorId((a) => conceptoDeArancel(a) === concepto && a.categoria == null, aranceles);
}

/** Fila `area` de un lugar: la categoría exacta si existe, si no el catch-all. */
function arancelDeArea(aranceles: Arancel[], lugar?: LugarCobro): Arancel | undefined {
  if (!lugar) return undefined;
  return arancelDeLugar(aranceles, "area", lugar, true);
}

/**
 * Primera fila de un concepto para un lugar, por id ascendente. Con
 * `categoriaExacta` intenta primero la categoría del lugar y cae al catch-all
 * (`categoria` null); los conceptos que no usan categoría van directo al
 * catch-all.
 */
function arancelDeLugar(
  aranceles: Arancel[],
  concepto: ConceptoCobro,
  lugar: LugarCobro,
  categoriaExacta: boolean,
): Arancel | undefined {
  if (categoriaExacta && lugar.categoria) {
    const exacta = aranceles.find(
      (a) =>
        conceptoDeArancel(a) === concepto &&
        a.area === lugar.area &&
        a.predio === lugar.predio &&
        a.categoria === lugar.categoria,
    );
    if (exacta) return exacta;
  }
  return primeraPorId(
    (a) =>
      conceptoDeArancel(a) === concepto &&
      a.area === lugar.area &&
      a.predio === lugar.predio &&
      a.categoria == null,
    aranceles,
  );
}

/** TODAS las filas `servicio` de un lugar, por id ascendente (N apartes → N líneas). */
function arancelesDeServicio(aranceles: Arancel[], lugar: LugarCobro): Arancel[] {
  return aranceles
    .filter(
      (a) =>
        conceptoDeArancel(a) === "servicio" &&
        a.area === lugar.area &&
        a.predio === lugar.predio &&
        a.categoria == null,
    )
    .sort((x, y) => (x.id < y.id ? -1 : 1));
}

/** Primera fila que cumple el predicado, por id ascendente (determinismo). */
function primeraPorId(match: (a: Arancel) => boolean, aranceles: Arancel[]): Arancel | undefined {
  return [...aranceles].filter(match).sort((x, y) => (x.id < y.id ? -1 : 1))[0];
}

/** Total estimado de las líneas compuestas; el servidor recalcula el suyo. */
export function totalEstimado(lineas: LineaCobro[]): number {
  return lineas.reduce((s, l) => s + l.monto, 0);
}

/**
 * Texto legible de los avisos de resolución de un cobro (D8, ReQ-011).
 *
 * El backend es el único que redacta el motivo (un `arancelId` re-etiquetado o
 * fuera de lugar que se cobró al precio correcto): acá solo se descartan los
 * vacíos y se unen para mostrarlos en un único aviso al operador. Devuelve
 * `null` cuando no hay nada que avisar, para que el llamador no abra un toast
 * vacío. Nunca afirma un importe: el total y el desglose son los que resuelve
 * el servidor.
 */
export function formatearAvisosCobro(avisos?: readonly string[] | null): string | null {
  const limpios = (avisos ?? []).map((a) => a.trim()).filter((a) => a.length > 0);
  if (limpios.length === 0) return null;
  return limpios.join(" · ");
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
 * Aranceles que un cobro puede tikear para un conjunto de lugares (ReQ-001).
 *
 * Devuelve, sin duplicados y en orden estable:
 * - para cada lugar: su fila `area` (categoría exacta o catch-all) y TODAS sus
 *   filas `servicio` (N apartes del mismo lugar → N filas tickeables);
 * - las filas `cuota social` y el carrier `recargo`, que no dependen del lugar
 *   (ReQ-101). El llamador decide si ofrecer la cuota según la membresía del
 *   socio; acá sólo se lista lo que el catálogo puede cobrar.
 *
 * Un lugar sin fila `servicio` no aporta línea de servicio (ReQ-003): no hay
 * nada que ofrecer y el diálogo muestra el aviso.
 */
export function arancelesDisponibles(
  aranceles: Arancel[],
  lugares: readonly LugarCobro[],
): Arancel[] {
  const vistos = new Set<string>();
  const out: Arancel[] = [];
  const agregar = (a: Arancel | undefined) => {
    if (!a || vistos.has(a.id)) return;
    vistos.add(a.id);
    out.push(a);
  };
  for (const lugar of lugares) {
    agregar(arancelDeArea(aranceles, lugar));
    for (const servicio of arancelesDeServicio(aranceles, lugar)) agregar(servicio);
  }
  agregar(arancelPorConcepto(aranceles, "cuota social"));
  agregar(arancelPorConcepto(aranceles, "recargo"));
  return out;
}

/**
 * Membresía que ancla un lugar: la de concepto área en ese área+predio
 * (ReQ-004). Prefiere al Titular y desempata por id ascendente, igual que el
 * servidor. Una membresía de cuota social (sin área) nunca ancla un lugar.
 */
export function membresiaDeLugar(
  membresias: readonly Membresia[],
  lugar: LugarCobro,
): Membresia | undefined {
  const delLugar = membresias
    .filter(
      (m) =>
        conceptoDeMembresia(m) === "area" && m.area === lugar.area && m.predio === lugar.predio,
    )
    .sort((x, y) => (x.id < y.id ? -1 : 1));
  return delLugar.find((m) => m.rol === "Titular") ?? delLugar[0];
}

export interface OpcionesItemsPorArancel {
  /** Ancla de las líneas sin lugar (cuota social y recargo); `PagoItem` exige una. */
  anclas: AnclasCobro;
  /**
   * Miembros que DEBEN la cuota social → multiplicador de su línea (CS-03 +
   * regla del dueño). No es la cantidad de integrantes: un socio ya pago no se
   * cuenta. `0` = todos al día → no se emite línea de cuota.
   */
  miembrosImpagos: number;
  /** Ajuste de importe por arancelId: el recargo (siempre) y los servicios (ReQ-010). */
  ajustes?: Readonly<Record<string, number>> | undefined;
}

/**
 * Compone UNA línea por cada `arancelId` tickeado por el operador (ReQ-001 /
 * ReQ-012).
 *
 * La identidad es la fila de catálogo, no el concepto: tickear dos apartes de
 * servicio del mismo lugar emite DOS líneas, cada una con su monto, algo que la
 * composición por concepto no podía representar. Nada tickeado → cero líneas, y
 * ese array vacío es lo que deja el botón de confirmar deshabilitado.
 *
 * Cada línea de área/servicio resuelve su ancla por el lugar de SU fila
 * (ReQ-004). El monto y el total son una estimación: el servidor re-resuelve y
 * es la única autoridad (PAG-01).
 *
 * - `area` → monto de catálogo, factor 1.
 * - `servicio` → monto de catálogo o el `ajuste` de este cobro, factor 1.
 * - `cuota social` → precio de UN miembro × integrantes IMPAGOS de la unidad;
 *   con todos al día no hay línea (el servidor hace lo mismo, PAG-01).
 * - `recargo` → el importe tipeado (`ajuste`); sin importe mayor a 0 no se emite.
 */
export function itemsPorArancel(
  aranceles: Arancel[],
  lugares: readonly LugarCobrable[],
  marcas: ReadonlySet<string>,
  opciones: OpcionesItemsPorArancel,
): LineaCobro[] {
  const lineas: LineaCobro[] = [];
  for (const arancelId of marcas) {
    const arancel = aranceles.find((a) => a.id === arancelId);
    if (!arancel) continue;
    const concepto = conceptoDeArancel(arancel);

    if (concepto === "area") {
      const membresiaId =
        lugarCobrableDeArancel(arancel, lugares)?.membresiaId ?? opciones.anclas.area;
      if (!membresiaId) continue;
      lineas.push({
        concepto,
        arancelId: arancel.id,
        arancelNombre: arancel.nombre,
        membresiaId,
        monto: arancel.monto,
        factor: 1,
      });
      continue;
    }

    if (concepto === "servicio") {
      const membresiaId =
        lugarCobrableDeArancel(arancel, lugares)?.membresiaId ?? opciones.anclas.area;
      if (!membresiaId) continue;
      const monto = opciones.ajustes?.[arancel.id] ?? arancel.monto;
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

    if (concepto === "cuota social") {
      const membresiaId = opciones.anclas.cuota;
      if (!membresiaId) continue;
      const factor = Math.max(0, opciones.miembrosImpagos);
      // Todos al día: nadie debe la cuota, así que no se emite línea (el
      // servidor tampoco la produciría: no hay nada que cobrar).
      if (factor <= 0) continue;
      lineas.push({
        concepto,
        arancelId: arancel.id,
        arancelNombre: arancel.nombre,
        membresiaId,
        monto: arancel.monto * factor,
        factor,
      });
      continue;
    }

    // recargo: el catálogo sólo presta el carrier; el importe lo carga el operador.
    const membresiaId = opciones.anclas.area;
    if (!membresiaId) continue;
    const monto = opciones.ajustes?.[arancel.id] ?? 0;
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
  }
  return lineas;
}

/** Lugar cobrable al que pertenece una fila del catálogo (su ancla, ReQ-004). */
function lugarCobrableDeArancel(
  arancel: Arancel,
  lugares: readonly LugarCobrable[],
): LugarCobrable | undefined {
  const usaCategoria = conceptoDeArancel(arancel) === "area";
  return lugares.find(
    (l) =>
      l.area === arancel.area &&
      l.predio === arancel.predio &&
      (!usaCategoria || arancel.categoria == null || l.categoria === arancel.categoria),
  );
}

/** Concepto de una membresía; sin `concepto` servido, un área es un área. */
export function conceptoDeMembresia(m: Membresia): ConceptoMembresia {
  return m.concepto ?? "area";
}

// ---------------------------------------------------------------------------
// Cuota social: quién la debe (regla del dueño) — espejo de la regla servidor
// ---------------------------------------------------------------------------

/**
 * Fecha de hoy en ISO corto usando el reloj LOCAL, igual que `date.today()` del
 * servidor. No se usa `toISOString()` (UTC): cerca de medianoche la fecha UTC y
 * la local difieren y el cliente estimaría un impago que el servidor cobra de
 * otro modo.
 */
export function hoyLocalISO(): string {
  const d = new Date();
  const mes = String(d.getMonth() + 1).padStart(2, "0");
  const dia = String(d.getDate()).padStart(2, "0");
  return `${d.getFullYear()}-${mes}-${dia}`;
}

/** La membresía de cuota social del socio, o `undefined` si no tiene fila. */
export function cuotaSocialDe(
  membresias: readonly Membresia[],
  socioId: string,
): Membresia | undefined {
  return membresias.find((m) => m.socioId === socioId && conceptoDeMembresia(m) === "cuota social");
}

/**
 * ¿La cuota social está al día? Espejo EXACTO de la regla del servidor
 * (`cobro._cuota_impaga` / `estado_socio.Vigencia`): está al día si hay fila,
 * no está parada (`suspendida`/`baja`) y su `vencimiento` no es anterior a hoy.
 * `vencimiento == hoy` está al día. Sin fila → impaga.
 */
export function cuotaAlDia(
  cuota: Pick<Membresia, "estado" | "vencimiento"> | undefined,
  hoy: string,
): boolean {
  if (!cuota) return false;
  if (cuota.estado === "suspendida" || cuota.estado === "baja") return false;
  return cuota.vencimiento >= hoy;
}

/**
 * Cantidad de integrantes de una unidad que DEBEN la cuota social: el
 * multiplicador de la línea de cuota (el servidor es la autoridad final, acá
 * solo se estima con la misma regla). Un integrante ya pago no se cuenta.
 *
 * `members` son las membresías de área de la unidad y `membresias` el padrón
 * completo (para encontrar la cuota de cada socio por `socioId`).
 */
export function miembrosCuotaImpaga(
  members: readonly Membresia[],
  membresias: readonly Membresia[],
  hoy: string,
): number {
  return members.filter((m) => !cuotaAlDia(cuotaSocialDe(membresias, m.socioId), hoy)).length;
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
