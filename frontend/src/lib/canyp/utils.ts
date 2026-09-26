import type { EstadoSocio } from "./types";

/**
 * Orden de severidad de los 4 estados servidos (EST-01), de más urgente a menos.
 *
 * Es el orden de presentación que consumen los badges y el agregado por unidad
 * (`estadoCriticoDe`). El string ES la nominación exacta de UI (UI-04): el
 * frontend nunca la arma, la muestra tal cual viene del backend.
 */
export const ORDEN_ESTADOS: readonly EstadoSocio[] = [
  "Inactivo — revisar",
  "Socio activo — revisar",
  "Socio activo",
  "Solo cuota social",
];

/** Días restantes (pueden ser negativos) hasta un vencimiento, a las 12:00 locales. */
export function diasRestantes(vencimiento: string) {
  const hoy = new Date();
  hoy.setHours(12, 0, 0, 0);
  const v = new Date(`${vencimiento}T12:00:00`);
  return Math.round((v.getTime() - hoy.getTime()) / 86400000);
}

export function formatARS(n: number) {
  return `$ ${n.toLocaleString("es-AR")}`;
}

export function formatFecha(iso: string) {
  const [y, m, d] = iso.split("-");
  return `${d}/${m}/${y}`;
}
