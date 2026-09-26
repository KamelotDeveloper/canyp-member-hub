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
 * - `itemsParaMembresias` builds one PagoItem per (membresía, arancel) so each
 *   item renews ITS own membership (RQ 14 multi-membresía), reusing the same
 *   matching rule the /pagos page already applies.
 */

import type {
  Arancel,
  Area,
  CategoriaParcela,
  ImportMembresia,
  ImportPayload,
  ImportSocio,
  Membresia,
  Parcela,
  Predio,
  Rol,
  UnidadFiltro,
  UnidadGroup,
} from "./types";
import { estadoVisual, type EstadoVisual } from "./utils";

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

/** Un ítem de cobro ya resuelto contra un arancel (para buildUnitPago). */
export interface PagoItemResuelto {
  arancelId: string;
  arancelNombre: string;
  montoAplicado: number;
  membresiaId: string;
  monto: number;
}

/**
 * Resuelve el arancel aplicable por area + predio + categoría (regla RQ 13,
 * igual que `resolver_monto` del backend): primero el arancel de la categoría
 * exacta; si no hay, el catch-all (categoría null) del área+predio.
 */
export function arancelPara(
  area: Area,
  predio: Predio,
  categoria: CategoriaParcela | null,
  aranceles: Arancel[],
): Arancel | undefined {
  if (categoria) {
    const exact = aranceles.find(
      (a) => a.area === area && a.predio === predio && a.categoria === categoria,
    );
    if (exact) return exact;
  }
  return aranceles.find((a) => a.area === area && a.predio === predio && a.categoria == null);
}

/**
 * Genera UN único ítem de cobro para la unidad: el arancel de su categoría.
 * El costo es por unidad/categoría, NO por integrante — una Cabaña Chica cuesta
 * lo mismo con 3 o 10 integrantes. El ítem se liga a la membresía del titular;
 * el pago renueva a TODOS los miembros vía `membresiaIds` (RQ 14).
 */
export function itemsParaMembresias(
  members: Membresia[],
  aranceles: Arancel[],
  categoria: CategoriaParcela | null = null,
): PagoItemResuelto[] {
  const titular = members.find((m) => m.rol === "Titular") ?? members[0];
  if (!titular) return [];
  const directo = titular.arancelId
    ? aranceles.find((a) => a.id === titular.arancelId)
    : undefined;
  const a = directo ?? arancelPara(titular.area, titular.predio, categoria, aranceles);
  if (!a) return [];
  return [
    {
      arancelId: a.id,
      arancelNombre: a.nombre,
      montoAplicado: a.monto,
      monto: a.monto,
      membresiaId: titular.id,
    },
  ];
}

/**
 * Resuelve un PagoItem por membresía usando la categoría de SU parcela (para
 * el flujo general de /pagos, donde se pueden elegir membresías de distintas
 * unidades). Igual que `itemsParaMembresias` pero derivando la categoría de
 * cada membresía a partir de `parcelaId` en vez de una categoría única.
 */
export function itemsParaMembresiasConParcelas(
  members: Membresia[],
  aranceles: Arancel[],
  parcelas: Parcela[],
): PagoItemResuelto[] {
  const out: PagoItemResuelto[] = [];
  for (const m of members) {
    const parcela = m.parcelaId ? parcelas.find((p) => p.id === m.parcelaId) : undefined;
    const categoria = parcela?.categoria ?? null;
    const directo = m.arancelId
      ? aranceles.find((a) => a.id === m.arancelId)
      : undefined;
    const a = directo ?? arancelPara(m.area, m.predio, categoria, aranceles);
    if (a) {
      out.push({
        arancelId: a.id,
        arancelNombre: a.nombre,
        montoAplicado: a.monto,
        monto: a.monto,
        membresiaId: m.id,
      });
    }
  }
  return out;
}

// ---------------------------------------------------------------------------
// Estado crítico de una unidad + filtros (RQ 3 / RQ 4)
// ---------------------------------------------------------------------------

/**
 * Orden de severidad de los estados visuales — el más crítico primero (RQ 3).
 * `vencida` es lo más crítico (membresía vencida), seguida de `por_vencer`,
 * `suspendida`, `baja` y `activa`.
 */
export const ORDEN_ESTADOS: EstadoVisual[] = [
  "vencida",
  "por_vencer",
  "suspendida",
  "baja",
  "activa",
];

/**
 * Estado visual más crítico presente en una unidad (RQ 3). Devuelve el primer
 * estado de `ORDEN_ESTADOS` que tenga al menos un miembro; si ninguno matchea
 * (grupo vacío o estados desconocidos) cae a `activa` por defecto.
 */
export function estadoCriticoDe(g: UnidadGroup): EstadoVisual {
  return ORDEN_ESTADOS.find((e) => g.members.some((m) => estadoVisual(m) === e)) ?? "activa";
}

/**
 * Filtra una lista de unidades según el filtro seleccionado (RQ 4).
 * - `todas`: no filtra.
 * - `vencidas`: solo unidades cuyo estado crítico es `vencida`.
 * - `por_vencer`: solo unidades cuyo estado crítico es `por_vencer`.
 * - `alertas`: unidades `vencida` o `por_vencer`.
 */
export function filtrarUnidades(grupos: UnidadGroup[], filtro: UnidadFiltro): UnidadGroup[] {
  return grupos.filter((g) => {
    const e = estadoCriticoDe(g);
    if (filtro === "vencidas") return e === "vencida";
    if (filtro === "por_vencer") return e === "por_vencer";
    if (filtro === "alertas") return e === "vencida" || e === "por_vencer";
    return true;
  });
}
