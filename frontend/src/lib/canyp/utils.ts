import type { Membresia } from "./types";

export type EstadoVisual = "activa" | "por_vencer" | "vencida" | "suspendida" | "baja";

export function diasRestantes(vencimiento: string) {
  const hoy = new Date();
  hoy.setHours(12, 0, 0, 0);
  const v = new Date(`${vencimiento}T12:00:00`);
  return Math.round((v.getTime() - hoy.getTime()) / 86400000);
}

export function estadoVisual(m: Membresia): EstadoVisual {
  if (m.estado === "baja") return "baja";
  if (m.estado === "suspendida") return "suspendida";
  const d = diasRestantes(m.vencimiento);
  if (d < 0) return "vencida";
  if (d <= 30) return "por_vencer";
  return "activa";
}

export const estadoLabel: Record<EstadoVisual, string> = {
  activa: "Activa",
  por_vencer: "Por vencer",
  vencida: "Vencida",
  suspendida: "Suspendida",
  baja: "Dada de baja",
};

export function formatARS(n: number) {
  return `$ ${n.toLocaleString("es-AR")}`;
}

export function formatFecha(iso: string) {
  const [y, m, d] = iso.split("-");
  return `${d}/${m}/${y}`;
}
