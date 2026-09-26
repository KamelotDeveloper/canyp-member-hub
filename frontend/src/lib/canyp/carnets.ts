import type { Area, Membresia } from "./types";

/** Initials for the photo fallback circle: first two words, uppercased. */
export function iniciales(nombre: string): string {
  const partes = nombre.trim().split(/\s+/).filter(Boolean);
  if (partes.length === 0) return "?";
  return partes
    .slice(0, 2)
    .map((p) => p[0]!.toUpperCase())
    .join("");
}

/** Unique non-baja areas of a socio's memberships. */
export function areasDeSocio(membresias: Membresia[], socioId: string): Area[] {
  const areas: Area[] = [];
  const seen = new Set<Area>();
  for (const m of membresias) {
    if (m.socioId !== socioId) continue;
    if (m.estado === "baja") continue;
    // Una cuota social no es un área física (CS-01): se saltea en el carnet.
    if (!m.area) continue;
    if (seen.has(m.area)) continue;
    seen.add(m.area);
    areas.push(m.area);
  }
  return areas;
}

/** Batch items into A4 "hojas" (8 carnets per sheet); last batch may be partial. */
export function agruparPorHojas<T>(items: T[], porHoja = 8): T[][] {
  const hojas: T[][] = [];
  for (let i = 0; i < items.length; i += porHoja) {
    hojas.push(items.slice(i, i + porHoja));
  }
  return hojas;
}
