/**
 * Runtime + compile-time tests for CANYP utility functions (PR 3 cleanup).
 *
 * Imports use RELATIVE paths (not the `@/` alias) so the file is executable by
 * both `tsc` (compile-time convention in this repo) and `vitest` (runtime proof).
 */

import { describe, expect, it } from "vitest";
import { diasRestantes, estadoLabel, estadoVisual, formatARS, formatFecha } from "../utils";
import type { EstadoVisual } from "../utils";
import type { Membresia } from "../types";

// ---------------------------------------------------------------------------
// Compile-time: exports exist with the expected shapes
// ---------------------------------------------------------------------------

type FormatARSIsFn = typeof formatARS extends (n: number) => string ? true : false;
const _formatARSCheck: FormatARSIsFn = true;

type FormatFechaIsFn = typeof formatFecha extends (iso: string) => string ? true : false;
const _formatFechaCheck: FormatFechaIsFn = true;

type DiasRestantesIsFn = typeof diasRestantes extends (v: string) => number ? true : false;
const _diasRestantesCheck: DiasRestantesIsFn = true;

type EstadoVisualIsFn = typeof estadoVisual extends (m: Membresia) => EstadoVisual ? true : false;
const _estadoVisualCheck: EstadoVisualIsFn = true;

type EstadoLabelIsRecord = typeof estadoLabel extends Record<EstadoVisual, string> ? true : false;
const _estadoLabelCheck: EstadoLabelIsRecord = true;

// EstadoVisual must be the union used across the app.
const _estadoVisualUnion: EstadoVisual[] = [
  "activa",
  "por_vencer",
  "vencida",
  "suspendida",
  "baja",
];

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

  it("estadoVisual derives the visual status from estado + vencimiento", () => {
    const future = "2099-01-01";
    const past = "2000-01-01";

    function isoPlusDays(days: number): string {
      const d = new Date();
      d.setHours(12, 0, 0, 0);
      d.setDate(d.getDate() + days);
      return d.toISOString().slice(0, 10);
    }

    function m(overrides: Partial<Membresia>): Membresia {
      return {
        id: "m-test",
        socioId: "s-test",
        area: "Balseros",
        predio: "Embalse",
        estado: "activa",
        vencimiento: future,
        ...overrides,
      };
    }

    expect(estadoVisual(m({ estado: "baja" }))).toBe("baja");
    expect(estadoVisual(m({ estado: "suspendida" }))).toBe("suspendida");
    expect(estadoVisual(m({ vencimiento: future }))).toBe("activa");
    expect(estadoVisual(m({ vencimiento: isoPlusDays(10) }))).toBe("por_vencer");
    expect(estadoVisual(m({ vencimiento: past }))).toBe("vencida");
  });

  it("estadoLabel provides human-readable Spanish labels", () => {
    expect(estadoLabel["activa"]).toBe("Activa");
    expect(estadoLabel["por_vencer"]).toBe("Por vencer");
    expect(estadoLabel["vencida"]).toBe("Vencida");
    expect(estadoLabel["suspendida"]).toBe("Suspendida");
    expect(estadoLabel["baja"]).toBe("Dada de baja");
  });
});
