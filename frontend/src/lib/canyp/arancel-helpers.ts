/**
 * Pure helpers for the catalog UI (`/aranceles`) — `cobro-aranceles-flexibles` PR4.
 *
 * The catalog is the one screen where a human decides WHAT a row prices, so the
 * decision rules live here as pure functions (no React) and the route only wires
 * them to selects, inputs and toasts. Two backend rules are the reason this
 * module exists at all:
 *
 * - **The dual rule** (`backend/services/resolucion.py`): `area` and `servicio`
 *   are PLACES — resolved by `area`+`predio` (`+categoria` for `area`), because
 *   two places of the club carry different prices. `cuota social` and `recargo`
 *   are CONCEPTS, not places: `resolver_arancel_concepto` finds them by `concepto`
 *   alone, and their `area`/`predio` exist only to satisfy the NOT NULL columns
 *   (ReQ-101).
 * - **Uniqueness is the 4-tuple** `(area, predio, categoria, concepto)`
 *   (`routers/aranceles.py:_checar_tupla`, ReQ-006). Duplicates answer 409.
 *
 * That second rule is why `LUGAR_NEUTRAL` is a CONSTANT and not "whatever the
 * operator last picked": a form that sent a lazy place for a non-place concept
 * would miss the 409 guard and slip a SECOND `cuota social` row into the catalog,
 * where the resolver silently prices the lowest id (ReQ-008). The place is
 * ignored by the resolver, so the only thing it can do is break uniqueness.
 */

import type { CreateArancelInput } from "./api";
import { ApiError } from "./api";
import type { Area, Arancel, CategoriaParcela, ConceptoCobro, Predio } from "./types";

/** Los 4 conceptos, en el orden en que se listan en los selects. */
export const CONCEPTOS: ConceptoCobro[] = ["area", "servicio", "cuota social", "recargo"];

/**
 * Etiqueta legible de cada concepto (UI pública).
 *
 * Same vocabulary the charge dialogs render from the catalog `nombre` — same
 * word for the same concept in both screens. The labels are what disambiguate
 * the seeded `a7/a12/a13 "Cuota"` (concepto `area`) from `a15 "Cuota social"`
 * (concepto `cuota social`): identical `nombre`, different concept, different
 * price (ReQ-013).
 */
export const CONCEPTO_LABELS: Record<ConceptoCobro, string> = {
  area: "Cuota de la unidad",
  "cuota social": "Cuota social",
  recargo: "Recargo",
  servicio: "Servicio",
};

/** Una línea por concepto: qué resuelve y qué tiene que configurar el admin. */
export const CONCEPTO_AYUDA: Record<ConceptoCobro, string> = {
  area: "Se resuelve por lugar: área + predio, y la categoría distingue el tamaño de la parcela.",
  servicio:
    "Se resuelve por lugar: una fila por área + predio. Sin categoría (precio de todo el lugar).",
  "cuota social":
    "Precio único de UN socio, multiplicado por la cantidad de miembros. El área y el predio no cuentan.",
  recargo:
    "No usa el monto del catálogo: el operador carga el importe en cada cobro. El monto se deja en 0.",
};

/**
 * Placeholder enviado por los conceptos que NO son un lugar.
 *
 * `Guardería/Almafuerte` a propósito: es la misma pareja que usan los carriers
 * sembrados (`a14` recargo, `a15` cuota social), así que un segundo ítem de
 * cuota social choca contra el 409 que nombra `a15` en vez de crear una tupla
 * nueva que el resolver no vería.
 */
export const LUGAR_NEUTRAL = { area: "Guardería", predio: "Almafuerte" } as const;

/** ¿El concepto se resuelve por LUGAR (área+predio) o sólo por concepto? */
export function esPorLugar(concepto: ConceptoCobro): boolean {
  return concepto === "area" || concepto === "servicio";
}

/**
 * ¿La categoría de parcela aplica a este concepto?
 *
 * Sólo `area` la usa (`resolver_monto` filtra por `categoria` en esa rama). Un
 * SERVICIO con categoría priced una sola medida de parcela y dejaría sin
 * precio a las demás — el `NULL` es justamente la rama catch-all. Los conceptos
 * no-lugar tampoco: `resolver_arancel_concepto` busca `categoria IS NULL`.
 */
export function usaCategoria(concepto: ConceptoCobro): boolean {
  return concepto === "area";
}

/** Estado del form de alta/edición: sólo los campos que el operador ve. */
export interface ArancelForm {
  nombre: string;
  concepto: ConceptoCobro;
  area: Area;
  predio: Predio;
  categoria: CategoriaParcela | null;
  /** Texto del input: vacío o no numérico vale 0, como antes de este PR. */
  monto: string;
}

export const ARANCEL_FORM_VACIO: ArancelForm = {
  nombre: "",
  concepto: "area",
  area: "Balseros",
  predio: "Embalse",
  categoria: null,
  monto: "",
};

/** Copia editable de una fila del catálogo, con su `vigenteDesde` intacto. */
export function formDeArancel(a: Arancel): ArancelForm & { id: string; vigenteDesde: string } {
  return {
    id: a.id,
    nombre: a.nombre,
    concepto: a.concepto ?? "area",
    area: a.area,
    predio: a.predio,
    categoria: a.categoria ?? null,
    monto: String(a.monto),
    vigenteDesde: a.vigenteDesde,
  };
}

/**
 * Payload de alta/edición con las reglas de concepto ya aplicadas (ReQ-005).
 *
 * Un solo builder para POST y PUT: `ArancelUpdate` es todo-opcional, así que un
 * payload completo también es un update parcial válido. Enviar `vigenteDesde`
 * explícito preserva la regla del backend (el monto recién freezes a hoy; el
 * resto de los campos no tocan la fecha).
 */
export function payloadArancel(form: ArancelForm, vigenteDesde: string): CreateArancelInput {
  return {
    nombre: form.nombre.trim(),
    concepto: form.concepto,
    area: esPorLugar(form.concepto) ? form.area : LUGAR_NEUTRAL.area,
    predio: esPorLugar(form.concepto) ? form.predio : LUGAR_NEUTRAL.predio,
    monto: Number(form.monto) || 0,
    categoria: usaCategoria(form.concepto) ? form.categoria : null,
    vigenteDesde,
  };
}

/**
 * Mensaje del toast: el `detail` del backend si vino, si no el genérico.
 *
 * `apiFetch` ya mete `body.detail` en `ApiError.message`, así que los dos 409
 * llegan íntegros — el de tupla duplicada ("Ya existe un arancel con area=…,
 * concepto=… (id=…)") y el de delete bloqueado ("No se puede eliminar el
 * arancel a1: 2 pago_items (pi1, …)"). Lo que faltaba era NO reemplazarlos por
 * un texto genérico (ReQ-006/ReQ-007).
 */
export function mensajeDeError(error: unknown, fallback: string): string {
  return error instanceof ApiError && error.message ? error.message : fallback;
}
