/**
 * Contract tests for the catalog UI rules — `cobro-aranceles-flexibles` PR4.
 *
 * The assertions are about the BACKEND contract this form has to respect, not
 * about the rendering:
 * - the dual rule of `services/resolucion.py` (place-priced vs concept-priced),
 * - the 4-tuple uniqueness of `routers/aranceles.py:_checar_tupla` (ReQ-006),
 * - the 409 `detail` reaching the toast (ReQ-006/ReQ-007).
 */

import { describe, expect, it } from "vitest";
import { ApiError } from "../api";
import {
  ARANCEL_FORM_VACIO,
  CONCEPTO_AYUDA,
  CONCEPTO_LABELS,
  CONCEPTOS,
  LUGAR_NEUTRAL,
  esPorLugar,
  formDeArancel,
  mensajeDeError,
  payloadArancel,
  usaCategoria,
  type ArancelForm,
} from "../arancel-helpers";
import type { Arancel, ConceptoCobro } from "../types";

const form = (patch: Partial<ArancelForm> = {}): ArancelForm => ({
  ...ARANCEL_FORM_VACIO,
  nombre: "Servicio",
  monto: "2500",
  ...patch,
});

function arancel(patch: Partial<Arancel> = {}): Arancel {
  return {
    id: "a1",
    nombre: "Amarre",
    area: "Balseros",
    predio: "Embalse",
    monto: 18500,
    vigenteDesde: "2026-01-01",
    historico: [],
    ...patch,
  };
}

describe("vocabulario de conceptos", () => {
  it("exposes the 4 backend conceptos, no duplicates, stable order", () => {
    expect(CONCEPTOS).toEqual(["area", "servicio", "cuota social", "recargo"]);
    expect(new Set(CONCEPTOS).size).toBe(4);
  });

  it("labels every concepto with a distinct readable sentence (ReQ-013)", () => {
    for (const c of CONCEPTOS) {
      expect(CONCEPTO_LABELS[c]).toBeTruthy();
      expect(CONCEPTO_AYUDA[c]).toBeTruthy();
    }
    const labels = CONCEPTOS.map((c) => CONCEPTO_LABELS[c]);
    expect(new Set(labels).size).toBe(4);
    // The case that motivated the column: a7/a12/a13 "Cuota" (area) vs a15
    // "Cuota social" (cuota social). Same label, no way to tell them apart.
    expect(CONCEPTO_LABELS.area).not.toBe(CONCEPTO_LABELS["cuota social"]);
  });
});

describe("regla dual: lugar vs concepto", () => {
  it("area y servicio se resuelven por lugar; cuota social y recargo no", () => {
    expect(esPorLugar("area")).toBe(true);
    expect(esPorLugar("servicio")).toBe(true);
    expect(esPorLugar("cuota social")).toBe(false);
    expect(esPorLugar("recargo")).toBe(false);
  });

  it("sólo area usa la categoría de parcela", () => {
    expect(CONCEPTOS.filter(usaCategoria)).toEqual(["area"]);
  });
});

describe("payloadArancel", () => {
  it("area manda el lugar elegido y la categoría (ReQ-005)", () => {
    const p = payloadArancel(
      form({ concepto: "area", area: "Cabañeros", predio: "Almafuerte", categoria: "Grande" }),
      "2026-09-27",
    );
    expect(p).toMatchObject({
      concepto: "area",
      area: "Cabañeros",
      predio: "Almafuerte",
      categoria: "Grande",
      vigenteDesde: "2026-09-27",
    });
  });

  it("servicio manda el lugar pero NUNCA la categoría (rama catch-all del resolver)", () => {
    const p = payloadArancel(
      form({ concepto: "servicio", area: "Cabañeros", predio: "Almafuerte", categoria: "Grande" }),
      "2026-09-27",
    );
    expect(p.area).toBe("Cabañeros");
    expect(p.predio).toBe("Almafuerte");
    expect(p.categoria).toBeNull();
  });

  it.each<ConceptoCobro>(["cuota social", "recargo"])(
    "%s ignora el lugar elegido y manda el neutro (placeholder NOT NULL)",
    (concepto) => {
      const p = payloadArancel(
        form({ concepto, area: "Windsurf", predio: "Almafuerte", categoria: "Chica" }),
        "2026-09-27",
      );
      expect(p.area).toBe(LUGAR_NEUTRAL.area);
      expect(p.predio).toBe(LUGAR_NEUTRAL.predio);
      expect(p.categoria).toBeNull();
    },
  );

  it("el placeholder hace que dos cuota social con lugares distintos choquen en el 409", () => {
    // If the chosen place travelled, the tuple would differ, the ReQ-006 409
    // would not fire, and a second cuota social row would silently lose to the
    // lower price in the resolver (ReQ-008).
    const a = payloadArancel(form({ concepto: "cuota social", area: "Balseros" }), "2026-09-27");
    const b = payloadArancel(form({ concepto: "cuota social", area: "Windsurf" }), "2026-09-27");
    expect([a.area, a.predio, a.categoria]).toEqual([b.area, b.predio, b.categoria]);
  });

  it("mismo concepto + mismo lugar + misma categoría sí es la misma tupla (409 esperable)", () => {
    const base: Partial<ArancelForm> = {
      concepto: "area",
      area: "Balseros",
      predio: "Embalse",
      categoria: null,
    };
    const uno = payloadArancel(form({ ...base, monto: "1" }), "2026-09-27");
    const otro = payloadArancel(form({ ...base, monto: "999" }), "2026-09-27");
    expect([uno.area, uno.predio, uno.categoria, uno.concepto]).toEqual([
      otro.area,
      otro.predio,
      otro.categoria,
      otro.concepto,
    ]);
    expect(uno.monto).not.toBe(otro.monto);
  });

  it("convierte el monto a número y cae a 0, y recorta el nombre", () => {
    expect(payloadArancel(form({ monto: "7300" }), "2026-09-27").monto).toBe(7300);
    expect(payloadArancel(form({ monto: "" }), "2026-09-27").monto).toBe(0);
    expect(payloadArancel(form({ nombre: "  Luz  " }), "2026-09-27").nombre).toBe("Luz");
  });
});

describe("formDeArancel", () => {
  it("copia la fila con el concepto servido, sin inventar categoría", () => {
    const f = formDeArancel(arancel({ concepto: "servicio", monto: 5000 }));
    expect(f).toEqual({
      id: "a1",
      nombre: "Amarre",
      concepto: "servicio",
      area: "Balseros",
      predio: "Embalse",
      categoria: null,
      monto: "5000",
      vigenteDesde: "2026-01-01",
    });
  });

  it("una respuesta vieja sin concepto no rompe la edición", () => {
    expect(formDeArancel(arancel({ concepto: undefined })).concepto).toBe("area");
  });
});

describe("mensajeDeError (409)", () => {
  it("muestra el detail de la tupla duplicada tal cual (ReQ-006)", () => {
    const detail =
      "Ya existe un arancel con area=Balseros, predio=Embalse, categoria=—, concepto=servicio (id=a_serv_balseros)";
    expect(mensajeDeError(new ApiError(409, detail), "fallback")).toBe(detail);
  });

  it("muestra el detail del delete bloqueado con los conteos (ReQ-007)", () => {
    const detail = "No se puede eliminar el arancel a1: 2 pago_items (pi1, pi4)";
    expect(mensajeDeError(new ApiError(409, detail), "fallback")).toBe(detail);
  });

  it("cae al texto genérico con un error que no es del backend", () => {
    expect(mensajeDeError(new TypeError("boom"), "No se pudo guardar.")).toBe(
      "No se pudo guardar.",
    );
    expect(mensajeDeError(new ApiError(500, ""), "No se pudo guardar.")).toBe(
      "No se pudo guardar.",
    );
    expect(mensajeDeError(undefined, "No se pudo guardar.")).toBe("No se pudo guardar.");
  });
});
