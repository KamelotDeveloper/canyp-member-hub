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
  CategoriaParcela,
  ImportMembresia,
  ImportPayload,
  ImportSocio,
  Membresia,
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

/** Estado del formulario "Nueva unidad" antes de convertirlo a payload. */
export interface NuevaUnidadForm {
  nombre: string;
  tipo: "cabaña" | "balsa";
  categoria?: CategoriaParcela;
  predio: Predio;
  vencimiento: string;
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
  if (!form.socios[0]!.nombre.trim() || !form.socios[0]!.dni.trim()) return null;

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
    predio: form.predio,
    miembros,
  };
  if (form.categoria) unidad.categoria = form.categoria;

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
 * Genera un PagoItem por cada (membresía, arancel) que haga match por
 * area + predio. Cada ítem lleva la membresiaId de SU membresía (RQ 14), de
 * modo que al crear el Pago cada membresía se renueva de forma independiente.
 */
export function itemsParaMembresias(
  members: Membresia[],
  aranceles: Arancel[],
): PagoItemResuelto[] {
  const out: PagoItemResuelto[] = [];
  for (const m of members) {
    for (const a of aranceles) {
      if (a.area === m.area && a.predio === m.predio) {
        out.push({
          arancelId: a.id,
          arancelNombre: a.nombre,
          montoAplicado: a.monto,
          monto: a.monto,
          membresiaId: m.id,
        });
      }
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
