/**
 * Runtime + compile-time tests for CANYP utility functions.
 *
 * Imports use RELATIVE paths (not the `@/` alias) so the file is executable by
 * both `tsc` (compile-time convention in this repo) and `vitest` (runtime proof).
 */

import { describe, expect, it } from "vitest";
import { diasRestantes, formatARS, formatFecha, ORDEN_ESTADOS } from "../utils";
import type { EstadoSocio } from "../types";

// ---------------------------------------------------------------------------
// Compile-time: exports exist with the expected shapes
// ---------------------------------------------------------------------------

type FormatARSIsFn = typeof formatARS extends (n: number) => string ? true : false;
const _formatARSCheck: FormatARSIsFn = true;

type FormatFechaIsFn = typeof formatFecha extends (iso: string) => string ? true : false;
const _formatFechaCheck: FormatFechaIsFn = true;

type DiasRestantesIsFn = typeof diasRestantes extends (v: string) => number ? true : false;
const _diasRestantesCheck: DiasRestantesIsFn = true;

describe("utils", () => {
  it("formatARS formats with Argentine peso grouping", () => {
    expect(formatARS(1000)).toBe("$ 1.000");
    expect(formatARS(0)).toBe("$ 0");
    expect(formatARS(1234567)).toBe("$ 1.234.567");
  });

  it("formatFecha converts ISO YYYY-MM-DD to DD/MM/YYYY", () => {
    expect(formatFecha("2024-03-09")).toBe("09/03/2024");
    expect(formatFecha("2000-12-01")).toBe("01/12/2000");
  });

  it("diasRestantes signs relative to today and reports a 5-day gap", () => {
    const past = "2000-01-01";
    const future = "2099-01-01";
    expect(diasRestantes(past)).toBeLessThan(0);
    expect(diasRestantes(future)).toBeGreaterThan(0);

    function isoPlusDays(days: number): string {
      const d = new Date();
      d.setHours(12, 0, 0, 0);
      d.setDate(d.getDate() + days);
      return d.toISOString().slice(0, 10);
    }

    const gap = diasRestantes(isoPlusDays(10)) - diasRestantes(isoPlusDays(5));
    expect(gap).toBe(5);
  });
});

// ---------------------------------------------------------------------------
// ORDEN_ESTADOS — los 4 estados que SERVE el backend (EST-01)
// ---------------------------------------------------------------------------

describe("ORDEN_ESTADOS (EST-01)", () => {
  it("orders the 4 server-served states from most urgent to least", () => {
    expect(ORDEN_ESTADOS).toEqual([
      "Inactivo — revisar",
      "Socio activo — revisar",
      "Socio activo",
      "Solo cuota social",
    ]);
  });

  it("uses the exact backend nominaciones, em dash included (UI-04)", () => {
    // El string ES la nominación de UI: no se parafrasea ni se arma en el
    // cliente. Si el backend cambiara uno, esta lista debe cambiar con él.
    for (const estado of ORDEN_ESTADOS) {
      expect(typeof estado).toBe("string");
      expect(estado).not.toBe("");
    }
    expect(ORDEN_ESTADOS.filter((e) => e.includes("—"))).toHaveLength(2);
  });

  it("covers every value of the EstadoSocio vocabulary, without duplicates", () => {
    const vocabulary: EstadoSocio[] = [
      "Socio activo",
      "Socio activo — revisar",
      "Inactivo — revisar",
      "Solo cuota social",
    ];
    expect([...ORDEN_ESTADOS].sort()).toEqual([...vocabulary].sort());
  });
});
