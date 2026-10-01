/**
 * Contract tests for the two helpers that decide WHICH PLACE a membership row
 * carries — the "written and never read" class, second occurrence.
 *
 * A membership stores both `area` and `predio`, and the charge prices its area
 * line with `Arancel.area == area AND Arancel.predio == predio`
 * (`backend/services/resolucion.py:resolver_monto`). So a row whose `predio`
 * contradicts its `area` is a row NOTHING can price: `_item_area` returns `None`,
 * the line is silently dropped, and the amount is neither charged nor renewed.
 *
 * The screen that writes memberships used to send a literal
 * `predio: "Almafuerte"` for every area and filtered its arancel select on that
 * same hardcoded predio. Against the LIVE catalog (read-only, 2026-09-28) that
 * leaves the select empty for two of the four areas and creates unpriceable rows
 * for them, so the fixtures below are the real catalog, not invented data.
 */

import { describe, expect, it } from "vitest";
import { arancelesDeArea, predioDeArancel } from "../arancel-helpers";
import type { Arancel } from "../types";

/** The production catalog, verbatim: 5 rows, no RECARGO carrier, no Cabañeros. */
const CATALOGO_REAL: Arancel[] = [
  arancel({ id: "a_area_balseros", area: "Balseros", predio: "Embalse", monto: 450000 }),
  arancel({
    id: "a_serv_balseros",
    area: "Balseros",
    predio: "Embalse",
    monto: 15000,
    concepto: "servicio",
  }),
  arancel({
    id: "a_cuota",
    area: "Guardería",
    predio: "Almafuerte",
    monto: 3000,
    concepto: "cuota social",
  }),
  arancel({ id: "a_area_guarderia", area: "Guardería", predio: "Embalse", monto: 20000 }),
  arancel({ id: "a_area_windsurf", area: "Windsurf", predio: "Almafuerte", monto: 10000 }),
];

function arancel(patch: Partial<Arancel>): Arancel {
  return {
    id: "a",
    nombre: "Cuota",
    area: "Balseros",
    predio: "Embalse",
    monto: 0,
    concepto: "area",
    vigenteDesde: "2026-01-01",
    historico: [],
    ...patch,
  };
}

describe("arancelesDeArea — el select no puede quedar vacio por un predio fijo", () => {
  it("ofrece los aranceles de Balseros, que viven en Embalse (no en Almafuerte)", () => {
    const opciones = arancelesDeArea(CATALOGO_REAL, "Balseros");
    expect(opciones.map((a) => a.id)).toEqual(["a_area_balseros", "a_serv_balseros"]);
  });

  it("ofrece los aranceles de Guardería, que el catálogoREAL ubica en Embalse", () => {
    // The domain comment in `models/enums.py` says Guardería is Almafuerte and
    // the live catalog says Embalse. This test pins the CATALOG, on purpose: it
    // is the only one of the two that can price a line, and the area->predio
    // question is the owner's to settle, not the form's.
    const opciones = arancelesDeArea(CATALOGO_REAL, "Guardería");
    expect(opciones.map((a) => a.id)).toEqual(["a_cuota", "a_area_guarderia"]);
  });

  it("ofrece los aranceles de Windsurf", () => {
    expect(arancelesDeArea(CATALOGO_REAL, "Windsurf").map((a) => a.id)).toEqual([
      "a_area_windsurf",
    ]);
  });

  it("devuelve una lista vacia, no un error, para un area sin catalogo", () => {
    // Cabañeros has no catalog row at all: the select is legitimately empty and
    // the operator can still create the membership with "Sin arancel".
    expect(arancelesDeArea(CATALOGO_REAL, "Cabañeros")).toEqual([]);
  });

  it("nunca cruza un area con otro", () => {
    for (const area of ["Balseros", "Cabañeros", "Guardería", "Windsurf"] as const) {
      for (const a of arancelesDeArea(CATALOGO_REAL, area)) {
        expect(a.area).toBe(area);
      }
    }
  });
});

describe("predioDeArancel — la fila no puede contradecir al catálogo que la cobra", () => {
  it("toma el predio del arancel elegido, no un lugar fijo", () => {
    expect(predioDeArancel(CATALOGO_REAL, "a_area_balseros")).toBe("Embalse");
    expect(predioDeArancel(CATALOGO_REAL, "a_area_windsurf")).toBe("Almafuerte");
    expect(predioDeArancel(CATALOGO_REAL, "a_area_guarderia")).toBe("Embalse");
  });

  it("devuelve undefined sin arancel, para que el llamador conserve su valor", () => {
    expect(predioDeArancel(CATALOGO_REAL, "")).toBeUndefined();
    expect(predioDeArancel(CATALOGO_REAL, undefined)).toBeUndefined();
  });

  it("devuelve undefined para un arancel que ya no esta en el catalogo", () => {
    // A stale id must not invent a place: the caller keeps the membership's own
    // `predio` and the charge reports the mismatch through `avisos` (D8).
    expect(predioDeArancel(CATALOGO_REAL, "a_borrado")).toBeUndefined();
  });

  it("el invicto: el par (area, predio) que produce SI existe en el catalogo", () => {
    // The invariant the whole fix exists for. For every area of the real
    // catalog, the membership a hand-created row would carry has to resolve.
    for (const area of ["Balseros", "Cabañeros", "Guardería", "Windsurf"] as const) {
      for (const elegido of arancelesDeArea(CATALOGO_REAL, area)) {
        const creado = {
          area: elegido.area,
          predio: predioDeArancel(CATALOGO_REAL, elegido.id) ?? "Almafuerte",
        };
        const existe = CATALOGO_REAL.some(
          (a) => a.area === creado.area && a.predio === creado.predio,
        );
        expect(existe, `${creado.area}/${creado.predio} no existe en el catalogo`).toBe(true);
      }
    }
  });

  it("el pathname viejo producia un par que NO existe para Balseros", () => {
    // Control: what the screen used to send, and why it was unpriceable.
    const parViejo = { area: "Balseros", predio: "Almafuerte" as const };
    expect(
      CATALOGO_REAL.some((a) => a.area === parViejo.area && a.predio === parViejo.predio),
    ).toBe(false);
  });
});
